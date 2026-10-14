"""
Вкладка "ГСВ" (внутреннее газоснабжение): таблица всех созданных договоров с поиском.
Позволяет создавать договоры без сметы и переходить в их карточки.
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QHeaderView,
                              QTableWidget, QTableWidgetItem, QAbstractItemView, QLineEdit, QMenu, QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from .database import db
from .pagination import RegistryPager
from .widgets import SmartTableManager
from .contract_card import ContractCardDialog

from .registry_tools import RegistryTools, search_clause


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
        acts=QPushButton("Ведомость актов…");acts.setToolTip("Подписанные акты за календарный месяц для бухгалтерии");acts.clicked.connect(lambda:__import__("smetagaz.acts_statement_view",fromlist=["x"]).ActsStatementDialog("contracts",self).exec());top_bar.addWidget(acts)
        st_btn=QPushButton("Статусы…");st_btn.setToolTip("Редактировать свои статусы договоров Монтаж ГСВ");st_btn.clicked.connect(self.edit_statuses);top_bar.addWidget(st_btn)
        imp_btn=QPushButton("Импорт из Excel…");imp_btn.setToolTip("Загрузить договоры монтажа ГСВ из таблицы Excel");imp_btn.clicked.connect(self.import_excel);top_bar.addWidget(imp_btn)
        tags=QPushButton("Теги для шаблонов");tags.clicked.connect(self.show_tag_reference);top_bar.addWidget(tags)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        search_bar = QHBoxLayout()          # вторая строка: поиск, сохранённые выборки и настройка колонок
        search_bar.addWidget(QLabel("Поиск:"))
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("№, объект, клиент, телефон, адрес, статус, примечание…")
        self.search_inp.textChanged.connect(self.load_data)
        search_bar.addWidget(self.search_inp, 1)
        layout.addLayout(search_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["№ договора", "Дата заключения", "Объект / Адрес", "Клиент", "Стоимость, BYN", "Статусы", "Примечание"])
        self.table.verticalHeader().setVisible(False)          # порядковые номера строк не нужны: договор определяет его № договора
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self.open_contract)

        self.tools = RegistryTools(db, 'contracts', self.table, self.search_inp, search_bar)
        self.table_manager = SmartTableManager(self.table, main_col=2, default_widths={0: 120, 1: 100, 3: 200, 4: 130})
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
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
        search_str = self.search_inp.text().strip()

        query = """
            SELECT c.id, c.contract_number, c.contract_date, c.object_name, c.object_address, coalesce(nullif(c.client_name,''),c.party_name,''),
                   c.contract_amount, coalesce(c.statuses_text,''), coalesce(c.notes,'')
            FROM contracts c
            LEFT JOIN estimates e ON c.estimate_id = e.id
        """
        params = []
        if search_str:
            clause, found = search_clause(search_str, ['c.contract_number', 'c.object_name', 'e.title', 'c.client_name', 'c.party_name', 'c.object_address', 'c.client_address', 'c.designer_code',
                                                       'c.statuses_text', 'c.notes'], ['c.client_phone'])
            query += " WHERE " + clause
            params.extend(found)
        query += " ORDER BY c.id DESC"

        rows = self.pager.fetch(query, tuple(params))
        self.table.setRowCount(len(rows))

        for r_idx, (c_id, num, c_date, obj_name, address, client, amt, statuses, notes) in enumerate(rows):
            i_num = QTableWidgetItem(num or "Б/Н")
            i_num.setData(Qt.ItemDataRole.UserRole, c_id)
            self.table.setItem(r_idx, 0, i_num)
            i_date = QTableWidgetItem(c_date or "")
            i_date.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r_idx, 1, i_date)
            place = obj_name if not address or address == obj_name else (f"{obj_name} — {address}" if obj_name else address)
            self.table.setItem(r_idx, 2, QTableWidgetItem(place or ""))
            self.table.setItem(r_idx, 3, QTableWidgetItem(client or ""))
            val = float(amt) if amt else 0.0
            i_amt = QTableWidgetItem(f"{val:,.2f}".replace(",", " "))
            i_amt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r_idx, 4, i_amt)
            self.table.setItem(r_idx, 5, QTableWidgetItem(statuses))
            note = " ".join(str(notes).split())
            i_note = QTableWidgetItem(note[:120] + ("…" if len(note) > 120 else ""))
            i_note.setToolTip(str(notes))
            self.table.setItem(r_idx, 6, i_note)

        self.table.setUpdatesEnabled(True)
        self.table_manager.adjust_main_column()
        self.fit_columns()

    CAPS = {0: 130, 1: 170, 2: 340, 3: 190, 4: 150, 5: 240}

    def fit_columns(self):
        """Колонки по содержимому, но с пределом ширины, чтобы вся таблица помещалась в окно; последняя («Примечание») занимает остаток."""
        header = self.table.horizontalHeader()
        self.table.resizeColumnsToContents()
        for col in range(self.table.columnCount()):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            width = self.table.columnWidth(col) + 12
            self.table.setColumnWidth(col, max(70, min(self.CAPS.get(col, 400), width)))
        header.setStretchLastSection(True)

    def new_contract(self):
        dlg = ContractCardDialog(parent=self)
        dlg.exec()
        self.load_data()

    def edit_statuses(self):
        from .gsvm_statuses_ui import StatusEditorDialog
        StatusEditorDialog(self).exec()
        self.load_data()

    def import_excel(self):
        from .gsvm_import_view import ImportGsvmDialog
        ImportGsvmDialog(self).exec()
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
