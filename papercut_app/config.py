"""
HES-SO PaperCut Print Client - Configuration and Constants
"""

import os
import json
import time
import traceback
import keyring

KEYRING_SERVICE = "hes-so-papercut"
KEYRING_ACCOUNT = "data"
DEFAULT_HOST = "10.130.26.29"
DEFAULT_CHROME = "/Applications/Chromium.app/Contents/MacOS/Chromium"
VIRTUAL_PRINTER_PORT = 8631
CHROME_DIR = os.path.expanduser("~/.hes-papercut/chromium")
APP_DIR = os.path.expanduser("~/.hes-papercut")
LOG_PATH = os.path.join(APP_DIR, "app.log")


def log(msg, exc=None):
    """Append a timestamped message to app log (for bundled app debugging)."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
            if exc is not None:
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except Exception:
        pass


def _load_blob():
    """Load all stored data from a single keyring item (minimizes keychain prompts)."""
    try:
        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    # Migrate legacy multi-item storage if present
    try:
        username = keyring.get_password(KEYRING_SERVICE, "username")
        password = keyring.get_password(KEYRING_SERVICE, "password")
        if username and password:
            data = {
                "username": username,
                "password": password,
                "host": keyring.get_password(KEYRING_SERVICE, "host") or DEFAULT_HOST,
                "chrome_path": keyring.get_password(KEYRING_SERVICE, "chrome_path") or DEFAULT_CHROME,
                "auto_boot_server": keyring.get_password(KEYRING_SERVICE, "auto_boot_server") == "1",
            }
            _save_blob(data)
            for key in ("username", "password", "host", "chrome_path", "auto_boot_server"):
                try:
                    keyring.delete_password(KEYRING_SERVICE, key)
                except Exception:
                    pass
            return data
    except Exception:
        pass
    return {}


def _save_blob(data):
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, json.dumps(data))
    except Exception as e:
        print(f"Warning: could not save to keyring: {e}")


def load_credentials():
    """Load saved credentials/settings (single keychain access)."""
    data = _load_blob()
    username = data.get("username", "")
    password = data.get("password", "")
    host = data.get("host") or DEFAULT_HOST
    chrome_path = data.get("chrome_path") or DEFAULT_CHROME
    if username and password:
        return {"username": username, "password": password, "host": host, "chrome_path": chrome_path}
    return {}


def save_credentials(username, password, host=DEFAULT_HOST, chrome_path=DEFAULT_CHROME):
    """Save credentials after successful login (preserves other settings)."""
    data = _load_blob()
    data.update({
        "username": username,
        "password": password,
        "host": host or DEFAULT_HOST,
        "chrome_path": chrome_path or DEFAULT_CHROME,
    })
    _save_blob(data)


def load_auto_boot_server():
    """Return True if the print server should auto-start when the app opens."""
    return bool(_load_blob().get("auto_boot_server", False))


def save_auto_boot_server(value):
    """Persist auto-boot preference in the system keyring."""
    data = _load_blob()
    data["auto_boot_server"] = bool(value)
    _save_blob(data)


def clear_credentials():
    """Remove saved credentials/settings from keyring."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except Exception:
        pass
    # Also clear legacy keys if any remain
    for key in ("username", "password", "host", "chrome_path", "auto_boot_server"):
        try:
            keyring.delete_password(KEYRING_SERVICE, key)
        except Exception:
            pass