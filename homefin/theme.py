"""Светлое оформление в стиле ПТО: нейтральный фон, белые карточки, скругления, один акцентный цвет."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPalette, QPixmap

ACCENT = "#1B6B62"  # бирюзово-зелёный, как в ПТО
C = dict(bg="#F7F7F8", panel="#FFFFFF", text="#18181B", text2="#3F3F46", muted="#5B5B66", line="#ECECEF",
         border="#D4D4DB", hover="#F1F1F4", alt="#FAFAFB", disabled="#A1A1AA", scroll="#D4D4D8",
         scroll_hover="#A1A1AA", good="#15803D", bad="#B91C1C", warn="#B45309")
FONTS = ["Inter", "Segoe UI Variable", "Segoe UI", "Noto Sans", "Arial", "DejaVu Sans"]


def mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(*(round(x + (y - x) * t) for x, y in ((ca.red(), cb.red()), (ca.green(), cb.green()),
                                                         (ca.blue(), cb.blue())))).name()


def _arrows(color: str) -> dict[str, str]:
    """PNG-стрелки для списков и счётчиков: Qt сам их в таблице стилей не рисует."""
    from PyQt6.QtSvg import QSvgRenderer
    folder = Path(tempfile.mkdtemp(prefix="homefin-theme-"))
    out = {}
    for name, pts in (("down", "3,6 8,11 13,6"), ("up", "3,10 8,5 13,10")):
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><polyline points="{pts}" fill="none" '
               f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        QSvgRenderer(QByteArray(svg.encode())).render(p)
        p.end()
        path = folder / f"{name}.png"
        pix.save(str(path))
        out[name] = path.as_posix()
    return out


def apply(app) -> None:
    c = dict(C)
    c.update(accent=ACCENT, accent_hover=mix(ACCENT, "#000000", 0.15), accent_press=mix(ACCENT, "#000000", 0.30),
             sel=mix(ACCENT, "#FFFFFF", 0.90))
    app.setStyle("Fusion")
    font = QFont(FONTS[0])
    font.setFamilies(FONTS)
    font.setPointSize(10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    pal = QPalette()
    for role, col in ((QPalette.ColorRole.Window, c["bg"]), (QPalette.ColorRole.WindowText, c["text"]),
                      (QPalette.ColorRole.Base, c["panel"]), (QPalette.ColorRole.AlternateBase, c["alt"]),
                      (QPalette.ColorRole.Text, c["text"]), (QPalette.ColorRole.Button, c["panel"]),
                      (QPalette.ColorRole.ButtonText, c["text"]), (QPalette.ColorRole.ToolTipBase, c["panel"]),
                      (QPalette.ColorRole.ToolTipText, c["text"]), (QPalette.ColorRole.Highlight, c["sel"]),
                      (QPalette.ColorRole.HighlightedText, c["text"]), (QPalette.ColorRole.PlaceholderText, c["muted"]),
                      (QPalette.ColorRole.Link, c["accent"])):
        pal.setColor(role, QColor(col))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["disabled"]))
    app.setPalette(pal)
    ar = _arrows(c["text2"])
    app.setStyleSheet(f'''
    QWidget {{ color:{c['text']}; }}
    QMainWindow, QDialog {{ background:{c['bg']}; }}
    QToolTip {{ background:{c['text']}; color:{c['panel']}; border:0; border-radius:6px; padding:6px 10px; }}
    QLabel {{ background:transparent; }}
    QFrame#sidebar {{ background:{c['panel']}; border:0; border-right:1px solid {c['line']}; }}
    QLabel#brand {{ font-size:18px; font-weight:700; padding:6px 8px; }}
    QLabel#logoMark {{ background:{c['accent']}; color:#FFFFFF; border-radius:10px; font-size:20px; font-weight:700; }}
    QLabel#navSection {{ color:{c['muted']}; font-size:11px; font-weight:600; letter-spacing:1px; padding:10px 14px 2px 14px; }}
    QPushButton#navButton {{ text-align:left; background:transparent; color:{c['text2']}; border:0; border-radius:8px; padding:8px 12px; min-height:22px; font-weight:400; }}
    QPushButton#navButton:hover {{ background:{c['hover']}; color:{c['text']}; }}
    QPushButton#navButton:checked {{ background:{c['sel']}; color:{c['accent']}; font-weight:600; }}
    QFrame#pageHeader {{ background:{c['bg']}; border:0; }}
    QLabel#pageTitle {{ font-size:24px; font-weight:600; }}
    QLabel#pageSubtitle {{ color:{c['muted']}; font-size:12px; }}
    QPushButton {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:8px; padding:6px 14px; min-height:22px; }}
    QPushButton:hover {{ background:{c['hover']}; }}
    QPushButton:pressed {{ background:{c['line']}; }}
    QPushButton:focus {{ border:1px solid {c['accent']}; }}
    QPushButton:disabled {{ color:{c['disabled']}; background:{c['alt']}; border-color:{c['line']}; }}
    QPushButton[type="primary"] {{ background:{c['accent']}; border:1px solid {c['accent']}; color:#FFFFFF; font-weight:600; }}
    QPushButton[type="primary"]:hover {{ background:{c['accent_hover']}; border-color:{c['accent_hover']}; }}
    QPushButton[type="primary"]:pressed {{ background:{c['accent_press']}; }}
    QPushButton[type="danger"] {{ color:#B91C1C; border-color:#F3C5C5; }}
    QPushButton[type="danger"]:hover {{ background:#FEF2F2; }}
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {{
        background:{c['panel']}; border:1px solid {c['border']}; border-radius:8px; padding:5px 10px; min-height:22px;
        selection-background-color:{c['accent']}; selection-color:#FFFFFF; }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDateEdit:hover {{ border-color:{c['muted']}; }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {{ border:1px solid {c['accent']}; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border:0; width:26px; subcontrol-origin:padding; subcontrol-position:center right; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image:url({ar['down']}); width:14px; height:14px; }}
    QSpinBox {{ padding-right:24px; }}
    QSpinBox::up-button {{ subcontrol-origin:border; subcontrol-position:top right; width:22px; border:0; background:transparent; }}
    QSpinBox::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right; width:22px; border:0; background:transparent; }}
    QSpinBox::up-arrow {{ image:url({ar['up']}); width:10px; height:10px; }}
    QSpinBox::down-arrow {{ image:url({ar['down']}); width:10px; height:10px; }}
    QComboBox QAbstractItemView {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:8px; selection-background-color:{c['sel']}; selection-color:{c['text']}; outline:0; padding:4px; }}
    QCheckBox {{ spacing:8px; min-height:22px; }}
    QTableView {{ qproperty-showGrid:false; background:{c['panel']}; alternate-background-color:{c['panel']}; border:1px solid {c['line']}; border-radius:10px; selection-background-color:{c['sel']}; selection-color:{c['text']}; outline:0; }}
    QTableView::item {{ padding:5px 8px; border-bottom:1px solid {c['line']}; }}
    QTableView::item:selected {{ background:{c['sel']}; color:{c['text']}; }}
    QTableView::item:hover {{ background:{c['hover']}; }}
    QHeaderView::section {{ background:{c['panel']}; color:{c['muted']}; font-weight:600; font-size:12px; padding:9px 10px; border:0; border-bottom:1px solid {c['border']}; }}
    QGroupBox {{ background:{c['panel']}; border:1px solid {c['line']}; border-radius:12px; margin-top:16px; padding:18px 12px 12px; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:14px; padding:0 6px; color:{c['text2']}; font-weight:600; }}
    QScrollArea {{ border:0; background:transparent; }}
    QScrollBar:vertical {{ background:transparent; width:12px; margin:0; }}
    QScrollBar::handle:vertical {{ background:{c['scroll']}; border-radius:4px; min-height:30px; margin:2px; }}
    QScrollBar::handle:vertical:hover {{ background:{c['scroll_hover']}; }}
    QScrollBar:horizontal {{ background:transparent; height:12px; }}
    QScrollBar::handle:horizontal {{ background:{c['scroll']}; border-radius:4px; min-width:30px; margin:2px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
    QProgressBar {{ border:0; background:{c['line']}; border-radius:4px; text-align:center; min-height:14px; }}
    QProgressBar::chunk {{ background:{c['accent']}; border-radius:4px; }}
    QMenu {{ background:{c['panel']}; border:1px solid {c['line']}; border-radius:10px; padding:6px; }}
    QMenu::item {{ padding:7px 26px 7px 14px; border-radius:6px; }}
    QMenu::item:selected {{ background:{c['hover']}; }}
    QStatusBar {{ background:{c['bg']}; color:{c['muted']}; }}
    QDialogButtonBox QPushButton {{ min-width:84px; }}
    QCalendarWidget QAbstractItemView {{ background:{c['panel']}; selection-background-color:{c['accent']}; selection-color:#FFFFFF; border:0; outline:0; }}
    QCalendarWidget QTableView::item {{ padding:0; border:0; }}
    QCalendarWidget QHeaderView::section {{ padding:2px 0; border:0; color:{c['muted']}; }}
    QCalendarWidget QToolButton {{ background:transparent; border:0; border-radius:6px; padding:4px 8px; min-width:28px; }}
    QCalendarWidget QToolButton:hover {{ background:{c['hover']}; }}
    ''')
