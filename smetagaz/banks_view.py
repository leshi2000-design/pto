"""Реестр банков (вкладка «Справочника юрлиц»)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit,
                              QVBoxLayout, QWidget)

from . import banks_domain as bd
from .database import db


class BankDialog(QDialog):
    def __init__(self, bid=None, parent=None):
        super().__init__(parent)
        self.bid = bid
        self.setWindowTitle('Банк' if bid else 'Новый банк')
        self.resize(520, 360)
        f = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText('ОАО «Белагропромбанк»')
        self.bic = QLineEdit()
        self.bic.setPlaceholderText('BAPBBY2X')
        self.address = QLineEdit()
        self.unp = QLineEdit()
        self.note = QTextEdit()
        self.note.setMaximumHeight(70)
        for label, w in (('Название *', self.name), ('БИК (SWIFT)', self.bic), ('Адрес банка', self.address), ('УНП банка', self.unp), ('Примечание', self.note)):
            f.addRow(label, w)
        hint = QLabel('Название, БИК и адрес подставляются в реквизиты юрлиц, выбравших этот банк. Изменив банк здесь, вы обновите реквизиты у всех таких юрлиц.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #605E5C;')
        f.addRow(hint)
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        if bid:
            b = bd.get(db, bid)
            self.name.setText(b['name'])
            self.bic.setText(b['bic'] or '')
            self.address.setText(b['address'] or '')
            self.unp.setText(b['unp'] or '')
            self.note.setPlainText(b['note'] or '')

    def save(self):
        try:
            self.bid = bd.save(db, dict(name=self.name.text(), bic=self.bic.text(), address=self.address.text(), unp=self.unp.text(), note=self.note.toPlainText()), self.bid)
        except ValueError as e:
            QMessageBox.warning(self, 'Банк не сохранён', str(e))
            return
        self.accept()


class BanksRegistry(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Название, БИК, адрес…')
        bar.addWidget(self.search, 1)
        for text, fn in (('Добавить банк', self.add), ('Изменить', self.edit), ('Удалить', self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text == 'Добавить банк':
                b.setProperty('type', 'primary')
            bar.addWidget(b)
        layout.addLayout(bar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Банк', 'БИК', 'Адрес', 'УНП', 'Юрлиц с этим банком'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        layout.addWidget(self.table, 1)
        self.search.textChanged.connect(self.load_data)
        self.load_data()

    def load_data(self, *_):
        rows = bd.listing(db, self.search.text().strip())
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate((row[1], row[2], row[3], row[4], row[6] or '')):
                item = QTableWidgetItem(str(v or ''))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row[0])
                self.table.setItem(r, c, item)

    def current(self):
        r = self.table.currentRow()
        item = self.table.item(r, 0) if r >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add(self):
        BankDialog(None, self).exec()
        self.load_data()

    def edit(self):
        bid = self.current()
        if bid:
            BankDialog(bid, self).exec()
            self.load_data()

    def delete(self):
        bid = self.current()
        if bid and QMessageBox.question(self, 'Удалить банк', 'Удалить банк из реестра? У юрлиц его название и БИК останутся текстом.') == QMessageBox.StandardButton.Yes:
            bd.delete(db, bid)
            self.load_data()
