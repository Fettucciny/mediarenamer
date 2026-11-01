"""OTA updates from GitHub releases.

The app checks https://github.com/Fettucciny/mediarenamer releases for a tag
newer than the running version, downloads the MediaRenamer-Setup.exe asset,
and runs it silently (/S). The installer replaces the files in
C:\\Program Files\\MediaRenamer and relaunches the app.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__

REPO = "Fettucciny/mediarenamer"
ASSET = "MediaRenamer-Setup.exe"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_HEADERS = {"User-Agent": f"mediarenamer/{__version__}",
            "Accept": "application/vnd.github+json"}


@dataclass
class Update:
    version: str
    notes: str
    url: str
    size: int


def _ver_tuple(v: str) -> tuple:
    parts = []
    for p in v.strip().lstrip("vV").split("."):
        num = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts or [0])


def is_newer(tag: str, current: str = __version__) -> bool:
    return _ver_tuple(tag) > _ver_tuple(current)


def check_latest(timeout: float = 10.0) -> Update | None:
    """Return the available Update, or None if up to date / unreachable."""
    req = urllib.request.Request(_API, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    tag = data.get("tag_name") or ""
    if not is_newer(tag):
        return None
    for asset in data.get("assets", []):
        if asset.get("name") == ASSET:
            return Update(version=tag.lstrip("vV"),
                          notes=(data.get("body") or "").strip(),
                          url=asset["browser_download_url"],
                          size=int(asset.get("size") or 0))
    return None


def download(upd: Update, progress=None) -> Path:
    """Download the installer to a temp file; progress(done, total) optional."""
    dest = Path(tempfile.gettempdir()) / f"MediaRenamer-Setup-{upd.version}.exe"
    req = urllib.request.Request(upd.url, headers={"User-Agent": _HEADERS["User-Agent"]})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or upd.size or 0)
        done = 0
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return dest


def launch_installer(setup: Path) -> None:
    """Start the silent installer and return; the caller should exit the app.

    The installer elevates itself (UAC prompt), waits for this process to
    exit, swaps the files in place, and relaunches the app.
    """
    subprocess.Popen([str(setup), "/S"], close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def running_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))
