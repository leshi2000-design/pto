"""
Вкладка "ГСВ" (внутреннее газоснабжение): таблица всех созданных договоров с поиском.
Позволяет создавать договоры без сметы и переходить в их карточки.
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QTableWidget, QTableWidgetItem, QAbstractItemView, QLineEdit, QMenu, QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from .database import db
from .pagination import RegistryPager
from .widgets import SmartTableManager
from .contract_card import ContractCardDialog

class ContractsRegistryView(QWidget):
    def __init__(self):
        super().__init__()
        self.pager=RegistryPager(self)
        layout = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        btn_new = QPushButton("Создать договор")
        btn_new.setProperty("type", "primary")
        btn_new.clicked.connect(self.new_contract)
        top_bar.addWidget(btn_new)
        payments=QPushButton("Оплаты");payments.clicked.connect(self.open_payments);top_bar.addWidget(payments)
        tags=QPushButton("Теги для шаблонов");tags.clicked.connect(self.show_tag_reference);top_bar.addWidget(tags)
        top_bar.addSpacing(20)

        top_bar.addWidget(QLabel("Поиск:"))
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("№, объект, клиент...")
        self.search_inp.setFixedWidth(250)
        self.search_inp.textChanged.connect(self.load_data)
        top_bar.addWidget(self.search_inp)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["№ Договора", "Дата", "Объект / Адрес", "Сумма (руб)", "Привязанная смета"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self.open_contract)

        self.table_manager = SmartTableManager(self.table, main_col=2, default_widths={0: 120, 1: 100, 3: 130, 4: 250})
        layout.addWidget(self.table)

    def open_payments(self):
        r=self.table.currentRow()
        if r>=0:
            from .payments_view import PaymentsDialog
            PaymentsDialog('contracts',self.table.item(r,0).data(Qt.ItemDataRole.UserRole),self).exec();self.load_data()
    def show_tag_reference(self):
        from .executive_workspace import TagReferenceDialog
        TagReferenceDialog('contracts',self).exec()
    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        self.table.selectRow(item.row())

        menu = QMenu(self)
        act_open = QAction("Открыть карточку", self)
        act_open.triggered.connect(self.open_contract)
        menu.addAction(act_open)

        menu.addSeparator()
        act_del = QAction("Удалить договор", self)
        act_del.triggered.connect(self.delete_contract)
        menu.addAction(act_del)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def load_data(self):
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        search_str = self.search_inp.text().strip().lower()

        query = """
            SELECT c.id, c.contract_number, c.contract_date, c.object_name, c.contract_amount, e.title 
            FROM contracts c
            LEFT JOIN estimates e ON c.estimate_id = e.id
        """
        params = []
        if search_str:
            query += " WHERE LOWER(c.contract_number) LIKE ? OR LOWER(c.object_name) LIKE ? OR LOWER(e.title) LIKE ?"
            params.extend([f"%{search_str}%", f"%{search_str}%", f"%{search_str}%"])
        query += " ORDER BY c.id DESC"

        rows = self.pager.fetch(query, tuple(params))
        self.table.setRowCount(len(rows))

        for r_idx, (c_id, num, c_date, obj_name, amt, est_title) in enumerate(rows):
            i_num = QTableWidgetItem(num or "Б/Н")
            i_num.setData(Qt.ItemDataRole.UserRole, c_id)
            self.table.setItem(r_idx, 0, i_num)

            i_date = QTableWidgetItem(c_date or "")
            i_date.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r_idx, 1, i_date)

            self.table.setItem(r_idx, 2, QTableWidgetItem(obj_name or ""))

            val = float(amt) if amt else 0.0
            i_amt = QTableWidgetItem(f"{val:,.2f}".replace(",", " "))
            i_amt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r_idx, 3, i_amt)

            self.table.setItem(r_idx, 4, QTableWidgetItem(est_title or "— нет сметы —"))

        self.table.setUpdatesEnabled(True)
        self.table_manager.adjust_main_column()

    def new_contract(self):
        dlg = ContractCardDialog(parent=self)
        dlg.exec()
        self.load_data()

    def open_contract(self):
        curr = self.table.currentRow()
        if curr >= 0:
            c_id = self.table.item(curr, 0).data(Qt.ItemDataRole.UserRole)
            dlg = ContractCardDialog(contract_id=c_id, parent=self)
            dlg.exec()
            self.load_data()

    def delete_contract(self):
        curr = self.table.currentRow()
        if curr >= 0:
            c_id = self.table.item(curr, 0).data(Qt.ItemDataRole.UserRole)
            if QMessageBox.question(self, "Удаление", "Удалить выбранный договор? (Связанная смета удалена не будет)") == QMessageBox.StandardButton.Yes:
                db.execute("DELETE FROM contract_equipment WHERE contract_id=?", (c_id,))
                db.execute("DELETE FROM contracts WHERE id=?", (c_id,))
                self.load_data()
