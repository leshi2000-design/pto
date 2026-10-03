"""
Диалоги общего назначения, используемые в справочнике и в редакторе смет.
"""
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QTableWidget, QTableWidgetItem, QMessageBox, QDialog,
                              QAbstractItemView, QLineEdit, QComboBox, QDoubleSpinBox,
                              QDateEdit, QGridLayout, QGroupBox)
from PyQt6.QtCore import Qt, QDate

from .database import db
from .pagination import RegistryPager
from .widgets import SmartTableManager

class CustomItemDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Произвольная позиция")
        self.resize(450, 250)
        self.result_data = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Тип:"))
        self.cb_type = QComboBox()
        self.cb_type.addItems(["Материал", "Работа"])
        layout.addWidget(self.cb_type)

        layout.addWidget(QLabel("Наименование:"))
        self.inp_name = QLineEdit()
        layout.addWidget(self.inp_name)

        h_l = QHBoxLayout()
        v_u = QVBoxLayout()
        v_u.addWidget(QLabel("Ед. изм.:"))
        self.inp_unit = QLineEdit("шт")
        v_u.addWidget(self.inp_unit)

        v_pu = QVBoxLayout()
        v_pu.addWidget(QLabel("Цена закупки (скрытая):"))
        self.inp_purch = QDoubleSpinBox()
        self.inp_purch.setMaximum(10000000)
        self.inp_purch.setDecimals(2)
        v_pu.addWidget(self.inp_purch)

        v_p = QVBoxLayout()
        v_p.addWidget(QLabel("Цена продажи (руб):"))
        self.inp_price = QDoubleSpinBox()
        self.inp_price.setMaximum(10000000)
        self.inp_price.setDecimals(2)
        v_p.addWidget(self.inp_price)

        h_l.addLayout(v_u)
        h_l.addLayout(v_pu)
        h_l.addLayout(v_p)
        layout.addLayout(h_l)

        btn_bar = QHBoxLayout()
        btn_ok = QPushButton("Добавить")
        btn_ok.setProperty("type", "primary")
        btn_ok.clicked.connect(self.accept_data)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_bar.addStretch()
        btn_bar.addWidget(btn_cancel)
        btn_bar.addWidget(btn_ok)
        layout.addLayout(btn_bar)

    def accept_data(self):
        name = self.inp_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Введите наименование.")
            return
        self.result_data = {
            "type": self.cb_type.currentText(),
            "name": name,
            "unit": self.inp_unit.text().strip() or "шт",
            "purchase_price": self.inp_purch.value(),
            "price": self.inp_price.value()
        }
        self.accept()

class LegacyPaymentDialog(QDialog):
    def __init__(self, est_id, current_total, parent=None):
        super().__init__(parent)
        self.setWindowTitle("История оплат по смете")
        self.resize(500, 450)
        self.est_id = est_id
        self.current_total = current_total
        self.remainder = current_total

        layout = QVBoxLayout(self)
        self.lbl_info = QLabel()
        self.lbl_info.setStyleSheet("font-size: 11pt; font-weight: bold; padding-bottom: 10px;")
        layout.addWidget(self.lbl_info)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Дата платежа", "Внесенная сумма (руб)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table_manager = SmartTableManager(self.table, main_col=0, default_widths={1: 180})
        layout.addWidget(self.table)

        self.btn_del = QPushButton("Удалить выбранный платеж")
        self.btn_del.setProperty("type", "danger")
        self.btn_del.clicked.connect(self.del_payment)
        layout.addWidget(self.btn_del)

        grp = QGroupBox("Внести новый платеж")
        grp_layout = QGridLayout(grp)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.spin_paid = QDoubleSpinBox()
        self.spin_paid.setMaximum(1000000000)
        self.spin_paid.setDecimals(2)

        grp_layout.addWidget(QLabel("Дата:"), 0, 0)
        grp_layout.addWidget(self.date_edit, 0, 1)
        grp_layout.addWidget(QLabel("Сумма:"), 1, 0)
        grp_layout.addWidget(self.spin_paid, 1, 1)

        btn_add = QPushButton("Внести платеж")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.add_payment)
        btn_full = QPushButton("Оплатить остаток")
        btn_full.clicked.connect(lambda: self.spin_paid.setValue(self.remainder))

        grp_layout.addWidget(btn_add, 0, 2)
        grp_layout.addWidget(btn_full, 1, 2)
        layout.addWidget(grp)

        self.load_data()

    def update_parents(self):
        p = self.parent()
        if p:
            if hasattr(p, 'load_data'): p.load_data()
            if hasattr(p, 'load_items'): p.load_items()
            if hasattr(p, 'parent') and p.parent() and hasattr(p.parent(), 'load_data'):
                p.parent().load_data()

    def load_data(self):
        rows = db.fetchall("SELECT id, date, amount FROM payments WHERE estimate_id=? ORDER BY date DESC, id DESC", (self.est_id,))
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        paid = 0.0
        latest_date = ""
        for r, (pid, dt, amt) in enumerate(rows):
            item_dt = QTableWidgetItem(dt)
            item_dt.setData(Qt.ItemDataRole.UserRole, pid)
            self.table.setItem(r, 0, item_dt)

            val = float(amt) if amt is not None else 0.0
            item_amt = QTableWidgetItem(f"{val:,.2f}".replace(",", " "))
            item_amt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 1, item_amt)
            paid += val
            if not latest_date or dt > latest_date: latest_date = dt

        self.table.setUpdatesEnabled(True)
        db.execute("UPDATE estimates SET paid=?, payment_date=? WHERE id=?", (paid, latest_date, self.est_id))
        self.update_parents()

        debt = self.current_total - paid
        self.remainder = max(0, debt)
        self.lbl_info.setText(f"Смета: {self.current_total:,.2f} руб.   |   Оплачено: {paid:,.2f} руб.   |   Долг: {debt:,.2f} руб.".replace(",", " "))

    def add_payment(self):
        amt = self.spin_paid.value()
        if amt <= 0: return
        dt = self.date_edit.date().toString("yyyy-MM-dd")
        db.execute("INSERT INTO payments (estimate_id, amount, date) VALUES (?, ?, ?)", (self.est_id, amt, dt))
        self.spin_paid.setValue(0)
        self.load_data()

    def del_payment(self):
        curr = self.table.currentRow()
        if curr >= 0:
            pid = self.table.item(curr, 0).data(Qt.ItemDataRole.UserRole)
            db.execute("DELETE FROM payments WHERE id=?", (pid,))
            self.load_data()

class WorkSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор монтажной работы")
        self.resize(450, 150)
        self.selected_work = None
        layout = QVBoxLayout(self)
        self.combo_work = QComboBox()
        self.works = db.fetchall("""SELECT name, unit, price, purchase_price,
                                     labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs
                                     FROM materials WHERE item_type='Работа' ORDER BY name""")
        for w_name, w_unit, w_price, w_purch, labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs in self.works:
            val = float(w_price) if w_price is not None else 0.0
            p_val = float(w_purch) if w_purch is not None else 0.0
            data = (w_name, w_unit, val, p_val, labor_hours or 0.0, hourly_rate or 0.0, overhead_pct or 0.0, profit_pct or 0.0, other_costs or 0.0)
            self.combo_work.addItem(f"{w_name} ({val:,.2f} руб.)", data)
        layout.addWidget(QLabel("Выберите работу:"))
        layout.addWidget(self.combo_work)

        btn_bar = QHBoxLayout()
        btn_select = QPushButton("Добавить")
        btn_select.setProperty("type", "primary")
        btn_cancel = QPushButton("Отмена")
        btn_select.clicked.connect(self.select_work)
        btn_cancel.clicked.connect(self.reject)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_cancel)
        btn_bar.addWidget(btn_select)
        layout.addLayout(btn_bar)

    def select_work(self):
        data = self.combo_work.currentData()
        if data:
            self.selected_work = {"name": data[0], "unit": data[1], "price": data[2], "purchase_price": data[3],
                                   "labor_hours": data[4], "hourly_rate": data[5], "overhead_pct": data[6],
                                   "profit_pct": data[7], "other_costs": data[8]}
            self.accept()

class MaterialSelectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.pager=RegistryPager(self,self.load_materials)
        self.setWindowTitle("Справочник (Только материалы)")
        self.resize(850, 500)
        self.selected_material = None

        layout = QVBoxLayout(self)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск...")
        self.search_input.textChanged.connect(self.filter_materials)
        layout.addWidget(self.search_input)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Наименование", "Ед.", "Цена", "Примечание"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table_manager = SmartTableManager(self.table, main_col=0, default_widths={1: 85, 2: 130, 3: 200})
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_select = QPushButton("Выбрать")
        btn_select.setProperty("type", "primary")
        btn_select.clicked.connect(self.select_material)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_select)
        layout.addLayout(btn_layout)

        self.load_materials()
        self.table.doubleClicked.connect(self.select_material)

    def load_materials(self):
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        rows = self.pager.fetch("SELECT id, name, unit, price, note, purchase_price FROM materials WHERE item_type='Материал' AND (LOWER(name) LIKE ? OR LOWER(note) LIKE ?) ORDER BY id DESC",("%"+self.search_input.text().casefold()+"%",)*2)
        self.table.setRowCount(len(rows))
        for r, (mat_id, name, unit, price, note, purch) in enumerate(rows):
            item_name = QTableWidgetItem(name or "")
            item_name.setData(Qt.ItemDataRole.UserRole, mat_id)
            item_name.setData(Qt.ItemDataRole.UserRole + 1, float(purch or 0.0))
            self.table.setItem(r, 0, item_name)

            i_unit = QTableWidgetItem(unit or "")
            i_unit.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 1, i_unit)

            val = float(price) if price is not None else 0.0
            i_price = QTableWidgetItem(f"{val:,.2f}".replace(",", " "))
            i_price.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 2, i_price)

            self.table.setItem(r, 3, QTableWidgetItem(note or ""))
        self.table.setUpdatesEnabled(True)

    def filter_materials(self, text):
        self.load_materials()

    def select_material(self):
        curr = self.table.currentRow()
        if curr >= 0 and not self.table.isRowHidden(curr):
            price_text = self.table.item(curr, 2).text().replace(" ", "").replace(",", ".")
            price_val = float(price_text) if price_text else 0.0
            purch_val = self.table.item(curr, 0).data(Qt.ItemDataRole.UserRole + 1)
            self.selected_material = {"name": self.table.item(curr, 0).text(), "unit": self.table.item(curr, 1).text(), "price": price_val, "purchase_price": purch_val}
            self.accept()

def PaymentDialog(est_id,current_total,parent=None):
    from .payments_view import PaymentsDialog
    return PaymentsDialog('estimates',est_id,parent)
