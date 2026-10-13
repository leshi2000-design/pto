"""Современное минималистичное оформление: светлая и тёмная темы, мягкие нейтральные цвета, скругления, тонкие разделители, один акцентный цвет.
Контраст основного текста не ниже WCAG AA."""
from PyQt6.QtCore import QObject, QEvent
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtWidgets import QWidget

MODERN_ACCENT = '#4F46E5'        # индиго; прежние акценты по умолчанию (небесный, синий Office) заменяются на него
OFFICE_BLUE = MODERN_ACCENT      # прежнее имя
LEGACY_ACCENTS = {'#0284c7', '#2563eb', '#185abd', ''}
FONT_FALLBACKS = ['Inter', 'Segoe UI Variable', 'Segoe UI', 'Noto Sans', 'Arial', 'DejaVu Sans']

LIGHT = dict(bg='#F7F7F8', panel='#FFFFFF', side='#FFFFFF', text='#18181B', text2='#3F3F46', muted='#5B5B66', line='#ECECEF', border='#D4D4DB', hover='#F1F1F4',
             alt='#FAFAFB', disabled='#A1A1AA', header='#FFFFFF', scroll='#D4D4D8', scroll_hover='#A1A1AA')
DARK = dict(bg='#111113', panel='#1A1A1E', side='#151518', text='#F4F4F5', text2='#D4D4D8', muted='#A1A1AA', line='#27272D', border='#3A3A42', hover='#25252B',
            alt='#1E1E23', disabled='#6B6B75', header='#1A1A1E', scroll='#3F3F46', scroll_hover='#6B6B75')


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
        c['sel'] = mix(base, '#000000', 0.55)
        c['sel_text'] = '#FFFFFF'
    else:
        c['accent'] = base
        c['accent_fg'] = base
        c['accent_hover'] = mix(base, '#000000', 0.15)
        c['accent_press'] = mix(base, '#000000', 0.30)
        c['sel'] = mix(base, '#FFFFFF', 0.90)
        c['sel_text'] = c['text']
    return c


# Цвета, зашитые в виджеты для светлой темы, в тёмной подменяются на читаемые (фильтр срабатывает при оформлении каждого виджета)
DARK_TEXT_FIX = {'#605E5C': '#C8C6C4', '#15803D': '#4ADE80', '#B45309': '#F5B04A', '#A4262C': '#F1707B'}


def _fix_widget(w, dark):
    """В тёмной теме подменяет зашитые светлые цвета текста; исходный стиль запоминается и возвращается при переходе на светлую тему."""
    original = w.property('_sg_orig_style')
    ss = w.styleSheet()
    if not dark:
        if original is not None:
            w.setProperty('_sg_orig_style', None)
            w.setStyleSheet(original)
        return
    base = original if original is not None else ss
    if base and any(k in base for k in DARK_TEXT_FIX):
        fixed = base
        for k, v in DARK_TEXT_FIX.items():
            fixed = fixed.replace(f'color: {k}', f'color: {v}').replace(f'color:{k}', f'color:{v}')
        if fixed != ss:
            if original is None:
                w.setProperty('_sg_orig_style', ss)
            w.setStyleSheet(fixed)


class _DarkTextFix(QObject):
    dark = False

    def eventFilter(self, obj, event):
        if self.dark and event.type() == QEvent.Type.Polish and isinstance(obj, QWidget):
            _fix_widget(obj, True)
        return False


def _install_filter(app, dark):
    fix = getattr(app, '_dark_text_fix', None)
    if fix is None:
        fix = _DarkTextFix(app)
        app.installEventFilter(fix)
        app._dark_text_fix = fix
    fix.dark = dark
    for w in app.allWidgets():       # уже созданные виджеты: подмена в тёмной теме, возврат исходного стиля в светлой
        _fix_widget(w, dark)


_ARROW_DIR = None


def _arrow_files(color):
    """Стрелки для списков и счётчиков (PNG во временной папке): Qt в таблице стилей не рисует их сам."""
    import tempfile
    from pathlib import Path
    from PyQt6.QtCore import QByteArray, Qt
    from PyQt6.QtGui import QPixmap, QPainter
    from PyQt6.QtSvg import QSvgRenderer
    global _ARROW_DIR
    if _ARROW_DIR is None:       # отдельный приватный каталог на экземпляр приложения
        _ARROW_DIR = Path(tempfile.mkdtemp(prefix='smetagaz-theme-'))
    folder = _ARROW_DIR
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
    return '#D4D4D8' if dark else '#3F3F46'


def apply(app, dark=False, family='Segoe UI', size=10, accent=''):
    c = colors(dark, accent)
    app.setStyle('Fusion')
    font = QFont(family or FONT_FALLBACKS[0])
    font.setFamilies([f for f in dict.fromkeys([family or FONT_FALLBACKS[0], *FONT_FALLBACKS])])
    try:
        size = int(float(size))
    except (ValueError, TypeError):
        size = 10
    font.setPointSize(max(10, min(14, size)))
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
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
    QToolTip {{ background:{c['text']}; color:{c['panel']}; border:0; border-radius:6px; padding:6px 10px; }}
    QLabel {{ background:transparent; }}

    /* Боковая панель: белая, выбранный пункт — мягкая «таблетка» */
    QFrame#sidebar {{ background:{c['side']}; border:0; border-right:1px solid {c['line']}; }}
    QFrame#sidebar QLabel {{ color:{c['muted']}; }}
    QLabel#brand {{ font-size:18px; font-weight:700; color:{c['text']}; padding:6px 8px; }}
    QScrollArea#navigation {{ background:transparent; border:0; }}
    QWidget#navContent {{ background:{c['side']}; }}
    QPushButton#navButton {{ text-align:left; background:transparent; color:{c['text2']}; border:0; border-radius:8px; padding:8px 12px; min-height:22px; font-weight:400; }}
    QPushButton#navButton:hover {{ background:{c['hover']}; color:{c['text']}; }}
    QPushButton#navButton:checked {{ background:{c['sel']}; color:{c['accent_fg'] if not dark else '#FFFFFF'}; font-weight:600; }}
    QLabel#navSection {{ color:{c['muted']}; font-size:11px; font-weight:600; letter-spacing:1px; padding:10px 14px 2px 14px; background:transparent; }}
    QFrame#navDivider {{ background:transparent; border:0; max-height:0px; }}

    /* Заголовок страницы */
    QFrame#pageHeader {{ background:{c['bg']}; border:0; }}
    QLabel#pageTitle {{ font-size:24px; font-weight:600; color:{c['text']}; }}
    QLabel#pageSubtitle {{ color:{c['muted']}; font-size:12px; }}

    /* Кнопки: плоские, с тонкой рамкой; главная — залитая акцентом */
    QPushButton {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:8px; padding:6px 14px; min-height:22px; }}
    QPushButton:hover {{ background:{c['hover']}; }}
    QPushButton:pressed {{ background:{c['line']}; }}
    QPushButton:focus {{ border:1px solid {c['accent_fg']}; }}
    QPushButton:disabled {{ color:{c['disabled']}; background:{c['alt']}; border-color:{c['line']}; }}
    QPushButton:checked {{ background:{c['sel']}; border-color:{c['sel']}; color:{c['sel_text'] if dark else c['accent_fg']}; font-weight:600; }}
    QPushButton[type="primary"] {{ background:{c['accent']}; border:1px solid {c['accent']}; color:#FFFFFF; font-weight:600; }}
    QPushButton[type="primary"]:hover {{ background:{c['accent_hover']}; border-color:{c['accent_hover']}; }}
    QPushButton[type="primary"]:pressed {{ background:{c['accent_press']}; }}
    QPushButton[type="primary"]:disabled {{ background:{c['line']}; border-color:{c['line']}; color:{c['disabled']}; }}
    QPushButton[type="danger"] {{ color:{'#F87171' if dark else '#B91C1C'}; border-color:{'#7F2A2A' if dark else '#F3C5C5'}; }}
    QPushButton[type="danger"]:hover {{ background:{'#3A1F21' if dark else '#FEF2F2'}; }}
    QPushButton[type="warning"] {{ color:{'#FBBF24' if dark else '#92400E'}; border-color:{'#6B4E12' if dark else '#F3DDB0'}; }}
    QPushButton::menu-indicator {{ subcontrol-position:right center; subcontrol-origin:padding; right:6px; }}

    /* Поля ввода */
    QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{
        background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:8px; padding:5px 10px; min-height:22px;
        selection-background-color:{c['accent']}; selection-color:#FFFFFF; }}
    QLineEdit:hover, QTextEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QDateEdit:hover {{ border-color:{c['muted']}; }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {{ border:1px solid {c['accent_fg']}; }}
    QLineEdit:read-only {{ background:{c['alt']}; }}
    QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QDateEdit:disabled {{ background:{c['alt']}; color:{c['disabled']}; border-color:{c['line']}; }}
    QComboBox::drop-down, QDateEdit::drop-down {{ border:0; width:26px; subcontrol-origin:padding; subcontrol-position:center right; }}
    QComboBox::down-arrow, QDateEdit::down-arrow {{ image:url({arrows['down']}); width:14px; height:14px; }}
    QSpinBox, QDoubleSpinBox, QTimeEdit {{ padding-right:24px; }}
    QSpinBox::up-button, QDoubleSpinBox::up-button, QTimeEdit::up-button {{ subcontrol-origin:border; subcontrol-position:top right; width:22px; border:0; background:transparent; }}
    QSpinBox::down-button, QDoubleSpinBox::down-button, QTimeEdit::down-button {{ subcontrol-origin:border; subcontrol-position:bottom right; width:22px; border:0; background:transparent; }}
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover, QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background:{c['hover']}; }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QTimeEdit::up-arrow {{ image:url({arrows['up']}); width:10px; height:10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QTimeEdit::down-arrow {{ image:url({arrows['down']}); width:10px; height:10px; }}
    QComboBox QAbstractItemView {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['border']}; border-radius:8px; selection-background-color:{c['sel']}; selection-color:{c['sel_text']}; outline:0; padding:4px; }}
    QCheckBox, QRadioButton {{ spacing:8px; min-height:22px; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color:{c['disabled']}; }}

    /* Таблицы и списки: без сетки, тонкие линии строк */
    QTableView {{ qproperty-showGrid:false; qproperty-alternatingRowColors:false; }}
    QTableView, QTreeView, QListView, QListWidget {{ background:{c['panel']}; alternate-background-color:{c['alt']}; color:{c['text']}; border:1px solid {c['line']}; border-radius:10px;
        selection-background-color:{c['sel']}; selection-color:{c['sel_text']}; outline:0; }}
    QTableView::item, QTreeView::item, QListView::item {{ padding:5px 8px; border-bottom:1px solid {c['line']}; }}
    QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{ background:{c['sel']}; color:{c['sel_text']}; }}
    QTableView::item:hover, QTreeView::item:hover {{ background:{c['hover']}; }}
    QHeaderView::section {{ background:{c['header']}; color:{c['muted']}; font-weight:600; font-size:12px; padding:9px 10px; border:0; border-bottom:1px solid {c['border']}; }}
    QTableCornerButton::section {{ background:{c['header']}; border:0; border-bottom:1px solid {c['border']}; }}

    /* Вкладки: тонкое подчёркивание выбранной */
    QTabWidget::pane {{ background:{c['panel']}; border:1px solid {c['line']}; border-radius:10px; top:-1px; }}
    QTabBar::tab {{ background:transparent; color:{c['muted']}; border:0; border-bottom:2px solid transparent; padding:8px 14px; margin-right:4px; }}
    QTabBar::tab:hover {{ color:{c['text']}; }}
    QTabBar::tab:selected {{ color:{c['accent_fg']}; border-bottom:2px solid {c['accent_fg']}; font-weight:600; }}
    QTabBar::tab:disabled {{ color:{c['disabled']}; }}

    /* Группы-карточки */
    QGroupBox {{ background:{c['panel']}; border:1px solid {c['line']}; border-radius:12px; margin-top:16px; padding:18px 12px 12px; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:14px; padding:0 6px; color:{c['text2']}; font-weight:600; }}
    QFrame#metricCard {{ background:{c['panel']}; border:1px solid {c['line']}; border-radius:12px; padding:12px; }}

    /* Прокрутка */
    QScrollArea {{ border:0; background:transparent; }}
    QScrollBar:vertical {{ background:transparent; width:12px; margin:0; }}
    QScrollBar::handle:vertical {{ background:{c['scroll']}; border-radius:4px; min-height:30px; margin:2px; }}
    QScrollBar::handle:vertical:hover {{ background:{c['scroll_hover']}; }}
    QScrollBar:horizontal {{ background:transparent; height:12px; }}
    QScrollBar::handle:horizontal {{ background:{c['scroll']}; border-radius:4px; min-width:30px; margin:2px; }}
    QScrollBar::handle:horizontal:hover {{ background:{c['scroll_hover']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}

    QProgressBar {{ border:0; background:{c['line']}; border-radius:4px; text-align:center; color:{c['text']}; min-height:8px; }}
    QProgressBar::chunk {{ background:{c['accent']}; border-radius:4px; }}
    QMenu {{ background:{c['panel']}; color:{c['text']}; border:1px solid {c['line']}; border-radius:10px; padding:6px; }}
    QMenu::item {{ padding:7px 26px 7px 14px; border-radius:6px; }}
    QMenu::item:selected {{ background:{c['hover']}; color:{c['text']}; }}
    QMenu::item:disabled {{ color:{c['disabled']}; }}
    QMenu::separator {{ height:1px; background:{c['line']}; margin:4px 6px; }}
    QSplitter::handle {{ background:transparent; }}
    QSplitter::handle:horizontal {{ width:6px; }} QSplitter::handle:vertical {{ height:6px; }}
    QDialogButtonBox QPushButton {{ min-width:84px; }}
    QCalendarWidget QAbstractItemView {{ selection-background-color:{c['accent']}; selection-color:#FFFFFF; }}
    QCalendarWidget QToolButton {{ color:{c['text']}; background:transparent; border:0; padding:4px 8px; }}
    ''')
