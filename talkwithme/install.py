r"""Installing TalkWithMe properly: a stable home, a Start-menu entry, and
autostart at login.

Running from dist\ inside the build folder works but is fragile — a
rebuild replaces the file underneath a pinned shortcut, and moving the
project breaks it. So install() copies the exe to a per-user location the
way real Windows apps do, and points everything at that copy.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys

from . import autostart
from .icon import save_ico

log = logging.getLogger("talkwithme.install")

APP_NAME = "TalkWithMe"
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                            "Programs", APP_NAME)
INSTALLED_EXE = os.path.join(INSTALL_DIR, f"{APP_NAME}.exe")
ICON_PATH = os.path.join(INSTALL_DIR, f"{APP_NAME}.ico")
START_MENU_DIR = os.path.join(os.environ.get("APPDATA", ""),
                               r"Microsoft\Windows\Start Menu\Programs")
SHORTCUT_PATH = os.path.join(START_MENU_DIR, f"{APP_NAME}.lnk")


def is_installed() -> bool:
    return os.path.exists(INSTALLED_EXE)


def running_from_install_dir() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    return os.path.normcase(sys.executable) == os.path.normcase(INSTALLED_EXE)


def _create_shortcut(path: str, target: str, icon: str | None = None,
                      description: str = "") -> None:
    """A .lnk via the Windows Script Host COM object — the only way to make
    a real shortcut without shipping extra dependencies."""
    import win32com.client
    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortCut(path)
    link.TargetPath = target
    link.WorkingDirectory = os.path.dirname(target)
    link.Description = description or f"{APP_NAME} — dicteren met je stem"
    # Point at the icon embedded in the exe rather than a loose .ico:
    # Windows refreshes that reliably, and there is no second file to
    # go missing or fall out of date.
    if icon and os.path.exists(icon):
        link.IconLocation = icon
    else:
        link.IconLocation = f"{target},0"
    link.save()


def install(source_exe: str | None = None) -> str:
    """Copy the exe into place, add a Start-menu entry, enable autostart.
    Returns the installed exe path."""
    source = source_exe or (sys.executable if getattr(sys, "frozen", False) else None)
    if source is None:
        raise RuntimeError(
            "Installeren kan alleen vanaf de gebouwde .exe "
            "(bouw eerst met: pyinstaller talkwithme.spec)")

    os.makedirs(INSTALL_DIR, exist_ok=True)

    if os.path.normcase(source) != os.path.normcase(INSTALLED_EXE):
        # Windows locks a running exe, so a reinstall over a live copy
        # fails; move the old one aside first and let it go on reboot.
        if os.path.exists(INSTALLED_EXE):
            stale = INSTALLED_EXE + ".old"
            try:
                if os.path.exists(stale):
                    os.remove(stale)
                os.replace(INSTALLED_EXE, stale)
            except OSError as e:
                log.warning("kon oude versie niet opzijzetten: %s", e)
        shutil.copy2(source, INSTALLED_EXE)

    try:
        save_ico(ICON_PATH)
    except Exception as e:
        log.warning("kon icoon niet schrijven: %s", e)

    try:
        _create_shortcut(SHORTCUT_PATH, INSTALLED_EXE, f"{INSTALLED_EXE},0")
    except Exception as e:
        log.warning("kon Start-menu snelkoppeling niet maken: %s", e)

    autostart.enable()
    return INSTALLED_EXE


def uninstall() -> None:
    autostart.disable()
    for path in (SHORTCUT_PATH, ICON_PATH):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError as e:
            log.warning("kon %s niet verwijderen: %s", path, e)
