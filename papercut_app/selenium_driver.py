"""
HES-SO PaperCut Print Client - Selenium Driver & Printing
"""

import os
import sys
import time
import subprocess
import shutil
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .config import DEFAULT_CHROME, CHROME_DIR

CHROME_PATHS = [
    # macOS
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Linux
    "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/brave-browser", "/usr/bin/microsoft-edge",
    "/usr/bin/microsoft-edge-stable",
    "/snap/bin/chromium", "/snap/bin/brave", "/snap/bin/microsoft-edge",
    "/opt/google/chrome/chrome",
    "/opt/chromium/chromium",
    "/opt/microsoft/msedge/msedge",
    # Windows
    "C:\\Program Files\\Chromium\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Chromium\\Application\\chrome.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
    "C:\\Program Files (x86)\\BraveSoftware\\Brave-Browser\\Application\\brave.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
]

FIREFOX_PATHS = [
    # macOS
    "/Applications/Firefox.app/Contents/MacOS/firefox",
    "/Applications/Firefox Developer Edition.app/Contents/MacOS/firefox",
    "/Applications/Firefox Nightly.app/Contents/MacOS/firefox",
    "/Applications/LibreWolf.app/Contents/MacOS/librewolf",
    # Linux
    "/usr/bin/firefox",
    "/usr/bin/firefox-esr",
    "/usr/bin/librewolf",
    "/snap/bin/firefox",
    "/snap/bin/librewolf",
    "/usr/local/bin/firefox",
    "/usr/local/bin/librewolf",
    "/opt/firefox/firefox",
    # Windows
    "C:\\Program Files\\Mozilla Firefox\\firefox.exe",
    "C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe",
    "C:\\Program Files\\LibreWolf\\librewolf.exe",
]

SAFARI_PATHS = [
    "/Applications/Safari.app/Contents/MacOS/Safari",
    "/System/Cryptexes/App/System/Applications/Safari.app/Contents/MacOS/Safari",
]


def _browser_kind(path):
    name = os.path.basename(path or "").lower()
    p = (path or "").lower()
    if "safari" in name or "/safari.app/" in p:
        return "safari"
    if "firefox" in name or "librewolf" in name:
        return "firefox"
    return "chrome"


def _find_first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def _playwright_cache_dirs():
    dirs = []
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        appdata = os.environ.get("APPDATA")
        if local:
            dirs.append(os.path.join(local, "ms-playwright"))
        if appdata:
            dirs.append(os.path.join(appdata, "ms-playwright"))
    else:
        dirs.append(os.path.expanduser("~/.cache/ms-playwright"))
    return dirs


def _find_playwright_chromium():
    for pw_dir in _playwright_cache_dirs():
        if os.path.isdir(pw_dir):
            for d in sorted(os.listdir(pw_dir)):
                if d.startswith("chromium"):
                    for root, _, files in os.walk(os.path.join(pw_dir, d)):
                        for f in files:
                            if f in ("chrome", "chromium", "chrome.exe"):
                                return os.path.join(root, f)
    return None


def _normalize_preference(preferred):
    if preferred in (None, "auto"):
        return "auto"
    if preferred in ("firefox", "gecko", "librewolf"):
        return "firefox"
    if preferred in ("chrome", "chromium"):
        return "chrome"
    if preferred == "safari":
        return "safari"
    return "auto"


def find_browser(browser_path=None, allow_download=True, preferred=None):
    """Find available browser. preferred: auto|chrome|chromium|firefox|gecko|librewolf|safari."""
    pref = _normalize_preference(preferred)

    # 1. Configured/preferred path if compatible with preference
    if browser_path and os.path.exists(browser_path):
        if pref == "auto" or _browser_kind(browser_path) == pref:
            return browser_path

    if pref == "firefox":
        path = _find_first_existing(FIREFOX_PATHS) or shutil.which("firefox") or shutil.which("librewolf")
        return path

    if pref == "safari":
        if sys.platform != "darwin":
            return None
        path = _find_first_existing(SAFARI_PATHS) or ("/Applications/Safari.app/Contents/MacOS/Safari" if sys.platform == "darwin" else None)
        if path and os.path.exists(path):
            return path
        return None

    if pref == "chrome":
        path = _find_first_existing(CHROME_PATHS)
        if not path:
            path = _find_playwright_chromium()
        if not path:
            for cmd in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable", "brave-browser", "brave"):
                path = shutil.which(cmd)
                if path:
                    break
        if not path and allow_download:
            try:
                download_chromium()
                path = _find_playwright_chromium() or _find_first_existing(CHROME_PATHS)
            except Exception:
                pass
        return path

    # auto: Firefox/LibreWolf -> Chromium/Chrome-family -> Playwright Chromium -> Safari (macOS) -> PATH -> download Chromium
    path = _find_first_existing(FIREFOX_PATHS)
    if path:
        return path
    path = _find_first_existing(CHROME_PATHS)
    if path:
        return path
    path = _find_playwright_chromium()
    if path:
        return path
    if sys.platform == "darwin":
        path = _find_first_existing(SAFARI_PATHS)
        if path:
            return path
    for cmd in ("firefox", "librewolf", "google-chrome", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable", "brave-browser", "brave"):
        p = shutil.which(cmd)
        if p:
            return p
    if allow_download:
        try:
            download_chromium()
            path = _find_playwright_chromium() or _find_first_existing(CHROME_PATHS)
            if path:
                return path
        except Exception:
            pass
    return None


# Backward-compatible names
def find_chrome(chrome_path=None):
    return find_browser(chrome_path, allow_download=True, preferred="chrome")


def download_chromium():
    """Download only Chromium browser binary, skip system deps (ffmpeg, fonts, etc.)."""
    os.makedirs(CHROME_DIR, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "--no-deps", "chromium"],
        check=True, timeout=300
    )


def _create_driver(browser_path=None, preferred=None):
    if browser_path is None or not os.path.exists(browser_path) or (
        _normalize_preference(preferred) != "auto" and _browser_kind(browser_path) != _normalize_preference(preferred)
    ):
        browser_path = find_browser(browser_path, preferred=preferred)
    if not browser_path or not os.path.exists(browser_path):
        raise RuntimeError("No supported browser found for requested engine (Chrome/Chromium/Edge/Brave/Firefox/LibreWolf/Safari).")

    kind = _browser_kind(browser_path)
    if kind == "firefox":
        from selenium.webdriver.firefox.options import Options as FirefoxOptions
        from selenium.webdriver.firefox.service import Service as FirefoxService
        opts = FirefoxOptions()
        opts.binary_location = browser_path
        opts.add_argument("-headless")
        opts.set_preference("accept_insecure_certs", True)
        opts.set_preference("intl.accept_languages", "en-US, en")
        opts.set_preference("privacy.resistFingerprinting", False)
        opts.set_capability("unhandledPromptBehavior", "dismiss")
        try:
            service = FirefoxService(log_output=os.devnull)
            driver = webdriver.Firefox(service=service, options=opts)
        except Exception:
            driver = webdriver.Firefox(options=opts)
    elif kind == "safari":
        if sys.platform != "darwin":
            raise RuntimeError("Safari WebDriver is only available on macOS.")
        from selenium.webdriver.safari.options import Options as SafariOptions
        opts = SafariOptions()
        # Safari: headless not supported; requires "Allow Remote Automation" + safaridriver enabled
        try:
            driver = webdriver.Safari(options=opts)
        except Exception:
            driver = webdriver.Safari()
    else:
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        opts = ChromeOptions()
        opts.binary_location = browser_path
        opts.add_argument("--headless=new")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-logging")
        opts.add_argument("--log-level=3")
        opts.add_experimental_option("excludeSwitches", ["enable-logging"])
        try:
            from selenium.webdriver.chrome.service import Service as ChromeService
            service = ChromeService(log_output=os.devnull)
            driver = webdriver.Chrome(service=service, options=opts)
        except Exception:
            driver = webdriver.Chrome(options=opts)

    driver.set_page_load_timeout(30)
    return driver


def _login(driver, host, username, password, status_cb):
    status_cb("Logging in...")
    driver.get(f"https://{host}/user")
    time.sleep(2)
    username_el = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "inputUsername"))
    )
    username_el.send_keys(username)
    password_el = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "inputPassword"))
    )
    password_el.send_keys(password, Keys.RETURN)
    time.sleep(3)


def selenium_submit_print(host, username, password, printer, file_path, copies=1,
                          chrome_path=DEFAULT_CHROME, status_cb=lambda m: None, should_cancel=lambda: False, browser_preference=None):
    driver = _create_driver(chrome_path, preferred=browser_preference)
    wait = WebDriverWait(driver, 15)
    try:
        _login(driver, host, username, password, status_cb)
        if should_cancel():
            status_cb("Cancelled.")
            return "cancelled"

        # Open WebPrint page
        status_cb("Opening print wizard...")
        driver.get(f"https://{host}/app?service=page/UserWebPrint")
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn[onclick*='disableUserWebPrintStartLink']")))
        if should_cancel():
            status_cb("Cancelled.")
            return "cancelled"

        # Click "Submit a Job"
        sendfile = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn[onclick*='disableUserWebPrintStartLink']"))
        )
        driver.execute_script("arguments[0].click();", sendfile)
        wait.until(lambda d: d.execute_script("return typeof selectPrinter === 'function';"))
        if should_cancel():
            status_cb("Cancelled.")
            return "cancelled"

        # Select printer
        status_cb("Selecting printer...")
        server_name, printer_name_ = printer
        driver.execute_script(f"selectPrinter('{server_name}', '{printer_name_}');")
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='$Submit'][value*='Document']")))
        if should_cancel():
            status_cb("Cancelled.")
            return "cancelled"

        # Copies
        if copies > 1:
            copies_input = wait.until(EC.presence_of_element_located((By.ID, "copies-input")))
            copies_input.clear()
            copies_input.send_keys(str(copies))

        # Click "2. Print Options and Account Selection"
        doc_btn = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name='$Submit'][value*='Document']"))
        )
        doc_btn.click()
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
        if should_cancel():
            status_cb("Cancelled.")
            return "cancelled"

        # Upload file
        status_cb("Uploading file...")
        time.sleep(1)
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        target = next((i for i in file_inputs if i.get_attribute("id") != "upload-input"), None)
        if not target:
            target = driver.find_element(By.ID, "upload-input")
        target.send_keys(os.path.abspath(file_path))
        time.sleep(5)
        if should_cancel():
            status_cb("Cancelled.")
            return "cancelled"

        # Submit
        submit = wait.until(EC.presence_of_element_located((By.ID, "upload")))
        driver.execute_script("arguments[0].click();", submit)
        time.sleep(8)
        if should_cancel():
            status_cb("Cancelled.")
            return "cancelled"

        status_cb("Print job submitted!")
        return "done"
    except Exception as e:
        status_cb(f"Error: {e}")
        return "error"
    finally:
        driver.quit()