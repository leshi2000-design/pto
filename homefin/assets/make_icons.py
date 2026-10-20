"""Перегенерация icon.png и icon.ico из logo.svg: python homefin/assets/make_icons.py"""
import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

HERE = Path(__file__).parent
SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(svg: QSvgRenderer, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    svg.render(p)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def main():
    _app = QGuiApplication(sys.argv[:1] + ["-platform", "offscreen"])
    svg = QSvgRenderer(str(HERE / "logo.svg"))
    render(svg, 256).save(str(HERE / "icon.png"))
    images = [(s, png_bytes(render(svg, s))) for s in SIZES]
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for s, png in images:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    (HERE / "icon.ico").write_bytes(head + entries + data)


if __name__ == "__main__":
    main()
