# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for HES-SO Print (macOS .app)."""
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
APP_NAME = 'HES-SO Print'
if sys.platform == 'win32':
    icon_file = 'hes-so-printer-icon.ico' if os.path.exists('hes-so-printer-icon.ico') else None
elif sys.platform == 'darwin':
    icon_file = 'hes-so-printer-icon.icns' if os.path.exists('hes-so-printer-icon.icns') else None
else:
    icon_file = 'hes-icon.png' if os.path.exists('hes-icon.png') else None

hiddenimports = [
    'selenium', 'keyring', 'pypdf',
    'fastapi', 'uvicorn', 'starlette', 'pydantic', 'pydantic_core',
    'python_multipart', 'multipart', 'anyio', 'sniffio', 'idna', 'h11',
    'typing_extensions', 'annotated_types',
    'papercut_app', 'papercut_app.gui', 'papercut_app.config',
    'papercut_app.http_engine', 'papercut_app.selenium_driver',
    'papercut_app.virtual_printer', 'papercut_app.ipp_server', 'papercut_app.helpers',
]
for pkg in ('selenium', 'uvicorn', 'fastapi', 'starlette', 'pydantic', 'pydantic_core', 'anyio', 'multipart', 'python_multipart', 'keyring', 'pypdf'):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

a = Analysis(
    ['papercut_app/main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=list(dict.fromkeys(hiddenimports)),
    hookspath=[],
    runtime_hooks=[],
    excludes=['playwright', 'pytest', 'pip', 'setuptools', 'wheel', 'numpy', 'torch', 'cv2'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name=f'{APP_NAME}.app',
        icon=icon_file,
        bundle_identifier='ch.hesso.print',
        info_plist={
            'NSHighResolutionCapable': True,
            'CFBundleShortVersionString': '1.0.0',
            'CFBundleName': APP_NAME,
            'CFBundleDisplayName': APP_NAME,
        },
    )