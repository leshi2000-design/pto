"""Правка уже сохранённой записи входящего документа (реквизиты и привязка к объекту)."""
from PyQt6.QtWidgets import QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QLineEdit, QPushButton, QLabel

from . import incoming_domain as inc
from . import staff_domain as sd
from .database import db
from .domain_widgets import OptionalDate


class EditDialog(QDialog):
    def __init__(self, d, parent=None):
        super().__init__(parent)
        self.d = d
        self.setWindowTitle('Входящий документ')
        self.resize(560, 360)
        f = QFormLayout(self)
        f.addRow(QLabel(f'<b>{d["name"]}</b>'))
        self.kind = QComboBox()
        self.kind.addItems(inc.KINDS)
        self.kind.setCurrentText(d['kind'])
        self.number = QLineEdit(d['number'])
        self.date = OptionalDate()
        self.date.set_value(d['date'] or '')
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e9)
        self.amount.setDecimals(2)
        self.amount.setValue(d['amount'] or 0)
        self.counterparty = QLineEdit(d['counterparty'])
        self.note = QLineEdit(d['note'])
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти объект…')
        self.object = QComboBox()
        self.search.textChanged.connect(self.load_objects)
        for label, w in (('Вид', self.kind), ('Номер', self.number), ('Дата', self.date), ('Сумма', self.amount), ('Контрагент', self.counterparty), ('Примечание', self.note), ('Поиск объекта', self.search), ('Объект', self.object)):
            f.addRow(label, w)
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        self.load_objects()

    def load_objects(self):
        keep = self.object.currentData() if self.object.count() else ((self.d['owner_type'], self.d['owner_id']) if self.d['owner_type'] else None)
        self.object.clear()
        self.object.addItem('— без объекта —', None)
        for table, rid, label in sd.objects(db, self.search.text().strip()):
            self.object.addItem(label, (table, rid))
        for i in range(self.object.count()):
            if keep and self.object.itemData(i) == keep:
                self.object.setCurrentIndex(i)

    def save(self):
        obj = self.object.currentData() or ('', None)
        inc.update(db, self.d['id'], dict(kind=self.kind.currentText(), number=self.number.text(), doc_date=self.date.value() or '', amount=self.amount.value() or None,
                                           counterparty=self.counterparty.text(), owner_type=obj[0], owner_id=obj[1], note=self.note.text()))
        self.accept()
