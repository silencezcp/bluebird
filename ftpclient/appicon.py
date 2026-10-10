"""The application icon, drawn at runtime with QPainter.

No binary asset is checked in: the artwork is described once here and rendered
at whatever size is needed, which keeps it crisp from a 16 px title bar up to a
256 px executable icon.

The design is the messenger of the blue bird (青鸟传信): a blue bird climbing
to the upper right with a sealed letter in its beak.  The letter is what makes
it a file-transfer client rather than just a bird.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# palette
# ---------------------------------------------------------------------------
BODY = "#4FA8E0"             # blue bird, main plumage
BODY_DARK = "#2E7CB8"        # underside and shading
BODY_LIGHT = "#7CC4EE"       # sunlit upper edge
WING = "#2F79B5"             # the far wing, a step darker
WING_EDGE = "#256494"
BELLY = "#EAF5FD"            # pale breast
BEAK = "#F5A623"             # horn coloured beak
BEAK_DARK = "#D18A12"
EYE = "#1E2A38"
LETTER = "#FFFFFF"           # the sealed letter
LETTER_FOLD = "#8FB4D1"      # fold lines on the letter
LETTER_EDGE = "#5E8CB0"      # its outline, dark enough to read at 16 px
TRAIL = "#9CC9E8"            # the flight trail behind the bird


def _qcolor(value: str, alpha: int = 255) -> Any:
    from PyQt5.QtGui import QColor
    color = QColor(value)
    if alpha != 255:
        color.setAlpha(alpha)
    return color


def _qpoint(x: float, y: float) -> Any:
    from PyQt5.QtCore import QPointF
    return QPointF(x, y)


def _draw_bird(painter: Any, unit: float) -> None:
    """Paint the blue bird at a 64 unit scale (the caller has scaled)."""
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import (QBrush, QLinearGradient, QPainterPath, QPen)

    # -- flight trail: two tapering arcs behind the bird -----------------
    trail_pen = QPen(_qcolor(TRAIL, 150))
    trail_pen.setCapStyle(Qt.RoundCap)
    for offset, weight in ((0.0, 2.4), (4.6, 1.6)):
        path = QPainterPath()
        path.moveTo(4.0, 34.0 + offset)
        path.cubicTo(11.0, 30.0 + offset, 16.0, 27.0 + offset,
                     21.0, 25.5 + offset)
        pen = QPen(trail_pen)
        pen.setWidthF(weight)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
    painter.setPen(Qt.NoPen)

    # -- tail: a swept triangle, rearmost so it sits under the body ------
    tail = QPainterPath()
    tail.moveTo(30.0, 36.0)
    tail.lineTo(9.0, 43.5)
    tail.lineTo(11.5, 47.5)
    tail.lineTo(31.0, 44.0)
    tail.closeSubpath()
    painter.setBrush(QBrush(_qcolor(WING)))
    painter.setPen(QPen(_qcolor(WING_EDGE), 0.8))
    painter.drawPath(tail)

    # -- body: an ellipse rotated so the bird climbs to the right --------
    gradient = QLinearGradient(24.0, 24.0, 44.0, 50.0)
    gradient.setColorAt(0.0, _qcolor(BODY_LIGHT))
    gradient.setColorAt(0.45, _qcolor(BODY))
    gradient.setColorAt(1.0, _qcolor(BODY_DARK))
    painter.save()
    painter.translate(38.0, 37.0)
    painter.rotate(-24.0)
    body = QRectF(-14.5, -9.5, 29.0, 19.0)
    painter.setBrush(QBrush(gradient))
    painter.setPen(QPen(_qcolor(BODY_DARK), 1.0))
    painter.drawEllipse(body)
    painter.restore()

    # -- pale breast along the lower front of the body -------------------
    breast = QPainterPath()
    breast.moveTo(43.0, 30.0)
    breast.cubicTo(50.0, 33.0, 50.0, 41.0, 42.0, 45.0)
    breast.cubicTo(44.5, 40.0, 45.5, 34.5, 43.0, 30.0)
    breast.closeSubpath()
    painter.setBrush(QBrush(_qcolor(BELLY)))
    painter.setPen(Qt.NoPen)
    painter.drawPath(breast)

    # -- head ------------------------------------------------------------
    head = QPointF(47.5, 25.5)
    painter.setBrush(QBrush(_qcolor(BODY)))
    painter.setPen(QPen(_qcolor(BODY_DARK), 1.0))
    painter.drawEllipse(head, 7.6, 7.4)

    # -- beak: two halves, meeting at a point to the upper right ---------
    for points, colour in (
            ([(53.0, 22.4), (61.4, 19.6), (53.4, 25.6)], BEAK),
            ([(53.4, 26.0), (61.4, 19.6), (52.4, 28.4)], BEAK_DARK)):
        beak = QPainterPath()
        beak.moveTo(*points[0])
        beak.lineTo(*points[1])
        beak.lineTo(*points[2])
        beak.closeSubpath()
        painter.setBrush(QBrush(_qcolor(colour)))
        painter.setPen(Qt.NoPen)
        painter.drawPath(beak)

    # -- eye -------------------------------------------------------------
    painter.setBrush(QBrush(_qcolor(EYE)))
    painter.drawEllipse(QPointF(49.4, 24.6), 1.85, 1.85)
    painter.setBrush(QBrush(_qcolor("#FFFFFF", 210)))
    painter.drawEllipse(QPointF(50.1, 23.9), 0.62, 0.62)

    # -- near wing, sweeping forward over the body -----------------------
    wing = QPainterPath()
    wing.moveTo(35.0, 30.0)
    wing.cubicTo(43.0, 28.0, 46.0, 34.0, 42.0, 40.5)
    wing.cubicTo(38.0, 45.5, 30.0, 47.0, 25.0, 45.0)
    wing.cubicTo(29.0, 38.5, 31.0, 33.0, 35.0, 30.0)
    wing.closeSubpath()
    painter.setBrush(QBrush(_qcolor(WING)))
    painter.setPen(QPen(_qcolor(WING_EDGE), 0.9))
    painter.drawPath(wing)
    # two feather lines inside the wing
    feather_pen = QPen(_qcolor(WING_EDGE, 200))
    feather_pen.setWidthF(0.9)
    painter.setPen(feather_pen)
    painter.setBrush(Qt.NoBrush)
    for drop in (2.6, 5.0):
        line = QPainterPath()
        line.moveTo(34.0 + drop * 0.4, 32.5 + drop)
        line.cubicTo(37.5, 36.0 + drop * 0.5, 37.0, 39.0 + drop * 0.4,
                     34.0, 42.0 + drop * 0.35)
        painter.drawPath(line)
    painter.setPen(Qt.NoPen)

    # -- the letter, gripped in the beak ---------------------------------
    # the beak tip is at (61.4, 19.6).  The letter is placed so that tip sits
    # just inside its lower left corner, which is what makes it read as carried
    # rather than as a separate envelope floating past the bird.
    painter.save()
    painter.translate(56.4, 15.4)
    painter.rotate(22.0)
    letter = QRectF(-7.0, -4.0, 14.0, 10.0)
    painter.setBrush(QBrush(_qcolor(LETTER)))
    painter.setPen(QPen(_qcolor(LETTER_EDGE), 1.0))
    painter.drawRoundedRect(letter, 1.2, 1.2)
    # the flap: a wide V from the top corners down to the middle
    flap = QPainterPath()
    flap.moveTo(letter.left() + 1.0, letter.top() + 1.1)
    flap.lineTo(0.0, letter.top() + 5.4)
    flap.lineTo(letter.right() - 1.0, letter.top() + 1.1)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(_qcolor(LETTER_FOLD), 1.1))
    painter.drawPath(flap)
    painter.restore()



def draw_icon(painter: Any, size: int) -> None:
    """Paint the icon into ``painter`` inside a ``size`` x ``size`` box."""
    from PyQt5.QtGui import QPainter
    from PyQt5.QtCore import Qt

    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    # everything below is measured on a 64 unit grid, so one scale call makes
    # the artwork size independent
    unit = size / 64.0
    painter.save()
    painter.scale(unit, unit)
    painter.setPen(Qt.NoPen)
    _draw_bird(painter, unit)
    painter.restore()


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
    png = os.path.join(folder, "bluebird.png")
    if save_png(png, 256):
        written.append(png)
    ico = os.path.join(folder, "bluebird.ico")
    if save_ico(ico):
        written.append(ico)
    return written
