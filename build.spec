# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Donate Studio — --onedir build, zero-install exe.

Build on Windows:  pyinstaller build.spec
Output: dist/DonateStudio/DonateStudio.exe  (+ whole folder, ship it together)
"""
import os

block_cipher = None

FONT_SRC = os.path.join(os.path.abspath("."), "fonts", "BNazanin.ttf")
if not os.path.isfile(FONT_SRC):
    # fallback for local dev machines
    FONT_SRC = os.path.expanduser("~/workspace/user/files/BNazanin.ttf")
datas = []
if os.path.isfile(FONT_SRC):
    # bundled as fonts/BNazanin.ttf next to the exe; the engine picks it up
    # via sys._MEIPASS automatically.
    datas.append((FONT_SRC, "fonts"))

a = Analysis(
    ["app.py"],
    pathex=[os.path.abspath(".")],
    binaries=[],
    datas=datas,
    hiddenimports=["PIL", "numpy", "arabic_reshaper", "bidi"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DonateStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DonateStudio",
)
