"""
Вкладка "Юрлица": простой учёт договоров и актов с организациями по трём
направлениям (монтаж, техобслуживание, проверка дымовых/вентиляционных
каналов) плюс журнал регистрации исходящей документации. Без смет —
стоимость работ вводится одной цифрой, с отметкой "включает НДС".
"""
import sqlite3

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QLabel,
    QLineEdit, QTextEdit, QComboBox, QPushButton, QDateEdit, QDoubleSpinBox,
    QCheckBox, QTableWidget, QTableWidgetItem, QAbstractItemView, QDialog,
    QMessageBox,
)
from PyQt6.QtCore import Qt, QDate

from .database import db
from .legal_entities_domain import DIRECTIONS, STATUSES, next_outgoing_number


def fmt_amount(value, vat_included):
    return f"{float(value or 0):,.2f} руб. ({'с НДС' if vat_included else 'без НДС'})".replace(",", " ")


def populate_client_combo(combo, selected=None):
    combo.clear()
    combo.addItem("— выберите клиента —", None)
    for cid, name in db.fetchall("SELECT id, name FROM le_clients ORDER BY name"):
        combo.addItem(name, cid)
    if selected is not None:
        combo.setCurrentIndex(max(0, combo.findData(selected)))


# --- Юрлица (клиенты-организации) ---

class LegalClientDialog(QDialog):
    def __init__(self, client_id=None, parent=None):
        super().__init__(parent)
        self.client_id = client_id
        self.setWindowTitle("Карточка юрлица" if client_id else "Новое юрлицо")
        self.resize(480, 420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Наименование организации *:"))
        self.inp_name = QLineEdit()
        layout.addWidget(self.inp_name)

        layout.addWidget(QLabel("УНП / ИНН:"))
        self.inp_unp = QLineEdit()
        layout.addWidget(self.inp_unp)

        layout.addWidget(QLabel("Адрес:"))
        self.inp_address = QLineEdit()
        layout.addWidget(self.inp_address)

        row = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(QLabel("Контактное лицо:"))
        self.inp_contact = QLineEdit()
        col1.addWidget(self.inp_contact)
        col2 = QVBoxLayout()
        col2.addWidget(QLabel("Телефон:"))
        self.inp_phone = QLineEdit()
        col2.addWidget(self.inp_phone)
        row.addLayout(col1)
        row.addLayout(col2)
        layout.addLayout(row)

        layout.addWidget(QLabel("Email:"))
        self.inp_email = QLineEdit()
        layout.addWidget(self.inp_email)

        layout.addWidget(QLabel("Примечание:"))
        self.inp_note = QTextEdit()
        self.inp_note.setFixedHeight(70)
        layout.addWidget(self.inp_note)

        bar = QHBoxLayout()
        btn_save = QPushButton("Сохранить")
        btn_save.setProperty("type", "primary")
        btn_save.clicked.connect(self.save_data)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(btn_cancel)
        bar.addWidget(btn_save)
        layout.addLayout(bar)

        if client_id:
            self.load_data()

    def load_data(self):
        row = db.fetchone("SELECT name, unp, address, contact_person, phone, email, note FROM le_clients WHERE id=?", (self.client_id,))
        if not row:
            return
        name, unp, address, contact, phone, email, note = row
        self.inp_name.setText(name or "")
        self.inp_unp.setText(unp or "")
        self.inp_address.setText(address or "")
        self.inp_contact.setText(contact or "")
        self.inp_phone.setText(phone or "")
        self.inp_email.setText(email or "")
        self.inp_note.setPlainText(note or "")

    def save_data(self):
        name = self.inp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Укажите наименование организации.")
            return
        values = (name, self.inp_unp.text().strip(), self.inp_address.text().strip(),
                  self.inp_contact.text().strip(), self.inp_phone.text().strip(),
                  self.inp_email.text().strip(), self.inp_note.toPlainText().strip())
        if self.client_id:
            db.execute("UPDATE le_clients SET name=?, unp=?, address=?, contact_person=?, phone=?, email=?, note=? WHERE id=?",
                       (*values, self.client_id))
        else:
            self.client_id = db.execute(
                "INSERT INTO le_clients(name, unp, address, contact_person, phone, email, note) VALUES(?,?,?,?,?,?,?)",
                values).lastrowid
        self.accept()


class LegalClientsRegistry(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Наименование, УНП, контактное лицо, телефон…")
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        btn_add = QPushButton("Добавить юрлицо")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.add_client)
        bar.addWidget(btn_add)
        btn_edit = QPushButton("Изменить")
        btn_edit.clicked.connect(self.edit_client)
        bar.addWidget(btn_edit)
        btn_del = QPushButton("Удалить")
        btn_del.setProperty("type", "danger")
        btn_del.clicked.connect(self.delete_client)
        bar.addWidget(btn_del)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Наименование", "УНП", "Контактное лицо", "Телефон", "Email"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.edit_client)
        layout.addWidget(self.table, 1)

        self.load_data()

    def load_data(self):
        q = "%" + self.search.text().strip().casefold() + "%"
        rows = db.fetchall(
            """SELECT id, name, unp, contact_person, phone, email FROM le_clients
               WHERE LOWER(name||' '||coalesce(unp,'')||' '||coalesce(contact_person,'')||' '||coalesce(phone,'')) LIKE ?
               ORDER BY name""", (q,))
        self.table.setRowCount(len(rows))
        for r, (cid, name, unp, contact, phone, email) in enumerate(rows):
            item = QTableWidgetItem(name or "")
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self.table.setItem(r, 0, item)
            for c, value in enumerate((unp, contact, phone, email), start=1):
                self.table.setItem(r, c, QTableWidgetItem(value or ""))

    def selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def add_client(self):
        if LegalClientDialog(parent=self).exec():
            self.load_data()

    def edit_client(self):
        cid = self.selected_id()
        if cid and LegalClientDialog(cid, self).exec():
            self.load_data()

    def delete_client(self):
        cid = self.selected_id()
        if not cid:
            return
        if QMessageBox.question(self, "Удаление", "Удалить выбранное юрлицо?") != QMessageBox.StandardButton.Yes:
            return
        try:
            db.execute("DELETE FROM le_clients WHERE id=?", (cid,))
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Нельзя удалить", "У этого юрлица есть договоры — сначала удалите или перепривяжите их.")
            return
        self.load_data()


# --- Договоры ---

class LegalContractDialog(QDialog):
    def __init__(self, contract_id=None, parent=None):
        super().__init__(parent)
        self.contract_id = contract_id
        self.setWindowTitle("Карточка договора" if contract_id else "Новый договор")
        self.resize(560, 560)

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel("Направление:"), 0, 0)
        self.cmb_direction = QComboBox()
        self.cmb_direction.addItems(DIRECTIONS)
        grid.addWidget(self.cmb_direction, 0, 1, 1, 3)

        grid.addWidget(QLabel("Номер договора:"), 1, 0)
        self.inp_number = QLineEdit()
        grid.addWidget(self.inp_number, 1, 1)
        grid.addWidget(QLabel("Дата:"), 1, 2)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd.MM.yyyy")
        grid.addWidget(self.date, 1, 3)

        grid.addWidget(QLabel("Клиент:"), 2, 0)
        self.cmb_client = QComboBox()
        populate_client_combo(self.cmb_client)
        grid.addWidget(self.cmb_client, 2, 1, 1, 2)
        btn_new_client = QPushButton("+ Новый клиент…")
        btn_new_client.clicked.connect(self.add_client_inline)
        grid.addWidget(btn_new_client, 2, 3)

        grid.addWidget(QLabel("Объект / адрес работ:"), 3, 0)
        self.inp_object = QLineEdit()
        grid.addWidget(self.inp_object, 3, 1, 1, 3)

        grid.addWidget(QLabel("Сумма договора:"), 4, 0)
        self.spin_amount = QDoubleSpinBox()
        self.spin_amount.setRange(0, 1e9)
        self.spin_amount.setDecimals(2)
        self.spin_amount.setSuffix(" руб.")
        grid.addWidget(self.spin_amount, 4, 1)
        self.chk_vat = QCheckBox("В том числе НДС")
        grid.addWidget(self.chk_vat, 4, 2, 1, 2)

        grid.addWidget(QLabel("Статус:"), 5, 0)
        self.cmb_status = QComboBox()
        self.cmb_status.setEditable(True)
        self.cmb_status.addItems(STATUSES)
        grid.addWidget(self.cmb_status, 5, 1, 1, 3)
        layout.addLayout(grid)

        layout.addWidget(QLabel("Примечание:"))
        self.inp_note = QTextEdit()
        self.inp_note.setFixedHeight(80)
        layout.addWidget(self.inp_note)

        bar = QHBoxLayout()
        btn_save = QPushButton("Сохранить")
        btn_save.setProperty("type", "primary")
        btn_save.clicked.connect(self.save_data)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(btn_cancel)
        bar.addWidget(btn_save)
        layout.addLayout(bar)

        if contract_id:
            self.load_data()

    def add_client_inline(self):
        d = LegalClientDialog(parent=self)
        if d.exec():
            populate_client_combo(self.cmb_client, d.client_id)

    def load_data(self):
        row = db.fetchone(
            "SELECT direction, contract_number, contract_date, client_id, object_name, amount, vat_included, status, note FROM le_contracts WHERE id=?",
            (self.contract_id,))
        if not row:
            return
        direction, number, date_str, client_id, obj, amount, vat, status, note = row
        self.cmb_direction.setCurrentText(direction or DIRECTIONS[0])
        self.inp_number.setText(number or "")
        if date_str:
            d = QDate.fromString(date_str, "yyyy-MM-dd")
            if d.isValid():
                self.date.setDate(d)
        populate_client_combo(self.cmb_client, client_id)
        self.inp_object.setText(obj or "")
        self.spin_amount.setValue(float(amount or 0))
        self.chk_vat.setChecked(bool(vat))
        self.cmb_status.setCurrentText(status or STATUSES[0])
        self.inp_note.setPlainText(note or "")

    def save_data(self):
        if not self.inp_number.text().strip():
            QMessageBox.warning(self, "Ошибка", "Укажите номер договора.")
            return
        values = (
            self.cmb_direction.currentText(),
            self.inp_number.text().strip(),
            self.date.date().toString("yyyy-MM-dd"),
            self.cmb_client.currentData(),
            self.inp_object.text().strip(),
            self.spin_amount.value(),
            1 if self.chk_vat.isChecked() else 0,
            self.cmb_status.currentText().strip(),
            self.inp_note.toPlainText().strip(),
        )
        if self.contract_id:
            db.execute(
                """UPDATE le_contracts SET direction=?, contract_number=?, contract_date=?, client_id=?,
                   object_name=?, amount=?, vat_included=?, status=?, note=? WHERE id=?""",
                (*values, self.contract_id))
        else:
            self.contract_id = db.execute(
                """INSERT INTO le_contracts(direction, contract_number, contract_date, client_id, object_name,
                   amount, vat_included, status, note) VALUES(?,?,?,?,?,?,?,?,?)""",
                values).lastrowid
        self.accept()


class LegalContractsRegistry(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.cmb_direction = QComboBox()
        self.cmb_direction.addItem("Все направления", None)
        for d in DIRECTIONS:
            self.cmb_direction.addItem(d, d)
        self.cmb_direction.currentIndexChanged.connect(self.load_data)
        bar.addWidget(self.cmb_direction)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Номер, объект, клиент…")
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        btn_add = QPushButton("Создать договор")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.add_contract)
        bar.addWidget(btn_add)
        btn_edit = QPushButton("Изменить")
        btn_edit.clicked.connect(self.edit_contract)
        bar.addWidget(btn_edit)
        btn_del = QPushButton("Удалить")
        btn_del.setProperty("type", "danger")
        btn_del.clicked.connect(self.delete_contract)
        bar.addWidget(btn_del)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Направление", "№ Договора", "Дата", "Клиент", "Объект", "Сумма"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.edit_contract)
        layout.addWidget(self.table, 1)

        self.load_data()

    def load_data(self, *_):
        q = "%" + self.search.text().strip().casefold() + "%"
        sql = """SELECT c.id, c.direction, c.contract_number, c.contract_date, coalesce(cl.name,''), c.object_name, c.amount, c.vat_included
                  FROM le_contracts c LEFT JOIN le_clients cl ON cl.id=c.client_id
                  WHERE LOWER(coalesce(c.contract_number,'')||' '||coalesce(c.object_name,'')||' '||coalesce(cl.name,'')) LIKE ?"""
        params = [q]
        direction = self.cmb_direction.currentData()
        if direction:
            sql += " AND c.direction=?"
            params.append(direction)
        sql += " ORDER BY c.id DESC"
        rows = db.fetchall(sql, tuple(params))
        self.table.setRowCount(len(rows))
        for r, (cid, direction, number, date_str, client, obj, amount, vat) in enumerate(rows):
            item = QTableWidgetItem(direction or "")
            item.setData(Qt.ItemDataRole.UserRole, cid)
            self.table.setItem(r, 0, item)
            self.table.setItem(r, 1, QTableWidgetItem(number or "Б/Н"))
            self.table.setItem(r, 2, QTableWidgetItem(date_str or ""))
            self.table.setItem(r, 3, QTableWidgetItem(client))
            self.table.setItem(r, 4, QTableWidgetItem(obj or ""))
            amount_item = QTableWidgetItem(fmt_amount(amount, vat))
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 5, amount_item)

    def selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def add_contract(self):
        if LegalContractDialog(parent=self).exec():
            self.load_data()

    def edit_contract(self):
        cid = self.selected_id()
        if cid and LegalContractDialog(cid, self).exec():
            self.load_data()

    def delete_contract(self):
        cid = self.selected_id()
        if not cid:
            return
        if QMessageBox.question(self, "Удаление", "Удалить договор и все его акты?") != QMessageBox.StandardButton.Yes:
            return
        db.execute("DELETE FROM le_contracts WHERE id=?", (cid,))
        self.load_data()


# --- Акты ---

class LegalActDialog(QDialog):
    def __init__(self, act_id=None, contract_id=None, parent=None):
        super().__init__(parent)
        self.act_id = act_id
        self.setWindowTitle("Карточка акта" if act_id else "Новый акт")
        self.resize(520, 480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Договор:"))
        self.cmb_contract = QComboBox()
        self.populate_contracts(contract_id)
        layout.addWidget(self.cmb_contract)

        grid = QGridLayout()
        grid.addWidget(QLabel("Номер акта:"), 0, 0)
        self.inp_number = QLineEdit()
        grid.addWidget(self.inp_number, 0, 1)
        grid.addWidget(QLabel("Дата:"), 0, 2)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd.MM.yyyy")
        grid.addWidget(self.date, 0, 3)

        grid.addWidget(QLabel("Сумма акта:"), 1, 0)
        self.spin_amount = QDoubleSpinBox()
        self.spin_amount.setRange(0, 1e9)
        self.spin_amount.setDecimals(2)
        self.spin_amount.setSuffix(" руб.")
        grid.addWidget(self.spin_amount, 1, 1)
        self.chk_vat = QCheckBox("В том числе НДС")
        grid.addWidget(self.chk_vat, 1, 2, 1, 2)
        layout.addLayout(grid)

        layout.addWidget(QLabel("Описание выполненных работ:"))
        self.inp_description = QTextEdit()
        self.inp_description.setFixedHeight(70)
        layout.addWidget(self.inp_description)

        layout.addWidget(QLabel("Примечание:"))
        self.inp_note = QTextEdit()
        self.inp_note.setFixedHeight(60)
        layout.addWidget(self.inp_note)

        bar = QHBoxLayout()
        btn_save = QPushButton("Сохранить")
        btn_save.setProperty("type", "primary")
        btn_save.clicked.connect(self.save_data)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(btn_cancel)
        bar.addWidget(btn_save)
        layout.addLayout(bar)

        if act_id:
            self.load_data()

    def populate_contracts(self, selected=None):
        self.cmb_contract.clear()
        rows = db.fetchall(
            """SELECT c.id, c.contract_number, c.direction, coalesce(cl.name,'')
               FROM le_contracts c LEFT JOIN le_clients cl ON cl.id=c.client_id ORDER BY c.id DESC""")
        for cid, number, direction, client in rows:
            label = f"{number or 'Б/Н'} · {direction} · {client or 'без клиента'}"
            self.cmb_contract.addItem(label, cid)
        if selected is not None:
            self.cmb_contract.setCurrentIndex(max(0, self.cmb_contract.findData(selected)))

    def load_data(self):
        row = db.fetchone(
            "SELECT contract_id, act_number, act_date, amount, vat_included, description, note FROM le_acts WHERE id=?",
            (self.act_id,))
        if not row:
            return
        contract_id, number, date_str, amount, vat, description, note = row
        self.cmb_contract.setCurrentIndex(max(0, self.cmb_contract.findData(contract_id)))
        self.inp_number.setText(number or "")
        if date_str:
            d = QDate.fromString(date_str, "yyyy-MM-dd")
            if d.isValid():
                self.date.setDate(d)
        self.spin_amount.setValue(float(amount or 0))
        self.chk_vat.setChecked(bool(vat))
        self.inp_description.setPlainText(description or "")
        self.inp_note.setPlainText(note or "")

    def save_data(self):
        contract_id = self.cmb_contract.currentData()
        if not contract_id:
            QMessageBox.warning(self, "Ошибка", "Сначала создайте договор — акт привязывается к договору.")
            return
        values = (
            contract_id,
            self.inp_number.text().strip(),
            self.date.date().toString("yyyy-MM-dd"),
            self.spin_amount.value(),
            1 if self.chk_vat.isChecked() else 0,
            self.inp_description.toPlainText().strip(),
            self.inp_note.toPlainText().strip(),
        )
        if self.act_id:
            db.execute(
                "UPDATE le_acts SET contract_id=?, act_number=?, act_date=?, amount=?, vat_included=?, description=?, note=? WHERE id=?",
                (*values, self.act_id))
        else:
            self.act_id = db.execute(
                "INSERT INTO le_acts(contract_id, act_number, act_date, amount, vat_included, description, note) VALUES(?,?,?,?,?,?,?)",
                values).lastrowid
        self.accept()


class LegalActsRegistry(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.cmb_direction = QComboBox()
        self.cmb_direction.addItem("Все направления", None)
        for d in DIRECTIONS:
            self.cmb_direction.addItem(d, d)
        self.cmb_direction.currentIndexChanged.connect(self.load_data)
        bar.addWidget(self.cmb_direction)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Номер акта, договор, клиент…")
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        btn_add = QPushButton("Добавить акт")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.add_act)
        bar.addWidget(btn_add)
        btn_edit = QPushButton("Изменить")
        btn_edit.clicked.connect(self.edit_act)
        bar.addWidget(btn_edit)
        btn_del = QPushButton("Удалить")
        btn_del.setProperty("type", "danger")
        btn_del.clicked.connect(self.delete_act)
        bar.addWidget(btn_del)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Договор", "Клиент", "Направление", "№ Акта", "Дата", "Сумма"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.edit_act)
        layout.addWidget(self.table, 1)

        self.load_data()

    def load_data(self, *_):
        q = "%" + self.search.text().strip().casefold() + "%"
        sql = """SELECT a.id, c.contract_number, coalesce(cl.name,''), c.direction, a.act_number, a.act_date, a.amount, a.vat_included
                  FROM le_acts a JOIN le_contracts c ON c.id=a.contract_id LEFT JOIN le_clients cl ON cl.id=c.client_id
                  WHERE LOWER(coalesce(a.act_number,'')||' '||coalesce(c.contract_number,'')||' '||coalesce(cl.name,'')) LIKE ?"""
        params = [q]
        direction = self.cmb_direction.currentData()
        if direction:
            sql += " AND c.direction=?"
            params.append(direction)
        sql += " ORDER BY a.id DESC"
        rows = db.fetchall(sql, tuple(params))
        self.table.setRowCount(len(rows))
        for r, (aid, contract_number, client, direction, number, date_str, amount, vat) in enumerate(rows):
            item = QTableWidgetItem(contract_number or "Б/Н")
            item.setData(Qt.ItemDataRole.UserRole, aid)
            self.table.setItem(r, 0, item)
            self.table.setItem(r, 1, QTableWidgetItem(client))
            self.table.setItem(r, 2, QTableWidgetItem(direction or ""))
            self.table.setItem(r, 3, QTableWidgetItem(number or ""))
            self.table.setItem(r, 4, QTableWidgetItem(date_str or ""))
            amount_item = QTableWidgetItem(fmt_amount(amount, vat))
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 5, amount_item)

    def selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def add_act(self):
        if not db.fetchone("SELECT 1 FROM le_contracts LIMIT 1"):
            QMessageBox.information(self, "Нет договоров", "Сначала создайте хотя бы один договор во вкладке «Договоры».")
            return
        if LegalActDialog(parent=self).exec():
            self.load_data()

    def edit_act(self):
        aid = self.selected_id()
        if aid and LegalActDialog(aid, parent=self).exec():
            self.load_data()

    def delete_act(self):
        aid = self.selected_id()
        if not aid:
            return
        if QMessageBox.question(self, "Удаление", "Удалить выбранный акт?") != QMessageBox.StandardButton.Yes:
            return
        db.execute("DELETE FROM le_acts WHERE id=?", (aid,))
        self.load_data()


# --- Журнал регистрации исходящей документации ---

class OutgoingDocDialog(QDialog):
    def __init__(self, doc_id=None, parent=None):
        super().__init__(parent)
        self.doc_id = doc_id
        self.setWindowTitle("Исходящий документ" if doc_id else "Новый исходящий документ")
        self.resize(500, 420)

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel("Исходящий номер:"), 0, 0)
        self.inp_number = QLineEdit()
        if not doc_id:
            self.inp_number.setText(next_outgoing_number(db))
        grid.addWidget(self.inp_number, 0, 1)
        grid.addWidget(QLabel("Дата регистрации:"), 0, 2)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd.MM.yyyy")
        grid.addWidget(self.date, 0, 3)
        layout.addLayout(grid)

        layout.addWidget(QLabel("Кому / куда адресован:"))
        self.inp_recipient = QLineEdit()
        layout.addWidget(self.inp_recipient)

        layout.addWidget(QLabel("Юрлицо (необязательно):"))
        self.cmb_client = QComboBox()
        populate_client_combo(self.cmb_client)
        layout.addWidget(self.cmb_client)

        layout.addWidget(QLabel("Содержание / о чём документ:"))
        self.inp_subject = QTextEdit()
        self.inp_subject.setFixedHeight(70)
        layout.addWidget(self.inp_subject)

        layout.addWidget(QLabel("Примечание:"))
        self.inp_note = QTextEdit()
        self.inp_note.setFixedHeight(60)
        layout.addWidget(self.inp_note)

        bar = QHBoxLayout()
        btn_save = QPushButton("Сохранить")
        btn_save.setProperty("type", "primary")
        btn_save.clicked.connect(self.save_data)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(btn_cancel)
        bar.addWidget(btn_save)
        layout.addLayout(bar)

        if doc_id:
            self.load_data()

    def load_data(self):
        row = db.fetchone(
            "SELECT reg_number, reg_date, recipient, subject, client_id, note FROM le_outgoing WHERE id=?",
            (self.doc_id,))
        if not row:
            return
        number, date_str, recipient, subject, client_id, note = row
        self.inp_number.setText(number or "")
        if date_str:
            d = QDate.fromString(date_str, "yyyy-MM-dd")
            if d.isValid():
                self.date.setDate(d)
        self.inp_recipient.setText(recipient or "")
        populate_client_combo(self.cmb_client, client_id)
        self.inp_subject.setPlainText(subject or "")
        self.inp_note.setPlainText(note or "")

    def save_data(self):
        if not self.inp_recipient.text().strip():
            QMessageBox.warning(self, "Ошибка", "Укажите, кому адресован документ.")
            return
        values = (
            self.inp_number.text().strip(),
            self.date.date().toString("yyyy-MM-dd"),
            self.inp_recipient.text().strip(),
            self.inp_subject.toPlainText().strip(),
            self.cmb_client.currentData(),
            self.inp_note.toPlainText().strip(),
        )
        if self.doc_id:
            db.execute(
                "UPDATE le_outgoing SET reg_number=?, reg_date=?, recipient=?, subject=?, client_id=?, note=? WHERE id=?",
                (*values, self.doc_id))
        else:
            self.doc_id = db.execute(
                "INSERT INTO le_outgoing(reg_number, reg_date, recipient, subject, client_id, note) VALUES(?,?,?,?,?,?)",
                values).lastrowid
        self.accept()


class OutgoingLogRegistry(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Номер, адресат, содержание…")
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        btn_add = QPushButton("Зарегистрировать документ")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.add_doc)
        bar.addWidget(btn_add)
        btn_edit = QPushButton("Изменить")
        btn_edit.clicked.connect(self.edit_doc)
        bar.addWidget(btn_edit)
        btn_del = QPushButton("Удалить")
        btn_del.setProperty("type", "danger")
        btn_del.clicked.connect(self.delete_doc)
        bar.addWidget(btn_del)
        layout.addLayout(bar)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["№", "Дата", "Кому", "Содержание", "Юрлицо"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(self.edit_doc)
        layout.addWidget(self.table, 1)

        self.load_data()

    def load_data(self, *_):
        q = "%" + self.search.text().strip().casefold() + "%"
        rows = db.fetchall(
            """SELECT o.id, o.reg_number, o.reg_date, o.recipient, o.subject, coalesce(cl.name,'')
               FROM le_outgoing o LEFT JOIN le_clients cl ON cl.id=o.client_id
               WHERE LOWER(coalesce(o.reg_number,'')||' '||coalesce(o.recipient,'')||' '||coalesce(o.subject,'')) LIKE ?
               ORDER BY o.id DESC""", (q,))
        self.table.setRowCount(len(rows))
        for r, (oid, number, date_str, recipient, subject, client) in enumerate(rows):
            item = QTableWidgetItem(number or "")
            item.setData(Qt.ItemDataRole.UserRole, oid)
            self.table.setItem(r, 0, item)
            self.table.setItem(r, 1, QTableWidgetItem(date_str or ""))
            self.table.setItem(r, 2, QTableWidgetItem(recipient or ""))
            short = (subject or "").replace("\n", " ")
            self.table.setItem(r, 3, QTableWidgetItem(short[:120] + ("…" if len(short) > 120 else "")))
            self.table.setItem(r, 4, QTableWidgetItem(client))

    def selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def add_doc(self):
        if OutgoingDocDialog(parent=self).exec():
            self.load_data()

    def edit_doc(self):
        oid = self.selected_id()
        if oid and OutgoingDocDialog(oid, self).exec():
            self.load_data()

    def delete_doc(self):
        oid = self.selected_id()
        if not oid:
            return
        if QMessageBox.question(self, "Удаление", "Удалить запись журнала?") != QMessageBox.StandardButton.Yes:
            return
        db.execute("DELETE FROM le_outgoing WHERE id=?", (oid,))
        self.load_data()


# --- Главный виджет модуля ---

class LegalEntitiesView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(LegalContractsRegistry(), "Договоры")
        tabs.addTab(LegalActsRegistry(), "Акты")
        tabs.addTab(LegalClientsRegistry(), "Юрлица")
        tabs.addTab(OutgoingLogRegistry(), "Исходящая документация")
        layout.addWidget(tabs)
