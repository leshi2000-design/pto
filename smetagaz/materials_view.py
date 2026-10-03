"""
Вкладка "Справочник": дерево разделов/подразделов и таблица материалов и работ.
Поддерживает drag&drop материалов в разделы, парсинг цен с сайтов, импорт из
Excel и удаление дубликатов.
"""
import pandas as pd

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QTableWidget, QTableWidgetItem, QInputDialog, QMessageBox,
                              QFileDialog, QDialog, QAbstractItemView, QTreeWidget,
                              QTreeWidgetItem, QSplitter, QMenu)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction

from .database import db
from .pagination import RegistryPager
from .widgets import SmartTableManager
from .material_card import MaterialCardDialog
from .scraper import WebScraperDialog


class CategoriesTree(QTreeWidget):
    material_dropped = pyqtSignal(list, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        if event.source() and isinstance(event.source(), MaterialsTable):
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.source() and isinstance(event.source(), MaterialsTable):
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        source = event.source()
        if source and isinstance(source, MaterialsTable):
            item = self.itemAt(event.position().toPoint())
            target_cat_id = None
            if item:
                target_cat_id = item.data(0, Qt.ItemDataRole.UserRole)

            selected_rows = set(i.row() for i in source.selectedItems())
            mat_ids = [source.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in selected_rows]

            if mat_ids:
                self.material_dropped.emit(mat_ids, target_cat_id)
            event.accept()
        else:
            super().dropEvent(event)

class MaterialsTable(QTableWidget):
    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setAlternatingRowColors(True)

    def show_context_menu(self, pos):
        item = self.itemAt(pos)
        if not item: return
        row = item.row()

        if not self.item(row, 0).isSelected():
            self.clearSelection()
            self.selectRow(row)

        selected_rows = set(i.row() for i in self.selectedItems())
        mat_ids = [self.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in selected_rows]

        menu = QMenu(self)

        if len(selected_rows) == 1:
            act_edit = QAction("Изменить", self)
            act_edit.triggered.connect(self.parent_view.open_material_card)
            menu.addAction(act_edit)

        act_del = QAction("Удалить", self)
        act_del.triggered.connect(self.parent_view.del_material)
        menu.addAction(act_del)

        menu.addSeparator()
        move_menu = menu.addMenu("Отправить в раздел")
        act_none = QAction(" Без раздела", self)
        act_none.triggered.connect(lambda: self.parent_view.move_materials_to_cat(mat_ids, None))
        move_menu.addAction(act_none)

        roots = db.fetchall("SELECT id, name FROM categories WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            act_root = QAction(f"📁 {r_name}", self)
            act_root.triggered.connect(lambda checked, cat_id=r_id, ids=mat_ids: self.parent_view.move_materials_to_cat(ids, cat_id))
            move_menu.addAction(act_root)
            subs = db.fetchall("SELECT id, name FROM categories WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                act_sub = QAction(f"   📂 {s_name}", self)
                act_sub.triggered.connect(lambda checked, cat_id=s_id, ids=mat_ids: self.parent_view.move_materials_to_cat(ids, cat_id))
                move_menu.addAction(act_sub)
        menu.exec(self.viewport().mapToGlobal(pos))

class MaterialsView(QWidget):
    def __init__(self):
        super().__init__()
        self.pager=RegistryPager(self)
        main_layout = QVBoxLayout(self)
        actions = QHBoxLayout()

        self.btn_toggle_cat = QPushButton("Скрыть разделы")
        self.btn_toggle_cat.clicked.connect(self.toggle_categories)
        actions.addWidget(self.btn_toggle_cat)

        self.btn_open_card = QPushButton("Карточка")
        self.btn_open_card.setProperty("type", "primary")
        self.btn_add = QPushButton("Добавить позицию")
        self.btn_parse = QPushButton("Спарсить с сайта")
        self.btn_import_excel = QPushButton("Импорт Excel")

        self.btn_remove_dupes = QPushButton("Удалить дубликаты")
        self.btn_remove_dupes.clicked.connect(self.remove_duplicates)

        self.btn_del = QPushButton("Удалить выделенное")
        self.btn_del.setProperty("type", "danger")

        actions.addWidget(self.btn_open_card)
        actions.addWidget(self.btn_add)
        actions.addWidget(self.btn_parse)
        actions.addWidget(self.btn_import_excel)
        actions.addWidget(self.btn_remove_dupes)
        actions.addWidget(self.btn_del)
        actions.addStretch()
        main_layout.addLayout(actions)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.left_widget = QWidget()
        left_layout = QVBoxLayout(self.left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)

        self.tree = CategoriesTree()
        self.tree.setHeaderLabels(["Разделы (ПКМ для управления)"])
        self.tree.material_dropped.connect(self.move_materials_to_cat)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        left_layout.addWidget(self.tree)
        self.splitter.addWidget(self.left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 0, 0, 0)
        self.table = MaterialsTable(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Наименование", "Тип", "Ед.", "Цена (руб)", "Примечание", "URL"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_manager = SmartTableManager(self.table, main_col=0, default_widths={1: 80, 2: 70, 3: 100, 4: 150, 5: 120})
        right_layout.addWidget(self.table)
        self.splitter.addWidget(right_widget)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        main_layout.addWidget(self.splitter)

        self.btn_open_card.clicked.connect(self.open_material_card)
        self.btn_add.clicked.connect(self.add_material)
        self.btn_parse.clicked.connect(self.open_scraper)
        self.btn_import_excel.clicked.connect(self.import_materials_excel)
        self.btn_del.clicked.connect(self.del_material)

        self.tree.itemClicked.connect(self.on_category_selected)
        self.table.doubleClicked.connect(self.open_material_card)

        self.selected_category_id = None
        self.load_categories()
        self.load_data()

    def remove_duplicates(self):
        reply = QMessageBox.question(self, "Удаление дубликатов",
                                     "Будут удалены все материалы с одинаковым названием, типом, ед. изм. и ценой.\nОстанется только по одному экземпляру каждой позиции.\n\nПродолжить?")
        if reply == QMessageBox.StandardButton.Yes:
            try:
                res_before = db.fetchone("SELECT COUNT(*) FROM materials")
                count_before = res_before[0]

                db.execute("""
                    DELETE FROM materials 
                    WHERE id NOT IN (
                        SELECT MIN(id) 
                        FROM materials 
                        GROUP BY name, item_type, unit, price
                    )
                """)

                res_after = db.fetchone("SELECT COUNT(*) FROM materials")
                count_after = res_after[0]

                deleted = count_before - count_after
                QMessageBox.information(self, "Успех", f"Операция завершена.\nУдалено дубликатов: {deleted}")
                self.load_data()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Произошла ошибка при очистке:\n{e}")

    def show_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu(self)

        act_add_root = QAction("Добавить корневой раздел", self)
        act_add_root.triggered.connect(self.add_root_category)
        menu.addAction(act_add_root)

        if item:
            cat_id = item.data(0, Qt.ItemDataRole.UserRole)
            if cat_id is not None:
                act_add_sub = QAction("Добавить подраздел", self)
                act_add_sub.triggered.connect(lambda: self.add_sub_category(cat_id))
                menu.addAction(act_add_sub)

                act_edit = QAction("Переименовать", self)
                act_edit.triggered.connect(lambda: self.rename_category(item, cat_id))
                menu.addAction(act_edit)

                act_del = QAction("Удалить", self)
                act_del.triggered.connect(lambda: self.delete_category(cat_id))
                menu.addAction(act_del)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def add_root_category(self):
        name, ok = QInputDialog.getText(self, "Новый корневой раздел", "Название:")
        if ok and name.strip():
            db.execute("INSERT INTO categories (name) VALUES (?)", (name.strip(),))
            self.load_categories()

    def add_sub_category(self, parent_id):
        name, ok = QInputDialog.getText(self, "Новый подраздел", "Название:")
        if ok and name.strip():
            db.execute("INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name.strip(), parent_id))
            self.load_categories()

    def rename_category(self, item, cat_id):
        old_name = item.text(0).replace("📁 ", "").replace("📂 ", "").strip()
        name, ok = QInputDialog.getText(self, "Переименовать раздел", "Новое название:", text=old_name)
        if ok and name.strip():
            db.execute("UPDATE categories SET name=? WHERE id=?", (name.strip(), cat_id))
            self.load_categories()

    def delete_category(self, cat_id):
        if QMessageBox.question(self, "Удаление", "Удалить раздел и все его подразделы?\n(Материалы внутри переместятся в 'Без раздела')") == QMessageBox.StandardButton.Yes:
            db.execute("UPDATE materials SET category_id=NULL WHERE category_id=?", (cat_id,))
            subs = db.fetchall("SELECT id FROM categories WHERE parent_id=?", (cat_id,))
            for s in subs:
                db.execute("UPDATE materials SET category_id=NULL WHERE category_id=?", (s[0],))
            db.execute("DELETE FROM categories WHERE id=? OR parent_id=?", (cat_id, cat_id))
            self.load_categories()
            self.load_data()

    def toggle_categories(self):
        is_visible = self.left_widget.isVisible()
        self.left_widget.setVisible(not is_visible)
        self.btn_toggle_cat.setText("Показать разделы" if is_visible else "Скрыть разделы")

    def move_materials_to_cat(self, material_ids, category_id):
        if not material_ids: return
        placeholders = ",".join("?" * len(material_ids))
        params = [category_id] + material_ids
        db.execute(f"UPDATE materials SET category_id=? WHERE id IN ({placeholders})", tuple(params))
        self.load_data()

    def load_categories(self):
        self.tree.clear()
        all_item = QTreeWidgetItem([" Все материалы"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self.tree.addTopLevelItem(all_item)
        roots = db.fetchall("SELECT id, name FROM categories WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            r_item = QTreeWidgetItem([f"📁 {r_name}"])
            r_item.setData(0, Qt.ItemDataRole.UserRole, r_id)
            self.tree.addTopLevelItem(r_item)
            subs = db.fetchall("SELECT id, name FROM categories WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                s_item = QTreeWidgetItem([f"   📂 {s_name}"])
                s_item.setData(0, Qt.ItemDataRole.UserRole, s_id)
                r_item.addChild(s_item)
        self.tree.expandAll()
        self.tree.setCurrentItem(all_item)

    def on_category_selected(self, item, column):
        self.selected_category_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.load_data()

    def load_data(self):
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        if self.selected_category_id is None:
            rows = self.pager.fetch("SELECT id, name, item_type, unit, price, note, url FROM materials ORDER BY id DESC")
        else:
            rows = self.pager.fetch("SELECT id, name, item_type, unit, price, note, url FROM materials WHERE category_id=? ORDER BY id DESC", (self.selected_category_id,))

        self.table.setRowCount(len(rows))
        for r, (mat_id, name, itype, unit, price, note, url) in enumerate(rows):
            item_name = QTableWidgetItem(name or "")
            item_name.setData(Qt.ItemDataRole.UserRole, mat_id)
            self.table.setItem(r, 0, item_name)

            i_type = QTableWidgetItem(itype or "Материал")
            self.table.setItem(r, 1, i_type)

            i_u = QTableWidgetItem(unit or "")
            i_u.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 2, i_u)

            p_val = float(price) if price is not None else 0.0
            i_prc = QTableWidgetItem(f"{p_val:,.2f}".replace(",", " "))
            i_prc.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 3, i_prc)

            self.table.setItem(r, 4, QTableWidgetItem(note or ""))
            self.table.setItem(r, 5, QTableWidgetItem(url or ""))
        self.table.setUpdatesEnabled(True)
        self.table_manager.adjust_main_column()

    def open_material_card(self):
        selected_rows = set(item.row() for item in self.table.selectedItems())
        if not selected_rows: return

        row = list(selected_rows)[0]
        cell = self.table.item(row, 0)
        if cell:
            mat_id = cell.data(Qt.ItemDataRole.UserRole)
            dlg = MaterialCardDialog(mat_id, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                self.load_data()

    def add_material(self):
        cat_id = self.selected_category_id
        cur = db.execute("INSERT INTO materials (category_id, name, unit, price, item_type) VALUES (?, 'Новая позиция', 'шт', 0.0, 'Материал')", (cat_id,))
        dlg = MaterialCardDialog(cur.lastrowid, self)
        dlg.exec()
        self.load_data()

    def open_scraper(self):
        dlg = WebScraperDialog(current_cat_id=self.selected_category_id, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.parsed_data:
            d = dlg.parsed_data
            db.execute("INSERT INTO materials (category_id, name, unit, price, url, note, item_type) VALUES (?, ?, ?, ?, ?, ?, 'Материал')",
                       (d["category_id"], d["name"], d["unit"], d["price"], d["url"], d["note"]))
            self.load_data()

    def import_materials_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт из Excel", "", "Excel (*.xlsx *.xls)")
        if not path: return
        try:
            df = pd.read_excel(path)
            batch = []
            for _, row in df.iterrows():
                if pd.isna(row.iloc[0]): continue
                name = str(row.iloc[0]).strip()
                unit = str(row.iloc[1]).strip() if len(row) > 1 and not pd.isna(row.iloc[1]) else "шт"
                try: price = float(row.iloc[2]) if len(row) > 2 and not pd.isna(row.iloc[2]) else 0.0
                except ValueError: price = 0.0
                note = str(row.iloc[3]).strip() if len(row) > 3 and not pd.isna(row.iloc[3]) else ""
                url = str(row.iloc[4]).strip() if len(row) > 4 and not pd.isna(row.iloc[4]) else ""
                batch.append((self.selected_category_id, name, unit, price, note, url))
            db.executemany("INSERT INTO materials (category_id, name, unit, price, note, url, item_type) VALUES (?, ?, ?, ?, ?, ?, 'Материал')", batch)
            self.load_data()
            QMessageBox.information(self, "Успех", f"Импортировано {len(batch)} позиций.")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось прочитать Excel:\n{e}")

    def del_material(self):
        selected_rows = set(item.row() for item in self.table.selectedItems())
        if not selected_rows: return

        if QMessageBox.question(self, "Удаление", f"Удалить выбранные позиции ({len(selected_rows)} шт.)?") == QMessageBox.StandardButton.Yes:
            ids = []
            for row in selected_rows:
                cell = self.table.item(row, 0)
                if cell:
                    ids.append(cell.data(Qt.ItemDataRole.UserRole))
            if ids:
                placeholders = ",".join("?" * len(ids))
                db.execute(f"DELETE FROM materials WHERE id IN ({placeholders})", tuple(ids))
                self.load_data()


