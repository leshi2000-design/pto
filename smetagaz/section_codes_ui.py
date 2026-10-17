"""Настройки → «Номера разделов договоров»: у каждого вида договора свой номер раздела, который вводится вручную."""
from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from . import section_codes as sc
from .database import db


class SectionCodesBox(QGroupBox):
    def __init__(self, parent=None):
        super().__init__('Номера разделов договоров', parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('В номере договора «07-02/26» число «02» — номер раздела: он показывает вид договора. У каждого вида договора свой номер раздела; впишите нужные '
                                'в колонку «Номер раздела» (1–4 знака: цифры или буквы, у разных видов они не должны совпадать). Меняются только номера НОВЫХ договоров, '
                                'уже созданные остаются как есть.'))
        self.table = QTableWidget(len(sc.KINDS), 4)
        self.table.setHorizontalHeaderLabels(['Вид договора', 'Номер раздела', 'Пример следующего номера', 'Договоров с этим номером'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setMaximumHeight(60 + 32 * len(sc.KINDS))
        layout.addWidget(self.table)
        bar = QHBoxLayout()
        save = QPushButton('Сохранить номера разделов')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        reset = QPushButton('Вернуть стандартные')
        reset.clicked.connect(self.reset)
        self.status = QLabel('')
        bar.addWidget(save)
        bar.addWidget(reset)
        bar.addWidget(self.status, 1)
        layout.addLayout(bar)
        self.table.itemChanged.connect(lambda *_: self.refresh_examples())
        self.load()

    def load(self):
        self.table.blockSignals(True)
        for r, (key, (title, _default, where)) in enumerate(sc.KINDS.items()):
            name = QTableWidgetItem(f'{title}  ({where})')
            name.setFlags(Qt.ItemFlag.ItemIsEnabled)
            name.setData(Qt.ItemDataRole.UserRole, key)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, QTableWidgetItem(sc.code(db, key)))
            example = QTableWidgetItem()
            example.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 2, example)
            count = QTableWidgetItem(str(sc.used(db, key)))
            count.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(r, 3, count)
        self.table.blockSignals(False)
        self.refresh_examples()

    def values(self):
        return {self.table.item(r, 0).data(Qt.ItemDataRole.UserRole): self.table.item(r, 1).text().strip() for r in range(self.table.rowCount())}

    def refresh_examples(self):
        yy = date.today().year % 100
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            code = self.table.item(r, 1).text().strip() or '??'
            self.table.item(r, 2).setText(f'NN-{code}/{yy:02}')
        self.table.blockSignals(False)

    def save(self):
        values = self.values()
        changed = [sc.KINDS[k][0] for k, v in values.items() if v != sc.code(db, k)]
        if changed and QMessageBox.question(self, 'Номера разделов', 'Изменить номер раздела для: ' + ', '.join(changed) + '?\n\nНовые договоры получат новый номер раздела, '
                                            'прежние номера не изменятся.') != QMessageBox.StandardButton.Yes:
            return
        try:
            sc.save_all(db, values)
        except ValueError as e:
            QMessageBox.warning(self, 'Номера разделов', str(e))
            return
        self.status.setText('Сохранено' if changed else 'Изменений нет')
        self.load()

    def reset(self):
        for r, (key, (_t, default, _w)) in enumerate(sc.KINDS.items()):
            self.table.item(r, 1).setText(default)
