$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$AppName = "HES-SO Print"
$Venv = ".build-venv"
$Python = if ($env:PYTHON_VERSION) { $env:PYTHON_VERSION } else { "3.14" }
$env:PYINSTALLER_CONFIG_DIR = Join-Path (Get-Location) ".pyinstaller"

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, .pyinstaller, $Venv

if (Get-Command uv -ErrorAction SilentlyContinue) {
  uv venv --python $Python $Venv
  & "$Venv\Scripts\Activate.ps1"
  uv pip install --python "$Venv\Scripts\python.exe" --upgrade pyinstaller selenium keyring pypdf fastapi uvicorn python-multipart
} else {
  python -m venv $Venv
  & "$Venv\Scripts\Activate.ps1"
  python -m pip install --upgrade pip
  python -m pip install --upgrade pyinstaller selenium keyring pypdf fastapi uvicorn python-multipart
}

# Create .ico if missing (PyInstaller on Windows prefers .ico)
if (-not (Test-Path "hes-so-printer-icon.ico") -and (Test-Path "hes-icon.png")) {
  python -m pip install --upgrade pillow | Out-Null
  python -c "from PIL import Image; img=Image.open('hes-icon.png'); img.save('hes-so-printer-icon.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"
}

python -m PyInstaller papercut_app.spec --noconfirm --clean
Write-Host "Output: dist\$AppName\"