"""Модуль «Контакты»: рабочая телефонная книга."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from . import contacts_domain as cd
from .database import db
from .domain_widgets import PhonesEditor


class ContactDialog(QDialog):
    def __init__(self, contact_id=None, parent=None, preset=None):
        super().__init__(parent)
        self.contact_id = contact_id
        self.setWindowTitle('Контакт')
        self.resize(620, 620)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.organization = QLineEdit()
        self.position = QLineEdit()
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(cd.CATEGORIES)
        self.phone = PhonesEditor()
        self.email = QLineEdit()
        self.address = QLineEdit()
        self.client = QComboBox()
        self.client.addItem('— не связан —', None)
        for pid, nm in db.fetchall('SELECT id,name FROM crm.clients ORDER BY name'):
            self.client.addItem(nm, pid)
        self.legal = QComboBox()
        self.legal.addItem('— не связан —', None)
        for lid, nm in db.fetchall('SELECT id,name FROM le_clients ORDER BY name'):
            self.legal.addItem(nm, lid)
        self.note = QTextEdit()
        self.note.setFixedHeight(80)
        self.favorite = QCheckBox('Избранный (показывать сверху)')
        for label, w in (('Имя / ФИО *', self.name), ('Организация', self.organization), ('Должность', self.position), ('Категория', self.category), ('Телефоны', self.phone),
                         ('E-mail', self.email), ('Адрес', self.address), ('Клиент (физлицо)', self.client), ('Юрлицо', self.legal), ('Примечание', self.note)):
            form.addRow(label, w)
        form.addRow(self.favorite)
        layout.addLayout(form)
        hint = QLabel('Связь с клиентом или юрлицом необязательна: контакт может быть и просто нужным по работе номером.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        bar = QHBoxLayout()
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        cancel = QPushButton('Отмена')
        cancel.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(cancel)
        bar.addWidget(save)
        layout.addLayout(bar)
        data = cd.get_contact(db, contact_id) if contact_id else (preset or {})
        if data:
            self.fill(data)

    def fill(self, d):
        self.name.setText(d.get('name') or '')
        self.organization.setText(d.get('organization') or '')
        self.position.setText(d.get('position') or '')
        self.category.setCurrentText(d.get('category') or 'Рабочие')
        self.phone.setText(d.get('phone') or '')
        self.email.setText(d.get('email') or '')
        self.address.setText(d.get('address') or '')
        self.client.setCurrentIndex(max(0, self.client.findData(d.get('client_id'))))
        self.legal.setCurrentIndex(max(0, self.legal.findData(d.get('legal_id'))))
        self.note.setPlainText(d.get('note') or '')
        self.favorite.setChecked(bool(d.get('favorite')))

    def values(self):
        return dict(name=self.name.text(), organization=self.organization.text(), position=self.position.text(), category=self.category.currentText(), phone=self.phone.text(),
                    email=self.email.text(), address=self.address.text(), client_id=self.client.currentData(), legal_id=self.legal.currentData(), note=self.note.toPlainText(),
                    favorite=self.favorite.isChecked())

    def save(self):
        try:
            self.contact_id = cd.save_contact(db, self.values(), self.contact_id)
        except Exception as e:
            QMessageBox.warning(self, 'Контакт', str(e))
            return
        self.accept()


class ContactsView(QWidget):
    COLS = ['★', 'Имя', 'Организация', 'Должность', 'Телефоны', 'E-mail', 'Категория', 'Связь']

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Имя, организация, телефон, e-mail, примечание…')
        self.category = QComboBox()
        self.category.addItem('Все категории', '')
        for c in cd.CATEGORIES:
            self.category.addItem(c, c)
        self.linked = QComboBox()
        for text, key in (('Все контакты', ''), ('Только рабочие (без связи)', 'free'), ('Связанные с клиентами', 'client'), ('Связанные с юрлицами', 'legal')):
            self.linked.addItem(text, key)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.category)
        bar.addWidget(self.linked)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        for text, fn, kind in (('Добавить контакт', self.add, 'primary'), ('Изменить', self.edit, ''), ('★ Избранный', self.toggle_favorite, ''), ('Копировать телефон', self.copy_phone, ''),
                               ('Добавить из клиентов…', self.from_client, ''), ('Добавить из юрлиц…', self.from_legal, ''), ('Удалить', self.delete, 'danger')):
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 30), (1, 190), (2, 190), (3, 140), (5, 170), (6, 140), (7, 170)):
            self.table.setColumnWidth(col, width)
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table, 1)
        self.info = QLabel('')
        layout.addWidget(self.info)
        self.search.textChanged.connect(self.load_data)
        self.category.currentIndexChanged.connect(self.load_data)
        self.linked.currentIndexChanged.connect(self.load_data)

    def load_data(self, *_):
        rows = cd.listing(db, self.search.text().strip(), self.category.currentData() or '', self.linked.currentData() or '')
        self.table.setRowCount(len(rows))
        for r, c in enumerate(rows):
            link = ' · '.join(x for x in (f'клиент: {c["client_name"]}' if c['client_name'] else '', f'юрлицо: {c["legal_name"]}' if c['legal_name'] else '') if x)
            vals = ['★' if c['favorite'] else '', c['name'], c['organization'], c['position'], c['phone'], c['email'], c['category'], link]
            for i, v in enumerate(vals):
                it = QTableWidgetItem(str(v or ''))
                if i == 0:
                    it.setData(Qt.ItemDataRole.UserRole, c['id'])
                    it.setForeground(QColor('#D97706'))
                self.table.setItem(r, i, it)
        self.info.setText(f'Контактов: {len(rows)}')

    def selected(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def add(self):
        if ContactDialog(parent=self).exec():
            self.load_data()

    def edit(self, *_):
        cid = self.selected()
        if cid and ContactDialog(cid, self).exec():
            self.load_data()

    def toggle_favorite(self):
        cid = self.selected()
        c = cd.get_contact(db, cid) if cid else None
        if c:
            db.execute('UPDATE contacts SET favorite=? WHERE id=?', (0 if c['favorite'] else 1, cid))
            self.load_data()

    def copy_phone(self):
        cid = self.selected()
        c = cd.get_contact(db, cid) if cid else None
        if not c or not c['phone']:
            QMessageBox.information(self, 'Контакты', 'Выберите контакт с телефоном.')
            return
        QApplication.clipboard().setText(c['phone'])
        self.info.setText(f'Телефон скопирован: {c["phone"]}')

    def from_client(self):
        from .workspace_view import ClientPicker
        d = ClientPicker(self)
        if d.exec() and d.client_id:
            self.add_from('client', d.client_id)

    def from_legal(self):
        d = QDialog(self)
        d.setWindowTitle('Добавить контакт из юрлиц')
        lay = QVBoxLayout(d)
        box = QComboBox()
        box.setEditable(True)
        for lid, nm in db.fetchall('SELECT id,name FROM le_clients ORDER BY name'):
            box.addItem(nm, lid)
        lay.addWidget(QLabel('Юрлицо из справочника:'))
        lay.addWidget(box)
        ok = QPushButton('Добавить')
        ok.clicked.connect(d.accept)
        lay.addWidget(ok)
        if d.exec() and box.currentData() and box.currentText() == box.itemText(box.currentIndex()):
            self.add_from('legal', box.currentData())

    def add_from(self, kind, ref_id):
        try:
            cid, created = cd.add_from_directory(db, kind, ref_id)
        except Exception as e:
            QMessageBox.warning(self, 'Контакты', str(e))
            return
        self.load_data()
        if not created:
            QMessageBox.information(self, 'Контакты', 'Этот контакт уже есть в списке — открываю его.')
        ContactDialog(cid, self).exec()
        self.load_data()

    def delete(self):
        cid = self.selected()
        if cid and QMessageBox.question(self, 'Удаление', 'Удалить контакт? Карточка клиента или юрлица при этом не удаляется.') == QMessageBox.StandardButton.Yes:
            cd.delete_contact(db, cid)
            self.load_data()
