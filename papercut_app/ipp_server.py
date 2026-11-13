"""
Minimal IPP (Internet Printing Protocol) server for macOS printer integration.
Handles basic operations: Get-Printer-Attributes, Print-Job, Validate-Job,
Get-Jobs, Get-Job-Attributes, Cancel-Job.
"""

import struct
import io
import os
import tempfile
import time
from pathlib import Path

# IPP operation IDs
OP_PRINT_JOB = 0x0002
OP_VALIDATE_JOB = 0x0004
OP_CANCEL_JOB = 0x0008
OP_GET_JOB_ATTRIBUTES = 0x0009
OP_GET_JOBS = 0x000A
OP_GET_PRINTER_ATTRIBUTES = 0x000B
OP_PURGE_JOBS = 0x0012
OP_CUPS_GET_DEFAULT = 0x4001
OP_CUPS_GET_PRINTERS = 0x4002

# IPP status codes
STATUS_OK = 0x0000
STATUS_OK_IGNORED = 0x0001
STATUS_CLIENT_ERROR_NOT_FOUND = 0x0406
STATUS_CLIENT_ERROR_NOT_POSSIBLE = 0x0503

# Delimiter tags
TAG_END = 0x03
TAG_OPERATION = 0x01
TAG_JOB = 0x02
TAG_PRINTER = 0x04

# Value tags
TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_URI = 0x45
TAG_KEYWORD = 0x44
TAG_NAME = 0x42
TAG_CHARSET = 0x47
TAG_NATURAL_LANGUAGE = 0x48
TAG_MIME_TYPE = 0x49
TAG_TEXT = 0x41


def _read_attr(stream):
    """Read one IPP attribute from stream. Returns (tag, name, value) or None for delimiter/end."""
    b = stream.read(1)
    if not b:
        return None
    tag = b[0]
    if tag <= 0x05:  # delimiter tags
        stream.seek(-1, 1)
        return ("DELIM", tag, None)
    name_len = struct.unpack(">H", stream.read(2))[0]
    name = stream.read(name_len).decode("utf-8", "replace") if name_len > 0 else None
    val_len = struct.unpack(">H", stream.read(2))[0]
    val_raw = stream.read(val_len)

    if tag in (TAG_INTEGER, TAG_ENUM):
        value = struct.unpack(">i", val_raw)[0] if val_len == 4 else 0
    elif tag == TAG_BOOLEAN:
        value = val_raw[0] != 0 if val_len > 0 else False
    else:
        value = val_raw.decode("utf-8", "replace")

    return (tag, name, value)


def parse_ipp_request(data):
    """Parse IPP request. Returns dict with version, operation, request_id, attributes, data."""
    stream = io.BytesIO(data)
    version_major, version_minor = struct.unpack(">BB", stream.read(2))
    operation = struct.unpack(">H", stream.read(2))[0]
    request_id = struct.unpack(">I", stream.read(4))[0]

    attrs = {"operation": {}, "job": {}}
    current_group = None
    last_name = None

    while True:
        pos = stream.tell()
        attr = _read_attr(stream)
        if attr is None:
            break
        tag, name, value = attr
        if tag == "DELIM":
            delim = name
            stream.read(1)  # consume delimiter
            if delim == TAG_END:
                break
            elif delim == TAG_OPERATION:
                current_group = "operation"
            elif delim == TAG_JOB:
                current_group = "job"
            else:
                current_group = "other"
            last_name = None
            continue

        # Additional values (1setOf) have empty name
        if name is None or name == "":
            name = last_name
        else:
            last_name = name

        if current_group and name:
            if name in attrs.get(current_group, {}):
                existing = attrs[current_group][name]
                if not isinstance(existing, list):
                    attrs[current_group][name] = [existing]
                attrs[current_group][name].append(value)
            else:
                attrs.setdefault(current_group, {})[name] = value

    # Remaining data is document data
    doc_data = stream.read()
    return {
        "version_major": version_major,
        "version_minor": version_minor,
        "operation": operation,
        "request_id": request_id,
        "attributes": attrs,
        "data": doc_data,
    }


def _write_attr(buf, tag, name, value):
    """Write one IPP attribute."""
    name_bytes = name.encode("utf-8") if name else b""
    if tag in (TAG_INTEGER, TAG_ENUM):
        val_bytes = struct.pack(">i", int(value))
    elif tag == TAG_BOOLEAN:
        val_bytes = bytes([1 if value else 0])
    else:
        val_bytes = str(value).encode("utf-8")
    buf.write(bytes([tag]))
    buf.write(struct.pack(">H", len(name_bytes)))
    buf.write(name_bytes)
    buf.write(struct.pack(">H", len(val_bytes)))
    buf.write(val_bytes)


def build_ipp_response(request_id, status, printer_attrs=None, job_attrs=None, jobs_attrs=None):
    """Build IPP response bytes. jobs_attrs is a list of job attribute lists for multiple jobs."""
    buf = io.BytesIO()
    # Version 1.1, status, request_id
    buf.write(struct.pack(">BBHI", 1, 1, status, request_id))

    # Operation attributes
    buf.write(bytes([TAG_OPERATION]))
    _write_attr(buf, TAG_CHARSET, "attributes-charset", "utf-8")
    _write_attr(buf, TAG_NATURAL_LANGUAGE, "attributes-natural-language", "en")

    if printer_attrs:
        buf.write(bytes([TAG_PRINTER]))
        for tag, name, value in printer_attrs:
            if isinstance(value, list):
                _write_attr(buf, tag, name, value[0])
                for v in value[1:]:
                    _write_attr(buf, tag, "", v)
            else:
                _write_attr(buf, tag, name, value)

    if job_attrs:
        buf.write(bytes([TAG_JOB]))
        for tag, name, value in job_attrs:
            if isinstance(value, list):
                _write_attr(buf, tag, name, value[0])
                for v in value[1:]:
                    _write_attr(buf, tag, "", v)
            else:
                _write_attr(buf, tag, name, value)

    if jobs_attrs:
        for attrs in jobs_attrs:
            buf.write(bytes([TAG_JOB]))
            for tag, name, value in attrs:
                if isinstance(value, list):
                    _write_attr(buf, tag, name, value[0])
                    for v in value[1:]:
                        _write_attr(buf, tag, "", v)
                else:
                    _write_attr(buf, tag, name, value)

    buf.write(bytes([TAG_END]))
    return buf.getvalue()


def make_printer_attributes(queued_job_count=0):
    """Return standard printer attributes for IPP responses."""
    uri = "ipp://localhost:8631/ipp/print"
    return [
        (TAG_URI, "printer-uri-supported", uri),
        (TAG_URI, "printer-uri", uri),
        (TAG_URI, "device-uri", uri),
        (TAG_KEYWORD, "uri-security-supported", "none"),
        (TAG_KEYWORD, "uri-authentication-supported", "none"),
        (TAG_NAME, "printer-name", "PaperCut_Virtual"),
        (TAG_NAME, "printer-make-and-model", "PaperCut Virtual Printer"),
        (TAG_TEXT, "printer-info", "HES-SO PaperCut Virtual Printer"),
        (TAG_TEXT, "printer-location", "Virtual"),
        (TAG_TEXT, "printer-more-info", uri),
        (TAG_URI, "printer-uuid", "urn:uuid:12345678-1234-1234-1234-123456789abc"),
        (TAG_ENUM, "printer-state", 3),  # idle
        (TAG_KEYWORD, "printer-state-reasons", "none"),
        (TAG_TEXT, "printer-state-message", "idle"),
        (TAG_KEYWORD, "ipp-versions-supported", ["1.1", "1.0"]),
        (TAG_ENUM, "operations-supported", [OP_PRINT_JOB, OP_VALIDATE_JOB, OP_CANCEL_JOB, OP_GET_JOB_ATTRIBUTES, OP_GET_JOBS, OP_GET_PRINTER_ATTRIBUTES, OP_PURGE_JOBS]),
        (TAG_CHARSET, "charset-configured", "utf-8"),
        (TAG_CHARSET, "charset-supported", "utf-8"),
        (TAG_NATURAL_LANGUAGE, "natural-language-configured", "en"),
        (TAG_NATURAL_LANGUAGE, "generated-natural-language-supported", "en"),
        (TAG_MIME_TYPE, "document-format-default", "application/pdf"),
        (TAG_MIME_TYPE, "document-format-supported", ["application/pdf", "application/postscript", "application/octet-stream", "image/urf"]),
        (TAG_BOOLEAN, "printer-is-accepting-jobs", True),
        (TAG_INTEGER, "queued-job-count", queued_job_count),
        (TAG_KEYWORD, "pdl-override-supported", "not-attempted"),
        (TAG_KEYWORD, "compression-supported", "none"),
        (TAG_KEYWORD, "multiple-document-handling-supported", ["single-document", "separate-documents-collated-copies", "separate-documents-uncollated-copies"]),
        (TAG_INTEGER, "copies-supported", 999),
        (TAG_KEYWORD, "print-color-mode-supported", ["monochrome", "auto"]),
        (TAG_KEYWORD, "job-password-encryption-supported", "none"),
        (TAG_KEYWORD, "media-col-supported", ["media-size", "media-type"]),
    ]


def make_job_attributes(job_id, state="pending", state_reasons=None, job_name=None):
    """Return job attributes for IPP responses."""
    # IPP job states: 3=pending, 5=processing, 7=canceled, 9=completed, 8=aborted
    state_map = {
        "queued": 3, "pending": 3,
        "processing": 5,
        "completed": 9,
        "cancelled": 7, "canceled": 7, "cancelling": 7,
        "failed": 8, "aborted": 8,
    }
    ipp_state = state_map.get(state, 3)
    if state_reasons is None:
        if ipp_state == 7:
            state_reasons = "job-canceled-by-user"
        elif ipp_state == 9:
            state_reasons = "job-completed-successfully"
        elif ipp_state == 8:
            state_reasons = "aborted-by-system"
        elif ipp_state == 5:
            state_reasons = "job-printing"
        else:
            state_reasons = "none"

    if ipp_state == 9:
        impressions = 1
        state_message = "completed"
    elif ipp_state == 7:
        impressions = 0
        state_message = "canceled"
    elif ipp_state == 8:
        impressions = 0
        state_message = "aborted"
    elif ipp_state == 5:
        impressions = 0
        state_message = "processing"
    else:
        impressions = 0
        state_message = "pending"

    return [
        (TAG_INTEGER, "job-id", job_id),
        (TAG_URI, "job-uri", f"ipp://localhost:8631/ipp/jobs/{job_id}"),
        (TAG_URI, "job-printer-uri", "ipp://localhost:8631/ipp/print"),
        (TAG_ENUM, "job-state", ipp_state),
        (TAG_KEYWORD, "job-state-reasons", state_reasons),
        (TAG_TEXT, "job-state-message", state_message),
        (TAG_NAME, "job-name", job_name or f"Print Job {job_id}"),
        (TAG_NAME, "job-originating-user-name", "gabrielzeizer"),
        (TAG_INTEGER, "job-impressions-completed", impressions),
        (TAG_INTEGER, "job-media-sheets-completed", impressions),
    ]