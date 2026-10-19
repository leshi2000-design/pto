"""Визуальные статусы договоров со значками: Завершён, В работе, Просрочен, Годовой (и Расторгнут). Значки рисуются кодом, без файлов."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

COLORS = {'done': '#15803D', 'work': '#2563EB', 'overdue': '#DC2626', 'annual': '#7C3AED', 'cancelled': '#6B7280'}
TITLES = {'done': 'Завершён', 'work': 'В работе', 'overdue': 'Просрочен', 'annual': 'Годовой', 'cancelled': 'Расторгнут'}
_cache = {}


def title(key):
    return TITLES.get(key, '')


def color(key):
    return COLORS.get(key, '#6B7280')


def pixmap(key, size=16):
    """Круглый значок: ✔ завершён, часы — в работе, «!» — просрочен, круговая стрелка — годовой, крест — расторгнут."""
    ratio = 2
    side = size * ratio
    pix = QPixmap(side, side)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color(key)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(1, 1, side - 2, side - 2))
    pen = QPen(QColor('white'), side * 0.11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    s = side / 16.0
    if key == 'done':
        p.drawPolyline([QPointF(4.2 * s, 8.4 * s), QPointF(7 * s, 11 * s), QPointF(11.8 * s, 5.2 * s)])
    elif key == 'work':
        p.drawEllipse(QRectF(3.8 * s, 3.8 * s, 8.4 * s, 8.4 * s))
        p.drawPolyline([QPointF(8 * s, 5.6 * s), QPointF(8 * s, 8 * s), QPointF(9.8 * s, 9.2 * s)])
    elif key == 'overdue':
        p.drawLine(QPointF(8 * s, 4.2 * s), QPointF(8 * s, 9 * s))
        p.drawPoint(QPointF(8 * s, 11.6 * s))
    elif key == 'annual':
        p.drawArc(QRectF(4 * s, 4 * s, 8 * s, 8 * s), 40 * 16, 280 * 16)
        p.drawPolyline([QPointF(9.8 * s, 3.4 * s), QPointF(12 * s, 5 * s), QPointF(9.6 * s, 6.2 * s)])
    else:
        p.drawLine(QPointF(5 * s, 5 * s), QPointF(11 * s, 11 * s))
        p.drawLine(QPointF(11 * s, 5 * s), QPointF(5 * s, 11 * s))
    p.end()
    pix.setDevicePixelRatio(ratio)
    return pix


def icon(key, size=16):
    k = (key, size)
    if k not in _cache:
        _cache[k] = QIcon(pixmap(key, size))
    return _cache[k]
