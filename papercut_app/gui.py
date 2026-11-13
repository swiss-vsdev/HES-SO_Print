"""
HES-SO PaperCut Print Client - GUI
"""

import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .config import (
    load_credentials, save_credentials, clear_credentials,
    load_auto_boot_server, save_auto_boot_server, log,
    DEFAULT_HOST, DEFAULT_CHROME, VIRTUAL_PRINTER_PORT, LOG_PATH
)
from .http_engine import PaperCutSession
from .selenium_driver import find_browser, download_chromium, selenium_submit_print
from .helpers import (
    price_per_page, printer_name, pdf_pages, _trans, _pages, _parse_dt, _fmt24h, _last_print_display
)
from .virtual_printer import VirtualPrinterServer, HAS_FASTAPI


class LoginDialog(tk.Toplevel):
    def __init__(self, parent, username="", password="", host=DEFAULT_HOST):
        super().__init__(parent)
        self.title("PaperCut Login Setup")
        self.geometry("380x250")
        self.resizable(False, False)
        self.result = None
        self.deleted = False

        frm = ttk.Frame(self, padding=20)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Enter your HES-SO credentials:", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Label(frm, text="Username / Email:").pack(anchor="w")
        self.u_var = tk.StringVar(value=username)
        ttk.Entry(frm, textvariable=self.u_var, width=35).pack(fill="x", pady=(2, 8))

        ttk.Label(frm, text="Password:").pack(anchor="w")
        self.p_var = tk.StringVar(value=password)
        ttk.Entry(frm, textvariable=self.p_var, show="•", width=35).pack(fill="x", pady=(2, 12))

        btn_box = ttk.Frame(frm)
        btn_box.pack(fill="x", pady=(5, 0))
        ttk.Button(btn_box, text="Save & Continue", command=self._save).pack(side="right")
        ttk.Button(btn_box, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 8))
        if username:
            ttk.Button(btn_box, text="Log Out", command=self._delete).pack(side="left")

        self.transient(parent)
        self.grab_set()
        parent.wait_window(self)

    def _save(self):
        u = self.u_var.get().strip()
        p = self.p_var.get().strip()
        if not u or not p:
            messagebox.showwarning("Missing details", "Please fill in both username and password.")
            return
        self.result = (u, p)
        self.destroy()

    def _delete(self):
        if not messagebox.askyesno("Log Out", "Delete saved credentials ?", parent=self):
            return
        clear_credentials()
        self.deleted = True
        self.result = None
        self.destroy()


class PaperCutGUI:
    def __init__(self, root, forced_browser=None):
        self.root = root
        self.forced_browser = forced_browser
        self.root.title("HES-SO Print Client")
        self.root.geometry("720x690")
        self.root.resizable(False, False)
        try:
            style = ttk.Style()
            if "aqua" in style.theme_names():
                style.theme_use("aqua")
        except Exception:
            pass

        creds = load_credentials()
        self.username = creds.get("username", "")
        self.password = creds.get("password", "")
        self.host = creds.get("host", DEFAULT_HOST)
        self.chrome_path = creds.get("chrome_path", DEFAULT_CHROME)
        self.auto_boot_server = bool(creds.get("auto_boot_server", False)) if creds else False

        if not self.username or not self.password:
            while True:
                dlg = LoginDialog(root, self.username, self.password, self.host)
                if not dlg.result:
                    sys.exit(0)
                self.username, self.password = dlg.result
                self.session = PaperCutSession(self.host, self.username, self.password)
                try:
                    self.session.login()
                    save_credentials(self.username, self.password, self.host, self.chrome_path)
                    break
                except Exception as e:
                    messagebox.showerror("Login failed", f"{e}\nPlease try again.")
                    self.username = ""
                    self.password = ""
        else:
            self.session = PaperCutSession(self.host, self.username, self.password)

        self.cancel_flag = threading.Event()
        self.virtual_printer = None

        frm = ttk.Frame(root, padding=15)
        frm.pack(fill="both", expand=True)

        top_bar = ttk.Frame(frm)
        top_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(top_bar, text=f"Logged in as: {self.username}", font=("Helvetica", 9, "italic")).pack(side="left")
        ttk.Button(top_bar, text="Change Credentials", command=self._change_creds).pack(side="right")

        # Print Server toggle
        vp_frame = ttk.Frame(frm)
        vp_frame.pack(fill="x", pady=(0, 8))
        self.vp_status = tk.StringVar(value="Print Server: Off")
        self.vp_status_label = ttk.Label(vp_frame, textvariable=self.vp_status, foreground="gray", font=("Helvetica", 9))
        self.vp_status_label.pack(side="left")
        self.vp_btn = ttk.Button(vp_frame, text="Start Print Server", command=self._toggle_virtual_printer)
        self.vp_btn.pack(side="right")
        self.vp_info_btn = tk.Label(
            vp_frame, text="ⓘ", font=("Helvetica", 12),
            fg="#9ca3af"
        )
        self.vp_info_btn.pack(side="right", padx=(0, 6))
        self.vp_info_btn.bind("<Button-1>", lambda e: self._show_server_info())
        self.vp_info_btn.bind("<Enter>", lambda e: self.vp_info_btn.config(fg="#2563eb"))
        self.vp_info_btn.bind("<Leave>", lambda e: self.vp_info_btn.config(fg="#9ca3af"))

        opts = ttk.LabelFrame(frm, text="Printer Settings", padding=8)
        opts.pack(fill="x", pady=(0, 8))
        ttk.Label(opts, text="Size:").grid(row=0, column=0, sticky="w")
        self.size_var = tk.StringVar(value="A4")
        ttk.Combobox(opts, textvariable=self.size_var, values=["A4", "A3"], state="readonly", width=6).grid(row=0, column=1, padx=(0, 12))

        ttk.Label(opts, text="Color:").grid(row=0, column=2, sticky="w")
        self.color_var = tk.StringVar(value="BW")
        ttk.Combobox(opts, textvariable=self.color_var, values=["BW", "Color"], state="readonly", width=7).grid(row=0, column=3, padx=(0, 12))

        ttk.Label(opts, text="Duplex:").grid(row=0, column=4, sticky="w")
        self.duplex_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, variable=self.duplex_var).grid(row=0, column=5)

        ttk.Label(opts, text="Copies:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.copies_var = tk.IntVar(value=1)
        ttk.Spinbox(opts, from_=1, to=999, textvariable=self.copies_var, width=5).grid(row=1, column=1, sticky="w", pady=(6, 0))

        fil = ttk.LabelFrame(frm, text="Document Selection", padding=8)
        fil.pack(fill="x", pady=(0, 8))
        self.file_var = tk.StringVar()
        ttk.Entry(fil, textvariable=self.file_var, width=45).pack(side="left", fill="x", expand=True)
        ttk.Button(fil, text="Browse...", command=self.browse).pack(side="left", padx=(6, 0))
        self.estimate_lbl = ttk.Label(frm, text="", foreground="dodgerblue")
        self.estimate_lbl.pack(anchor="w", pady=(0, 4))

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(0, 4))
        self.print_btn = ttk.Button(btns, text="Print Document", command=self.print_file)
        self.print_btn.pack(side="left")
        self.cancel_btn = ttk.Button(btns, text="Cancel", command=self.cancel_print, state="disabled")
        self.cancel_btn.pack(side="left", padx=(8, 0))

        self.status = tk.StringVar(value="")
        ttk.Label(frm, textvariable=self.status, foreground="gray").pack(anchor="w", pady=(0, 8))

        self.stats_box = ttk.LabelFrame(frm, text="Account Overview", padding=8)
        self.stats_box.pack(fill="both", expand=True, pady=(8, 0))

        self.stat_cards = ttk.Frame(self.stats_box)
        self.stat_cards.pack(fill="x", pady=(0, 6))
        self.stat_cards.config(height=140)
        self.stat_cards.pack_propagate(False)
        self.stat_cards.columnconfigure((0, 1, 2), weight=1, uniform="card")
        self.stat_cards.rowconfigure((0, 1), weight=1, uniform="card")
        self.stat_vars = {}
        cards = [
            ("balance", "💰", "Balance"),
            ("jobs", "🖨️", "Print Jobs"),
            ("pages", "📄", "Total Pages"),
            ("trees", "🌳", "Trees Impact"),
            ("co2", "♻️", "CO2 Impact"),
            ("last_print", "🕐", "Last Print"),
        ]
        for i, (key, icon, label) in enumerate(cards):
            card = tk.Frame(self.stat_cards, bg="#f2f4f7", highlightthickness=1, highlightbackground="#d8dde3", padx=8, pady=4)
            card.grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="nsew")
            tk.Label(card, bg="#f2f4f7", text=icon, font=("Helvetica", 16)).grid(row=0, column=0, rowspan=2, sticky="w")
            sub = tk.Frame(card, bg="#f2f4f7")
            sub.grid(row=0, column=1, padx=(6, 0), rowspan=2, sticky="nsew")
            tk.Label(sub, bg="#f2f4f7", text=label, fg="#6b7280", font=("Helvetica", 9)).grid(row=0, column=0, sticky="w")
            self.stat_vars[key] = tk.StringVar(value="…")
            tk.Label(sub, bg="#f2f4f7", textvariable=self.stat_vars[key], fg="#1f2937", font=("Helvetica", 11, "bold"), anchor="w").grid(row=1, column=0, sticky="nw")

        tree_frame = ttk.Frame(self.stats_box)
        tree_frame.pack(fill="both", expand=True)
        cols = ("date", "doc", "pages", "cost", "status")
        self.jobs_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=8)
        heads = {"date": "Date", "doc": "Document", "pages": "Pages", "cost": "Cost", "status": "Status"}
        widths = {"date": 130, "doc": 160, "pages": 50, "cost": 60, "status": 80}
        for c in cols:
            self.jobs_tree.heading(c, text=heads[c])
            self.jobs_tree.column(c, width=widths[c], anchor="w")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.jobs_tree.yview)
        self.jobs_tree.configure(yscrollcommand=scrollbar.set)
        self.jobs_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.stats_status = tk.StringVar(value="Loading account stats...")
        ttk.Label(self.stats_box, textvariable=self.stats_status, foreground="gray").pack(anchor="w", pady=(4, 0))

        for v in (self.size_var, self.color_var, self.copies_var, self.file_var):
            v.trace_add("write", lambda *_: self._update_estimate())
        self.duplex_var.trace_add("write", lambda *_: self._update_estimate())

        threading.Thread(target=self._load_stats, daemon=True).start()
        if self.auto_boot_server:
            self.root.after(500, self._toggle_virtual_printer)

    def _change_creds(self):
        dlg = LoginDialog(self.root, self.username, self.password, self.host)
        if dlg.result:
            username, password = dlg.result
            session = PaperCutSession(self.host, username, password)
            try:
                session.login()
            except Exception as e:
                messagebox.showerror("Login failed", f"{e}\nCredentials not saved.", parent=self.root)
                return
            self.username, self.password = username, password
            self.session = session
            save_credentials(self.username, self.password, self.host, self.chrome_path)
            self._refresh_stats()
        elif dlg.deleted:
            self.username = ""
            self.password = ""
            self.session = None

    def _load_stats(self):
        try:
            stats = self.session.get_stats()
            self.root.after(0, lambda: self._render_stats(stats))
        except Exception as e:
            err = str(e)
            self.root.after(0, lambda m=err: self.stats_status.set(f"Stats error: {m}"))

    def _refresh_stats(self):
        self.stats_status.set("Refreshing...")
        threading.Thread(target=self._load_stats, daemon=True).start()

    def _render_stats(self, stats):
        for k in ["balance", "jobs", "pages", "trees", "co2"]:
            if k in self.stat_vars and k in stats:
                self.stat_vars[k].set(stats[k])

        recent = stats.get("recent_jobs", [])
        # Last print = most recent actually printed job (not cancelled/pending)
        last_date = "—"
        for j in recent:
            if _trans(j.get("status", "")) == "Printed":
                last_date = j.get("date", "—")
                break
        self.stat_vars["last_print"].set(_last_print_display(last_date))

        for r in self.jobs_tree.get_children():
            self.jobs_tree.delete(r)

        for j in stats.get("queued_jobs", [])[:20]:
            dt = _parse_dt(j["date"])
            date = _fmt24h(dt) if dt else j["date"]
            self.jobs_tree.insert("", "end", values=(date, j["doc"][:30], _pages(j["pages"]), j["cost"], _trans(j["status"])))
        for j in recent[:30]:
            dt = _parse_dt(j["date"])
            date = _fmt24h(dt) if dt else j["date"]
            self.jobs_tree.insert("", "end", values=(date, j["doc"][:30], _pages(j["pages"]), j["cost"], _trans(j["status"])))

        self.stats_status.set(f"Updated {time.strftime('%H:%M:%S')}")

    def _update_estimate(self):
        size = self.size_var.get()
        color = self.color_var.get()
        copies = max(1, self.copies_var.get())
        pp = price_per_page(size, color)
        path = self.file_var.get()
        n = pdf_pages(path) if path and os.path.isfile(path) else None
        if n is None:
            total = f"{pp:.2f} CHF/page"
            detail = ""
        else:
            total = f"{pp * n * copies:.2f} CHF"
            detail = f" ({n} pg × {copies} copies)"
        self.estimate_lbl.config(
            text=f"{size}-{color}{'+RV' if self.duplex_var.get() else ''}: {total}{detail}"
        )

    def browse(self):
        p = filedialog.askopenfilename(title="Select document to print")
        if p:
            self.file_var.set(p)

    def print_file(self):
        file_path = self.file_var.get().strip()
        if not file_path or not os.path.isfile(file_path):
            messagebox.showwarning("Invalid file", "Please select a valid document to print.")
            return

        printer = printer_name(self.size_var.get(), self.color_var.get(), self.duplex_var.get())
        copies = max(1, self.copies_var.get())
        self.cancel_flag.clear()
        self.print_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")

        def worker():
            log(f"print requested: file={file_path} printer={printer} copies={copies}")
            self._update_status("Checking for browser...")
            try:
                path = find_browser(self.chrome_path, allow_download=False, preferred=self.forced_browser)
                if not path and self.forced_browser in (None, "auto", "chrome", "chromium"):
                    self._update_status("Downloading Chromium (one-time, ~150MB)...")
                    try:
                        download_chromium()
                    except Exception:
                        pass
                    path = find_browser(self.chrome_path, allow_download=False, preferred=self.forced_browser)
                if not path:
                    raise RuntimeError("No supported browser found for selected engine. Install Chrome/Chromium/Edge/Brave, Firefox/LibreWolf, or Safari.")
                self.chrome_path = path
                log(f"using browser: {path} (forced={self.forced_browser})")
            except Exception as e:
                log("browser setup failed", e)
                self._update_status(f"Browser setup failed: {e}")
                self.root.after(0, lambda: self.print_btn.config(state="normal"))
                self.root.after(0, lambda: self.cancel_btn.config(state="disabled"))
                self.root.after(0, lambda err=str(e): messagebox.showerror("Browser setup failed", err))
                return

            try:
                res = selenium_submit_print(
                    self.host, self.username, self.password,
                    printer, file_path, copies,
                    chrome_path=self.chrome_path,
                    status_cb=self._update_status,
                    should_cancel=self.cancel_flag.is_set,
                    browser_preference=self.forced_browser,
                )
            except Exception as e:
                log("print exception", e)
                res = "error"
                self._update_status(f"Error: {e}")
            log(f"print result: {res}")
            if res == "done":
                time.sleep(10)
                self._refresh_stats()
            elif res == "error":
                self.root.after(0, lambda: messagebox.showerror("Print failed", f"Print job failed. See log: {LOG_PATH}"))
            self.root.after(0, lambda: self.print_btn.config(state="normal"))
            self.root.after(0, lambda: self.cancel_btn.config(state="disabled"))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_print(self):
        self.cancel_flag.set()
        if self.virtual_printer:
            self.virtual_printer.cancel_all_jobs()
        self._update_status("Cancelling...")

    def _update_status(self, msg):
        log(f"status: {msg}")
        self.root.after(0, lambda: self.status.set(msg))

    def _toggle_virtual_printer(self):
        if self.virtual_printer and self.virtual_printer.is_running():
            self.virtual_printer.stop()
            self.vp_status.set("Print Server: Off")
            self.vp_status_label.config(foreground="gray")
            self.vp_btn.config(text="Start Print Server")
        else:
            if not HAS_FASTAPI:
                messagebox.showwarning("Missing dependencies", "fastapi and uvicorn required.\nRun: pip install fastapi uvicorn python-multipart")
                return
            self.virtual_printer = VirtualPrinterServer(
                self.host, self.username, self.password, self.chrome_path,
                status_cb=self._update_status,
                on_complete=lambda: self.root.after(0, self._refresh_stats),
                browser_preference=self.forced_browser,
            )
            log("starting print server")
            try:
                started = self.virtual_printer.start()
            except Exception as e:
                log("print server start exception", e)
                started = False
            if started:
                log("print server started")
                self.vp_status.set(f"Print Server: On (IPP :{VIRTUAL_PRINTER_PORT})")
                self.vp_status_label.config(foreground="green")
                self.vp_btn.config(text="Stop Print Server")
            else:
                self.virtual_printer = None
                log("print server failed to start")
                messagebox.showerror("Print Server", f"Failed to start print server. See log: {LOG_PATH}")

    def _show_server_info(self):
        win = tk.Toplevel(self.root)
        win.title("Print Server Connection")
        win.resizable(False, False)
        win.transient(self.root)

        info = (
            f"Address: 127.0.0.1\n"
            f"Port: {VIRTUAL_PRINTER_PORT}\n"
            f"Protocol: Internet Printing Protocol (IPP)\n"
            f"Queue: /ipp/print\n\n"
            f"Printer URI: ipp://127.0.0.1:{VIRTUAL_PRINTER_PORT}/ipp/print\n"
            f"HTTP API: http://127.0.0.1:{VIRTUAL_PRINTER_PORT}/print\n\n"
            f"Add as system printer (macOS):\n"
            f"1. System Settings → Printers & Scanners\n"
            f"2. Add Printer (bottom-left +)\n"
            f"3. Choose: IP\n"
            f"4. Address: 127.0.0.1\n"
            f"5. Protocol: Internet Printing Protocol (IPP)\n"
            f"6. Queue: /ipp/print\n"
            f"7. Name: PaperCut_Virtual\n"
            f"8. Use: Generic OpenSource Printer"
        )
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        bg = self.root.cget("background")
        txt = tk.Text(
            frm, wrap="word", height=17, width=52,
            borderwidth=0, highlightthickness=0, relief="flat",
            bg=bg, font=("TkDefaultFont",), cursor="arrow",
            insertontime=0,
        )
        txt.insert("1.0", info)
        txt.pack(anchor="w", fill="both", expand=True)
        txt.bind("<Key>", lambda e: "break")  # read-only but selectable/copyable

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))
        self.auto_boot_var = tk.BooleanVar(value=self.auto_boot_server)
        auto_boot_chk = ttk.Checkbutton(btns, text="Auto-boot Print Server", variable=self.auto_boot_var)
        auto_boot_chk.pack(side="left")
        def _save_auto_boot():
            self.auto_boot_server = self.auto_boot_var.get()
            save_auto_boot_server(self.auto_boot_server)
        auto_boot_chk.config(command=_save_auto_boot)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")