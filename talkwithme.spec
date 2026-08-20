# -*- mode: python ; coding: utf-8 -*-
# Bouwen: venv\Scripts\pyinstaller talkwithme.spec
# Verwacht een SmartScreen-waarschuwing bij de eerste start en mogelijk
# antivirus-meldingen door de low-level keyboard hook (§1 van de spec).

a = Analysis(
    ["run_talkwithme.py"],
    pathex=[],
    binaries=[],
    datas=[("config.default.yaml", ".")],
    hiddenimports=[
        "win32timezone",
        "pystray._win32",
        "keyring.backends.Windows",
        "win32com.client",
    ],
    hookspath=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TalkWithMe",
    console=False,
    onefile=True,
    icon="assets_icon.ico",
)
