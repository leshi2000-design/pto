"""Окно «Обновление цен по ссылкам»: проверка в фоне, таблица «было → стало», применение отмеченных цен."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox, QCheckBox)

from .database import db
from . import price_sync as ps
from . import background

COLORS = {'changed': '#B45309', 'same': '#15803D', 'suspicious': '#B91C1C', 'error': '#B91C1C'}


class PriceUpdateDialog(QDialog):
    def __init__(self, parent=None, category_id=None, ids=None):
        super().__init__(parent)
        self.setWindowTitle('Обновление цен по ссылкам поставщиков')
        self.resize(1100, 640)
        self.ids = list(ids) if ids is not None else ps.linked_material_ids(db, category_id)
        self.results, self.job = [], None
        layout = QVBoxLayout(self)
        self.info = QLabel(f'Позиций со ссылкой: {len(self.ids)}. Цены читаются со страниц поставщиков; новая цена записывается только после вашего подтверждения.')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Применить', 'Позиция', 'Было', 'Стало', 'Изменение', 'Результат', 'Ссылка'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((90, 330, 90, 90, 100, 330)):
            self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.btn_check = QPushButton('Проверить цены')
        self.btn_check.setProperty('type', 'primary')
        self.btn_check.clicked.connect(self.start)
        self.btn_apply = QPushButton('Применить отмеченные')
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.apply)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        for w in (self.btn_check, self.btn_apply):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(close)
        layout.addLayout(bar)
        self.status = QLabel('')
        layout.addWidget(self.status)

    def start(self):
        if not self.ids:
            QMessageBox.information(self, 'Цены', 'Ни у одной позиции не указана ссылка поставщика. Укажите её в карточке позиции.')
            return
        self.btn_check.setEnabled(False)
        self.btn_apply.setEnabled(False)
        self.status.setText('Проверка…')
        self.job = background.run(self, 'Проверка цен на сайтах', lambda ctx: ps.check_many(db, self.ids, ctx), done=self.show_results,
                                  error=self.failed, cancelled=self.cancelled)

    def failed(self, error):
        self.btn_check.setEnabled(True)
        self.status.setText(f'Проверка не выполнена: {error}')

    def cancelled(self):
        self.btn_check.setEnabled(True)
        self.status.setText('Проверка отменена. Цены не изменены.')

    def show_results(self, results):
        self.results = results
        ps.mark_checked(db, results)
        self.table.setRowCount(len(results))
        counts = {key: 0 for key in ps.STATUS_TEXT}
        for r, res in enumerate(results):
            counts[res['status']] += 1
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled if res['status'] in ('changed', 'suspicious') else Qt.ItemFlag.NoItemFlags)
            check.setCheckState(Qt.CheckState.Checked if res['status'] == 'changed' else Qt.CheckState.Unchecked)
            self.table.setItem(r, 0, check)
            delta = ''
            if res['new'] is not None and res['old']:
                delta = f'{(res["new"] / res["old"] - 1) * 100:+.1f}%'
            values = [res['name'], f'{res["old"]:.2f}', '' if res['new'] is None else f'{res["new"]:.2f}', delta, ps.STATUS_TEXT[res['status']] + (': ' + res['message'] if res['message'] and res['status'] != 'same' else ''), res['url']]
            for c, value in enumerate(values, 1):
                item = QTableWidgetItem(value)
                item.setToolTip(res['message'])
                if c == 5:
                    item.setForeground(QColor(COLORS[res['status']]))
                if c in (2, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, item)
        self.btn_check.setEnabled(True)
        self.btn_apply.setEnabled(counts['changed'] + counts['suspicious'] > 0)
        self.status.setText(f'Изменились: {counts["changed"]} · без изменений: {counts["same"]} · требуют проверки: {counts["suspicious"]} · ошибки: {counts["error"]}. '
                            'Позиции с резким изменением цены не отмечены: проверьте их вручную.')

    def apply(self):
        changes = []
        for r, res in enumerate(self.results):
            item = self.table.item(r, 0)
            if item and item.checkState() == Qt.CheckState.Checked and res['new']:
                changes.append((res['id'], res['new']))
        if not changes:
            QMessageBox.information(self, 'Цены', 'Не отмечено ни одной позиции.')
            return
        count = ps.apply_prices(db, changes)
        self.btn_apply.setEnabled(False)
        self.status.setText(f'Цены обновлены у {count} позиций. История изменений сохранена в карточке позиции.')


class PriceHistoryDialog(QDialog):
    def __init__(self, material_id, parent=None):
        super().__init__(parent)
        self.setWindowTitle('История цен')
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        rows = ps.history(db, material_id)
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(['Когда', 'Было', 'Стало', 'Источник'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        for r, (when, old, new, source) in enumerate(rows):
            for c, value in enumerate((when.replace('T', ' '), f'{old or 0:.2f}', f'{new or 0:.2f}', source)):
                table.setItem(r, c, QTableWidgetItem(value))
        layout.addWidget(table)
        if not rows:
            layout.addWidget(QLabel('Изменений цены по ссылке пока не было.'))
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
