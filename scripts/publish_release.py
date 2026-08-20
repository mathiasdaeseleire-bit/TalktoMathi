"""Publish a GitHub release with the built exe as its asset.

Credentials come from the git credential helper — the same ones git
already used to push — so no token is ever written to a file or printed.

Usage:
    venv\\Scripts\\python scripts\\publish_release.py [--draft]

The asset must be named exactly TalkWithMe.exe: the updater looks the
release up by that name and ignores anything else.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from talkwithme import __version__
from talkwithme.install import APP_NAME

REPO = "mathiasdaeseleire-bit/TalkwithMe"
ASSET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "dist", f"{APP_NAME}.exe")
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def github_token() -> str:
    """Ask git's credential helper, exactly as git itself would."""
    result = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, check=True)
    for line in result.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise SystemExit("Geen GitHub-inloggegevens gevonden. Push eerst een keer met git.")


def notes_for(version: str) -> str:
    """Pull this version's section out of the changelog."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "CHANGELOG.md")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return ""

    out, collecting = [], False
    for line in lines:
        if line.startswith("## "):
            if collecting:
                break
            collecting = line.strip() == f"## {version}"
            continue
        if collecting:
            out.append(line)
    return "\n".join(out).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", action="store_true",
                        help="maak een concept in plaats van te publiceren")
    args = parser.parse_args()

    if not os.path.exists(ASSET):
        raise SystemExit(f"Niet gevonden: {ASSET}\nBouw eerst met pyinstaller.")

    tag = f"v{__version__}"
    size_mb = os.path.getsize(ASSET) / (1024 * 1024)
    token = github_token()
    auth = {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"}

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        existing = client.get(f"{API}/repos/{REPO}/releases/tags/{tag}", headers=auth)
        if existing.status_code == 200:
            raise SystemExit(f"Release {tag} bestaat al. Verhoog __version__ eerst.")

        print(f"Release {tag} aanmaken in {REPO} ...")
        created = client.post(
            f"{API}/repos/{REPO}/releases", headers=auth,
            json={"tag_name": tag, "name": tag, "body": notes_for(__version__),
                  "draft": args.draft, "prerelease": False})
        if created.status_code not in (200, 201):
            raise SystemExit(f"Aanmaken mislukt: HTTP {created.status_code}\n"
                              f"{created.text[:400]}")

        release = created.json()
        upload_url = release["upload_url"].split("{")[0]

        print(f"{APP_NAME}.exe uploaden ({size_mb:.0f} MB) ...")
        with open(ASSET, "rb") as f:
            uploaded = client.post(
                upload_url, headers={**auth, "Content-Type": "application/octet-stream"},
                params={"name": f"{APP_NAME}.exe"}, content=f.read())
        if uploaded.status_code not in (200, 201):
            raise SystemExit(f"Upload mislukt: HTTP {uploaded.status_code}\n"
                              f"{uploaded.text[:400]}")

    print(f"Klaar: {release['html_url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
