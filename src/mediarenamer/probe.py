"""Video format ({vf}) and codec ({vc}) the way FileBot reports them.

Order of evidence: MediaInfo library if one can be found (FileBot ships one),
then the file name's own tags, then nothing. Never raises.
"""
from __future__ import annotations

import ctypes
import os
import re
from functools import lru_cache
from pathlib import Path

_DLL_CANDIDATES = [
    os.environ.get("MEDIAINFO_DLL", ""),
    r"C:\Program Files\FileBot\lib\MediaInfo.dll",
    r"C:\Program Files\MediaInfo\MediaInfo.dll",
    "MediaInfo.dll", "libmediainfo.so.0", "libmediainfo.dylib",
]


@lru_cache(maxsize=1)
def _lib():
    for cand in _DLL_CANDIDATES:
        if not cand:
            continue
        try:
            lib = ctypes.CDLL(cand)
        except OSError:
            continue
        try:
            lib.MediaInfo_New.restype = ctypes.c_void_p
            lib.MediaInfo_Open.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
            lib.MediaInfo_Open.restype = ctypes.c_size_t
            lib.MediaInfo_Get.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t,
                                          ctypes.c_wchar_p, ctypes.c_int, ctypes.c_int]
            lib.MediaInfo_Get.restype = ctypes.c_wchar_p
            lib.MediaInfo_Close.argtypes = [ctypes.c_void_p]
            lib.MediaInfo_Delete.argtypes = [ctypes.c_void_p]
            return lib
        except AttributeError:
            continue
    return None


def mediainfo_available() -> bool:
    return _lib() is not None


def _mediainfo_video(path: Path) -> dict[str, str]:
    lib = _lib()
    if lib is None:
        return {}
    h = lib.MediaInfo_New()
    try:
        if not lib.MediaInfo_Open(h, str(path)):
            return {}
        out = {}
        for key in ("Height", "Width", "ScanType", "Format", "Encoded_Library/Name",
                    "Encoded_Library", "CodecID"):
            v = lib.MediaInfo_Get(h, 1, 0, key, 1, 0)   # stream kind 1 = Video, info kind 1 = Text
            if v:
                out[key] = v
        lib.MediaInfo_Close(h)
        return out
    except Exception:
        return {}
    finally:
        lib.MediaInfo_Delete(h)


def _vf_from_height(height: int, interlaced: bool) -> str:
    if height >= 2000:
        p = 2160
    elif height >= 1000:
        p = 1080
    elif height >= 700:
        p = 720
    elif height >= 560:
        p = 576
    else:
        p = 480
    return f"{p}{'i' if interlaced else 'p'}"


def _vc_from_info(fmt: str, lib: str) -> str:
    f, l = fmt.upper(), lib.lower()
    if f == "AVC":
        return "x264" if "x264" in l else "AVC"
    if f == "HEVC":
        return "x265" if "x265" in l else "HEVC"
    if f in ("MPEG-4 VISUAL",):
        return "XviD" if "xvid" in l else "DivX"
    return fmt or ""


_NAME_VF = re.compile(r"(?i)(?<!\d)(480|576|720|1080|2160|4320)([pi])(?!\w)|(?<!\w)(4k|uhd)(?!\w)")
_NAME_VC = re.compile(r"(?i)(?<![a-z0-9])(x\.?264|x\.?265|h\.?264|h\.?265|hevc|avc|av1|xvid|divx|vp9)(?![a-z0-9])")


def probe(path: Path) -> tuple[str, str]:
    """Return (vf, vc), either may be ''."""
    info = _mediainfo_video(path) if path.is_file() and path.stat().st_size > 0 else {}
    vf = vc = ""
    try:
        if info.get("Height", "").isdigit():
            vf = _vf_from_height(int(info["Height"]), info.get("ScanType", "").lower().startswith("inter"))
        if info.get("Format"):
            vc = _vc_from_info(info["Format"], info.get("Encoded_Library/Name") or info.get("Encoded_Library") or "")
    except Exception:
        pass
    name = path.name
    if not vf:
        m = _NAME_VF.search(name)
        if m:
            vf = "2160p" if m.group(3) else f"{m.group(1)}{m.group(2).lower()}"
    if not vc:
        m = _NAME_VC.search(name)
        if m:
            t = m.group(1).lower().replace(".", "")
            vc = {"h264": "x264", "h265": "x265", "hevc": "HEVC", "avc": "AVC", "av1": "AV1",
                  "xvid": "XviD", "divx": "DivX", "vp9": "VP9"}.get(t, t)
    return vf, vc
