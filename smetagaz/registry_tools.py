"""Инструменты реестров: умный поиск (слова, телефон, адрес), сохранённые выборки и настройка колонок.
Выборки и скрытые колонки хранятся в настройках по ключу реестра."""
import json
import re

from PyQt6.QtWidgets import QToolButton, QMenu, QInputDialog, QMessageBox, QHeaderView
from PyQt6.QtCore import Qt, QObject
from PyQt6.QtGui import QAction


def search_clause(text, text_exprs, phone_exprs=()):
    """(SQL, параметры): каждое слово запроса должно найтись в одном из текстовых полей; слово из ≥3 цифр ищется и в телефонах без учёта пробелов, скобок и «+»."""
    text = str(text or '').strip().casefold()
    words = [w for w in re.split(r'\s+', text) if w]
    if not words:
        return '1=1', []
    if re.fullmatch(r'[\d\s+()\-]+', text) and sum(ch.isdigit() for ch in text) >= 3 and phone_exprs:
        words = [text]             # запрос из цифр, пробелов и скобок — это телефон целиком («29 111 22»)
    haystack = " || ' ' || ".join(f"coalesce({e},'')" for e in text_exprs) or "''"
    parts, params = [], []
    for word in words:
        piece = [f'LOWER({haystack}) LIKE ?']
        params.append(f'%{word}%')
        digits = ''.join(ch for ch in word if ch.isdigit())
        if len(digits) >= 3:
            for expr in phone_exprs:
                piece.append(f'digits({expr}) LIKE ?')
                params.append(f'%{digits}%')
        parts.append('(' + ' OR '.join(piece) + ')')
    return ' AND '.join(parts), params


def _load(db, key, default):
    try:
        value = json.loads(db.get_setting(key, ''))
        return value if isinstance(value, type(default)) else default
    except (ValueError, TypeError):
        return default


TITLES = {'contracts': 'Реестр · Монтаж ГСВ', 'gsv_projects': 'Реестр · Проекты ГСВ', 'welders': 'Сварщики', 'contracts_le': 'Реестр · Юрлица', 'contracts_smr': 'Реестр · СМР'}


class RegistryTools(QObject):
    """Подключается к таблице и строке поиска реестра: кнопки «Выборки» и «Колонки», меню заголовка."""

    def __init__(self, db, key, table, search_edit, bar_layout=None, parent=None):
        super().__init__(table)        # принадлежит таблице: без циклических ссылок Python, уничтожается вместе с ней
        self.db, self.key, self.table, self.search, self.parent = db, key, table, search_edit, parent or table
        self.filters_button = QToolButton()
        self.filters_button.setText('Выборки ▾')
        self.filters_button.setToolTip('Сохранить текущий поиск под именем и быстро возвращаться к нему')
        self.filters_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.columns_button = QToolButton()
        self.columns_button.setText('Колонки ▾')
        self.columns_button.setToolTip('Показать или скрыть колонки')
        self.columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        for button in (self.filters_button, self.columns_button):
            button.setProperty('registryTool', True)
            button.setMinimumHeight(30)
        self.filters_menu, self.columns_menu = QMenu(self.filters_button), QMenu(self.columns_button)
        self.filters_menu.aboutToShow.connect(self.build_filters_menu)
        self.columns_menu.aboutToShow.connect(self.build_columns_menu)
        self.filters_button.setMenu(self.filters_menu)
        self.columns_button.setMenu(self.columns_menu)
        if bar_layout is not None:
            index = bar_layout.count()
            if index and bar_layout.itemAt(index - 1).spacerItem() is not None:
                index -= 1
            bar_layout.insertWidget(index, self.filters_button)
            bar_layout.insertWidget(index + 1, self.columns_button)
            from .print_ui import make_buttons
            title = TITLES.get(key, 'Реестр')
            self.pdf_button, self.print_button = make_buttons(table, lambda: self.print_data(title), title)
            for k, button in enumerate((self.pdf_button, self.print_button)):
                button.setProperty('registryTool', True)
                button.setMinimumHeight(30)
                bar_layout.insertWidget(index + 2 + k, button)
        header = table.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.show_header_menu)
        self.apply_columns()

    def print_data(self, title):
        from .print_ui import table_html
        q = self.search.text().strip() if hasattr(self.search, 'text') else ''
        return table_html(title, self.table, f'поиск: {q}' if q else '')

    def show_header_menu(self, pos):
        self.build_columns_menu()
        self.columns_menu.exec(self.table.horizontalHeader().mapToGlobal(pos))

    # --- колонки -------------------------------------------------------------------------------
    def _count(self):
        return self.table.model().columnCount() if hasattr(self.table, 'model') and self.table.model() is not None else self.table.columnCount()

    def _label(self, col):
        model = self.table.model()
        value = model.headerData(col, Qt.Orientation.Horizontal) if model is not None else None
        return str(value) if value else f'Колонка {col + 1}'

    def hidden(self):
        return {int(i) for i in _load(self.db, f'cols_{self.key}', []) if isinstance(i, int)}

    def apply_columns(self):
        hidden = self.hidden()
        for col in range(self._count()):
            self.table.setColumnHidden(col, col in hidden)
        if len(hidden) >= self._count():          # нельзя скрыть всё
            self.table.setColumnHidden(0, False)

    def build_columns_menu(self):
        self.columns_menu.clear()
        hidden = self.hidden()
        for col in range(self._count()):
            action = QAction(self._label(col), self.columns_menu)
            action.setCheckable(True)
            action.setChecked(col not in hidden)
            action.setData(col)
            action.toggled.connect(self.on_column_toggled)
            self.columns_menu.addAction(action)
        self.columns_menu.addSeparator()
        reset = self.columns_menu.addAction('Показать все колонки')
        reset.triggered.connect(self.reset_columns)

    def on_column_toggled(self, on):
        self.set_visible(int(self.sender().data()), on)

    def set_visible(self, col, visible):
        hidden = self.hidden()
        if visible:
            hidden.discard(col)
        elif len(hidden) + 1 < self._count():
            hidden.add(col)
        self.db.set_setting(f'cols_{self.key}', json.dumps(sorted(hidden)))
        self.apply_columns()

    def reset_columns(self):
        self.db.set_setting(f'cols_{self.key}', '[]')
        self.apply_columns()

    # --- выборки -------------------------------------------------------------------------------
    def filters(self):
        return _load(self.db, f'filters_{self.key}', {})

    def build_filters_menu(self):
        self.filters_menu.clear()
        saved = self.filters()
        for name, state in saved.items():
            action = self.filters_menu.addAction(name)
            action.setData(str(state.get('text', '')))
            action.triggered.connect(self.apply_filter)
        if saved:
            self.filters_menu.addSeparator()
        save = self.filters_menu.addAction('Сохранить текущий поиск как…')
        save.setEnabled(bool(self.search.text().strip()))
        save.triggered.connect(self.save_current)
        clear = self.filters_menu.addAction('Сбросить поиск')
        clear.triggered.connect(self.clear_search)
        if saved:
            remove = self.filters_menu.addMenu('Удалить выборку')
            for name in saved:
                entry = remove.addAction(name)
                entry.setData(name)
                entry.triggered.connect(self.delete_clicked)

    def apply_filter(self):
        self.search.setText(str(self.sender().data() or ''))

    def clear_search(self):
        self.search.setText('')

    def delete_clicked(self):
        self.delete(str(self.sender().data()))

    def save_current(self):
        text = self.search.text().strip()
        name, ok = QInputDialog.getText(self.parent, 'Выборка', 'Название выборки:', text=text[:40])
        name = name.strip()
        if not ok or not name:
            return
        saved = self.filters()
        if name in saved and QMessageBox.question(self.parent, 'Выборка', f'Выборка «{name}» уже есть. Заменить?') != QMessageBox.StandardButton.Yes:
            return
        saved[name] = {'text': text}
        self.db.set_setting(f'filters_{self.key}', json.dumps(saved, ensure_ascii=False))

    def delete(self, name):
        saved = self.filters()
        saved.pop(name, None)
        self.db.set_setting(f'filters_{self.key}', json.dumps(saved, ensure_ascii=False))


def autofit_columns(table, max_width=460, min_width=70, stretch_last=True):
    """Ширина колонок по содержимому (с пределом), чтобы данные читались без захода в карточку; пользователь может менять ширину вручную."""
    header = table.horizontalHeader()
    table.resizeColumnsToContents()
    for col in range(table.columnCount()):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        table.setColumnWidth(col, max(min_width, min(max_width, table.columnWidth(col) + 14)))
    header.setStretchLastSection(stretch_last)
