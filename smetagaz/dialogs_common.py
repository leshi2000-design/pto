"""
Диалоги общего назначения, используемые в справочнике и в редакторе смет.
"""
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QTableWidget, QTableWidgetItem, QMessageBox, QDialog,
                              QAbstractItemView, QLineEdit, QComboBox, QDoubleSpinBox,
                              QDateEdit, QGridLayout, QGroupBox)
from PyQt6.QtCore import Qt, QDate

from .date_widgets import DateEdit
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
        self.date_edit = DateEdit()
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

class CatalogPickerDialog(QDialog):
    """Выбор материала или работы по дереву справочника: слева папки (разделы справочника), справа позиции выбранной папки (с вложенными).
    Поиск ищет по всему справочнику выбранного вида."""
    ITEM_TYPE = 'Материал'
    TITLE = 'Справочник · материалы'

    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem, QSplitter, QHeaderView
        self.setWindowTitle(self.TITLE)
        self.resize(1050, 600)
        self.selected = None
        layout = QVBoxLayout(self)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Поиск по всему справочнику…')
        self.search_input.textChanged.connect(self.load_items)
        layout.addWidget(self.search_input)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Разделы справочника'])
        self.tree.itemSelectionChanged.connect(self.load_items)
        split.addWidget(self.tree)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Наименование', 'Ед.', 'Цена', 'Примечание'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 110)
        self.table.setColumnWidth(3, 200)
        split.addWidget(self.table)
        split.setSizes([300, 750])
        layout.addWidget(split, 1)
        bar = QHBoxLayout()
        self.counter = QLabel('')
        bar.addWidget(self.counter, 1)
        cancel = QPushButton('Отмена')
        cancel.clicked.connect(self.reject)
        pick = QPushButton('Выбрать')
        pick.setProperty('type', 'primary')
        pick.clicked.connect(self.pick)
        bar.addWidget(cancel)
        bar.addWidget(pick)
        layout.addLayout(bar)
        self.table.doubleClicked.connect(self.pick)
        self.build_tree()
        self.load_items()

    # --- дерево
    def build_tree(self):
        from PyQt6.QtWidgets import QTreeWidgetItem
        cats = db.fetchall('SELECT id,name,parent_id FROM categories ORDER BY name COLLATE NOCASE')
        counts = dict(db.fetchall('SELECT coalesce(category_id,0),count(*) FROM materials WHERE item_type=? GROUP BY coalesce(category_id,0)', (self.ITEM_TYPE,)))
        children = {}
        for cid, name, parent in cats:
            children.setdefault(parent, []).append((cid, name))

        def subtree_ids(cid):
            ids = [cid]
            for child, _n in children.get(cid, []):
                ids += subtree_ids(child)
            return ids
        self.tree.clear()
        total = sum(counts.values())
        root = QTreeWidgetItem([f'Весь справочник ({total})'])
        root.setData(0, Qt.ItemDataRole.UserRole, 'all')
        self.tree.addTopLevelItem(root)

        def add(parent_item, cid, name):
            ids = subtree_ids(cid)
            n = sum(counts.get(i, 0) for i in ids)
            if not n:
                return
            node = QTreeWidgetItem([f'{name} ({n})'])
            node.setData(0, Qt.ItemDataRole.UserRole, ids)
            parent_item.addChild(node)
            for child, cname in children.get(cid, []):
                add(node, child, cname)
        known = {c[0] for c in cats}
        for cid, name in children.get(None, []):
            add(root, cid, name)
        for parent, items in children.items():           # папки, чей родитель удалён, показываем наверху
            if parent is not None and parent not in known:
                for cid, name in items:
                    add(root, cid, name)
        if counts.get(0):
            node = QTreeWidgetItem([f'Без раздела ({counts[0]})'])
            node.setData(0, Qt.ItemDataRole.UserRole, 'none')
            root.addChild(node)
        root.setExpanded(True)
        self.tree.setCurrentItem(root)

    # --- позиции
    def columns(self):
        return 'id, name, unit, price, note, purchase_price'

    def load_items(self, *_):
        text = self.search_input.text().strip().casefold()
        where, params = ['item_type=?'], [self.ITEM_TYPE]
        node = self.tree.currentItem()
        scope = node.data(0, Qt.ItemDataRole.UserRole) if node else 'all'
        if not text:
            if scope == 'none':
                where.append('category_id IS NULL')
            elif isinstance(scope, list):
                where.append(f"category_id IN ({','.join('?' for _ in scope)})")
                params += scope
        else:
            where.append("(LOWER(name) LIKE ? OR LOWER(coalesce(note,'')) LIKE ?)")
            params += [f'%{text}%'] * 2
        rows = db.fetchall(f"SELECT {self.columns()} FROM materials WHERE {' AND '.join(where)} ORDER BY name COLLATE NOCASE, id LIMIT 1500", tuple(params))
        self.rows = rows
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            name, unit, price, note = row[1], row[2], row[3], row[4]
            item = QTableWidgetItem(name or '')
            item.setData(Qt.ItemDataRole.UserRole, row[0])
            self.table.setItem(r, 0, item)
            u = QTableWidgetItem(unit or '')
            u.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 1, u)
            p = QTableWidgetItem(f'{float(price or 0):,.2f}'.replace(',', ' '))
            p.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 2, p)
            self.table.setItem(r, 3, QTableWidgetItem(note or ''))
        self.table.setUpdatesEnabled(True)
        self.counter.setText(f'Позиций: {len(rows)}' + (' (показаны первые 1500)' if len(rows) >= 1500 else ''))

    def build_selection(self, row):
        return {'id': row[0], 'name': row[1], 'unit': row[2] or '', 'price': float(row[3] or 0), 'purchase_price': float(row[5] or 0)}

    def pick(self, *_):
        r = self.table.currentRow()
        if 0 <= r < len(self.rows):
            self.selected = self.build_selection(self.rows[r])
            self.finish()
            self.accept()

    def finish(self):
        pass


class WorkSelectionDialog(CatalogPickerDialog):
    ITEM_TYPE = 'Работа'
    TITLE = 'Справочник · работы'

    def __init__(self, parent=None):
        self.selected_work = None
        super().__init__(parent)

    def columns(self):
        return 'id, name, unit, price, note, purchase_price, labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs'

    def build_selection(self, row):
        base = super().build_selection(row)
        base.update(labor_hours=row[6] or 0.0, hourly_rate=row[7] or 0.0, overhead_pct=row[8] or 0.0, profit_pct=row[9] or 0.0, other_costs=row[10] or 0.0)
        return base

    def finish(self):
        self.selected_work = self.selected


class MaterialSelectionDialog(CatalogPickerDialog):
    ITEM_TYPE = 'Материал'
    TITLE = 'Справочник · материалы'

    def __init__(self, parent=None):
        self.selected_material = None
        super().__init__(parent)

    def finish(self):
        self.selected_material = self.selected


def PaymentDialog(est_id,current_total,parent=None):
    from .payments_view import PaymentsDialog
    return PaymentsDialog('estimates',est_id,parent)
