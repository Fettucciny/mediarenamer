"""Build dist/MediaRenamer-Setup.exe.

Steps: PyInstaller onedir build of the GUI -> zip it -> PyInstaller onefile
build of the installer stub with the zip and version embedded.

Usage: python tools/build_installer.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from mediarenamer import __version__  # noqa: E402


def run(*cmd: str) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    icon = ROOT / "assets" / "icon.ico"
    gui_icon = ROOT / "src" / "mediarenamer" / "gui" / "icon.ico"
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed",
        "--name", "MediaRenamer", "--collect-submodules", "mediarenamer",
        "--icon", str(icon),
        "--add-data", f"{gui_icon};mediarenamer/gui",
        "-p", "src", "--specpath", "build_spec", "tools/entry_gui.py")

    app_dir = ROOT / "dist" / "MediaRenamer"
    app_zip = ROOT / "build" / "app.zip"
    app_zip.parent.mkdir(exist_ok=True)
    print("+ zipping", app_dir)
    with zipfile.ZipFile(app_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in app_dir.rglob("*"):
            z.write(p, Path("MediaRenamer") / p.relative_to(app_dir))

    ver_file = ROOT / "build" / "VERSION"
    ver_file.write_text(__version__)

    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile",
        "--name", "MediaRenamer-Setup", "--uac-admin", "--icon", str(icon),
        "--add-data", f"{app_zip};.", "--add-data", f"{ver_file};.",
        "--specpath", "build_spec", "tools/installer_stub.py")

    setup = ROOT / "dist" / "MediaRenamer-Setup.exe"
    print(f"done: {setup} ({setup.stat().st_size / 1e6:.1f} MB), version {__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
