"""Оформление в стиле Microsoft Office (Fluent): светлая и тёмная темы, крупный чёткий шрифт, контраст не ниже WCAG AA для основного текста."""
from PyQt6.QtCore import QObject, QEvent
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtWidgets import QWidget

OFFICE_BLUE = '#185ABD'          # синий Word; прежний «небесный» акцент по умолчанию заменяется на него
LEGACY_ACCENTS = {'#0284c7', '#2563eb', ''}
FONT_FALLBACKS = ['Segoe UI', 'Segoe UI Variable', 'Calibri', 'Arial', 'Noto Sans', 'DejaVu Sans']

LIGHT = dict(bg='#F3F2F1', panel='#FFFFFF', side='#FFFFFF', text='#201F1E', text2='#323130', muted='#605E5C', line='#E1DFDD', border='#8A8886', hover='#EDEBE9',
             alt='#FAF9F8', disabled='#A19F9D', header='#F3F2F1', scroll='#C8C6C4', scroll_hover='#A19F9D')
DARK = dict(bg='#1F1E1D', panel='#292827', side='#252423', text='#F3F2F1', text2='#E1DFDD', muted='#C8C6C4', line='#3B3A39', border='#8A8886', hover='#3B3A39',
            alt='#2F2E2D', disabled='#797775', header='#323130', scroll='#605E5C', scroll_hover='#8A8886')


def mix(a, b, t):
    """Смешивает цвета: t=0 — a, t=1 — b."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t), round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def colors(dark=False, accent=''):
    """Цвета темы. accent — пользовательский акцентный цвет (прежний цвет по умолчанию заменяется синим Office)."""
    c = dict(DARK if dark else LIGHT)
    base = accent if accent and accent.lower() not in LEGACY_ACCENTS else OFFICE_BLUE
    if dark:
        c['accent'] = mix(base, '#FFFFFF', 0.10)                 # заливка кнопок: белый текст читается
        c['accent_fg'] = mix(base, '#FFFFFF', 0.55)              # цвет акцентного текста на тёмном фоне
        c['accent_hover'] = mix(base, '#FFFFFF', 0.22)
        c['accent_press'] = base
        c['sel'] = mix(base, '#000000', 0.25)
        c['sel_text'] = '#FFFFFF'
    else:
        c['accent'] = base
        c['accent_fg'] = base
        c['accent_hover'] = mix(base, '#000000', 0.15)
        c['accent_press'] = mix(base, '#000000', 0.30)
        c['sel'] = mix(base, '#FFFFFF', 0.85)
        c['sel_text'] = c['text']
    return c


# Цвета, зашитые в виджеты для светлой темы, в тёмной подменяются на читаемые (фильтр срабатывает при оформлении каждого виджета)
DARK_TEXT_FIX = {'#605E5C': '#C8C6C4', '#15803D': '#4ADE80', '#B45309': '#F5B04A', '#A4262C': '#F1707B'}


class _DarkTextFix(QObject):
    dark = False

    def eventFilter(self, obj, event):
        if self.dark and event.type() == QEvent.Type.Polish and isinstance(obj, QWidget):
            ss = obj.styleSheet()
            if ss and any(k in ss for k in DARK_TEXT_FIX):
                for k, v in DARK_TEXT_FIX.items():
                    ss = ss.replace(f'color: {k}', f'color: {v}').replace(f'color:{k}', f'color:{v}')
                obj.setStyleSheet(ss)
        return False


def _install_filter(app, dark):
    fix = getattr(app, '_dark_text_fix', None)
    if fix is None:
        fix = _DarkTextFix(app)
        app.installEventFilter(fix)
        app._dark_text_fix = fix
    fix.dark = dark
    if dark:       # уже созданные виджеты
        for w in app.allWidgets():
            ss = w.styleSheet()
            if ss and any(k in ss for k in DARK_TEXT_FIX):
                for k, v in DARK_TEXT_FIX.items():
                    ss = ss.replace(f'color: {k}', f'color: {v}').replace(f'color:{k}', f'color:{v}')
                w.setStyleSheet(ss)


def _arrow_files(color):
    """Стрелки для списков и счётчиков (PNG во временной папке): Qt в таблице стилей не рисует их сам."""
    import tempfile
    from pathlib import Path
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtGui import QPixmap, QPainter
    from PyQt6.QtSvg import QSvgRenderer
    folder = Path(tempfile.gettempdir()) / 'smetagaz_theme'
    folder.mkdir(exist_ok=True)
    paths = {}
    for name, points in (('down', '3,6 8,11 13,6'), ('up', '3,10 8,5 13,10')):
        path = folder / f'{name}_{color.lstrip("#")}.png'
        if not path.exists():
            svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
            pix = QPixmap(32, 32)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            QSvgRenderer(QByteArray(svg.encode())).render(painter)
            painter.end()
            pix.save(str(path))
        paths[name] = path.as_posix()
    return paths


def accent_fg():
    """Акцентный цвет для текста с учётом темы (для виджетов, которые задают цвет сами)."""
    try:
        from .database import db
        return colors(db.get_setting('is_dark', '0') == '1', db.get_setting('accent_color', ''))['accent_fg']
    except Exception:
        return OFFICE_BLUE


def icon_color(dark=False):
    return '#E1DFDD' if dark else '#323130'


def apply(app, dark=False, family='Segoe UI', size=10, accent=''):
    c = colors(dark, accent)
    app.setStyle('Fusion')
    font = QFont(family or FONT_FALLBACKS[0])
    font.setFamilies([f for f in dict.fromkeys([family or FONT_FALLBACKS[0], *FONT_FALLBACKS])])
    font.setPointSize(max(10, min(14, int(size or 10))))
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(font)
    palette = QPalette()
    for role, color in [(QPalette.ColorRole.Window, c['bg']), (QPalette.ColorRole.WindowText, c['text']), (QPalette.ColorRole.Base, c['panel']), (QPalette.ColorRole.AlternateBase, c['alt']),
                        (QPalette.ColorRole.Text, c['text']), (QPalette.ColorRole.Button, c['panel']), (QPalette.ColorRole.ButtonText, c['text']), (QPalette.ColorRole.ToolTipBase, c['panel']),
                        (QPalette.ColorRole.ToolTipText, c['text']), (QPalette.ColorRole.Highlight, c['sel']), (QPalette.ColorRole.HighlightedText, c['sel_text']),
                        (QPalette.ColorRole.PlaceholderText, c['muted']), (QPalette.ColorRole.Link, c['accent_fg'])]:
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c['disabled']))
    app.setPalette(palette)
    _install_filter(app, dark)
    arrows = _arrow_files(c['text2'])
    app.setStyleSheet(f'''
    QWidget {{ color:{c['text']}; }}
    QMainWindow, QDialog {{ background:{c['bg']}; }}
    QToolTip {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; padding:6px 8px; }}
    QLabel {{ background:transparent; }}

    /* Боковая панель: светлая «навигация» Office, выбранный пункт — акцентная полоса слева */
    QFrame#sidebar {{ background:{c['side']}; border:0; border-right:1px solid {c['line']}; }}
    QFrame#sidebar QLabel {{ color:{c['muted']}; }}
    QLabel#brand {{ font-size:19px; font-weight:700; color:{c['accent_fg']}; padding:4px 6px; }}
    QScrollArea#navigation {{ background:transparent; border:0; }}
    QWidget#navContent {{ background:{c['side']}; }}
    QPushButton#navButton {{ text-align:left; background:transparent; color:{c['text2']}; border:0; border-left:3px solid transparent; border-radius:2px; padding:8px 12px; min-height:22px; font-weight:400; }}
    QPushButton#navButton:hover {{ background:{c['hover']}; color:{c['text']}; }}
    QPushButton#navButton:checked {{ background:{c['sel']}; color:{c['accent_fg'] if not dark else c['sel_text']}; border-left:3px solid {c['accent_fg']}; font-weight:700; }}
    QLabel#navSection {{ color:{c['muted']}; font-size:11px; font-weight:700; letter-spacing:1px; padding:6px 14px 2px 14px; background:transparent; }}
    QFrame#navDivider {{ background:{c['line']}; border:0; max-height:1px; }}

    /* Заголовок страницы */
    QFrame#pageHeader {{ background:{c['panel']}; border-bottom:1px solid {c['line']}; }}
    QLabel#pageTitle {{ font-size:22px; font-weight:600; color:{c['text']}; }}
    QLabel#pageSubtitle {{ color:{c['muted']}; font-size:12px; }}

    /* Кнопки */
    QPushButton {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:2px; padding:5px 14px; min-height:22px; }}
    QPushButton:hover {{ background:{c['hover']}; border-color:{c['muted']}; }}
    QPushButton:pressed {{ background:{c['line']}; }}
    QPushButton:focus {{ border:2px solid {c['accent_fg']}; padding:4px 13px; }}
    QPushButton:disabled {{ color:{c['disabled']}; background:{c['alt']}; border-color:{c['line']}; }}
    QPushButton:checked {{ background:{c['sel']}; border-color:{c['accent_fg']}; color:{c['sel_text'] if dark else c['accent_fg']}; font-weight:600; }}
    QPushButton[type="primary"] {{ background:{c['accent']}; border:1px solid {c['accent']}; color:#FFFFFF; font-weight:600; }}
    QPushButton[type="primary"]:hover {{ background:{c['accent_hover']}; border-color:{c['accent_hover']}; }}
    QPushButton[type="primary"]:pressed {{ background:{c['accent_press']}; }}
    QPushButton[type="primary"]:disabled {{ background:{c['line']}; border-color:{c['line']}; color:{c['disabled']}; }}
    QPushButton[type="danger"] {{ color:{'#F1707B' if dark else '#A4262C'}; border-color:{'#F1707B' if dark else '#A4262C'}; }}
    QPushButton[type="danger"]:hover {{ background:{'#442726' if dark else '#FDE7E9'}; }}
    QPushButton[type="warning"] {{ color:{'#F7B955' if dark else '#8A5A00'}; border-color:{'#F7B955' if dark else '#8A5A00'}; }}
    QPushButton::menu-indicator {{ subcontrol-position:right center; subcontrol-origin:padding; right:6px; }}

    /* Поля ввода: чёткая рамка и акцентная линия при вводе */
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:2px; padding:4px 8px; min-height:22px;
        selection-background-color:{c['accent']}; selection-color:#FFFFFF; }}
    QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover {{ border-color:{c['text2']}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {{ border:1px solid {c['accent_fg']}; border-bottom:2px solid {c['accent_fg']}; }}
    QLineEdit:read-only {{ background:{c['alt']}; }}
    QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled {{ background:{c['alt']}; color:{c['disabled']}; border-color:{c['line']}; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border:0; width:26px; subcontrol-origin:padding; subcontrol-position:center right; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image:url({arrows['down']}); width:14px; height:14px; }}
    QSpinBox, QDoubleSpinBox, QTimeEdit {{ padding-right:24px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button {{ subcontrol-origin:border; subcontrol-position:top right; width:22px; border:0; border-left:1px solid {c['line']}; background:transparent; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right; width:22px; border:0; border-left:1px solid {c['line']}; background:transparent; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background:{c['hover']}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{ image:url({arrows['up']}); width:10px; height:10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{ image:url({arrows['down']}); width:10px; height:10px; }}
    QComboBox QAbstractItemView {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; selection-background-color:{c['sel']}; selection-color:{c['sel_text']}; outline:0; }}
    QCheckBox, QRadioButton {{ spacing:8px; min-height:22px; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color:{c['disabled']}; }}

    /* Таблицы и списки */
    QTableView {{ qproperty-showGrid:false; qproperty-alternatingRowColors:true; }}
    QTableView, QTreeView, QListView, QListWidget {{ background:{c['panel']}; alternate-background-color:{c['alt']}; color:{c['text']}; border:1px solid {c['line']}; border-radius:2px;
        selection-background-color:{c['sel']}; selection-color:{c['sel_text']}; outline:0; }}
    QTableView::item, QTreeView::item, QListView::item {{ padding:4px 6px; border-bottom:1px solid {c['line']}; }}
    QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{ background:{c['sel']}; color:{c['sel_text']}; }}
    QTableView::item:hover, QTreeView::item:hover {{ background:{c['hover']}; }}
    QHeaderView::section {{ background:{c['header']}; color:{c['text2']}; font-weight:600; padding:7px 8px; border:0; border-right:1px solid {c['line']}; border-bottom:1px solid {c['border']}; }}
    QTableCornerButton::section {{ background:{c['header']}; border:0; border-bottom:1px solid {c['border']}; }}

    /* Вкладки — как в ленте Office: подчёркивание выбранной */
    QTabWidget::pane {{ background:{c['panel']}; border:1px solid {c['line']}; border-top:1px solid {c['line']}; top:-1px; }}
    QTabBar::tab {{ background:transparent; color:{c['text2']}; border:0; border-bottom:3px solid transparent; padding:8px 16px; margin-right:2px; }}
    QTabBar::tab:hover {{ background:{c['hover']}; color:{c['text']}; }}
    QTabBar::tab:selected {{ color:{c['accent_fg']}; border-bottom:3px solid {c['accent_fg']}; font-weight:600; }}
    QTabBar::tab:disabled {{ color:{c['disabled']}; }}

    /* Группы-карточки */
    QGroupBox {{ background:{c['panel']}; border:1px solid {c['line']}; border-radius:4px; margin-top:16px; padding:16px 10px 10px; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 6px; color:{c['text2']}; font-weight:600; }}
    QFrame#metricCard {{ background:{c['panel']}; border:1px solid {c['line']}; border-radius:4px; padding:12px; }}

    /* Прокрутка */
    QScrollArea {{ border:0; background:transparent; }}
    QScrollBar:vertical {{ background:transparent; width:12px; margin:0; }}
    QScrollBar::handle:vertical {{ background:{c['scroll']}; border-radius:3px; min-height:30px; margin:2px; }}
    QScrollBar::handle:vertical:hover {{ background:{c['scroll_hover']}; }}
    QScrollBar:horizontal {{ background:transparent; height:12px; }}
    QScrollBar::handle:horizontal {{ background:{c['scroll']}; border-radius:3px; min-width:30px; margin:2px; }}
    QScrollBar::handle:horizontal:hover {{ background:{c['scroll_hover']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}

    QProgressBar {{ border:0; background:{c['line']}; border-radius:2px; text-align:center; color:{c['text']}; min-height:14px; }}
    QProgressBar::chunk {{ background:{c['accent']}; border-radius:2px; }}
    QMenu {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; padding:4px 0; }}
    QMenu::item {{ padding:7px 28px 7px 20px; }}
    QMenu::item:selected {{ background:{c['hover']}; color:{c['text']}; }}
    QMenu::item:disabled {{ color:{c['disabled']}; }}
    QMenu::separator {{ height:1px; background:{c['line']}; margin:4px 0; }}
    QSplitter::handle {{ background:{c['line']}; }}
    QSplitter::handle:horizontal {{ width:1px; }} QSplitter::handle:vertical {{ height:1px; }}
    QDialogButtonBox QPushButton {{ min-width:84px; }}
    QCalendarWidget QAbstractItemView {{ selection-background-color:{c['accent']}; selection-color:#FFFFFF; }}
    QCalendarWidget QToolButton {{ color:{c['text']}; background:transparent; border:0; padding:4px 8px; }}
    ''')
