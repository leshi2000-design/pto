"""
Вкладка "Реестр смет": дерево папок и таблица смет с поиском, фильтром по
статусу, созданием/дублированием/удалением смет (теперь с безопасными транзакциями).
"""
import os
import re
import json
import logging
from datetime import datetime

import pandas as pd

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QTableWidget, QTableWidgetItem, QInputDialog, QMessageBox,
                              QFileDialog, QDialog, QAbstractItemView, QLineEdit, QTreeWidget,
                              QTreeWidgetItem, QSplitter, QComboBox, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QAction

from .database import db
from .pagination import RegistryPager
from .widgets import SmartTableManager
from .dialogs_common import PaymentDialog
from .estimate_editor import EstimateEditorDialog


class EstimatesTree(QTreeWidget):
    estimate_dropped = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        if event.source() and isinstance(event.source(), EstimatesTable):
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.source() and isinstance(event.source(), EstimatesTable):
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        source = event.source()
        if source and isinstance(source, EstimatesTable):
            item = self.itemAt(event.position().toPoint())
            target_cat_id = None
            if item:
                target_cat_id = item.data(0, Qt.ItemDataRole.UserRole)

            row = source.currentRow()
            if row >= 0:
                est_item = source.item(row, 0)
                if est_item:
                    est_id = est_item.data(Qt.ItemDataRole.UserRole)
                    self.estimate_dropped.emit(est_id, target_cat_id)
            event.accept()
        else:
            super().dropEvent(event)

class EstimatesTable(QTableWidget):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

    def show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item: return
        row = item.row()
        self.selectRow(row)
        est_id = self.item(row, 0).data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        act_open = QAction("Открыть / Изменить", self)
        act_open.triggered.connect(self.parent_view.open_estimate)
        menu.addAction(act_open)

        act_copy = QAction("Создать копию сметы", self)
        act_copy.triggered.connect(self.parent_view.duplicate_estimate)
        menu.addAction(act_copy)

        act_pay = QAction("Внести оплату", self)
        act_pay.triggered.connect(lambda: self.parent_view.open_payment(row))
        menu.addAction(act_pay)

        menu.addSeparator()
        move_menu = menu.addMenu("Отправить в папку")
        act_none = QAction(" Без папки", self)
        act_none.triggered.connect(lambda: self.parent_view.move_estimate_to_folder(est_id, None))
        move_menu.addAction(act_none)

        roots = db.fetchall("SELECT id, name FROM estimate_folders WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            act_root = QAction(f"📁 {r_name}", self)
            act_root.triggered.connect(lambda checked, f_id=r_id: self.parent_view.move_estimate_to_folder(est_id, f_id))
            move_menu.addAction(act_root)
            subs = db.fetchall("SELECT id, name FROM estimate_folders WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                act_sub = QAction(f"   📂 {s_name}", self)
                act_sub.triggered.connect(lambda checked, f_id=s_id: self.parent_view.move_estimate_to_folder(est_id, f_id))
                move_menu.addAction(act_sub)

        menu.addSeparator()
        act_del = QAction("Удалить", self)
        act_del.triggered.connect(self.parent_view.delete_estimate)
        menu.addAction(act_del)
        menu.exec(self.viewport().mapToGlobal(pos))

class EstimatesView(QWidget):
    def __init__(self):
        super().__init__()
        self.pager=RegistryPager(self)
        layout = QVBoxLayout(self)

        actions = QHBoxLayout()
        self.btn_toggle_folders = QPushButton("Скрыть папки")
        self.btn_toggle_folders.clicked.connect(self.toggle_folders)
        actions.addWidget(self.btn_toggle_folders)

        btn_new = QPushButton("Создать смету")
        btn_new.setProperty("type", "primary")

        btn_import_field = QPushButton("Импорт отчета монтажника")
        btn_import_field.clicked.connect(self.import_field_report)

        actions.addWidget(btn_new)
        actions.addWidget(btn_import_field)
        layout.addLayout(actions)
        actions=QHBoxLayout()

        actions.addWidget(QLabel("Поиск:"))
        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("Объект, клиент, телефон...")
        self.search_inp.setMinimumWidth(180)
        self.search_inp.textChanged.connect(self.load_data)
        actions.addWidget(self.search_inp)

        actions.addWidget(QLabel("Статус:"))
        self.combo_status = QComboBox()
        self.combo_status.addItems(["📁 Все сметы", "📌 Предварительная смета", "🚀 Передано в работу", "⏳ Ожидает оплаты", "💰 Оплачено"])
        self.combo_status.currentIndexChanged.connect(self.load_data)
        actions.addWidget(self.combo_status)

        actions.addStretch()

        self.btn_cols = QPushButton("Настройка колонок ▼")
        self.cols_menu = QMenu(self)
        self.col_actions = []
        self.headers = ["Шифр / Объект", "Клиент", "Телефон", "Статусы", "Дата", "Сумма (руб)", "Оплачено", "Долг"]

        hidden_cols = []
        try: hidden_cols = json.loads(db.get_setting("estimates_hidden_cols", "[]"))
        except (ValueError, TypeError) as e: logging.warning(f"Некорректный estimates_hidden_cols: {e}")

        for i, header in enumerate(self.headers):
            act = QAction(header, self)
            act.setCheckable(True)
            act.setChecked(i not in hidden_cols)
            if i == 0: act.setEnabled(False)
            act.toggled.connect(lambda checked, idx=i: self.toggle_column(idx, not checked))
            self.cols_menu.addAction(act)
            self.col_actions.append(act)

        self.btn_cols.setMenu(self.cols_menu)
        actions.addWidget(self.btn_cols)
        layout.addLayout(actions)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.left_widget = QWidget()
        left_layout = QVBoxLayout(self.left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)

        self.tree = EstimatesTree()
        self.tree.setHeaderLabels(["Папки смет (ПКМ)"])
        self.tree.estimate_dropped.connect(self.move_estimate_to_folder)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        left_layout.addWidget(self.tree)
        self.splitter.addWidget(self.left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 0, 0, 0)

        self.table = EstimatesTable(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)

        for i in hidden_cols:
            if i != 0: self.table.setColumnHidden(i, True)

        self.table_manager = SmartTableManager(self.table, main_col=0, default_widths={1: 150, 2: 120, 3: 160, 4: 100, 5: 120, 6: 110, 7: 110})
        right_layout.addWidget(self.table)
        self.splitter.addWidget(right_widget)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        layout.addWidget(self.splitter)

        btn_new.clicked.connect(self.new_estimate)
        self.tree.itemClicked.connect(self.on_folder_selected)
        self.table.doubleClicked.connect(self.open_estimate)

        self.selected_folder_id = None
        self.load_folders()
        self.load_data()

    def show_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        act_add_root = QAction("Добавить корневую папку", self)
        act_add_root.triggered.connect(self.add_root_folder)
        menu.addAction(act_add_root)

        if item:
            folder_id = item.data(0, Qt.ItemDataRole.UserRole)
            if folder_id is not None:
                act_add_sub = QAction("Добавить подпапку", self)
                act_add_sub.triggered.connect(lambda: self.add_sub_folder(folder_id))
                menu.addAction(act_add_sub)

                act_edit = QAction("Переименовать", self)
                act_edit.triggered.connect(lambda: self.rename_folder(item, folder_id))
                menu.addAction(act_edit)

                act_del = QAction("Удалить", self)
                act_del.triggered.connect(lambda: self.delete_folder(folder_id))
                menu.addAction(act_del)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def add_root_folder(self):
        name, ok = QInputDialog.getText(self, "Новая папка", "Название:")
        if ok and name.strip():
            db.execute("INSERT INTO estimate_folders (name) VALUES (?)", (name.strip(),))
            self.load_folders()

    def add_sub_folder(self, parent_id):
        name, ok = QInputDialog.getText(self, "Новая подпапка", "Название:")
        if ok and name.strip():
            db.execute("INSERT INTO estimate_folders (name, parent_id) VALUES (?, ?)", (name.strip(), parent_id))
            self.load_folders()

    def rename_folder(self, item, folder_id):
        old_name = item.text(0).replace("📁 ", "").replace("📂 ", "").strip()
        name, ok = QInputDialog.getText(self, "Переименовать папку", "Новое название:", text=old_name)
        if ok and name.strip():
            db.execute("UPDATE estimate_folders SET name=? WHERE id=?", (name.strip(), folder_id))
            self.load_folders()

    def delete_folder(self, folder_id):
        if QMessageBox.question(self, "Удаление", "Удалить папку и все подпапки?\n(Сами сметы не будут удалены, а переместятся в 'Все сметы')") == QMessageBox.StandardButton.Yes:
            db.execute("UPDATE estimates SET folder_id=NULL WHERE folder_id=?", (folder_id,))
            subs = db.fetchall("SELECT id FROM estimate_folders WHERE parent_id=?", (folder_id,))
            for s in subs:
                db.execute("UPDATE estimates SET folder_id=NULL WHERE folder_id=?", (s[0],))
            db.execute("DELETE FROM estimate_folders WHERE id=? OR parent_id=?", (folder_id, folder_id))
            self.load_folders()
            self.load_data()

    def toggle_folders(self):
        is_visible = self.left_widget.isVisible()
        self.left_widget.setVisible(not is_visible)
        self.btn_toggle_folders.setText("Показать папки" if is_visible else "Скрыть папки")

    def move_estimate_to_folder(self, estimate_id, folder_id):
        db.execute("UPDATE estimates SET folder_id=? WHERE id=?", (folder_id, estimate_id))
        self.load_data()

    def load_folders(self):
        self.tree.clear()
        all_item = QTreeWidgetItem([" Все сметы"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self.tree.addTopLevelItem(all_item)
        roots = db.fetchall("SELECT id, name FROM estimate_folders WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            r_item = QTreeWidgetItem([f"📁 {r_name}"])
            r_item.setData(0, Qt.ItemDataRole.UserRole, r_id)
            self.tree.addTopLevelItem(r_item)
            subs = db.fetchall("SELECT id, name FROM estimate_folders WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                s_item = QTreeWidgetItem([f"   📂 {s_name}"])
                s_item.setData(0, Qt.ItemDataRole.UserRole, s_id)
                r_item.addChild(s_item)
        self.tree.expandAll()
        self.tree.setCurrentItem(all_item)

    def on_folder_selected(self, item, column):
        self.selected_folder_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.load_data()

    def toggle_column(self, col_idx, hide):
        self.table.setColumnHidden(col_idx, hide)
        hidden_cols = [i for i in range(self.table.columnCount()) if self.table.isColumnHidden(i)]
        db.set_setting("estimates_hidden_cols", json.dumps(hidden_cols))
        self.table_manager.adjust_main_column()

    def load_data(self):
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)

        curr_status_raw = self.combo_status.currentText()
        curr_status = re.sub(r'^[📁📌🚀⏳💰]\s*', '', curr_status_raw).strip()

        search_str = self.search_inp.text().strip().lower() if hasattr(self, 'search_inp') else ""

        query = "SELECT id, title, client_name, client_phone, statuses, date, total, paid FROM estimates"
        params = []
        conditions = []

        if self.selected_folder_id is not None:
            conditions.append("folder_id = ?")
            params.append(self.selected_folder_id)

        if curr_status != "Все сметы":
            conditions.append("statuses LIKE ?")
            params.append(f"%{curr_status}%")

        if search_str:
            conditions.append("(LOWER(title) LIKE ? OR LOWER(client_name) LIKE ? OR LOWER(client_phone) LIKE ?)")
            params.extend([f"%{search_str}%", f"%{search_str}%", f"%{search_str}%"])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY id DESC"

        rows = self.pager.fetch(query, tuple(params))

        self.table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            est_id, title, c_name, c_phone, statuses, date, total, paid = row
            total = total or 0.0
            paid = paid or 0.0
            debt = total - paid

            item_title = QTableWidgetItem(title or "")
            item_title.setData(Qt.ItemDataRole.UserRole, est_id)
            self.table.setItem(row_idx, 0, item_title)
            self.table.setItem(row_idx, 1, QTableWidgetItem(c_name or ""))
            self.table.setItem(row_idx, 2, QTableWidgetItem(c_phone or ""))
            self.table.setItem(row_idx, 3, QTableWidgetItem(statuses or ""))

            try:
                display_date = datetime.strptime(date, "%Y-%m-%d").strftime("%d.%m.%Y")
            except (ValueError, TypeError):
                display_date = date

            item_date = QTableWidgetItem(display_date)
            item_date.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_idx, 4, item_date)

            item_total = QTableWidgetItem(f"{total:,.2f}".replace(",", " "))
            item_total.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row_idx, 5, item_total)

            item_paid = QTableWidgetItem(f"{paid:,.2f}".replace(",", " "))
            item_paid.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_paid.setForeground(QColor("#16A34A") if paid > 0 else QColor("#94A3B8"))
            self.table.setItem(row_idx, 6, item_paid)

            item_debt = QTableWidgetItem(f"{debt:,.2f}".replace(",", " "))
            item_debt.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_debt.setForeground(QColor("#DC2626") if debt > 0 else QColor("#16A34A"))
            self.table.setItem(row_idx, 7, item_debt)

        self.table.setUpdatesEnabled(True)
        self.table_manager.adjust_main_column()

    def duplicate_estimate(self):
        curr = self.table.currentRow()
        if curr >= 0:
            est_id = self.table.item(curr, 0).data(Qt.ItemDataRole.UserRole)
            old_est = db.fetchone("SELECT title, client_name, client_phone, statuses, total, folder_id FROM estimates WHERE id=?", (est_id,))
            if not old_est: return

            new_title = f"{old_est[0]} (копия)"
            date_str = datetime.now().strftime("%Y-%m-%d")

            try:
                with db.transaction() as cur:
                    columns=[r[1] for r in db.fetchall('PRAGMA table_info(estimates)') if r[1] not in ('id','title','date','paid','payment_date')]
                    names=','.join(columns)
                    cur.execute(f"INSERT INTO estimates(title,date,paid,payment_date,{names}) SELECT ?,?,0,'',{names} FROM estimates WHERE id=?",(new_title,date_str,est_id))
                    new_id=cur.lastrowid
                    columns=[r[1] for r in db.fetchall('PRAGMA table_info(estimate_items)') if r[1] not in ('id','estimate_id')]
                    names=','.join(columns)
                    cur.execute(f"INSERT INTO estimate_items(estimate_id,{names}) SELECT ?,{names} FROM estimate_items WHERE estimate_id=?",(new_id,est_id))

                logging.info(f"Создана копия сметы ID {est_id} -> новая ID {new_id}")
                self.load_data()
                QMessageBox.information(self, "Успех", f"Копия сметы «{new_title}» успешно создана!")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось создать копию:\n{e}")

    def import_field_report(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать отчет монтажника", "", "Excel (*.xlsx *.xls)")
        if not path: return
        try:
            df = pd.read_excel(path, header=None).dropna(how='all').dropna(axis=1, how='all')

            col_name, col_unit, col_qty = None, None, None
            start_row = 0

            for r_idx, row in df.head(30).iterrows():
                f_name, f_unit, f_qty = None, None, None
                for c_idx, val in enumerate(row):
                    if pd.isna(val): continue
                    c_str = str(val).lower()
                    if any(k in c_str for k in ['наименование', 'материал', 'работа', 'позиция', 'назв']):
                        f_name = c_idx
                    elif any(k in c_str for k in ['ед', 'изм', 'единица']):
                        f_unit = c_idx
                    elif any(k in c_str for k in ['кол', 'количество', 'объем']):
                        f_qty = c_idx

                if f_name is not None and f_qty is not None:
                    col_name, col_unit, col_qty = f_name, f_unit, f_qty
                    start_row = r_idx + 1
                    break

            if col_name is None or col_qty is None:
                if len(df.columns) >= 4:
                    col_name, col_unit, col_qty = 1, 2, 3
                elif len(df.columns) >= 3:
                    col_name, col_unit, col_qty = 0, 1, 2
                else:
                    QMessageBox.warning(self, "Ошибка", "Не удалось распознать структуру таблицы. Проверьте файл.")
                    return
                start_row = 0

            base_name = os.path.splitext(os.path.basename(path))[0]
            date_str = datetime.now().strftime("%Y-%m-%d")
            catalog = db.fetchall("SELECT name, unit, price, item_type FROM materials")
            catalog_map={}
            for item in catalog:
                key=((item[0] or "").strip().casefold(),(item[1] or "").strip().casefold())
                catalog_map.setdefault(key,[]).append(item)

            try:
                with db.transaction() as cur:
                    def_ov = float(db.get_setting('def_overhead_pct', '15.0'))
                    def_pr = float(db.get_setting('def_profit_pct', '10.0'))
                    def_vat = float(db.get_setting('def_vat_pct', '20.0'))
                    def_soc = float(db.get_setting('def_social_pct', '34.6'))

                    cur.execute("""INSERT INTO estimates 
                                        (title, date, total, paid, statuses, overhead_pct, profit_pct, vat_pct, social_pct, folder_id) 
                                        VALUES (?, ?, 0.0, 0.0, 'Передано в работу', ?, ?, ?, ?, ?)""",
                                     (f"Отчет: {base_name}", date_str, def_ov, def_pr, def_vat, def_soc, self.selected_folder_id))
                    est_id = cur.lastrowid

                    added_count = 0
                    total_sum = 0.0

                    for r_idx in range(start_row, len(df)):
                        row = df.iloc[r_idx]

                        if col_name >= len(row): continue
                        raw_name = row[col_name]
                        if pd.isna(raw_name) or not str(raw_name).strip(): continue
                        name_str = str(raw_name).strip()

                        if "итого" in name_str.lower() or "сумма" in name_str.lower(): continue

                        if col_qty >= len(row): continue
                        raw_qty = row[col_qty]
                        if pd.isna(raw_qty): continue

                        qty_str = str(raw_qty).replace(',', '.').replace(' ', '')
                        match = re.search(r'\d+(?:\.\d+)?', qty_str)
                        if not match: continue
                        qty = float(match.group(0))
                        if qty <= 0: continue

                        unit_str = "шт"
                        if col_unit is not None and col_unit < len(row):
                            raw_unit = row[col_unit]
                            if not pd.isna(raw_unit):
                                unit_str = str(raw_unit).strip()

                        candidates=catalog_map.get((name_str.casefold(),unit_str.casefold()),[])
                        best_match=candidates[0] if len(candidates)==1 else None
                        if best_match:
                            m_name, m_unit, m_price, m_type = best_match
                            price = float(m_price) if m_price else 0.0
                            sm = qty * price
                            total_sum += sm
                            cur.execute("INSERT INTO estimate_items (estimate_id, item_type, name, unit, quantity, price, sum) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                       (est_id, m_type, m_name, m_unit, qty, price, sm))
                        else:
                            cur.execute("INSERT INTO estimate_items (estimate_id, item_type, name, unit, quantity, price, sum) VALUES (?, 'Материал', ?, ?, ?, 0.0, 0.0)",
                                       (est_id, name_str, unit_str, qty))
                        added_count += 1

                    cur.execute("UPDATE estimates SET total=? WHERE id=?", (total_sum, est_id))

                    if added_count == 0:
                        cur.execute("DELETE FROM estimates WHERE id=?", (est_id,))

                if added_count == 0:
                    QMessageBox.warning(self, "Пусто", "Файл прочитан, но не найдено ни одной позиции с количеством. Убедитесь, что в файле есть колонка с числами.")
                else:
                    logging.info(f"Импортирован отчет: смета ID {est_id}, позиций: {added_count}")
                    QMessageBox.information(self, "Успех", f"Отчет обработан.\nДобавлено позиций: {added_count}\nЦены подставлены только для точных совпадений названия и единицы. Проверьте нулевые цены.")
                    self.load_data()
                    editor = EstimateEditorDialog(est_id, f"Отчет: {base_name}", self)
                    editor.exec()

                self.load_data()
            except Exception as e:
                raise e
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", f"Не удалось прочитать файл отчета:\n{e}\n\nВозможно файл открыт в Excel.")

    def new_estimate(self):
        name, ok = QInputDialog.getText(self, "Новая смета", "Шифр или наименование объекта:")
        if ok and name.strip():
            date_str = datetime.now().strftime("%Y-%m-%d")
            def_ov = float(db.get_setting('def_overhead_pct', '15.0'))
            def_pr = float(db.get_setting('def_profit_pct', '10.0'))
            def_vat = float(db.get_setting('def_vat_pct', '20.0'))
            def_soc = float(db.get_setting('def_social_pct', '34.6'))

            cur = db.execute("""INSERT INTO estimates 
                                (title, date, total, paid, statuses, overhead_pct, profit_pct, vat_pct, social_pct, folder_id) 
                                VALUES (?, ?, 0.0, 0.0, 'Предварительная смета', ?, ?, ?, ?, ?)""",
                             (name.strip(), date_str, def_ov, def_pr, def_vat, def_soc, self.selected_folder_id))
            est_id = cur.lastrowid
            logging.info(f"Создана смета: {name.strip()} (ID {est_id})")
            editor = EstimateEditorDialog(est_id, name.strip(), self)
            editor.exec()
            self.load_data()

    def open_estimate(self):
        curr = self.table.currentRow()
        if curr >= 0:
            est_id = self.table.item(curr, 0).data(Qt.ItemDataRole.UserRole)
            title = self.table.item(curr, 0).text()
            editor = EstimateEditorDialog(est_id, title, self)
            editor.exec()
            self.load_data()

    def open_payment(self, row):
        est_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        total_str = self.table.item(row, 5).text()
        total = float(total_str.replace(" ", "").replace(",", "."))
        dlg = PaymentDialog(est_id, total, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.load_data()

    def delete_estimate(self):
        curr = self.table.currentRow()
        if curr >= 0:
            est_id = self.table.item(curr, 0).data(Qt.ItemDataRole.UserRole)
            if QMessageBox.question(self, "Удаление", "Удалить смету и все позиции?\nБлагодаря защите БД, связанные с ней элементы будут аккуратно удалены.") == QMessageBox.StandardButton.Yes:
                # Транзакция для безопасного удаления, хотя ON DELETE CASCADE сделает основную работу
                try:
                    with db.transaction() as cur:
                        cur.execute("DELETE FROM estimates WHERE id=?", (est_id,))
                    logging.info(f"Удалена смета ID {est_id}")
                    self.load_data()
                except Exception as e:
                    QMessageBox.critical(self, "Ошибка удаления", f"Не удалось удалить смету:\n{e}")
