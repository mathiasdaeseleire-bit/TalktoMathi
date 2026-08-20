r"""Self-update from GitHub Releases.

Windows locks a running .exe, so the app cannot overwrite itself. The
usual dance: download the new build next to the old one, then hand off to
a small batch script that waits for this process to exit, swaps the
files, and relaunches. The script deletes itself afterwards.

A release is discovered through the GitHub API: the newest release's tag
(v1.2.3) is compared against __version__, and the asset named
TalkWithMe.exe is what gets downloaded.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass

import httpx

from . import __version__
from .install import APP_NAME, INSTALL_DIR, INSTALLED_EXE

log = logging.getLogger("talkwithme.updater")

API_TEMPLATE = "https://api.github.com/repos/{repo}/releases/latest"
ASSET_NAME = f"{APP_NAME}.exe"
TIMEOUT_S = 15.0


@dataclass
class Release:
    version: str
    tag: str
    url: str
    notes: str
    size: int

    @property
    def size_mb(self) -> float:
        return self.size / (1024 * 1024)


class UpdateError(Exception):
    pass


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Unparseable pieces sort as 0 rather than
    raising, so a stray tag can't break the comparison."""
    cleaned = re.sub(r"^[vV]", "", (text or "").strip())
    parts = re.split(r"[.\-+]", cleaned)
    numbers: list[int] = []
    for part in parts:
        match = re.match(r"\d+", part)
        if not match:
            break
        numbers.append(int(match.group()))
    return tuple(numbers) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def check(repo: str) -> Release | None:
    """Returns the latest release when it's newer than what's running."""
    if not repo:
        return None
    try:
        resp = httpx.get(API_TEMPLATE.format(repo=repo),
                          headers={"Accept": "application/vnd.github+json"},
                          timeout=TIMEOUT_S, follow_redirects=True)
    except Exception as e:
        raise UpdateError(f"kon GitHub niet bereiken: {e}") from e

    if resp.status_code == 404:
        raise UpdateError(f"geen releases gevonden voor {repo}")
    if resp.status_code != 200:
        raise UpdateError(f"GitHub gaf HTTP {resp.status_code}")

    data = resp.json()
    tag = data.get("tag_name") or ""
    if not is_newer(tag):
        return None

    asset = next((a for a in data.get("assets", [])
                   if a.get("name", "").lower() == ASSET_NAME.lower()), None)
    if asset is None:
        raise UpdateError(f"release {tag} bevat geen {ASSET_NAME}")

    return Release(
        version=re.sub(r"^[vV]", "", tag),
        tag=tag,
        url=asset["browser_download_url"],
        notes=(data.get("body") or "").strip(),
        size=int(asset.get("size") or 0),
    )


def download(release: Release, progress=None) -> str:
    """Fetch the new build next to the installed one. Returns its path."""
    os.makedirs(INSTALL_DIR, exist_ok=True)
    target = os.path.join(INSTALL_DIR, f"{APP_NAME}.new.exe")
    tmp = target + ".part"
    try:
        with httpx.stream("GET", release.url, timeout=TIMEOUT_S,
                           follow_redirects=True) as resp:
            if resp.status_code != 200:
                raise UpdateError(f"download gaf HTTP {resp.status_code}")
            total = int(resp.headers.get("content-length") or release.size or 0)
            done = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=262144):
                    f.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done / total)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"download mislukt: {e}") from e

    if os.path.getsize(tmp) < 1_000_000:
        os.remove(tmp)
        raise UpdateError("gedownload bestand is verdacht klein, afgebroken")

    os.replace(tmp, target)
    return target


def apply_and_restart(new_exe: str) -> None:
    """Hand off to a batch script and quit: the running exe is locked, so
    the swap has to happen after this process is gone."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("bijwerken kan alleen vanaf de gebouwde .exe")

    target = INSTALLED_EXE if os.path.exists(INSTALLED_EXE) else sys.executable
    script = os.path.join(tempfile.gettempdir(), f"{APP_NAME}_update.cmd")

    # /pid waits for this process; the retry loop covers a slow exit.
    with open(script, "w", encoding="ascii", errors="ignore") as f:
        f.write(f"""@echo off
setlocal
set "TARGET={target}"
set "NEWEXE={new_exe}"
:wait
tasklist /FI "PID eq {os.getpid()}" 2>nul | find "{os.getpid()}" >nul
if not errorlevel 1 (
    ping -n 2 127.0.0.1 >nul
    goto wait
)
for /L %%i in (1,1,20) do (
    move /Y "%TARGET%" "%TARGET%.old" >nul 2>&1
    move /Y "%NEWEXE%" "%TARGET%" >nul 2>&1
    if exist "%TARGET%" if not exist "%NEWEXE%" goto done
    ping -n 2 127.0.0.1 >nul
)
:done
del "%TARGET%.old" >nul 2>&1
start "" "%TARGET%"
del "%~f0" >nul 2>&1
""")

    subprocess.Popen(["cmd", "/c", script],
                      creationflags=subprocess.CREATE_NO_WINDOW
                      | subprocess.DETACHED_PROCESS,
                      close_fds=True)
