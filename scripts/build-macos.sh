#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
APP_NAME="HES-SO Print"
VENV=".build-venv"
PYTHON_VERSION="${PYTHON_VERSION:-3.14.7}"
export PYINSTALLER_CONFIG_DIR="$PWD/.pyinstaller"

rm -rf build dist .pyinstaller "$VENV"
if command -v uv >/dev/null 2>&1; then
  uv python install "$PYTHON_VERSION"
  uv venv --python "$PYTHON_VERSION" "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  uv pip install --python "$VENV/bin/python" --upgrade pyinstaller selenium keyring pypdf fastapi uvicorn python-multipart
else
  python3 -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  python -m pip install --upgrade pip >/dev/null
  python -m pip install --upgrade pyinstaller selenium keyring pypdf fastapi uvicorn python-multipart
fi
python -m PyInstaller papercut_app.spec --noconfirm --clean
deactivate || true
echo "App: dist/${APP_NAME}.app"