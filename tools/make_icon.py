"""Render assets/icon.svg to a multi-size Windows .ico (PNG-compressed entries).

Uses PySide6's SVG renderer (already a dependency) and writes the ICO
container by hand, so no Pillow is needed. Output: assets/icon.ico plus
a 256px assets/icon.png for the GUI window icon.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "assets" / "icon.svg"
ICO = ROOT / "assets" / "icon.ico"
PNG = ROOT / "assets" / "icon.png"
SIZES = [16, 20, 24, 32, 48, 64, 128, 256]


def render(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p)
    p.end()
    buf = QBuffer()
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    if size == 256:
        img.save(str(PNG), "PNG")
    return bytes(buf.data())


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - needed for font/paint engines
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        print("icon.svg failed to load", file=sys.stderr)
        return 1
    pngs = [(s, render(renderer, s)) for s in SIZES]

    # ICO container: ICONDIR + ICONDIRENTRY per image + raw PNG blobs.
    out = struct.pack("<HHH", 0, 1, len(pngs))
    offset = 6 + 16 * len(pngs)
    for size, data in pngs:
        b = 0 if size == 256 else size
        out += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in pngs:
        out += data
    ICO.write_bytes(out)
    print(f"wrote {ICO} ({len(out)} bytes, {len(pngs)} sizes) and {PNG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
