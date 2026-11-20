# -*- mode: python ; coding: utf-8 -*-
"""Reproducible PyInstaller onedir build for VencordAutoRepair."""

from pathlib import Path


ROOT = Path(SPECPATH).resolve()
APP_NAME = "VencordAutoRepair"
ASSETS = ROOT / "assets"

datas = [
    (str(ASSETS / "VencordAutoRepair.ico"), "assets"),
    (str(ASSETS / "VencordAutoRepair.png"), "assets"),
    (str(ROOT / "LICENSE"), "."),
    (
        str(ASSETS / "package_metadata" / "VencordAutoRepair-0.4.1.dist-info"),
        "VencordAutoRepair-0.4.1.dist-info",
    ),
]

hiddenimports = [
    "app_runtime",
    "gui",
    "main",
    "startup_manager",
    "pythoncom",
    "pywintypes",
    "win32api",
    "win32com",
    "win32com.client",
    "win32security",
]

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["_pytest", "pytest", "test_main", "tests"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

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
    disable_windowed_traceback=False,
    icon=str(ASSETS / "VencordAutoRepair.ico"),
    version=str(ASSETS / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

