"""
Вкладка "Исполнительная документация": Справочник сертификатов (с папками и редактированием)
и генератор пакетов документов (актов и сертификатов) по объектам.
"""
import os
import logging

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QTableWidget, QTableWidgetItem, QAbstractItemView, QDialog,
                              QLineEdit, QComboBox, QSplitter, QTabWidget, QTreeWidget,
                              QTreeWidgetItem, QMenu, QCheckBox, QDateEdit, QGridLayout,
                              QMessageBox, QFileDialog, QGroupBox, QInputDialog)
from PyQt6.QtCore import Qt, QDate, pyqtSignal
from PyQt6.QtGui import QColor, QAction

from .database import db
from .platform_utils import open_local
from .pagination import RegistryPager
from .widgets import SmartTableManager

def open_or_print_file(path, action="open"):
    if path and os.path.exists(path):
        try:
            if action == "print":
                open_local(os.path.abspath(path), "print")
            else:
                open_local(os.path.abspath(path))
        except Exception as e:
            QMessageBox.warning(None, "Ошибка", f"Не удалось выполнить действие с файлом:\n{e}")
    else:
        QMessageBox.warning(None, "Файл не найден", f"Файл перемещен или удален:\n{path}")


# --- СПРАВОЧНИК СЕРТИФИКАТОВ ---

class CertificatesTree(QTreeWidget):
    cert_dropped = pyqtSignal(list, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        if event.source() and isinstance(event.source(), CertificatesTable):
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.source() and isinstance(event.source(), CertificatesTable):
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        source = event.source()
        if source and isinstance(source, CertificatesTable):
            item = self.itemAt(event.position().toPoint())
            target_folder_id = None
            if item:
                target_folder_id = item.data(0, Qt.ItemDataRole.UserRole)

            selected_rows = set(i.row() for i in source.selectedItems())
            cert_ids = [source.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in selected_rows]

            if cert_ids:
                self.cert_dropped.emit(cert_ids, target_folder_id)
            event.accept()
        else:
            super().dropEvent(event)


class CertificatesTable(QTableWidget):
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
        cert_ids = [self.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in selected_rows]

        menu = QMenu(self)

        if len(selected_rows) == 1:
            act_edit = QAction("Изменить / Открыть", self)
            act_edit.triggered.connect(self.parent_view.edit_certificate)
            menu.addAction(act_edit)

        act_del = QAction("Удалить", self)
        act_del.triggered.connect(self.parent_view.delete_certificate)
        menu.addAction(act_del)

        menu.addSeparator()
        move_menu = menu.addMenu("Отправить в папку")
        act_none = QAction(" Без папки", self)
        act_none.triggered.connect(lambda: self.parent_view.move_certs_to_folder(cert_ids, None))
        move_menu.addAction(act_none)

        roots = db.fetchall("SELECT id, name FROM certificate_folders WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            act_root = QAction(f"📁 {r_name}", self)
            act_root.triggered.connect(lambda checked, f_id=r_id, ids=cert_ids: self.parent_view.move_certs_to_folder(ids, f_id))
            move_menu.addAction(act_root)
            subs = db.fetchall("SELECT id, name FROM certificate_folders WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                act_sub = QAction(f"   📂 {s_name}", self)
                act_sub.triggered.connect(lambda checked, f_id=s_id, ids=cert_ids: self.parent_view.move_certs_to_folder(ids, f_id))
                move_menu.addAction(act_sub)

        menu.exec(self.viewport().mapToGlobal(pos))


class CertificateEditDialog(QDialog):
    def __init__(self, cert_id=None, parent=None):
        super().__init__(parent)
        self.cert_id = cert_id
        self.setWindowTitle("Карточка сертификата")
        self.resize(500, 300)

        layout = QVBoxLayout(self)

        grid = QGridLayout()
        grid.addWidget(QLabel("Папка:"), 0, 0)
        self.cmb_folder = QComboBox()
        self.load_folders()
        grid.addWidget(self.cmb_folder, 0, 1)

        grid.addWidget(QLabel("Наименование:"), 1, 0)
        self.inp_name = QLineEdit()
        grid.addWidget(self.inp_name, 1, 1)

        grid.addWidget(QLabel("Номер:"), 2, 0)
        self.inp_num = QLineEdit()
        grid.addWidget(self.inp_num, 2, 1)

        grid.addWidget(QLabel("Срок действия:"), 3, 0)
        h_date = QHBoxLayout()
        self.chk_unlimited = QCheckBox("Бессрочный")
        self.dt_valid = QDateEdit(calendarPopup=True)
        self.dt_valid.setDate(QDate.currentDate().addYears(1))

        self.chk_unlimited.toggled.connect(lambda c: self.dt_valid.setDisabled(c))
        h_date.addWidget(self.chk_unlimited)
        h_date.addWidget(self.dt_valid)
        grid.addLayout(h_date, 3, 1)

        grid.addWidget(QLabel("Файл:"), 4, 0)
        h_file = QHBoxLayout()
        self.inp_file = QLineEdit()
        self.inp_file.setReadOnly(True)
        btn_browse = QPushButton("Выбрать...")
        btn_browse.clicked.connect(self.browse_file)
        btn_open = QPushButton("Открыть")
        btn_open.clicked.connect(lambda: open_or_print_file(self.inp_file.text(), "open"))
        h_file.addWidget(self.inp_file)
        h_file.addWidget(btn_browse)
        h_file.addWidget(btn_open)
        grid.addLayout(h_file, 4, 1)

        layout.addLayout(grid)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("Сохранить")
        btn_save.setProperty("type", "primary")
        btn_save.clicked.connect(self.save_data)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

        if self.cert_id:
            self.load_data()
        else:
            self.chk_unlimited.setChecked(True)

    def load_folders(self):
        self.cmb_folder.clear()
        self.cmb_folder.addItem(" Без папки", None)
        roots = db.fetchall("SELECT id, name FROM certificate_folders WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            self.cmb_folder.addItem(f"📁 {r_name}", r_id)
            subs = db.fetchall("SELECT id, name FROM certificate_folders WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                self.cmb_folder.addItem(f"   📂 {s_name}", s_id)

    def browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите скан сертификата (PDF, JPG, PNG)", "", "Все файлы (*.*)")
        if path:self.inp_file.setText(os.path.abspath(path))

    def load_data(self):
        row = db.fetchone("SELECT name, cert_number, valid_to, file_path, folder_id FROM certificates WHERE id=?", (self.cert_id,))
        if row:
            name, num, valid, f_path, folder_id = row
            self.inp_name.setText(name or "")
            self.inp_num.setText(num or "")
            self.inp_file.setText(f_path or "")

            if folder_id is not None:
                idx = self.cmb_folder.findData(folder_id)
                if idx >= 0: self.cmb_folder.setCurrentIndex(idx)

            if not valid:
                self.chk_unlimited.setChecked(True)
            else:
                self.chk_unlimited.setChecked(False)
                self.dt_valid.setDate(QDate.fromString(valid, "yyyy-MM-dd"))

    def save_data(self):
        name = self.inp_name.text().strip()
        num = self.inp_num.text().strip()
        f_path = self.inp_file.text().strip()
        folder_id = self.cmb_folder.currentData()

        valid = "" if self.chk_unlimited.isChecked() else self.dt_valid.date().toString("yyyy-MM-dd")

        if self.cert_id:
            db.execute("UPDATE certificates SET name=?, cert_number=?, valid_to=?, file_path=?, folder_id=? WHERE id=?",
                       (name, num, valid, f_path, folder_id, self.cert_id))
        else:
            db.execute("INSERT INTO certificates (name, cert_number, valid_to, file_path, folder_id) VALUES (?, ?, ?, ?, ?)",
                       (name, num, valid, f_path, folder_id))
        self.accept()


class CertificatesTab(QWidget):
    def __init__(self):
        super().__init__()
        self.pager=RegistryPager(self)
        main_layout = QVBoxLayout(self)

        actions = QHBoxLayout()
        self.btn_toggle_folders = QPushButton("Скрыть папки")
        self.btn_toggle_folders.clicked.connect(self.toggle_folders)
        actions.addWidget(self.btn_toggle_folders)

        btn_add = QPushButton("Добавить сертификат")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.add_certificate)

        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("🔍 Поиск по названию или номеру...")
        self.search_inp.setFixedWidth(250)
        self.search_inp.textChanged.connect(self.load_data)

        actions.addWidget(btn_add)
        actions.addStretch()
        actions.addWidget(self.search_inp)
        main_layout.addLayout(actions)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.left_widget = QWidget()
        left_layout = QVBoxLayout(self.left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)

        self.tree = CertificatesTree()
        self.tree.setHeaderLabels(["Папки (ПКМ для управления)"])
        self.tree.cert_dropped.connect(self.move_certs_to_folder)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_tree_context_menu)
        left_layout.addWidget(self.tree)
        self.splitter.addWidget(self.left_widget)

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 0, 0, 0)

        self.table = CertificatesTable(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Наименование", "№ Сертификата", "Годен до", "Файл"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_certificate)

        self.table_manager = SmartTableManager(self.table, main_col=0)
        right_layout.addWidget(self.table)
        self.splitter.addWidget(right_widget)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        main_layout.addWidget(self.splitter)

        self.tree.itemClicked.connect(self.on_folder_selected)

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
            db.execute("INSERT INTO certificate_folders (name) VALUES (?)", (name.strip(),))
            self.load_folders()

    def add_sub_folder(self, parent_id):
        name, ok = QInputDialog.getText(self, "Новая подпапка", "Название:")
        if ok and name.strip():
            db.execute("INSERT INTO certificate_folders (name, parent_id) VALUES (?, ?)", (name.strip(), parent_id))
            self.load_folders()

    def rename_folder(self, item, folder_id):
        old_name = item.text(0).replace("📁 ", "").replace("📂 ", "").strip()
        name, ok = QInputDialog.getText(self, "Переименовать папку", "Новое название:", text=old_name)
        if ok and name.strip():
            db.execute("UPDATE certificate_folders SET name=? WHERE id=?", (name.strip(), folder_id))
            self.load_folders()

    def delete_folder(self, folder_id):
        if QMessageBox.question(self, "Удаление", "Удалить папку и все подпапки?\n(Сертификаты переместятся в 'Все сертификаты')") == QMessageBox.StandardButton.Yes:
            db.execute("UPDATE certificates SET folder_id=NULL WHERE folder_id=?", (folder_id,))
            subs = db.fetchall("SELECT id FROM certificate_folders WHERE parent_id=?", (folder_id,))
            for s in subs:
                db.execute("UPDATE certificates SET folder_id=NULL WHERE folder_id=?", (s[0],))
            db.execute("DELETE FROM certificate_folders WHERE id=? OR parent_id=?", (folder_id, folder_id))
            self.load_folders()
            self.load_data()

    def toggle_folders(self):
        is_visible = self.left_widget.isVisible()
        self.left_widget.setVisible(not is_visible)
        self.btn_toggle_folders.setText("Показать папки" if is_visible else "Скрыть папки")

    def move_certs_to_folder(self, cert_ids, folder_id):
        if not cert_ids: return
        placeholders = ",".join("?" * len(cert_ids))
        params = [folder_id] + cert_ids
        db.execute(f"UPDATE certificates SET folder_id=? WHERE id IN ({placeholders})", tuple(params))
        self.load_data()

    def load_folders(self):
        self.tree.clear()
        all_item = QTreeWidgetItem([" Все сертификаты"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self.tree.addTopLevelItem(all_item)
        roots = db.fetchall("SELECT id, name FROM certificate_folders WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            r_item = QTreeWidgetItem([f"📁 {r_name}"])
            r_item.setData(0, Qt.ItemDataRole.UserRole, r_id)
            self.tree.addTopLevelItem(r_item)
            subs = db.fetchall("SELECT id, name FROM certificate_folders WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                s_item = QTreeWidgetItem([f"   📂 {s_name}"])
                s_item.setData(0, Qt.ItemDataRole.UserRole, s_id)
                r_item.addChild(s_item)
        self.tree.expandAll()
        self.tree.setCurrentItem(all_item)

    def on_folder_selected(self, item, column):
        self.selected_folder_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.load_data()

    def load_data(self):
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        q = self.search_inp.text().strip().lower()

        sql = "SELECT id, name, cert_number, valid_to, file_path FROM certificates"
        params = []
        conditions = []

        if self.selected_folder_id is not None:
            conditions.append("folder_id = ?")
            params.append(self.selected_folder_id)

        if q:
            conditions.append("(LOWER(name) LIKE ? OR LOWER(cert_number) LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY id DESC"

        rows = self.pager.fetch(sql, tuple(params))
        self.table.setRowCount(len(rows))

        today = QDate.currentDate().toString("yyyy-MM-dd")
        for r, (c_id, name, num, valid, path) in enumerate(rows):
            i_name = QTableWidgetItem(name or "")
            i_name.setData(Qt.ItemDataRole.UserRole, c_id)
            i_name.setData(Qt.ItemDataRole.UserRole + 1, path)
            self.table.setItem(r, 0, i_name)

            self.table.setItem(r, 1, QTableWidgetItem(num or ""))

            i_valid = QTableWidgetItem(valid or "Бессрочно")
            i_valid.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if valid and valid < today:
                i_valid.setForeground(QColor("#DC2626"))
                i_valid.setText(f"Просрочен ({valid})")
            self.table.setItem(r, 2, i_valid)

            filename = os.path.basename(path) if path else "Нет файла"
            self.table.setItem(r, 3, QTableWidgetItem(filename))

        self.table.setUpdatesEnabled(True)

    def add_certificate(self):
        if CertificateEditDialog(parent=self).exec():
            self.load_data()

    def edit_certificate(self):
        selected_rows = set(item.row() for item in self.table.selectedItems())
        if not selected_rows: return

        row = list(selected_rows)[0]
        c_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        if CertificateEditDialog(c_id, self).exec():
            self.load_data()

    def delete_certificate(self):
        selected_rows = set(item.row() for item in self.table.selectedItems())
        if not selected_rows: return

        if QMessageBox.question(self, "Удаление", f"Удалить выбранные сертификаты ({len(selected_rows)} шт.)?") == QMessageBox.StandardButton.Yes:
            for row in selected_rows:
                c_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
                path = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1)
                db.execute("DELETE FROM certificates WHERE id=?", (c_id,))
                db.execute("UPDATE contract_equipment SET linked_cert_id=NULL WHERE linked_cert_id=?", (c_id,))
                try:
                    if path and os.path.exists(path): os.remove(path)
                except OSError as e:
                    logging.warning(f"Не удалось удалить файл {path}: {e}")
            self.load_data()


# --- СБОРКА ИСПОЛНИТЕЛЬНОЙ ДОКУМЕНТАЦИИ ---

class ExecDocsBuilderTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        # Выбор проекта
        box_project = QHBoxLayout()
        box_project.addWidget(QLabel("Выберите договор / объект:"))
        self.cmb_projects = QComboBox()
        self.cmb_projects.setMinimumWidth(400)
        self.cmb_projects.currentIndexChanged.connect(self.load_project_equipment)
        box_project.addWidget(self.cmb_projects)
        box_project.addStretch()

        btn_print_all = QPushButton("🖨️ Печать всех сертификатов объекта")
        btn_print_all.setProperty("type", "primary")
        btn_print_all.clicked.connect(self.print_all_certificates)
        box_project.addWidget(btn_print_all)
        layout.addLayout(box_project)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        left_widget = QGroupBox("Смонтированное оборудование (из карточки договора)")
        left_layout = QVBoxLayout(left_widget)

        self.table_eq = QTableWidget()
        self.table_eq.setColumnCount(3)
        self.table_eq.setHorizontalHeaderLabels(["Наименование", "№ Сертификата", "Статус файла"])
        self.table_eq.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_eq.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_eq.doubleClicked.connect(self.link_certificate)
        self.table_manager = SmartTableManager(self.table_eq, main_col=0)
        left_layout.addWidget(self.table_eq)
        left_layout.addWidget(QLabel("💡 Двойной клик по строке, чтобы привязать файл из справочника"))
        self.splitter.addWidget(left_widget)

        right_widget = QGroupBox("Генерация актов (Word)")
        right_layout = QVBoxLayout(right_widget)

        self.btn_act_hidden = QPushButton("📄 Акт освидетельствования скрытых работ")
        self.btn_act_test = QPushButton("📄 Акт испытаний газопровода")
        self.btn_act_weld = QPushButton("📄 Журнал сварочных работ")

        for btn in [self.btn_act_hidden, self.btn_act_test, self.btn_act_weld]:
            btn.setMinimumHeight(40)
            btn.clicked.connect(self.generate_stub)
            right_layout.addWidget(btn)

        right_layout.addStretch()
        self.splitter.addWidget(right_widget)

        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter)

        from .welding_documents import ObjectDossierWidget
        self.object_docs=ObjectDossierWidget('contracts')
        self.builder_tabs=QTabWidget()
        layout.removeWidget(self.splitter)
        self.builder_tabs.addTab(self.object_docs,'Все документы объекта')
        self.builder_tabs.addTab(self.splitter,'Оборудование и выгрузка')
        layout.addWidget(self.builder_tabs,1)
        self.load_projects()

    def generate_stub(self):
        from .workspace_view import ExportDialog
        cid=self.cmb_projects.currentData()
        if cid:ExportDialog('contracts',cid,self).exec()
        else:QMessageBox.information(self,'Документы','Сначала выберите договор')

    def load_projects(self):
        self.cmb_projects.clear()
        rows = db.fetchall("""
            SELECT c.id, c.contract_number, c.object_name, e.title 
            FROM contracts c LEFT JOIN estimates e ON c.estimate_id = e.id 
            ORDER BY c.id DESC
        """)
        for c_id, num, obj, est in rows:
            name = f"Договор №{num or 'Б/Н'} | {obj or 'Без адреса'} | Смета: {est or '—'}"
            self.cmb_projects.addItem(name, c_id)

    def load_project_equipment(self):
        self.table_eq.setRowCount(0)
        c_id = self.cmb_projects.currentData()
        self.object_docs.bind(c_id)
        if not c_id: return

        rows = db.fetchall("SELECT id, equipment_name, certificate_number, linked_cert_id FROM contract_equipment WHERE contract_id=?", (c_id,))
        self.table_eq.setRowCount(len(rows))

        for r, (eq_id, name, cert_num, linked_id) in enumerate(rows):
            i_name = QTableWidgetItem(name or "")
            i_name.setData(Qt.ItemDataRole.UserRole, eq_id)
            i_name.setData(Qt.ItemDataRole.UserRole + 1, linked_id)
            self.table_eq.setItem(r, 0, i_name)
            self.table_eq.setItem(r, 1, QTableWidgetItem(cert_num or ""))

            if linked_id:
                cert_file = db.fetchone("SELECT file_path FROM certificates WHERE id=?", (linked_id,))
                if cert_file and cert_file[0] and os.path.exists(cert_file[0]):
                    i_status = QTableWidgetItem("✅ Файл привязан")
                    i_status.setForeground(QColor("#16A34A"))
                else:
                    i_status = QTableWidgetItem("⚠️ Файл потерян")
                    i_status.setForeground(QColor("#D97706"))
            else:
                i_status = QTableWidgetItem("❌ Нет файла")
                i_status.setForeground(QColor("#DC2626"))

            self.table_eq.setItem(r, 2, i_status)

    def link_certificate(self):
        curr = self.table_eq.currentRow()
        if curr < 0: return
        eq_id = self.table_eq.item(curr, 0).data(Qt.ItemDataRole.UserRole)

        certs = db.fetchall("SELECT id, name, cert_number FROM certificates ORDER BY name")
        if not certs:
            QMessageBox.warning(self, "Пусто", "Справочник сертификатов пуст.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Выбор сертификата")
        layout = QVBoxLayout(dlg)
        cmb = QComboBox()
        cmb.addItem("--- Отвязать файл ---", None)
        for c_id, name, num in certs:
            cmb.addItem(f"{name} (№ {num})", c_id)

        layout.addWidget(QLabel("Выберите файл из справочника:"))
        layout.addWidget(cmb)
        btn = QPushButton("Применить")
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected_cert_id = cmb.currentData()
            db.execute("UPDATE contract_equipment SET linked_cert_id=? WHERE id=?", (selected_cert_id, eq_id))
            self.load_project_equipment()

    def print_all_certificates(self):
        from .gsv_domain import dossier
        from pathlib import Path
        cid=self.cmb_projects.currentData()
        if not cid:return
        rows=dossier(db,'contracts',cid);paths=list(dict.fromkeys(row['path'] for row in rows if row['path']))
        missing=[path for path in paths if not Path(path).is_file()]
        if missing:QMessageBox.warning(self,'Недоступные документы','Исправьте пути перед печатью:\n'+'\n'.join(missing));return
        if not paths:QMessageBox.information(self,'Документы','Нет файлов для печати');return
        if QMessageBox.question(self,'Печать',f'Отправить на печать {len(paths)} документов объекта?')==QMessageBox.StandardButton.Yes:
            for path in paths:open_or_print_file(path,'print')


class ExecutiveDocsView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        from .dossier_view import DossierRegistry,DossierTemplates
        self.tabs.addTab(DossierRegistry(), 'Объекты и комплекты ИД')
        self.tabs.addTab(CertificatesTab(), "🗃️ Справочник сертификатов")
        from .materials_view import MaterialsView
        self.tabs.addTab(MaterialsView(), "Материалы и сертификаты")
        self.tabs.addTab(DossierTemplates(), "Шаблоны ГСН / ГСВ")
        layout.addWidget(self.tabs)

    def load_data(self):
        self.tabs.widget(0).load_projects()
        self.tabs.widget(1).load_data()
