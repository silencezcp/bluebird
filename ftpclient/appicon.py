"""The application icon, drawn at runtime with QPainter.

No binary asset is checked in: the artwork is described once here and rendered
at whatever size is needed, which keeps it crisp from a 16 px title bar up to a
256 px executable icon.

The design is a soft blue cloud carrying the letters **FTP**, sitting on a
network of three green nodes joined by a bus - a file server in the cloud.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# palette
# ---------------------------------------------------------------------------
CLOUD_TOP = "#D3E7F7"        # light blue, top of the cloud
CLOUD_BOTTOM = "#B4D6F0"     # slightly deeper at the bottom edge
CLOUD_EDGE = "#9FC6E8"       # subtle outline
LETTER = "#22293A"           # near-black navy for "FTP"
BUS = "#22293A"              # the cable between the nodes
NODE = "#6CC24A"             # green nodes
NODE_DARK = "#4E9E33"        # shading on the lower half of a node
NODE_CORE = "#FFFFFF"        # white square inside a node


def _qcolor(value: str, alpha: int = 255) -> Any:
    from PyQt5.QtGui import QColor
    color = QColor(value)
    if alpha != 255:
        color.setAlpha(alpha)
    return color


def draw_icon(painter: Any, size: int) -> None:
    """Paint the icon into ``painter`` inside a ``size`` x ``size`` box."""
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import (QBrush, QFont, QLinearGradient, QPainterPath,
                             QPen)

    painter.setRenderHint(painter.Antialiasing, True)
    painter.setRenderHint(painter.TextAntialiasing, True)

    # work on a 64 unit grid so every measurement below is size independent
    unit = size / 64.0
    painter.save()
    painter.scale(unit, unit)
    painter.setPen(Qt.NoPen)

    # -- the cloud ------------------------------------------------------
    # three lobes over a rounded slab, which reads as one cloud outline
    lobes = (
        # (centre x, centre y, radius)
        (20.0, 17.5, 11.0),      # left lobe
        (32.0, 13.5, 14.0),      # tall middle lobe
        (44.5, 18.0, 10.5),      # right lobe
    )
    body = QRectF(11.0, 18.0, 42.0, 15.5)

    cloud = QPainterPath()
    cloud.addRoundedRect(body, 7.5, 7.5)
    for cx, cy, radius in lobes:
        lobe = QPainterPath()
        lobe.addEllipse(QPointF(cx, cy), radius, radius)
        cloud = cloud.united(lobe)

    gradient = QLinearGradient(0.0, 6.0, 0.0, 34.0)
    gradient.setColorAt(0.0, _qcolor(CLOUD_TOP))
    gradient.setColorAt(1.0, _qcolor(CLOUD_BOTTOM))
    painter.setBrush(QBrush(gradient))
    painter.setPen(QPen(_qcolor(CLOUD_EDGE), 1.2))
    painter.drawPath(cloud.simplified())
    painter.setPen(Qt.NoPen)

    # -- "FTP" ----------------------------------------------------------
    font = QFont()
    font.setBold(True)
    font.setPixelSize(17)
    font.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
    painter.setFont(font)
    painter.setPen(QPen(_qcolor(LETTER)))
    painter.drawText(QRectF(9.0, 14.5, 46.0, 18.0),
                     int(Qt.AlignCenter), "FTP")
    painter.setPen(Qt.NoPen)

    # -- the network bus and its three nodes ---------------------------
    # the nodes sit *below* the cable and do not touch each other
    bus_y = 45.0
    stem = QRectF(30.6, 31.0, 2.8, 12.5)
    painter.setBrush(QBrush(_qcolor(BUS)))
    painter.drawRoundedRect(stem, 1.2, 1.2)

    bus = QRectF(16.0, bus_y - 2.2, 32.0, 4.0)
    painter.drawRoundedRect(bus, 1.6, 1.6)

    node_radius = 7.4
    node_centre_y = bus_y + 5.8
    for cx in (16.0, 32.0, 48.0):
        node = QRectF(cx - node_radius, node_centre_y - node_radius,
                      node_radius * 2, node_radius * 2)
        painter.setBrush(QBrush(_qcolor(NODE)))
        painter.drawEllipse(node)
        # lower half slightly darker for a little depth
        shade = QPainterPath()
        shade.addEllipse(node)
        clip = QRectF(node.left(), node.center().y(),
                      node.width(), node.height() / 2.0 + 0.5)
        painter.setBrush(QBrush(_qcolor(NODE_DARK, 80)))
        painter.drawPath(shade.intersected(_path_from_rect(clip)).simplified())
        # white square core
        core = node_radius * 0.72
        painter.setBrush(QBrush(_qcolor(NODE_CORE)))
        painter.drawRoundedRect(
            QRectF(cx - core / 2.0, node_centre_y - core / 2.0, core, core),
            core * 0.24, core * 0.24)

    painter.restore()


def _path_from_rect(rect: Any) -> Any:
    from PyQt5.QtGui import QPainterPath
    path = QPainterPath()
    path.addRect(rect)
    return path


def pixmap(size: int = 64) -> Any:
    """A QPixmap of the icon at ``size`` x ``size``."""
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    if QApplication.instance() is None:
        raise RuntimeError("a QApplication is required to render the icon")
    scale = 2 if size <= 64 else 1        # render large then shrink: crisper
    canvas = QPixmap(size * scale, size * scale)
    canvas.fill(Qt.transparent)
    from PyQt5.QtGui import QPainter
    painter = QPainter(canvas)
    try:
        draw_icon(painter, size * scale)
    finally:
        painter.end()
    if scale != 1:
        canvas = canvas.scaled(size, size,
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return canvas


def icon() -> Any:
    """A multi-resolution QIcon for windows, the taskbar and the exe."""
    from PyQt5.QtGui import QIcon
    result = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        result.addPixmap(pixmap(size))
    return result


def save_png(path: str, size: int = 256) -> bool:
    """Write one PNG, for the packaging step."""
    try:
        image = pixmap(size)
        return bool(image.save(path, "PNG"))
    except Exception:
        return False


def save_ico(path: str,
             sizes: Tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)) -> bool:
    """Write a multi-resolution .ico for the executable.

    Qt can only save the sizes it is asked for via ``QImageWriter``, so the
    PNG frames are assembled into an ICO container by hand - the format is a
    small header plus the PNG payloads, which every Windows version since
    Vista understands.
    """
    import struct

    frames: List[Tuple[int, bytes]] = []
    for size in sizes:
        image = pixmap(size)
        if image.isNull():
            continue
        from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            continue
        buffer.close()
        payload = bytes(buffer.data())
        frames.append((size, payload))
    if not frames:
        return False

    header = struct.pack("<HHH", 0, 1, len(frames))   # reserved, type=icon, n
    directory = b""
    offset = 6 + 16 * len(frames)
    for size, payload in frames:
        dimension = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", dimension, dimension, 0, 0,
                                 1, 32, len(payload), offset)
        offset += len(payload)
    try:
        with open(path, "wb") as handle:
            handle.write(header + directory)
            for _size, payload in frames:
                handle.write(payload)
    except OSError:
        return False
    return True


def write_assets(folder: str) -> List[str]:
    """Write the icon assets used by the build (called from the tools)."""
    written: List[str] = []
    if not os.path.isdir(folder):
        os.makedirs(folder)
    png = os.path.join(folder, "smartftp.png")
    if save_png(png, 256):
        written.append(png)
    ico = os.path.join(folder, "smartftp.ico")
    if save_ico(ico):
        written.append(ico)
    return written
