"""
HES-SO PaperCut Print Client
Fast, self-contained desktop app for PaperCut printing and account management.
"""

__version__ = "1.0.0"
__author__ = "Gabriel Zeizer"

from .config import (
    KEYRING_SERVICE,
    DEFAULT_HOST,
    DEFAULT_CHROME,
    VIRTUAL_PRINTER_PORT,
    load_credentials,
    save_credentials,
    clear_credentials,
)
from .helpers import (
    price_per_page,
    printer_name,
    pdf_pages,
    _trans,
    _pages,
    _parse_dt,
    _fmt24h,
    _last_print_display,
)
from .http_engine import PaperCutSession
from .selenium_driver import (
    find_chrome,
    download_chromium,
    selenium_submit_print,
)
from .virtual_printer import VirtualPrinterServer, HAS_FASTAPI
from .gui import LoginDialog, PaperCutGUI

__all__ = [
    "KEYRING_SERVICE",
    "DEFAULT_HOST",
    "DEFAULT_CHROME",
    "VIRTUAL_PRINTER_PORT",
    "load_credentials",
    "save_credentials",
    "clear_credentials",
    "price_per_page",
    "printer_name",
    "pdf_pages",
    "_trans",
    "_pages",
    "_parse_dt",
    "_fmt24h",
    "_last_print_display",
    "PaperCutSession",
    "find_chrome",
    "download_chromium",
    "selenium_submit_print",
    "VirtualPrinterServer",
    "HAS_FASTAPI",
    "LoginDialog",
    "PaperCutGUI",
]