"""
HES-SO PaperCut Print Client - Virtual Printer HTTP Server
"""

import threading
import queue
import time
import tempfile
import os
import asyncio
import shutil
import subprocess
import uuid
import re
from pathlib import Path
from concurrent.futures import Future, TimeoutError as FutureTimeoutError

# Map selenium status messages to progress percentages
_PROGRESS_MAP = {
    "processing": 5,
    "checking for browser": 5,
    "downloading chromium": 10,
    "logging in": 20,
    "opening print wizard": 35,
    "selecting printer": 50,
    "uploading file": 65,
    "submitting": 80,
    "print job submitted": 95,
}

try:
    from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Request
    from fastapi.responses import Response
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from .config import VIRTUAL_PRINTER_PORT, log
from .selenium_driver import selenium_submit_print
from .helpers import printer_name
from . import ipp_server as ipp

class VirtualPrinterServer:
    """HTTP/IPP print server that accepts print jobs and forwards to PaperCut via Selenium."""

    def __init__(self, host, username, password, chrome_path, status_cb=lambda m: None, on_complete=None, browser_preference=None):
        self.host = host
        self.username = username
        self.password = password
        self.chrome_path = chrome_path
        self.browser_preference = browser_preference
        self.status_cb = status_cb
        self.on_complete = on_complete  # called after successful print (for stats refresh)
        self.server = None
        self.thread = None
        self.running = False
        self.print_queue = queue.Queue()
        self.worker_thread = None
        self.jobs = {}  # job_id -> job dict
        self.jobs_lock = threading.Lock()
        self.ipp_job_counter = 0
        self.ipp_to_job = {}  # ipp_job_id (int) -> job_id (str)
        self.default_options = {
            "size": "A4",
            "color": "BW",
            "duplex": False,
            "copies": 1,
        }

    def _new_job(self, filename, source="http"):
        job_id = uuid.uuid4().hex[:8]
        with self.jobs_lock:
            self.ipp_job_counter += 1
            ipp_id = self.ipp_job_counter
        job = {
            "id": job_id,
            "ipp_id": ipp_id,
            "filename": filename,
            "source": source,
            "state": "queued",      # queued, processing, completed, cancelled, failed
            "progress": 0,
            "message": "Queued",
            "cancel_event": threading.Event(),
            "created_at": time.time(),
        }
        with self.jobs_lock:
            self.jobs[job_id] = job
            self.ipp_to_job[ipp_id] = job_id
        return job

    def _get_job_by_ipp_id(self, ipp_id):
        with self.jobs_lock:
            job_id = self.ipp_to_job.get(ipp_id)
            if job_id:
                job = self.jobs.get(job_id)
                return dict(job) if job else None
        return None

    def _update_job(self, job_id, **kwargs):
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if job:
                job.update(kwargs)
        return self.jobs.get(job_id)

    def _get_job(self, job_id):
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def _list_jobs(self):
        with self.jobs_lock:
            return [{k: v for k, v in j.items() if k != "cancel_event"} for j in self.jobs.values()]

    def _status_to_progress(self, msg):
        m = (msg or "").lower()
        for key, pct in _PROGRESS_MAP.items():
            if key in m:
                return pct
        if "error" in m:
            return 0
        if "cancel" in m:
            return 0
        return None

    def _schedule_stats_refresh(self):
        """Refresh stats 10s after print sent."""
        if self.on_complete:
            def delayed():
                time.sleep(10)
                try:
                    self.on_complete()
                except Exception:
                    pass
            threading.Thread(target=delayed, daemon=True).start()

    def get_active_jobs(self):
        with self.jobs_lock:
            return [
                {k: v for k, v in j.items() if k != "cancel_event"}
                for j in self.jobs.values()
                if j["state"] in ("queued", "processing")
            ]

    def cancel_job(self, job_id):
        with self.jobs_lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            if job["state"] in ("completed", "failed", "cancelled"):
                return False
            job["cancel_event"].set()
            job["state"] = "cancelled"
            job["message"] = "Cancelled"
            job["progress"] = 0
            return True

    def cancel_all_jobs(self):
        with self.jobs_lock:
            for job in self.jobs.values():
                if job["state"] in ("queued", "processing"):
                    job["cancel_event"].set()
                    job["state"] = "cancelled"
                    job["message"] = "Cancelled"
                    job["progress"] = 0

    def purge_jobs(self):
        """Remove completed/cancelled/failed jobs from tracking."""
        with self.jobs_lock:
            to_remove = [jid for jid, j in self.jobs.items() if j["state"] in ("completed", "cancelled", "failed")]
            for jid in to_remove:
                job = self.jobs.pop(jid, None)
                if job:
                    self.ipp_to_job.pop(job.get("ipp_id"), None)

    def _worker(self):
        """Background worker that processes print jobs sequentially."""
        while self.running:
            try:
                item = self.print_queue.get(timeout=1)
                if item is None:
                    break
                file_path, options, result_future, job = item
                job_id = job["id"]
                filename = job.get("filename", Path(file_path).name)

                # Check if cancelled while queued
                if job["cancel_event"].is_set():
                    self._update_job(job_id, state="cancelled", progress=0, message="Cancelled")
                    if result_future:
                        result_future.set_result("cancelled")
                    self._cleanup_file(file_path)
                    continue

                self._update_job(job_id, state="processing", progress=10, message="Processing")
                self.status_cb(f"Print server: processing {filename}...")

                def job_status_cb(msg):
                    pct = self._status_to_progress(msg)
                    updates = {"message": msg}
                    if pct is not None:
                        updates["progress"] = pct
                    self._update_job(job_id, **updates)
                    self.status_cb(msg)

                try:
                    log(f"server job processing: {job_id} file={filename}")
                    res = selenium_submit_print(
                        self.host, self.username, self.password,
                        printer_name(options["size"], options["color"], options["duplex"]),
                        file_path, options["copies"],
                        chrome_path=self.chrome_path,
                        status_cb=job_status_cb,
                        should_cancel=job["cancel_event"].is_set,
                        browser_preference=self.browser_preference,
                    )
                    log(f"server job result: {job_id} res={res}")
                    cancelled = job["cancel_event"].is_set()
                    if res == "cancelled" or cancelled:
                        self._update_job(job_id, state="cancelled", progress=0, message="Cancelled")
                    elif res == "done":
                        # Small delay before marking complete (simulate printer finishing)
                        self._update_job(job_id, progress=98, message="Finalizing...")
                        time.sleep(2)
                        # Check again in case cancelled during finalize delay
                        if job["cancel_event"].is_set():
                            self._update_job(job_id, state="cancelled", progress=0, message="Cancelled")
                        else:
                            self._update_job(job_id, state="completed", progress=100, message="Completed")
                            self._schedule_stats_refresh()
                    else:
                        self._update_job(job_id, state="failed", message="Failed")
                    if result_future:
                        result_future.set_result(res)
                except Exception as e:
                    log(f"server job exception: {job_id}", e)
                    if job["cancel_event"].is_set():
                        self._update_job(job_id, state="cancelled", progress=0, message="Cancelled")
                    else:
                        self._update_job(job_id, state="failed", message=str(e))
                    if result_future:
                        result_future.set_exception(e)
                finally:
                    self._cleanup_file(file_path)
            except queue.Empty:
                continue

    def _cleanup_file(self, file_path):
        try:
            os.unlink(file_path)
        except:
            pass
        try:
            parent = os.path.dirname(file_path)
            if parent and os.path.basename(parent).startswith("papercut_"):
                shutil.rmtree(parent, ignore_errors=True)
        except:
            pass

    def _extract_print_data(self, data):
        """Extract actual document from PJL-wrapped data if present."""
        # Find document start markers
        pdf_start = data.find(b"%PDF")
        ps_start = data.find(b"%!")
        # Pick the earliest valid marker
        starts = [s for s in [pdf_start, ps_start] if s >= 0]
        if not starts:
            return data
        start = min(starts)
        extracted = data[start:]
        # Strip trailing UEL (Universal Exit Language) sequence if present
        uel = b"\x1b%-12345X"
        end = extracted.rfind(uel)
        if end > 0:
            extracted = extracted[:end]
        return extracted

    def _convert_ps_to_pdf(self, ps_path):
        """Convert PostScript to PDF if ghostscript is available."""
        out_dir = os.path.dirname(ps_path)
        base = Path(ps_path).stem or "print"
        pdf_path = os.path.join(out_dir, f"{base}.pdf")
        converters = [
            ["ps2pdf", ps_path, pdf_path],
            ["gs", "-dBATCH", "-dNOPAUSE", "-sDEVICE=pdfwrite", f"-sOutputFile={pdf_path}", ps_path],
            ["pstopdf", ps_path, "-o", pdf_path],
        ]
        for cmd in converters:
            if not shutil.which(cmd[0]):
                continue
            try:
                subprocess.run(cmd, check=True, timeout=60, capture_output=True)
                if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                    return pdf_path
            except Exception:
                pass
        return None

    def start(self):
        if not HAS_FASTAPI:
            self.status_cb("Print server: fastapi/uvicorn not installed")
            return False
        if self.running:
            return True

        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

        app = FastAPI(title="PaperCut Print Server")

        @app.get("/")
        async def root():
            return {
                "service": "PaperCut Print Server",
                "status": "running",
                "endpoints": {
                    "print": "POST /print",
                    "status": "GET /status",
                    "options": "GET /options"
                }
            }

        @app.get("/status")
        async def status():
            return {"running": self.running, "queue_size": self.print_queue.qsize()}

        @app.get("/options")
        async def options():
            return {
                "default": self.default_options,
                "sizes": ["A4", "A3"],
                "colors": ["BW", "Color"],
                "duplex": [False, True],
                "copies_range": [1, 999]
            }

        @app.post("/print")
        async def print_job(
            file: UploadFile = File(...),
            size: str = Form("A4"),
            color: str = Form("BW"),
            duplex: bool = Form(False),
            copies: int = Form(1),
            wait: bool = Form(True),
        ):
            if not self.running:
                raise HTTPException(503, "Print server stopped")

            if size not in ["A4", "A3"]:
                raise HTTPException(400, "size must be A4 or A3")
            if color not in ["BW", "Color"]:
                raise HTTPException(400, "color must be BW or Color")
            if not 1 <= copies <= 999:
                raise HTTPException(400, "copies must be 1-999")

            # Preserve original filename (including dots), sanitize path separators
            original_name = os.path.basename(file.filename or "document.pdf")
            if not original_name or original_name in (".", ".."):
                original_name = "document.pdf"
            tmp_dir = tempfile.mkdtemp(prefix="papercut_http_")
            tmp_path = os.path.join(tmp_dir, original_name)
            with open(tmp_path, "wb") as f:
                content = await file.read()
                f.write(content)

            job = self._new_job(original_name, source="http")
            future = Future()
            options = {"size": size, "color": color, "duplex": duplex, "copies": copies}
            self.print_queue.put((tmp_path, options, future, job))

            if not wait:
                return {"job_id": job["id"], "state": "queued", "file": original_name}

            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: future.result(timeout=300))
                job_info = self._get_job(job["id"]) or {}
                return {"job_id": job["id"], "status": result, "state": job_info.get("state"), "file": original_name}
            except FutureTimeoutError:
                raise HTTPException(504, "Print job timed out")
            except Exception as e:
                raise HTTPException(500, f"Print job failed: {e}")

        @app.get("/jobs")
        async def list_jobs():
            return {"jobs": self._list_jobs()}

        @app.get("/jobs/{job_id}")
        async def get_job(job_id: str):
            job = self._get_job(job_id)
            if not job:
                raise HTTPException(404, "Job not found")
            job.pop("cancel_event", None)
            return job

        @app.post("/jobs/{job_id}/cancel")
        @app.delete("/jobs/{job_id}")
        async def cancel_job(job_id: str):
            if not self.cancel_job(job_id):
                job = self._get_job(job_id)
                if not job:
                    raise HTTPException(404, "Job not found")
                return {"job_id": job_id, "state": job["state"], "message": "Job already finished"}
            return {"job_id": job_id, "state": "cancelled"}

        @app.post("/ipp")
        @app.post("/ipp/print")
        @app.post("/ipp/")
        @app.post("/printers/{name:path}")
        async def ipp_handler(request: Request, name: str = ""):
            body = await request.body()
            if len(body) < 8:
                return Response(content=b"", status_code=400)
            # Check if this looks like IPP
            if body[0] not in (0x01, 0x02):
                return Response(content=b"", status_code=400)
            try:
                req = ipp.parse_ipp_request(body)
            except Exception:
                return Response(content=b"", status_code=400)

            op = req["operation"]
            req_id = req["request_id"]
            op_attrs = req["attributes"].get("operation", {})

            # Debug logging
            try:
                op_names = {0x0002:"Print-Job",0x0004:"Validate-Job",0x0008:"Cancel-Job",0x0009:"Get-Job-Attrs",0x000A:"Get-Jobs",0x000B:"Get-Printer-Attrs",0x0012:"Purge-Jobs"}
                with open("/tmp/papercut_ipp.log", "a") as f:
                    f.write(f"{time.strftime('%H:%M:%S')} op={op_names.get(op, hex(op))} attrs={op_attrs} job_attrs={req['attributes'].get('job',{})}\n")
            except:
                pass

            if op == ipp.OP_GET_PRINTER_ATTRIBUTES:
                active = len(self.get_active_jobs())
                req_printer_uri = str(op_attrs.get("printer-uri", "ipp://localhost:8631/ipp/print"))
                resp = ipp.build_ipp_response(req_id, ipp.STATUS_OK, printer_attrs=ipp.make_printer_attributes(active))

            elif op == ipp.OP_VALIDATE_JOB:
                resp = ipp.build_ipp_response(req_id, ipp.STATUS_OK)

            elif op == ipp.OP_PRINT_JOB:
                doc_data = req.get("data", b"")
                try:
                    log(f"ipp print-job received: bytes={len(doc_data)} attrs={op_attrs}")
                    actual = self._extract_print_data(doc_data) if doc_data else b""
                    if not actual:
                        actual = doc_data
                    if not actual:
                        log("ipp print-job rejected: no document data")
                        resp = ipp.build_ipp_response(req_id, ipp.STATUS_CLIENT_ERROR_NOT_POSSIBLE)
                    else:
                        if actual.startswith(b"%PDF"):
                            ext = ".pdf"
                        elif actual.startswith(b"%!"):
                            ext = ".ps"
                        else:
                            ext = ".pdf"

                        job_name = str(op_attrs.get("job-name", f"print{ext}"))
                        job_name = re.sub(r"^\s*\d+\s*-\s*", "", job_name)
                        job_name = os.path.basename(job_name) or f"print{ext}"
                        if not Path(job_name).suffix:
                            job_name = f"{job_name}{ext}"

                        tmp_dir = tempfile.mkdtemp(prefix="papercut_ipp_")
                        tmp_path = os.path.join(tmp_dir, job_name)
                        with open(tmp_path, "wb") as f:
                            f.write(actual)

                        # Convert PS to PDF if needed
                        if ext == ".ps":
                            converted = self._convert_ps_to_pdf(tmp_path)
                            if converted:
                                try:
                                    os.unlink(tmp_path)
                                except Exception:
                                    pass
                                tmp_path = converted
                                job_name = os.path.basename(converted)
                            else:
                                log(f"ipp print-job PS conversion failed: {job_name}")
                                try:
                                    shutil.rmtree(tmp_dir, ignore_errors=True)
                                except Exception:
                                    pass
                                resp = ipp.build_ipp_response(req_id, ipp.STATUS_CLIENT_ERROR_NOT_POSSIBLE)
                                return Response(content=resp, media_type="application/ipp")

                        job = self._new_job(job_name, source="ipp")
                        options = dict(self.default_options)
                        copies = op_attrs.get("copies", 1)
                        try:
                            options["copies"] = max(1, int(copies))
                        except Exception:
                            pass
                        future = Future()
                        self.print_queue.put((tmp_path, options, future, job))
                        log(f"ipp print-job queued: ipp_id={job['ipp_id']} id={job['id']} file={job_name} path={tmp_path}")
                        resp = ipp.build_ipp_response(
                            req_id, ipp.STATUS_OK,
                            job_attrs=ipp.make_job_attributes(job["ipp_id"], state=job["state"], job_name=job["filename"])
                        )
                except Exception as e:
                    log("ipp print-job handler error", e)
                    resp = ipp.build_ipp_response(req_id, ipp.STATUS_CLIENT_ERROR_NOT_POSSIBLE)

            elif op == ipp.OP_GET_JOBS:
                # Return list of jobs (each as separate job group)
                which_jobs = str(op_attrs.get("which-jobs", "not-completed"))
                with self.jobs_lock:
                    job_list = list(self.jobs.values())
                if which_jobs == "completed":
                    job_list = [j for j in job_list if j["state"] in ("completed", "cancelled", "failed")]
                elif which_jobs == "not-completed":
                    job_list = [j for j in job_list if j["state"] in ("queued", "processing")]
                jobs_attrs = [
                    ipp.make_job_attributes(j["ipp_id"], state=j["state"], job_name=j.get("filename"))
                    for j in job_list[-50:]
                ]
                resp = ipp.build_ipp_response(req_id, ipp.STATUS_OK, jobs_attrs=jobs_attrs)

            elif op == ipp.OP_PURGE_JOBS:
                self.purge_jobs()
                resp = ipp.build_ipp_response(req_id, ipp.STATUS_OK)

            elif op == ipp.OP_GET_JOB_ATTRIBUTES:
                # Find job by job-id attribute (check operation and job groups)
                job_attrs = req["attributes"].get("job", {})
                all_attrs = {**job_attrs, **op_attrs}
                job_id_attr = all_attrs.get("job-id", 0)
                try:
                    ipp_job_id = int(job_id_attr)
                except:
                    ipp_job_id = 0
                if not ipp_job_id:
                    job_uri = str(all_attrs.get("job-uri", ""))
                    m = re.search(r'/jobs?/(\d+)', job_uri) or re.search(r'/(\d+)(?:\D*$)', job_uri)
                    if m:
                        ipp_job_id = int(m.group(1))
                j = self._get_job_by_ipp_id(ipp_job_id)
                if j:
                    resp = ipp.build_ipp_response(req_id, ipp.STATUS_OK, job_attrs=ipp.make_job_attributes(j["ipp_id"], state=j["state"], job_name=j.get("filename")))
                else:
                    resp = ipp.build_ipp_response(req_id, ipp.STATUS_CLIENT_ERROR_NOT_FOUND)

            elif op == ipp.OP_CANCEL_JOB:
                job_attrs = req["attributes"].get("job", {})
                all_attrs = {**job_attrs, **op_attrs}
                job_id_attr = all_attrs.get("job-id", 0)
                try:
                    ipp_job_id = int(job_id_attr)
                except:
                    ipp_job_id = 0
                if not ipp_job_id:
                    job_uri = str(all_attrs.get("job-uri", ""))
                    m = re.search(r'/jobs?/(\d+)', job_uri) or re.search(r'/(\d+)(?:\D*$)', job_uri)
                    if m:
                        ipp_job_id = int(m.group(1))
                j = self._get_job_by_ipp_id(ipp_job_id)
                if j:
                    if j["state"] in ("queued", "processing"):
                        self.cancel_job(j["id"])
                    # Return OK even if already cancelled/completed - stops retry loops
                    resp = ipp.build_ipp_response(req_id, ipp.STATUS_OK)
                else:
                    # Job not found (maybe purged) - return OK to stop retries
                    resp = ipp.build_ipp_response(req_id, ipp.STATUS_OK)

            else:
                # Unsupported operation - return success to be friendly
                resp = ipp.build_ipp_response(req_id, ipp.STATUS_OK)

            return Response(content=resp, media_type="application/ipp")

        self.app = app
        try:
            config = uvicorn.Config(
                app,
                host="127.0.0.1",
                port=VIRTUAL_PRINTER_PORT,
                log_level="warning",
                access_log=False,
            )
            self.server = uvicorn.Server(config)
            # uvicorn installs signal handlers by default; not allowed outside main thread
            self.server.install_signal_handlers = lambda: None
            self.thread = threading.Thread(target=self.server.run, daemon=True)
            self.thread.start()
            time.sleep(0.5)
            if self.thread.is_alive():
                log("virtual printer server thread alive")
                return True
            self.running = False
            log("virtual printer server thread exited immediately")
            self.status_cb("Print server: failed to start")
            return False
        except Exception as e:
            self.running = False
            log("virtual printer server start error", e)
            self.status_cb(f"Print server error: {e}")
            return False

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.print_queue.put(None)
        if self.worker_thread:
            self.worker_thread.join(timeout=2)
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=2)

    def is_running(self):
        return self.running