"""Интерфейс модулей «Юрлица» и «СМР»: карточка юрлица, договор с актами/справками/документами/оплатами/сметой, реестры, шаблоны и теги."""
import os

from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout, QLabel, QLineEdit, QTextEdit, QComboBox, QPushButton, QCheckBox,
                              QDoubleSpinBox, QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox, QFileDialog, QTabWidget, QRadioButton, QHeaderView,
                              QApplication, QGroupBox)
from PyQt6.QtCore import Qt, QDate, pyqtSignal
from PyQt6.QtGui import QColor

from .database import db
from . import contracts_core as cc
from . import gsv_domain
from .domain_widgets import OptionalDate
from .gsvm_docs import FORMATS
from .gsvm_tabs import STATE_TEXT, make_table, open_file, print_files, read_item
from .legal_entities_domain import DIRECTIONS
from .gsv_project_domain import date_short


def money(value):
    return f'{float(value or 0):,.2f}'.replace(',', ' ').replace('.', ',') + ' BYN'


def item(text, data=None, right=False):
    it = QTableWidgetItem('' if text is None else str(text))
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return it


def selected_data(table, col=0):
    r = table.currentRow()
    return table.item(r, col).data(Qt.ItemDataRole.UserRole) if r >= 0 and table.item(r, col) else None


def warn(parent, text, title='Ошибка'):
    QMessageBox.warning(parent, title, text)


# --- Юрлицо ------------------------------------------------------------------------------------

class LegalClientDialog(QDialog):
    """Карточка юрлица: полный набор реквизитов для РБ, руководитель, контактные лица."""
    def __init__(self, client_id=None, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.setWindowTitle('Карточка юрлица' if client_id else 'Новое юрлицо')
        self.resize(760, 640)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        self.f = {}

        def line(key, label, form, placeholder=''):
            w = QLineEdit()
            w.setPlaceholderText(placeholder)
            self.f[key] = w
            form.addRow(label, w)
        page = QWidget()
        form = QFormLayout(page)
        line('name', 'Краткое наименование *', form, 'ООО «Ромашка»')
        line('full_name', 'Полное наименование', form, 'Общество с ограниченной ответственностью «Ромашка»')
        line('unp', 'УНП', form, '9 цифр')
        line('okpo', 'ОКПО', form)
        line('legal_address', 'Юридический адрес', form)
        line('postal_address', 'Почтовый адрес', form, 'если пусто — как юридический')
        tabs.addTab(page, 'Организация')
        page = QWidget()
        form = QFormLayout(page)
        line('bank', 'Банк', form)
        line('bic', 'БИК', form)
        line('account', 'Расчётный счёт (IBAN)', form)
        tabs.addTab(page, 'Банк')
        page = QWidget()
        form = QFormLayout(page)
        line('head_position', 'Должность руководителя', form, 'Директор')
        line('head_name', 'ФИО руководителя', form)
        line('head_position_gen', 'Должность (родительный падеж)', form, 'директора')
        line('head_name_gen', 'ФИО (родительный падеж)', form, 'Иванова Ивана Ивановича')
        line('basis', 'Действует на основании', form, 'Устава / доверенности №… от …')
        tabs.addTab(page, 'Руководитель')
        page = QWidget()
        pl = QVBoxLayout(page)
        line_form = QFormLayout()
        line('phone', 'Общий телефон', line_form)
        line('email', 'Общий e-mail', line_form)
        pl.addLayout(line_form)
        pl.addWidget(QLabel('Контактные лица (первое используется в документах как «контактное лицо»):'))
        self.contacts = make_table(['ФИО', 'Должность', 'Телефон', 'E-mail'], (200, 150, 140))
        pl.addWidget(self.contacts, 1)
        bar = QHBoxLayout()
        for text, fn in (('＋ Контакт', lambda: self.add_contact()), ('Убрать', self.remove_contact)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        pl.addLayout(bar)
        tabs.addTab(page, 'Контакты')
        page = QWidget()
        pl = QVBoxLayout(page)
        self.note = QTextEdit()
        pl.addWidget(self.note)
        tabs.addTab(page, 'Примечание')
        if client_id:
            from .notes_view import NotesPanel
            tabs.addTab(NotesPanel(('le_clients', client_id)), 'Заметки')
        bar = QHBoxLayout()
        bar.addStretch()
        cancel = QPushButton('Отмена')
        cancel.clicked.connect(self.reject)
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save_data)
        bar.addWidget(cancel)
        bar.addWidget(save)
        layout.addLayout(bar)
        if client_id:
            self.load_data()
        else:
            self.f['head_position'].setText('Директор')
            self.f['head_position_gen'].setText('директора')
            self.f['basis'].setText('Устава')

    def add_contact(self, name='', position='', phone='', email=''):
        r = self.contacts.rowCount()
        self.contacts.insertRow(r)
        for c, v in enumerate((name, position, phone, email)):
            self.contacts.setItem(r, c, QTableWidgetItem(v or ''))

    def remove_contact(self):
        r = self.contacts.currentRow()
        if r >= 0:
            self.contacts.removeRow(r)

    def load_data(self):
        row = cc.legal(db, self.client_id)
        if not row:
            return
        for key, w in self.f.items():
            w.setText(row.get(key) or '')
        self.note.setPlainText(row.get('note') or '')
        for c in cc.contacts(db, self.client_id):
            self.add_contact(c['name'], c['position'], c['phone'], c['email'])

    def save_data(self):
        values = {k: w.text() for k, w in self.f.items()}
        values['note'] = self.note.toPlainText()
        rows = [dict(name=read_item(self.contacts, r, 0), position=read_item(self.contacts, r, 1), phone=read_item(self.contacts, r, 2), email=read_item(self.contacts, r, 3))
                for r in range(self.contacts.rowCount())]
        values['contact_person'] = next((r['name'] for r in rows if r['name']), '')
        try:
            self.client_id = cc.save_legal(db, values, self.client_id, rows)
        except ValueError as e:
            warn(self, str(e))
            return
        self.accept()


def populate_legal_combo(combo, selected=None):
    combo.clear()
    combo.addItem('— выберите юрлицо —', None)
    for lid, name in db.fetchall('SELECT id,name FROM le_clients ORDER BY name'):
        combo.addItem(name, lid)
    if selected is not None:
        combo.setCurrentIndex(max(0, combo.findData(selected)))


def populate_person_combo(combo, selected=None):
    combo.clear()
    combo.addItem('— выберите клиента —', None)
    for pid, name in db.fetchall('SELECT id,name FROM crm.clients ORDER BY name'):
        combo.addItem(name, pid)
    if selected is not None:
        combo.setCurrentIndex(max(0, combo.findData(selected)))


class PersonDialog(QDialog):
    """Быстрое добавление клиента-физлица (запись попадает в общий справочник «Клиенты»)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Новый клиент')
        self.person_id = None
        form = QFormLayout(self)
        self.name, self.phone, self.address = QLineEdit(), QLineEdit(), QLineEdit()
        self.passport, self.issuer = QLineEdit(), QLineEdit()
        self.issue_date = OptionalDate()
        for label, w in (('ФИО *', self.name), ('Телефон', self.phone), ('Адрес', self.address), ('Паспорт', self.passport), ('Кем выдан', self.issuer), ('Дата выдачи', self.issue_date)):
            form.addRow(label, w)
        b = QPushButton('Сохранить')
        b.setProperty('type', 'primary')
        b.clicked.connect(self.save)
        form.addRow(b)

    def save(self):
        try:
            self.person_id = gsv_domain.save_client(db, dict(name=self.name.text(), phone=self.phone.text(), address=self.address.text(), passport=self.passport.text(),
                                                             passport_issuer=self.issuer.text(), passport_date=self.issue_date.value()))
        except Exception as e:
            warn(self, str(e))
            return
        self.accept()


class LegalClientsRegistry(QWidget):
    """Справочник юрлиц."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Наименование, УНП, контактное лицо, телефон, адрес…')
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        for text, fn, kind in (('Добавить юрлицо', self.add_client, 'primary'), ('Изменить', self.edit_client, ''), ('Удалить', self.delete_client, 'danger')):
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        layout.addLayout(bar)
        self.table = make_table(['Наименование', 'УНП', 'Руководитель', 'Контактное лицо', 'Телефон', 'E-mail', 'Договоров'], (260, 110, 190, 170, 140, 170))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_client)
        layout.addWidget(self.table, 1)
        self.load_data()

    def load_data(self, *_):
        q = '%' + self.search.text().strip().casefold() + '%'
        rows = db.fetchall("""SELECT c.id,c.name,c.unp,c.head_name,c.contact_person,c.phone,c.email,
            (SELECT count(*) FROM le_contracts WHERE client_id=c.id)+(SELECT count(*) FROM smr_contracts WHERE legal_id=c.id)
            FROM le_clients c WHERE LOWER(c.name||' '||coalesce(c.full_name,'')||' '||coalesce(c.unp,'')||' '||coalesce(c.contact_person,'')||' '||coalesce(c.phone,'')||' '||
            coalesce(c.legal_address,'')||' '||coalesce(c.address,'')) LIKE ? ORDER BY c.name""", (q,))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row[1:]):
                self.table.setItem(r, c, item(v, row[0] if c == 0 else None, right=(c == 6)))

    def add_client(self):
        if LegalClientDialog(parent=self).exec():
            self.load_data()

    def edit_client(self, *_):
        cid = selected_data(self.table)
        if cid and LegalClientDialog(cid, self).exec():
            self.load_data()

    def delete_client(self):
        cid = selected_data(self.table)
        if not cid:
            return
        used = db.fetchone('SELECT (SELECT count(*) FROM le_contracts WHERE client_id=?)+(SELECT count(*) FROM smr_contracts WHERE legal_id=?)', (cid, cid))[0]
        used += db.fetchone('SELECT (SELECT count(*) FROM gsv_projects WHERE le_client_id=?)+(SELECT count(*) FROM contracts WHERE le_client_id=?)', (cid, cid))[0]
        if used:
            warn(self, f'Юрлицо используется в договорах и карточках ({used}). Сначала удалите или перепривяжите их.', 'Нельзя удалить')
            return
        if QMessageBox.question(self, 'Удаление', 'Удалить выбранное юрлицо?') != QMessageBox.StandardButton.Yes:
            return
        try:
            db.execute('DELETE FROM le_clients WHERE id=?', (cid,))
        except Exception as e:
            warn(self, str(e))
        self.load_data()


# --- Акт ---------------------------------------------------------------------------------------

class ActDialog(QDialog):
    def __init__(self, mod, contract_id, act_id=None, parent=None):
        super().__init__(parent)
        self.mod, self.contract_id, self.act_id = mod, contract_id, act_id
        self.setWindowTitle('Акт выполненных работ')
        self.resize(520, 420)
        form = QFormLayout(self)
        self.number = QLineEdit()
        self.date = OptionalDate()
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e9)
        self.amount.setDecimals(2)
        self.desc = QTextEdit()
        self.desc.setFixedHeight(90)
        self.signed = QCheckBox('Акт подписан')
        self.note = QLineEdit()
        for label, w in (('№ акта', self.number), ('Дата акта', self.date), ('Сумма (итого)', self.amount), ('Описание работ', self.desc), ('', self.signed), ('Примечание', self.note)):
            form.addRow(label, w)
        pull = QPushButton('Подставить остаток по договору')
        pull.clicked.connect(self.fill_rest)
        form.addRow(pull)
        b = QPushButton('Сохранить')
        b.setProperty('type', 'primary')
        b.clicked.connect(self.save)
        form.addRow(b)
        if act_id:
            a = cc.act(db, mod, act_id)
            self.number.setText(a['act_number'] or '')
            self.date.set_value(a['act_date'])
            self.amount.setValue(float(a['amount'] or 0))
            self.desc.setPlainText(a['description'] or '')
            self.signed.setChecked(bool(a['signed']))
            self.note.setText(a['note'] or '')
        else:
            self.date.set_value(QDate.currentDate().toString('yyyy-MM-dd'))
            self.desc.setPlainText(cc.contract(db, mod, contract_id).get('subject') or '')

    def fill_rest(self):
        total = float(cc.contract(db, self.mod, self.contract_id).get('amount') or 0)
        done = sum(float(a['amount'] or 0) for a in cc.acts(db, self.mod, self.contract_id) if a['id'] != self.act_id)
        self.amount.setValue(max(0.0, round(total - done, 2)))

    def save(self):
        try:
            self.act_id = cc.save_act(db, self.mod, dict(contract_id=self.contract_id, act_number=self.number.text(), act_date=self.date.value(), amount=self.amount.value(),
                                                         description=self.desc.toPlainText(), note=self.note.text(), signed=self.signed.isChecked()), self.act_id)
        except Exception as e:
            warn(self, str(e))
            return
        self.accept()


# --- Договор -----------------------------------------------------------------------------------

class ContractDialog(QDialog):
    def __init__(self, mod, contract_id=None, parent=None, preset=None):
        super().__init__(parent)
        self.mod = mod
        self.contract_id = contract_id
        self.title_name = cc.cfg(mod)['title']
        self.setWindowTitle(f'{self.title_name} · договор')
        self.resize(900, 720)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.build_main()
        self.build_acts()
        self.build_docs()
        self.status = QLabel('')
        layout.addWidget(self.status)
        bar = QHBoxLayout()
        for text, fn in (('Оплаты', self.open_payments), ('Создать задачу', self.create_task), ('Заметки', self.open_notes), ('Папка договора', self.open_folder)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        bar.addWidget(close)
        bar.addWidget(save)
        layout.addLayout(bar)
        if contract_id:
            self.load()
        else:
            self.date.set_value(QDate.currentDate().toString('yyyy-MM-dd'))
            self.refresh_number()
            for key, value in (preset or {}).items():
                self.apply_preset(key, value)
        self.refresh_all()

    def apply_preset(self, key, value):
        if key == 'legal_id' and value:
            self.set_party('legal', value)

    # --- вкладка «Договор»
    def build_main(self):
        page = QWidget()
        g = QGridLayout(page)
        r = 0
        self.number = QLineEdit()
        self.number.setPlaceholderText('назначается автоматически')
        self.date = OptionalDate()
        self.date.dateChanged.connect(lambda *_: self.refresh_number())
        g.addWidget(QLabel('Номер договора'), r, 0)
        g.addWidget(self.number, r, 1)
        g.addWidget(QLabel('Дата'), r, 2)
        g.addWidget(self.date, r, 3)
        r += 1
        if self.mod == 'le':
            self.direction = QComboBox()
            self.direction.setEditable(True)
            self.direction.addItems(DIRECTIONS)
            g.addWidget(QLabel('Направление'), r, 0)
            g.addWidget(self.direction, r, 1, 1, 3)
            r += 1
        self.rb_person = QRadioButton('Физическое лицо (клиент)')
        self.rb_legal = QRadioButton('Юридическое лицо')
        self.cmb_person, self.cmb_legal = QComboBox(), QComboBox()
        populate_person_combo(self.cmb_person)
        populate_legal_combo(self.cmb_legal)
        if self.mod == 'smr':
            row = QHBoxLayout()
            row.addWidget(self.rb_person)
            row.addWidget(self.rb_legal)
            row.addStretch()
            g.addWidget(QLabel('Контрагент'), r, 0)
            g.addLayout(row, r, 1, 1, 3)
            r += 1
            g.addWidget(self.cmb_person, r, 1, 1, 2)
            new_person = QPushButton('＋ Новый клиент…')
            new_person.clicked.connect(self.new_person)
            g.addWidget(new_person, r, 3)
            r += 1
            self.rb_person.setChecked(True)
            self.rb_person.toggled.connect(self.toggle_party)
        g.addWidget(QLabel('Юрлицо' if self.mod == 'smr' else 'Заказчик (юрлицо)'), r, 0)
        g.addWidget(self.cmb_legal, r, 1, 1, 2)
        new_legal = QPushButton('＋ Новое юрлицо…')
        new_legal.clicked.connect(self.new_legal)
        g.addWidget(new_legal, r, 3)
        r += 1
        self.party_info = QLabel('')
        self.party_info.setWordWrap(True)
        self.party_info.setStyleSheet('color:#65758b;')
        g.addWidget(self.party_info, r, 0, 1, 4)
        self.cmb_legal.currentIndexChanged.connect(self.refresh_party_info)
        self.cmb_person.currentIndexChanged.connect(self.refresh_party_info)
        r += 1
        self.obj, self.addr, self.subject = QLineEdit(), QLineEdit(), QLineEdit()
        for label, w in (('Объект', self.obj), ('Адрес объекта', self.addr), ('Предмет договора', self.subject)):
            g.addWidget(QLabel(label), r, 0)
            g.addWidget(w, r, 1, 1, 3)
            r += 1
        self.start, self.end = OptionalDate(), OptionalDate()
        g.addWidget(QLabel('Начало работ'), r, 0)
        g.addWidget(self.start, r, 1)
        g.addWidget(QLabel('Окончание работ'), r, 2)
        g.addWidget(self.end, r, 3)
        r += 1
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e9)
        self.amount.setDecimals(2)
        self.amount.setSuffix(' BYN')
        self.vat_included = QCheckBox('В сумму включён НДС')
        self.vat_rate = QDoubleSpinBox()
        self.vat_rate.setRange(0, 100)
        self.vat_rate.setSuffix(' %')
        self.vat_rate.setValue(20)
        g.addWidget(QLabel('Сумма договора'), r, 0)
        g.addWidget(self.amount, r, 1)
        g.addWidget(self.vat_included, r, 2)
        g.addWidget(self.vat_rate, r, 3)
        r += 1
        self.vat_info = QLabel('')
        g.addWidget(self.vat_info, r, 0, 1, 4)
        self.amount.valueChanged.connect(self.refresh_vat)
        self.vat_rate.valueChanged.connect(self.refresh_vat)
        self.vat_included.toggled.connect(self.refresh_vat)
        r += 1
        self.cmb_status = QComboBox()
        self.cmb_status.addItems(cc.STATUSES)
        self.signed = QCheckBox('Договор подписан')
        g.addWidget(QLabel('Статус'), r, 0)
        g.addWidget(self.cmb_status, r, 1)
        g.addWidget(self.signed, r, 2, 1, 2)
        r += 1
        self.note = QTextEdit()
        self.note.setFixedHeight(60)
        g.addWidget(QLabel('Примечание'), r, 0)
        g.addWidget(self.note, r, 1, 1, 3)
        r += 1
        if self.mod == 'smr':
            self.lbl_estimate = QLabel('')
            self.lbl_estimate.setWordWrap(True)
            g.addWidget(self.lbl_estimate, r, 0, 1, 4)
            r += 1
            bar = QHBoxLayout()
            self.est_buttons = {}
            for key, text, fn in (('create', 'Создать смету', self.create_estimate), ('link', 'Привязать смету…', self.link_estimate), ('pull', 'Получить стоимость из сметы', self.pull_estimate),
                                  ('history', 'История изменений', self.estimate_history), ('open', 'Открыть смету', self.open_estimate), ('export', 'Сформировать смету…', self.export_estimate)):
                b = QPushButton(text)
                b.clicked.connect(fn)
                self.est_buttons[key] = b
                bar.addWidget(b)
            g.addLayout(bar, r, 0, 1, 4)
            r += 1
        g.setRowStretch(r, 1)
        self.tabs.addTab(page, 'Договор')

    def toggle_party(self, *_):
        person = self.rb_person.isChecked()
        self.cmb_person.setEnabled(person)
        self.cmb_legal.setEnabled(not person)
        self.refresh_party_info()

    def set_party(self, kind, pid):
        if self.mod != 'smr':
            populate_legal_combo(self.cmb_legal, pid)
            return
        if kind == 'legal':
            self.rb_legal.setChecked(True)
            populate_legal_combo(self.cmb_legal, pid)
        else:
            self.rb_person.setChecked(True)
            populate_person_combo(self.cmb_person, pid)
        self.toggle_party()

    def new_person(self):
        d = PersonDialog(self)
        if d.exec():
            self.set_party('person', d.person_id)

    def new_legal(self):
        d = LegalClientDialog(parent=self)
        if d.exec():
            populate_legal_combo(self.cmb_legal, d.client_id)
            if self.mod == 'smr':
                self.rb_legal.setChecked(True)
            self.refresh_party_info()

    def party_kind(self):
        return 'legal' if self.mod == 'le' or self.rb_legal.isChecked() else 'person'

    def refresh_party_info(self, *_):
        if self.party_kind() == 'legal':
            lid = self.cmb_legal.currentData()
            row = cc.legal(db, lid) if lid else None
            self.party_info.setText('' if not row else f'УНП {row["unp"] or "—"} · {row["legal_address"] or row["address"] or "адрес не указан"} · руководитель: {row["head_name"] or "не указан"}')
        else:
            pid = self.cmb_person.currentData()
            row = gsv_domain.get_client(db, pid) if pid else None
            self.party_info.setText('' if not row else f'{row["phone"] or "телефон не указан"} · {row["address"] or "адрес не указан"}')

    def refresh_vat(self, *_):
        net, vat, gross = cc.vat_parts(self.amount.value(), self.vat_included.isChecked(), self.vat_rate.value())
        self.vat_info.setText(f'Без НДС: {money(net)} · НДС: {money(vat)} · Всего: {money(gross)}' if vat else 'НДС в сумму не включён: в документах «НДС не облагается».')
        self.vat_rate.setEnabled(self.vat_included.isChecked())

    def refresh_number(self):
        if self.contract_id or self.number.text().strip() and not getattr(self, 'auto_number', False):
            return
        _s, _y, number = cc.next_number(db, self.mod, self.date.value())
        self.number.setText(number)
        self.auto_number = True

    def values(self):
        v = dict(contract_number=self.number.text(), contract_date=self.date.value(), object_name=self.obj.text().strip(), object_address=self.addr.text().strip(),
                 subject=self.subject.text().strip(), start_date=self.start.value(), end_date=self.end.value(), amount=self.amount.value(), vat_included=int(self.vat_included.isChecked()),
                 vat_rate=self.vat_rate.value() if self.vat_included.isChecked() else 0, signed=int(self.signed.isChecked()), status=self.cmb_status.currentText(),
                 note=self.note.toPlainText().strip())
        if self.mod == 'le':
            v.update(direction=self.direction.currentText().strip() or DIRECTIONS[0], client_id=self.cmb_legal.currentData())
        else:
            kind = self.party_kind()
            v.update(party_type=kind, person_id=self.cmb_person.currentData() if kind == 'person' else None, legal_id=self.cmb_legal.currentData() if kind == 'legal' else None)
        return v

    def load(self):
        c = cc.contract(db, self.mod, self.contract_id)
        self.number.setText(c['contract_number'] or '')
        self.date.set_value(c['contract_date'])
        if self.mod == 'le':
            self.direction.setCurrentText(c['direction'] or DIRECTIONS[0])
            populate_legal_combo(self.cmb_legal, c['client_id'])
        else:
            populate_person_combo(self.cmb_person, c['person_id'])
            populate_legal_combo(self.cmb_legal, c['legal_id'])
            (self.rb_legal if c['party_type'] == 'legal' else self.rb_person).setChecked(True)
            self.toggle_party()
        self.obj.setText(c['object_name'] or '')
        self.addr.setText(c['object_address'] or '')
        self.subject.setText(c['subject'] or '')
        self.start.set_value(c['start_date'])
        self.end.set_value(c['end_date'])
        self.amount.setValue(float(c['amount'] or 0))
        self.vat_included.setChecked(bool(c['vat_included']))
        self.vat_rate.setValue(float(c['vat_rate'] or 20))
        self.cmb_status.setCurrentText(c['status'] or cc.STATUSES[0])
        self.signed.setChecked(bool(c['signed']))
        self.note.setPlainText(c['note'] or '')
        self.refresh_party_info()

    def save(self):
        try:
            self.contract_id = cc.save_contract(db, self.mod, self.values(), self.contract_id)
        except Exception as e:
            warn(self, str(e))
            return False
        self.number.setText(cc.contract(db, self.mod, self.contract_id)['contract_number'])
        self.status.setText('Договор сохранён.')
        self.refresh_all()
        return True

    def ensure_saved(self):
        return bool(self.contract_id) or self.save()

    # --- акты
    def build_acts(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.acts_table = make_table(['№', 'Дата', 'Сумма', 'Подписан', 'Акт', 'Справка', 'Описание'], (60, 100, 130, 90, 190, 190))
        self.acts_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.acts_table.doubleClicked.connect(self.edit_act)
        layout.addWidget(self.acts_table, 1)
        bar = QHBoxLayout()
        for text, fn in (('＋ Акт', self.add_act), ('Изменить', self.edit_act), ('Удалить', self.delete_act), ('Сформировать акт', lambda: self.make('act')),
                         ('Сформировать справку', lambda: self.make('statement')), ('Открыть акт', lambda: self.open_doc('act')), ('Открыть справку', lambda: self.open_doc('statement'))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        layout.addLayout(bar)
        self.acts_sum = QLabel('')
        layout.addWidget(self.acts_sum)
        self.tabs.addTab(page, 'Акты и справки')

    def refresh_acts(self):
        rows = cc.acts(db, self.mod, self.contract_id) if self.contract_id else []
        self.acts_table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            self.acts_table.setItem(r, 0, item(a['act_number'], a['id']))
            self.acts_table.setItem(r, 1, item(date_short(a['act_date']).rstrip('г.')))
            self.acts_table.setItem(r, 2, item(money(a['amount']), right=True))
            self.acts_table.setItem(r, 3, item('да' if a['signed'] else 'нет'))
            for c, kind in ((4, 'act'), (5, 'statement')):
                text, color = STATE_TEXT[cc.doc_state(db, self.mod, kind, a['id'])]
                it = item(text)
                it.setForeground(QColor(color))
                self.acts_table.setItem(r, c, it)
            self.acts_table.setItem(r, 6, item(a['description']))
        total = sum(float(a['amount'] or 0) for a in rows)
        self.acts_sum.setText(f'Актов: {len(rows)} · на сумму {money(total)} из {money(self.amount.value())}')

    def add_act(self):
        if self.ensure_saved() and ActDialog(self.mod, self.contract_id, parent=self).exec():
            self.refresh_all()

    def edit_act(self, *_):
        aid = selected_data(self.acts_table)
        if aid and ActDialog(self.mod, self.contract_id, aid, self).exec():
            self.refresh_all()

    def delete_act(self):
        aid = selected_data(self.acts_table)
        if aid and QMessageBox.question(self, 'Удаление', 'Удалить выбранный акт?') == QMessageBox.StandardButton.Yes:
            db.execute(f"DELETE FROM {cc.cfg(self.mod)['acts']} WHERE id=?", (aid,))
            self.refresh_all()

    # --- документы
    def build_docs(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.lbl_folder = QLabel('')
        self.lbl_folder.setWordWrap(True)
        layout.addWidget(self.lbl_folder)
        g = QGridLayout()
        self.doc_state_lbl = QLabel('')
        g.addWidget(QLabel('<b>Договор</b>'), 0, 0)
        g.addWidget(self.doc_state_lbl, 0, 1)
        self.btn_make_contract = QPushButton('Сформировать')
        self.btn_make_contract.clicked.connect(lambda: self.make('contract'))
        g.addWidget(self.btn_make_contract, 0, 2)
        for col, (text, fn) in enumerate((('Открыть', lambda: self.open_doc('contract')), ('Печать', lambda: self.print_doc('contract')), ('Привязать готовый…', lambda: self.link_doc('contract')))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            g.addWidget(b, 0, 3 + col)
        layout.addLayout(g)
        layout.addWidget(QLabel('Акты и справки о стоимости формируются на вкладке «Акты и справки» по выбранному акту. Шаблоны и теги настраиваются на вкладке «Шаблоны и теги» '
                                f'раздела «{self.title_name}» — они не связаны с другими разделами.'))
        layout.addStretch()
        self.tabs.addTab(page, 'Документы')

    def refresh_docs(self):
        state = cc.doc_state(db, self.mod, 'contract', self.contract_id) if self.contract_id else 'none'
        text, color = STATE_TEXT[state]
        self.doc_state_lbl.setText(text)
        self.doc_state_lbl.setStyleSheet(f'color:{color};font-weight:600;')
        self.btn_make_contract.setText('⟳ Переформировать' if state in ('stale', 'fresh', 'linked') else 'Сформировать')
        folder = cc.contract_folder(db, self.mod, self.contract_id) if self.contract_id else ''
        self.lbl_folder.setText(f'Папка договора: {folder}' if folder else 'Папка договора не привязана — программа предложит создать или выбрать её при формировании документов и кнопкой «Папка договора».')

    def ensure_folder(self):
        if cc.contract_folder(db, self.mod, self.contract_id):
            return True
        return self.open_folder(open_after=False)

    def open_folder(self, open_after=True):
        if not self.ensure_saved():
            return False
        from . import folder_ui
        current = cc.contract_folder(db, self.mod, self.contract_id)
        path, create = folder_ui.choose_folder(self, self.mod, cc.suggested_folder_name(db, self.mod, self.contract_id), current)
        if path:
            try:
                cc.link_folder(db, self.mod, self.contract_id, path, create)
            except Exception as e:
                warn(self, str(e))
                return False
            self.refresh_docs()
        folder = cc.contract_folder(db, self.mod, self.contract_id)
        if folder and open_after:
            from .platform_utils import open_local
            open_local(folder)
        return bool(folder)

    def ref_for(self, kind):
        return self.contract_id if kind == 'contract' else selected_data(self.acts_table)

    def make(self, kind):
        ref = self.ref_for(kind)
        if kind == 'contract' and not self.ensure_saved():
            return
        if not ref:
            warn(self, 'Выберите акт в таблице.' if kind != 'contract' else 'Сначала сохраните договор.')
            return
        from . import preflight_ui
        if not preflight_ui.confirm(self, f'«{cc.DOC_KINDS[kind][0]}»', cc.check(db, self.mod, kind, ref)):
            return
        if not self.ensure_folder():
            return
        try:
            path = cc.generate(db, self.mod, kind, ref)
        except Exception as e:
            warn(self, str(e))
            return
        self.status.setText('Сформировано: ' + path)
        self.refresh_all()
        open_file(self, path)

    def open_doc(self, kind):
        ref = self.ref_for(kind)
        if ref:
            open_file(self, cc.doc_path(db, self.mod, kind, ref))

    def print_doc(self, kind):
        ref = self.ref_for(kind)
        if ref:
            print_files(self, [cc.doc_path(db, self.mod, kind, ref)])

    def link_doc(self, kind):
        ref = self.ref_for(kind)
        if not ref:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Готовый документ', '', 'Документы (*.docx *.doc *.pdf *.xlsx)')
        if path:
            cc.link_doc(db, self.mod, kind, ref, path)
            self.refresh_all()

    def open_notes(self):
        if not self.ensure_saved():
            return
        from .notes_view import open_notes
        open_notes(self, cc.cfg(self.mod)['contracts'], self.contract_id)

    def create_task(self):
        if not self.ensure_saved():
            return
        from .tasks_view import new_task_for
        new_task_for(self, cc.cfg(self.mod)['contracts'], self.contract_id)

    # --- оплаты
    def open_payments(self):
        if not self.ensure_saved():
            return
        from .payments_view import PaymentsDialog
        PaymentsDialog(cc.cfg(self.mod)['contracts'], self.contract_id, self).exec()
        self.refresh_all()

    # --- смета (СМР)
    def refresh_estimate(self):
        if self.mod != 'smr':
            return
        state = cc.estimate_state(db, self.contract_id) if self.contract_id else 'none'
        c = cc.contract(db, 'smr', self.contract_id) if self.contract_id else {}
        eid = c.get('estimate_id')
        s = cc.md.estimate_summary(db, eid) if eid else None
        if not eid or not s:
            text, color = '<b>Смета</b><br>Нет данных. Создайте новую смету или привяжите существующую.', '#65758b'
        elif state == 'unsynced':
            text, color = f'<b>Смета «{s["title"]}»</b><br>Получите стоимость из сметы.', '#2563EB'
        elif state == 'stale':
            text, color = (f'<b>Смета «{s["title"]}»</b><br><b>Смета была изменена — обновите данные.</b> Сейчас: материалы {money(s["materials"])}, работы {money(s["works"])}, '
                           f'итого {money(s["total"])}.'), '#D97706'
        else:
            text, color = (f'<b>Смета «{s["title"]}»</b><br>Стоимость материалов: <b>{money(c["est_materials"])}</b> · стоимость работ: <b>{money(c["est_works"])}</b> · '
                           f'итого: <b>{money(c["amount"])}</b>'), '#16A34A'
        self.lbl_estimate.setText(text)
        self.lbl_estimate.setStyleSheet(f'color:{color};')
        has = bool(eid and s)
        for key in ('create', 'link'):
            self.est_buttons[key].setVisible(not has)
        for key in ('pull', 'history', 'open', 'export'):
            self.est_buttons[key].setVisible(has)

    def estimate_id(self):
        return cc.contract(db, 'smr', self.contract_id)['estimate_id'] if self.contract_id else None

    def create_estimate(self):
        if not self.ensure_saved():
            return
        c = cc.contract(db, 'smr', self.contract_id)
        p = cc.party(db, 'smr', c)
        with db.transaction():
            eid = db.execute('INSERT INTO estimates(title,date,total,paid,client_name) VALUES(?,?,0,0,?)',
                             (self.obj.text().strip() or 'Смета к договору ' + c['contract_number'], QDate.currentDate().toString('yyyy-MM-dd'), p['name'])).lastrowid
            cc.link_estimate(db, self.contract_id, eid)
        self.refresh_all()
        self.open_estimate()

    def link_estimate(self):
        if not self.ensure_saved():
            return
        d = QDialog(self)
        d.setWindowTitle('Привязать смету')
        d.resize(700, 480)
        layout = QVBoxLayout(d)
        search = QLineEdit()
        search.setPlaceholderText('Название сметы или клиент…')
        layout.addWidget(search)
        table = make_table(['Смета', 'Клиент', 'Итого'], (330, 200))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(table, 1)

        def load():
            q = '%' + search.text().casefold() + '%'
            rows = db.fetchall("""SELECT id,title,client_name,total FROM estimates WHERE id NOT IN (SELECT estimate_id FROM smr_contracts WHERE estimate_id IS NOT NULL AND id<>?)
                AND id NOT IN (SELECT estimate_id FROM contracts WHERE estimate_id IS NOT NULL)
                AND LOWER(coalesce(title,'')||' '||coalesce(client_name,'')) LIKE ? ORDER BY id DESC LIMIT 300""", (self.contract_id, q))
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, v in enumerate((row[1], row[2], money(row[3]))):
                    table.setItem(r, c, item(v, row[0]))
        search.textChanged.connect(load)
        load()
        pick = QPushButton('Привязать выбранную смету')
        pick.setProperty('type', 'primary')
        layout.addWidget(pick)

        def choose():
            eid = selected_data(table)
            if not eid:
                return
            try:
                cc.link_estimate(db, self.contract_id, eid)
            except Exception as e:
                warn(d, str(e), 'Смета')
                return
            d.accept()
        pick.clicked.connect(choose)
        table.cellDoubleClicked.connect(lambda *_: choose())
        if d.exec():
            self.refresh_all()

    def pull_estimate(self):
        if not self.ensure_saved():
            return
        try:
            s = cc.sync_estimate(db, self.contract_id)
        except ValueError as e:
            warn(self, str(e), 'Смета')
            return
        self.amount.setValue(s['total'])
        self.status.setText(f'Получено из сметы: материалы {money(s["materials"])}, работы {money(s["works"])}')
        self.refresh_all()

    def estimate_history(self):
        eid = self.estimate_id()
        if not eid:
            return
        d = QDialog(self)
        d.setWindowTitle('История изменений сметы')
        d.resize(880, 520)
        layout = QVBoxLayout(d)
        rows = cc.md.estimate_history(db, eid)
        table = make_table(['Когда', 'Что', 'Позиция', 'Подробности'], (150, 90, 280))
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                table.setItem(r, c, item(v))
        layout.addWidget(table, 1)
        if not rows:
            layout.addWidget(QLabel('Изменений сметы пока не зафиксировано.'))
        close = QPushButton('Закрыть')
        close.clicked.connect(d.accept)
        layout.addWidget(close)
        d.exec()

    def open_estimate(self):
        eid = self.estimate_id()
        if eid:
            from .estimate_editor import EstimateEditorDialog
            row = db.fetchone('SELECT title FROM estimates WHERE id=?', (eid,))
            EstimateEditorDialog(eid, row[0] or '', self).exec()
            self.refresh_all()

    def export_estimate(self):
        eid = self.estimate_id()
        if eid:
            from .workspace_view import ExportDialog
            ExportDialog('estimates', eid, self).exec()

    def refresh_all(self):
        self.refresh_vat()
        self.refresh_acts()
        self.refresh_docs()
        self.refresh_estimate()
        self.tabs.setTabEnabled(1, bool(self.contract_id))
        self.tabs.setTabEnabled(2, bool(self.contract_id))


# --- Реестры -----------------------------------------------------------------------------------

class ContractsRegistry(QWidget):
    def __init__(self, mod):
        super().__init__()
        self.mod = mod
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.cmb_status = QComboBox()
        self.cmb_status.addItem('Все статусы', None)
        for s in cc.STATUSES:
            self.cmb_status.addItem(s, s)
        self.cmb_status.currentIndexChanged.connect(self.load_data)
        bar.addWidget(self.cmb_status)
        self.cmb_signed = QComboBox()
        self.cmb_signed.addItem('Все', None)
        self.cmb_signed.addItem('Подписанные', 1)
        self.cmb_signed.addItem('Неподписанные', 0)
        self.cmb_signed.currentIndexChanged.connect(self.load_data)
        bar.addWidget(self.cmb_signed)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер, контрагент, объект…')
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        for text, fn, kind in (('Создать договор', self.add, 'primary'), ('Открыть', self.edit, ''), ('Оплаты', self.payments, ''), ('Ведомость актов за месяц…', self.statement, ''),
                               ('Удалить', self.delete, 'danger')):
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        layout.addLayout(bar)
        self.table = make_table(['№ договора', 'Дата', 'Контрагент', 'Объект', 'Сумма', 'Оплачено', 'Актов', 'Подписан', 'Статус'], (110, 95, 230, 240, 120, 120, 60, 90))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table, 1)
        self.total = QLabel('')
        layout.addWidget(self.total)
        self.load_data()

    def load_data(self, *_):
        c = cc.cfg(self.mod)
        q = self.search.text().strip().casefold()
        rows = db.fetchall(f"SELECT * FROM {c['contracts']} ORDER BY id DESC")
        cols = [r[1] for r in db.fetchall(f"PRAGMA table_info({c['contracts']})")]
        shown, total = [], 0.0
        for row in rows:
            rec = dict(zip(cols, row))
            label = cc.party_label(db, self.mod, rec)
            if q and q not in f"{rec['contract_number']} {label} {rec['object_name']} {rec['object_address']}".casefold():
                continue
            if self.cmb_status.currentData() and rec['status'] != self.cmb_status.currentData():
                continue
            signed = self.cmb_signed.currentData()
            if signed is not None and bool(rec['signed']) != bool(signed):
                continue
            shown.append((rec, label))
        self.table.setRowCount(len(shown))
        for r, (rec, label) in enumerate(shown):
            paid = sum(a for _d, a, _n in cc.payments(db, self.mod, rec['id']))
            total += float(rec['amount'] or 0)
            n_acts = db.fetchone(f"SELECT count(*) FROM {c['acts']} WHERE contract_id=?", (rec['id'],))[0]
            vals = [rec['contract_number'] or 'Б/Н', date_short(rec['contract_date']).rstrip('г.'), label, rec['object_address'] or rec['object_name'], money(rec['amount']), money(paid),
                    n_acts, 'да' if rec['signed'] else 'нет', rec['status']]
            for col, v in enumerate(vals):
                self.table.setItem(r, col, item(v, rec['id'] if col == 0 else None, right=col in (4, 5, 6)))
        self.total.setText(f'Договоров: {len(shown)} · на сумму {money(total)}')

    def add(self):
        if ContractDialog(self.mod, parent=self).exec() is not None:
            self.load_data()

    def edit(self, *_):
        cid = selected_data(self.table)
        if cid:
            ContractDialog(self.mod, cid, self).exec()
            self.load_data()

    def payments(self):
        cid = selected_data(self.table)
        if cid:
            from .payments_view import PaymentsDialog
            PaymentsDialog(cc.cfg(self.mod)['contracts'], cid, self).exec()
            self.load_data()

    def statement(self):
        from .acts_statement_view import ActsStatementDialog
        ActsStatementDialog(cc.cfg(self.mod)['contracts'], self).exec()

    def delete(self):
        cid = selected_data(self.table)
        if not cid:
            return
        if QMessageBox.question(self, 'Удаление', 'Удалить договор и все его акты?') != QMessageBox.StandardButton.Yes:
            return
        try:
            db.safety_backup('delete_contract')
        except Exception:
            pass
        try:
            db.execute(f"DELETE FROM {cc.cfg(self.mod)['contracts']} WHERE id=?", (cid,))
        except Exception as e:
            warn(self, str(e), 'Нельзя удалить')
        self.load_data()


class ActsRegistry(QWidget):
    def __init__(self, mod):
        super().__init__()
        self.mod = mod
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер акта, договор, контрагент…')
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        b = QPushButton('Открыть договор')
        b.clicked.connect(self.open_contract)
        bar.addWidget(b)
        layout.addLayout(bar)
        self.table = make_table(['№ акта', 'Дата', 'Договор', 'Контрагент', 'Сумма', 'Подписан', 'Описание'], (80, 95, 110, 230, 120, 90))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.open_contract)
        layout.addWidget(self.table, 1)
        self.load_data()

    def load_data(self, *_):
        c = cc.cfg(self.mod)
        q = self.search.text().strip().casefold()
        rows = db.fetchall(f"SELECT a.id,a.act_number,a.act_date,a.amount,a.signed,a.description,a.contract_id FROM {c['acts']} a ORDER BY a.act_date DESC,a.id DESC")
        out = []
        for aid, num, day, amount, signed, desc, cid in rows:
            ct = cc.contract(db, self.mod, cid)
            label = cc.party_label(db, self.mod, ct)
            if q and q not in f"{num} {ct['contract_number']} {label} {desc}".casefold():
                continue
            out.append((cid, [num, date_short(day).rstrip('г.'), ct['contract_number'], label, money(amount), 'да' if signed else 'нет', desc]))
        self.table.setRowCount(len(out))
        for r, (cid, vals) in enumerate(out):
            for col, v in enumerate(vals):
                self.table.setItem(r, col, item(v, cid if col == 0 else None, right=col == 4))

    def open_contract(self, *_):
        cid = selected_data(self.table)
        if cid:
            ContractDialog(self.mod, cid, self).exec()
            self.load_data()


# --- Шаблоны и теги ----------------------------------------------------------------------------

class TemplatesTab(QWidget):
    """Шаблоны документов и редактор тегов раздела (у каждого раздела свои)."""
    def __init__(self, mod):
        super().__init__()
        self.mod = mod
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Шаблоны и теги действуют только в разделе «{cc.cfg(mod)["title"]}». Теги записываются в Word-шаблоне в фигурных скобках, например {{НОМЕР_ДОГОВОРА}}.'))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        page = QWidget()
        pl = QVBoxLayout(page)
        self.tpl = make_table(['Документ', 'Файл шаблона (пусто — стандартный)'], (320,))
        self.tpl.setRowCount(len(cc.DOC_KINDS))
        for r, kind in enumerate(cc.DOC_KINDS):
            self.tpl.setItem(r, 0, item(cc.DOC_KINDS[kind][0], kind))
            self.tpl.setItem(r, 1, item(db.get_setting(cc.template_setting(mod, kind), '')))
        pl.addWidget(self.tpl, 1)
        if mod == 'smr':
            pl.addWidget(QLabel('Шаблон сметы и её теги настраиваются в модуле «Реестр смет».'))
        bar = QHBoxLayout()
        for text, fn in (('Выбрать шаблон…', self.choose_template), ('Открыть шаблон', self.open_template), ('Стандартный', self.reset_template)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        pl.addLayout(bar)
        tabs.addTab(page, 'Шаблоны документов')
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel('Для каждого тега задаются источник данных, формат и текст «если данных нет».'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск тега…')
        self.search.textChanged.connect(self.filter_rows)
        pl.addWidget(self.search)
        self.tags = make_table(['Тег', 'Источник данных', 'Формат', 'Если данных нет', 'Вкл.'], (260, 380, 240, 200, 60))
        self.tags.horizontalHeader().setStretchLastSection(False)
        self.tags.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        pl.addWidget(self.tags, 1)
        bar = QHBoxLayout()
        for text, fn in (('＋ Новый тег', self.new_tag), ('Удалить / отключить', self.delete_tag), ('Копировать тег', self.copy_tag), ('Сохранить теги', self.save_tags)):
            b = QPushButton(text)
            if text == 'Сохранить теги':
                b.setProperty('type', 'primary')
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.status = QLabel('')
        bar.addWidget(self.status, 1)
        pl.addLayout(bar)
        tabs.addTab(page, 'Редактор тегов')
        self.load_tags()

    def current_kind(self):
        return selected_data(self.tpl)

    def choose_template(self):
        kind = self.current_kind()
        if not kind:
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Шаблон документа', '', 'Шаблоны (*.docx)')
        if path:
            db.set_setting(cc.template_setting(self.mod, kind), path)
            self.tpl.item(self.tpl.currentRow(), 1).setText(path)

    def open_template(self):
        kind = self.current_kind()
        if kind:
            open_file(self, cc.template_path(db, self.mod, kind))

    def reset_template(self):
        kind = self.current_kind()
        if kind:
            db.set_setting(cc.template_setting(self.mod, kind), '')
            self.tpl.item(self.tpl.currentRow(), 1).setText('')

    def load_tags(self):
        self.sources = cc.available_sources(db, self.mod)
        self.tags.setRowCount(0)
        for row in cc.list_tags(db, self.mod):
            self.add_row(*row)
        self.filter_rows()

    def add_row(self, tag_id, name, source, fmt, empty_text, auto_key='', enabled=1, note=''):
        r = self.tags.rowCount()
        self.tags.insertRow(r)
        it = QTableWidgetItem(name)
        it.setData(Qt.ItemDataRole.UserRole, tag_id)
        if auto_key:
            it.setForeground(QColor('#2563EB'))
        self.tags.setItem(r, 0, it)
        src = QComboBox()
        for key, label in self.sources:
            src.addItem(label, key)
        if src.findData(source) < 0:
            src.addItem(source, source)
        src.setCurrentIndex(src.findData(source))
        self.tags.setCellWidget(r, 1, src)
        fm = QComboBox()
        for key, label in FORMATS.items():
            fm.addItem(label, key)
        fm.setCurrentIndex(max(0, fm.findData(fmt)))
        self.tags.setCellWidget(r, 2, fm)
        self.tags.setItem(r, 3, QTableWidgetItem(empty_text or ''))
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        chk.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.tags.setItem(r, 4, chk)

    def filter_rows(self, *_):
        q = self.search.text().casefold()
        for r in range(self.tags.rowCount()):
            self.tags.setRowHidden(r, bool(q) and q not in (read_item(self.tags, r, 0) + self.tags.cellWidget(r, 1).currentText()).casefold())

    def new_tag(self):
        self.add_row(None, 'НОВЫЙ_ТЕГ', self.sources[0][0], 'text', '', '', 1, '')
        self.tags.setCurrentCell(self.tags.rowCount() - 1, 0)
        self.tags.editItem(self.tags.item(self.tags.rowCount() - 1, 0))

    def delete_tag(self):
        r = self.tags.currentRow()
        if r < 0:
            return
        tag_id = self.tags.item(r, 0).data(Qt.ItemDataRole.UserRole)
        if tag_id:
            result = cc.delete_tag(db, self.mod, tag_id)
            self.status.setText('Тег удалён.' if result == 'deleted' else 'Стандартный тег отключён (его можно включить галочкой).')
            self.load_tags()
        else:
            self.tags.removeRow(r)

    def copy_tag(self):
        r = self.tags.currentRow()
        if r >= 0:
            QApplication.clipboard().setText('{' + read_item(self.tags, r, 0) + '}')
            self.status.setText('Скопировано: {' + read_item(self.tags, r, 0) + '}')

    def save_tags(self):
        errors = []
        with db.transaction():
            for r in range(self.tags.rowCount()):
                tag_id = self.tags.item(r, 0).data(Qt.ItemDataRole.UserRole)
                try:
                    new_id = cc.save_tag(db, self.mod, tag_id, read_item(self.tags, r, 0), self.tags.cellWidget(r, 1).currentData(), self.tags.cellWidget(r, 2).currentData(),
                                         read_item(self.tags, r, 3), self.tags.item(r, 4).checkState() == Qt.CheckState.Checked)
                    self.tags.item(r, 0).setData(Qt.ItemDataRole.UserRole, new_id)
                except ValueError as e:
                    errors.append(f'Строка {r + 1}: {e}')
        if errors:
            warn(self, '\n'.join(errors), 'Теги')
        else:
            self.status.setText('Теги сохранены. Документы с изменившимися значениями получат пометку «переформируйте».')
            self.load_tags()


class SmrView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(ContractsRegistry('smr'), 'Договоры')
        tabs.addTab(ActsRegistry('smr'), 'Акты')
        tabs.addTab(TemplatesTab('smr'), 'Шаблоны и теги')
        layout.addWidget(tabs)


class CustomerSwitch(QGroupBox):
    """Выбор заказчика в карточках проекта / монтажа ГСВ: физлицо (как раньше) или юрлицо из справочника «Юрлица».
    Документы юрлица (договор, акт, справка) оформляются только в разделе «Юрлица» — отсюда создаётся или открывается связанный договор."""
    changed = pyqtSignal()

    def __init__(self, source_type, source_id_getter, ensure_saved, parent=None):
        super().__init__('Заказчик', parent)
        self.source_type, self.source_id, self.ensure_saved = source_type, source_id_getter, ensure_saved
        layout = QGridLayout(self)
        self.rb_person = QRadioButton('Физическое лицо')
        self.rb_legal = QRadioButton('Юридическое лицо')
        self.rb_person.setChecked(True)
        layout.addWidget(self.rb_person, 0, 0)
        layout.addWidget(self.rb_legal, 0, 1)
        self.combo = QComboBox()
        populate_legal_combo(self.combo)
        layout.addWidget(self.combo, 1, 0, 1, 2)
        new = QPushButton('＋ Новое юрлицо…')
        new.clicked.connect(self.new_legal)
        layout.addWidget(new, 1, 2)
        self.info = QLabel('')
        self.info.setWordWrap(True)
        self.info.setStyleSheet('color:#65758b;')
        layout.addWidget(self.info, 2, 0, 1, 3)
        self.btn_contract = QPushButton('Договор в «Юрлицах»…')
        self.btn_contract.clicked.connect(self.open_contract)
        layout.addWidget(self.btn_contract, 3, 0, 1, 3)
        self.rb_legal.toggled.connect(self.toggled)
        self.combo.currentIndexChanged.connect(self.refresh)
        self.toggled()

    def is_legal(self):
        return self.rb_legal.isChecked()

    def legal_id(self):
        return self.combo.currentData() if self.is_legal() else None

    def set_legal(self, legal_id):
        populate_legal_combo(self.combo, legal_id)
        self.rb_legal.setChecked(bool(legal_id))
        self.rb_person.setChecked(not legal_id)
        self.toggled()

    def toggled(self, *_):
        legal = self.is_legal()
        self.combo.setEnabled(legal)
        self.btn_contract.setVisible(legal)
        self.refresh()
        self.changed.emit()

    def refresh(self, *_):
        row = cc.legal(db, self.combo.currentData()) if self.is_legal() and self.combo.currentData() else None
        if self.is_legal():
            self.info.setText(f'Договор, акт и справка оформляются в разделе «Юрлица». УНП {row["unp"] or "—"}, руководитель: {row["head_name"] or "не указан"}.' if row
                              else 'Выберите юрлицо. Договор, акт и справка оформляются в разделе «Юрлица».')
        else:
            self.info.setText('')

    def new_legal(self):
        d = LegalClientDialog(parent=self)
        if d.exec():
            populate_legal_combo(self.combo, d.client_id)
            self.rb_legal.setChecked(True)

    def open_contract(self):
        if not self.ensure_saved() or not self.source_id():
            return
        try:
            cid, created = cc.contract_from_source(db, self.source_type, self.source_id())
        except Exception as e:
            warn(self, str(e))
            return
        ContractDialog('le', cid, self).exec()
