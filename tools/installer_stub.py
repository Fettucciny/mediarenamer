"""MediaRenamer-Setup.exe — self-contained installer.

Bundled by PyInstaller --onefile with app.zip (the PyInstaller onedir build)
embedded. Installs to C:\\Program Files\\MediaRenamer, creates Start Menu and
Desktop shortcuts, and registers an uninstall entry.

Flags:
  /S          silent install (used for OTA updates); relaunches the app after
  /uninstall  remove the install directory, shortcuts and registry entry
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
import winreg
import zipfile
from pathlib import Path

APP = "MediaRenamer"
INSTALL_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / APP
UNINST_KEY = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{APP}"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated() -> None:
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    sys.exit(0 if rc > 32 else 1)


def msg(text: str, title: str = APP) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)


def kill_running() -> None:
    subprocess.run(["taskkill", "/IM", f"{APP}.exe", "/F"],
                   capture_output=True, creationflags=0x08000000)
    time.sleep(1.0)


def shortcuts(create: bool) -> None:
    start_menu = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / \
        "Microsoft/Windows/Start Menu/Programs" / f"{APP}.lnk"
    desktop = Path.home() / "Desktop" / f"{APP}.lnk"
    for lnk in (start_menu, desktop):
        if not create:
            lnk.unlink(missing_ok=True)
            continue
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
              f"$s.TargetPath='{INSTALL_DIR / (APP + '.exe')}';"
              f"$s.WorkingDirectory='{INSTALL_DIR}';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, creationflags=0x08000000)


def register(version: str) -> None:
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, UNINST_KEY) as k:
        def put(name, val):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        put("DisplayName", APP)
        put("DisplayVersion", version)
        put("Publisher", "Fettucciny")
        put("InstallLocation", str(INSTALL_DIR))
        put("DisplayIcon", str(INSTALL_DIR / f"{APP}.exe"))
        put("UninstallString", f'"{INSTALL_DIR / "Setup.exe"}" /uninstall')


def unregister() -> None:
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, UNINST_KEY)
    except OSError:
        pass


def install(silent: bool) -> None:
    src = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "app.zip"
    version = (Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "VERSION").read_text().strip()
    kill_running()
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    # extract to a staging dir, then swap files so a locked exe fails loudly
    stage = INSTALL_DIR.with_name(APP + ".new")
    shutil.rmtree(stage, ignore_errors=True)
    with zipfile.ZipFile(src) as z:
        z.extractall(stage)
    inner = stage / APP if (stage / APP).is_dir() else stage
    for attempt in range(5):
        try:
            shutil.rmtree(INSTALL_DIR, ignore_errors=False)
            break
        except OSError:
            time.sleep(1.5)
    shutil.move(str(inner), str(INSTALL_DIR))
    shutil.rmtree(stage, ignore_errors=True)
    # keep a copy of this installer for uninstall
    try:
        shutil.copy2(sys.executable, INSTALL_DIR / "Setup.exe")
    except OSError:
        pass
    shortcuts(create=True)
    register(version)
    if silent:
        subprocess.Popen([str(INSTALL_DIR / f"{APP}.exe")], close_fds=True)
    else:
        msg(f"{APP} {version} installed to\n{INSTALL_DIR}")
        subprocess.Popen([str(INSTALL_DIR / f"{APP}.exe")], close_fds=True)


def uninstall() -> None:
    kill_running()
    shortcuts(create=False)
    unregister()
    # this exe lives inside INSTALL_DIR; delete via a detached cmd after exit
    cmd = f'ping -n 3 127.0.0.1 >nul & rmdir /s /q "{INSTALL_DIR}"'
    subprocess.Popen(["cmd", "/c", cmd], creationflags=0x08000208)
    msg(f"{APP} removed.")


def main() -> int:
    args = [a.lower() for a in sys.argv[1:]]
    if not is_admin():
        relaunch_elevated()
    if "/uninstall" in args:
        uninstall()
    else:
        install(silent="/s" in args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
