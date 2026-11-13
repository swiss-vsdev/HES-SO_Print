#!/usr/bin/env python3
"""
HES-SO PaperCut Print Client - Direct Entry Point for uv run
Run from project root: uv run papercut_app/main.py
"""

import sys
import argparse
from pathlib import Path

# Add parent directory to path so papercut_app can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

import tkinter as tk
from papercut_app.gui import PaperCutGUI
from papercut_app.config import log


def _parse_args(argv=None):
    p = argparse.ArgumentParser(add_help=True)
    p.add_argument(
        "--browser",
        choices=["auto", "chrome", "chromium", "firefox", "gecko", "librewolf", "safari"],
        default="auto",
        help="Force browser engine for Selenium printing",
    )
    args, _ = p.parse_known_args(argv)
    return args


def main():
    try:
        args = _parse_args(sys.argv[1:])
        forced = None if args.browser == "auto" else args.browser
        log(f"app start (frozen={getattr(sys, 'frozen', False)} exe={sys.executable} browser={args.browser})")
        root = tk.Tk()
        app = PaperCutGUI(root, forced_browser=forced)
        root.mainloop()
        log("app exit")
    except Exception as e:
        log("app crashed", e)
        raise


if __name__ == "__main__":
    main()