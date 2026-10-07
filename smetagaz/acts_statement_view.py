"""Окно ведомости подписанных актов за месяц."""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
                              QAbstractItemView, QFileDialog, QMessageBox, QWidget)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from .database import db
from . import acts_statement as st
from .platform_utils import open_local


def money(v):
    return f'{float(v or 0):,.2f}'.replace(',', ' ').replace('.', ',')


class ActsStatementDialog(QDialog):
    def __init__(self, section, parent=None):
        super().__init__(parent)
        self.section = section
        self.data = {'signed': [], 'unsigned': []}
        self.setWindowTitle(f'Ведомость подписанных актов · {st.SECTIONS[section]}')
        self.resize(1100, 640)
        layout = QVBoxLayout(self)
        year, month = st.default_period()
        bar = QHBoxLayout()
        bar.addWidget(QLabel('Месяц:'))
        self.month = QComboBox()
        for i in range(1, 13):
            self.month.addItem(st.MONTHS[i].capitalize(), i)
        self.month.setCurrentIndex(month - 1)
        self.year = QSpinBox()
        self.year.setRange(2000, 2100)
        self.year.setValue(year)
        bar.addWidget(self.month)
        bar.addWidget(self.year)
        self.summary = QLabel()
        self.summary.setStyleSheet('font-weight: 600;')
        bar.addWidget(self.summary, 1)
        layout.addLayout(bar)
        self.tabs = QTabWidget()
        self.signed = self.make_table()
        self.unsigned = self.make_table()
        self.tabs.addTab(self.signed, 'Подписанные акты')
        self.tabs.addTab(self.unsigned, 'Не подписаны')
        layout.addWidget(self.tabs, 1)
        self.note = QLabel('')
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color: #65758b;')
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        excel = QPushButton('Сохранить ведомость в Excel…')
        excel.setProperty('type', 'primary')
        excel.clicked.connect(self.save_excel)
        collect = QPushButton('Собрать акты и ведомость в папку…')
        collect.clicked.connect(self.collect)
        open_act = QPushButton('Открыть акт')
        open_act.clicked.connect(self.open_selected)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        for b in (excel, collect, open_act):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.month.currentIndexChanged.connect(self.load)
        self.year.valueChanged.connect(self.load)
        self.load()

    @staticmethod
    def make_table():
        t = QTableWidget(0, 10)
        t.setHorizontalHeaderLabels(['Дата акта', '№ договора', 'Клиент', 'Объект', 'Адрес', 'Сумма', 'Оплачено', 'Остаток', 'Файл акта', 'Дата договора'])
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.horizontalHeader().setStretchLastSection(True)
        for i, w in enumerate((95, 110, 230, 220, 220, 90, 90, 90, 80)):
            t.setColumnWidth(i, w)
        return t

    def period(self):
        return self.year.value(), self.month.currentData()

    def load(self, *_):
        self.data = st.statement(db, self.section, *self.period())
        for table, rows in ((self.signed, self.data['signed']), (self.unsigned, self.data['unsigned'])):
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                values = [st._fmt(row['act_date']), row['contract_number'], row['client'], row['object'], row['address'], money(row['amount']), money(row['paid']),
                          money(row['rest']), 'есть' if row['file'] else 'нет', st._fmt(row['contract_date'])]
                for c, v in enumerate(values):
                    item = QTableWidgetItem(v)
                    item.setData(Qt.ItemDataRole.UserRole, r)
                    if c >= 5 and c <= 7:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if c == 8 and not row['file']:
                        item.setForeground(QColor('#DC2626'))
                    table.setItem(r, c, item)
        signed = self.data['signed']
        self.summary.setText(f'{st.period_label(*self.period()).capitalize()}: подписано актов — {len(signed)} на сумму {money(sum(r["amount"] for r in signed))} BYN; '
                             f'не подписано — {len(self.data["unsigned"])}')
        self.tabs.setTabText(0, f'Подписанные акты ({len(signed)})')
        self.tabs.setTabText(1, f'Не подписаны ({len(self.data["unsigned"])})')
        no_file = [r for r in signed if not r['file']]
        self.note.setText(f'У {len(no_file)} подписанных актов нет сформированного файла — они попадут только в ведомость.' if no_file else '')

    def save_excel(self):
        year, month = self.period()
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить ведомость', f'Ведомость_актов_{st.SECTIONS[self.section].replace(" ", "_")}_{year}-{month:02d}.xlsx', 'Excel (*.xlsx)')
        if not path:
            return
        try:
            st.export_statement(db, self.section, year, month, path)
        except OSError as e:
            QMessageBox.warning(self, 'Ведомость', f'Не удалось сохранить файл (возможно, он открыт в Excel):\n{e}')
            return
        open_local(path)

    def collect(self):
        year, month = self.period()
        target = QFileDialog.getExistingDirectory(self, 'Куда собрать акты и ведомость?')
        if not target:
            return
        try:
            result = st.collect_acts(db, self.section, year, month, target)
        except OSError as e:
            QMessageBox.warning(self, 'Ведомость', str(e))
            return
        text = f'Папка: {result["folder"]}\nСкопировано актов: {len(result["copied"])} из {result["total"]}; ведомость сохранена.'
        if result['missing']:
            text += '\n\nНет файла акта (сформируйте акт в карточке договора):\n' + '\n'.join(f'• {r["contract_number"]} — {r["client"]}' for r in result['missing'][:20])
        QMessageBox.information(self, 'Акты собраны', text)
        open_local(result['folder'])

    def open_selected(self):
        table = self.signed if self.tabs.currentIndex() == 0 else self.unsigned
        rows = self.data['signed'] if self.tabs.currentIndex() == 0 else self.data['unsigned']
        r = table.currentRow()
        if r < 0 or r >= len(rows):
            return
        if rows[r]['file']:
            open_local(rows[r]['file'])
        else:
            QMessageBox.information(self, 'Акт', 'Файл акта для этого договора не сформирован.')

