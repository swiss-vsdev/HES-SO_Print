"""
HES-SO PaperCut Print Client - Helper Functions
"""

import re
import time
import html as html_mod

def price_per_page(size, color):
    if size == "A4" and color == "Color":
        return 0.15
    return 0.05

def printer_name(size, color, duplex):
    name = "FollowMe"
    if size == "A3":
        name += "-A3"
    name += "-" + color
    if duplex:
        name += "-RV"
    return ("vmenpprint1", name)

def pdf_pages(path):
    try:
        import logging
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except Exception:
        pass
    try:
        with open(path, "rb") as f:
            data = f.read()
        return len(re.findall(rb"/Type\s*/Page(?![s])", data))
    except Exception:
        return None

def _trans(status):
    if not status or status.strip() == "?":
        return "Printed"
    s = status.lower()
    if "cancelled" in s or "annulé" in s:
        return "Cancelled"
    if "file d'attente" in s or "held" in s:
        return "Pending"
    if "printed" in s or "imprimé" in s:
        return "Printed"
    return status

def _pages(raw):
    """'1 (Color: 0)' -> '1'; keep only the page count."""
    if not raw:
        return raw
    return re.split(r'\s*\(', raw.strip())[0].strip()

def _parse_dt(raw):
    """Parse PaperCut date like 'Nov 12, 2026, 8:55:26 AM' -> datetime or None."""
    if not raw:
        return None
    m = re.match(r'([A-Za-z]{3})\.?\s+(\d{1,2}),?\s+(\d{4}),?\s+(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)?', raw.strip())
    if not m:
        return None
    mon = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
           "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    month = mon.get(m.group(1)[:3].title())
    if not month:
        return None
    try:
        hour = int(m.group(4))
        ampm = (m.group(7) or "").upper()
        if ampm == "PM" and hour != 12:
            hour += 12
        if ampm == "AM" and hour == 12:
            hour = 0
        return time.strptime(f"{int(m.group(3))}-{month}-{int(m.group(2))} {hour}:{m.group(5)}:{m.group(6)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

def _fmt24h(dt):
    """datetime -> '12.11.2026, 08:55:26' (European 24h)."""
    if not dt:
        return ""
    return time.strftime("%d.%m.%Y, %H:%M:%S", dt)

def _last_print_display(raw):
    """If today -> time only, else date (European)."""
    dt = _parse_dt(raw)
    if not dt:
        return raw or "—"
    now = time.localtime()
    if (dt.tm_year, dt.tm_mon, dt.tm_mday) == (now.tm_year, now.tm_mon, now.tm_mday):
        return time.strftime("%H:%M", dt)
    return time.strftime("%d.%m.%Y", dt)