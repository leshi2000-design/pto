"""Монтаж ГСН: вкладка «Пикеты» — ввод пикетов трассы (название, расстояние от начала, примечание). У каждого пикета есть свои теги для документов."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QInputDialog, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import gsn_docs as dd
from . import gsn_domain as gn
from .database import db

COLUMNS = ('Пикет', 'Расстояние от начала, м', 'Примечание')


class GsnPicketsTab(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        hint = QLabel('Пикеты трассы: название (например, ПК0, ПК1+50), расстояние от начала трассы в метрах и примечание. Сохраняются вместе с договором. Теги для шаблонов: '
                      '{ПИКЕТ_1}, {ПИКЕТ_2}, … (название), {ПИКЕТ_1_РАССТОЯНИЕ}, {ПИКЕТ_1_ПРИМЕЧАНИЕ} и так далее для каждого пикета (до 40 и больше, сколько введено); '
                      '{ПИКЕТЫ} — все названия по строкам, {ПИКЕТОВ_ВСЕГО} — количество. Если пикетов меньше, чем тегов в шаблоне, строка шаблона с лишним тегом из документа удаляется.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 200)
        self.table.setColumnWidth(1, 200)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(True)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.buttons = []
        for text, fn in (('Добавить пикет', self.add), ('Добавить несколько…', self.add_many), ('Удалить', self.remove), ('Вверх', lambda: self.move(-1)), ('Вниз', lambda: self.move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
            self.buttons.append(b)
        bar.addStretch()
        self.count = QLabel('')
        bar.addWidget(self.count)
        layout.addLayout(bar)
        self.table.itemChanged.connect(lambda *_: self.refresh_count())

    # --- данные ---
    def fill(self, rows):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for r in rows:
            self.append(r['name'], '' if r['distance'] is None else dd._num(r['distance']), r['note'])
        self.table.blockSignals(False)
        self.refresh_count()

    def load(self, cid):
        self.fill(gn.pickets(db, cid) if cid else [])

    def rows(self):
        """Строки таблицы для сохранения; ValueError с понятным текстом при ошибке ввода."""
        out = []
        for r in range(self.table.rowCount()):
            cells = [self.table.item(r, c) for c in range(3)]
            out.append(dict(name=cells[0].text() if cells[0] else '', distance=cells[1].text() if cells[1] else '', note=cells[2].text() if cells[2] else ''))
        return gn.clean_pickets(out)

    def append(self, name='', distance='', note=''):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, value in enumerate((name, distance, note)):
            item = QTableWidgetItem(str(value))
            if c == 1:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, c, item)
        return r

    def refresh_count(self):
        n = sum(1 for r in range(self.table.rowCount()) if any((self.table.item(r, c) and self.table.item(r, c).text().strip()) for c in range(3)))
        self.count.setText(f'Пикетов: {n}')

    # --- кнопки ---
    def add(self):
        r = self.append()
        self.table.setCurrentCell(r, 0)
        self.table.editItem(self.table.item(r, 0))
        self.refresh_count()

    def add_many(self):
        n, ok = QInputDialog.getInt(self, 'Несколько пикетов', 'Сколько пикетов добавить:', 5, 1, 500)
        if not ok:
            return
        step, ok = QInputDialog.getDouble(self, 'Несколько пикетов', 'Шаг между пикетами, м (0 — не заполнять расстояние):', 100, 0, 100000, 2)
        if not ok:
            return
        start = self.table.rowCount()
        for i in range(n):
            self.append(f'ПК{start + i}', dd._num(step * (start + i)) if step else '')
        self.refresh_count()

    def remove(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self.refresh_count()

    def move(self, delta):
        r = self.table.currentRow()
        t = r + delta
        if r < 0 or not 0 <= t < self.table.rowCount():
            return
        for c in range(3):
            a, b = self.table.takeItem(r, c), self.table.takeItem(t, c)
            self.table.setItem(r, c, b)
            self.table.setItem(t, c, a)
        self.table.setCurrentCell(t, self.table.currentColumn())

    def set_enabled_inputs(self, enabled):
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers if enabled else QAbstractItemView.EditTrigger.NoEditTriggers)
        for b in self.buttons:
            b.setEnabled(enabled)
