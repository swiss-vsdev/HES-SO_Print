# HES-SO Print

Desktop client for HES-SO PaperCut (WebPrint): view account stats, submit print jobs via Selenium, and run a local virtual print server (HTTP + IPP) that forwards jobs to PaperCut.

## Features

- **GUI (Tkinter):** login stored in OS keyring, account overview (balance/jobs/pages/CO₂/trees), recent jobs, print with size/color/duplex/copies and page-cost estimate.
- **Secure credentials:** stored in system keyring (`hes-so-papercut`), saved only after successful login.
- **Selenium WebPrint flow:** automated login/wizard/upload/submit with status/progress and cancel support.
- **Browser detection (auto):** Firefox/LibreWolf → installed Chromium/Chrome/Brave/Edge → Playwright Chromium cache → Safari (macOS) → PATH → (optional) Chromium download fallback.
  - Force engine: `--browser auto|chrome|chromium|firefox|gecko|librewolf|safari`
- **Virtual print server:** toggleable in app
  - HTTP API: `POST /print`, `GET /jobs`, `GET /jobs/{id}`, cancel endpoints (`127.0.0.1:8631`)
  - IPP endpoint: `ipp://127.0.0.1:8631/ipp/print` (basic ops for macOS printing/cancel handling)
- **Portable/buildable:** PyInstaller spec + scripts for macOS `.app`, Windows/Linux onedir builds, GitHub Actions workflow.

## Requirements

- Python 3.10+ (dev/build tested with 3.14 on macOS)
- A supported browser for Selenium: Firefox/LibreWolf, Chrome/Chromium/Brave/Edge, or Safari (macOS; requires Remote Automation)
- Network access to the PaperCut host (default `10.130.26.29`)

## Run from source

```bash
# with uv
uv run python -m papercut_app

# or
python3 -m papercut_app

# force browser engine
uv run python -m papercut_app --browser firefox
uv run python -m papercut_app --browser chrome
uv run python -m papercut_app --browser librewolf
uv run python -m papercut_app --browser safari
```

## Build (packaged app)

### macOS
```bash
./build.sh
# output: dist/HES-SO Print.app
```

### Linux / Windows
Build on the target OS (PyInstaller does not cross-compile):
```bash
bash scripts/build-linux.sh
```
```powershell
pwsh -File scripts/build-windows.ps1
```

### CI (all platforms)
GitHub Actions workflow: `.github/workflows/build.yml` (macOS/Windows/Linux artifacts).

## Virtual printer (macOS)

1. Start **Print Server** in the app.
2. Add printer: System Settings → Printers & Scanners → Add Printer → **IP**
   - Address: `127.0.0.1`
   - Protocol: **Internet Printing Protocol (IPP)**
   - Queue: `/ipp/print`
   - URI: `ipp://127.0.0.1:8631/ipp/print`

## Logs / troubleshooting

- App log: `~/.hes-papercut/app.log`
- IPP debug log: `/tmp/papercut_ipp.log`
- Run bundled app from terminal to see stdout/stderr:
  ```bash
  "dist/HES-SO Print.app/Contents/MacOS/HES-SO Print"
  ```
- macOS unsigned app: you may need right-click → Open on first launch.
- Safari: enable Develop → Allow Remote Automation and `safaridriver --enable`.
- Slim bundle does not include Playwright; install a browser locally (Chromium auto-download fallback requires Playwright).

## Repository layout

- `papercut_app/` — application package (`gui`, `http_engine`, `selenium_driver`, `virtual_printer`, `ipp_server`, etc.)
- `papercut_app.spec` — PyInstaller spec
- `scripts/` — platform build scripts
- `.github/workflows/build.yml` — multi-platform build workflow
