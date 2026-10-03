"""
Вкладка "Задачи и Календарь": Канбан-доска с интерактивными карточками,
перетаскиванием, сортировкой, а также сквозной календарь с отображением 
пользовательских событий, оплат, дат договоров и актов из других модулей.
"""
import sqlite3
from datetime import datetime
from html import escape

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QListWidget, QListWidgetItem, QAbstractItemView, QDialog,
                              QLineEdit, QTextEdit, QCalendarWidget, QTabWidget, QScrollArea,
                              QMessageBox, QTimeEdit, QComboBox, QFrame, QMenu)
from PyQt6.QtCore import Qt, QDate, pyqtSignal, QTime, QSize
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QAction

from .database import db

# --- ВИЗУАЛЬНАЯ КАРТОЧКА ЗАДАЧИ ---

class TaskCardWidget(QFrame):
    def __init__(self, title, desc, created_at, urgency, status, tags=None):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        bg_col = "#F8FAFC" if status == "done" else "#FFFFFF"
        border_col = "#E2E8F0" if status == "done" else "#CBD5E1"
        self.setStyleSheet(f"TaskCardWidget {{ background-color: {bg_col}; border: 1px solid {border_col}; border-radius: 8px; }}")

        lbl_title = QLabel(title)
        title_color = "#94A3B8" if status == "done" else "#0F172A"
        lbl_title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {title_color}; border: none;")
        lbl_title.setWordWrap(True)
        layout.addWidget(lbl_title)

        if desc:
            short_desc = desc.replace("\n", " ")
            if len(short_desc) > 65:
                short_desc = short_desc[:62] + "..."
            lbl_desc = QLabel(short_desc)
            lbl_desc.setStyleSheet("color: #64748B; font-size: 11px; border: none;")
            lbl_desc.setWordWrap(True)
            layout.addWidget(lbl_desc)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        try:
            dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            date_str = dt.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            date_str = created_at

        lbl_date = QLabel(f"🕒 {date_str}")
        lbl_date.setStyleSheet("color: #94A3B8; font-size: 10px; border: none;")

        lbl_urgency = QLabel(urgency)
        if status == "done":
            u_col = "#94A3B8"
        else:
            if urgency == "Критическая": u_col = "#EF4444"
            elif urgency == "Высокая": u_col = "#F59E0B"
            elif urgency == "Низкая": u_col = "#10B981"
            else: u_col = "#3B82F6"

        lbl_urgency.setStyleSheet(f"color: {u_col}; font-weight: bold; font-size: 10px; border: none;")

        footer.addWidget(lbl_date)
        footer.addStretch()
        footer.addWidget(lbl_urgency)
        layout.addLayout(footer)

        if tags:
            chips = " ".join(
                f'<span style="background-color:{color or "#64748B"};color:#fff;border-radius:6px;'
                f'padding:1px 6px;margin-right:3px;font-size:9px;">{escape(name)}</span>'
                for name, color in tags
            )
            lbl_tags = QLabel(chips)
            lbl_tags.setTextFormat(Qt.TextFormat.RichText)
            lbl_tags.setWordWrap(True)
            lbl_tags.setStyleSheet("border: none;")
            layout.addWidget(lbl_tags)

# --- КАНБАН-ДОСКА ---

class KanbanListWidget(QListWidget):
    """Специальный QListWidget с поддержкой Drag&Drop и контекстным меню"""
    status_changed = pyqtSignal()
    delete_requested = pyqtSignal(int)

    def __init__(self, status_code):
        super().__init__()
        self.status_code = status_code
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setStyleSheet("QListWidget { background-color: transparent; border: none; } QListWidget::item { margin-bottom: 8px; }")

    def dropEvent(self, event):
        super().dropEvent(event)
        for i in range(self.count()):
            task_id = self.item(i).data(Qt.ItemDataRole.UserRole)
            db.execute("UPDATE kanban_tasks SET status=? WHERE id=?", (self.status_code, task_id))
        self.status_changed.emit()

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item:
            task_id = item.data(Qt.ItemDataRole.UserRole)
            menu = QMenu(self)

            act_edit = QAction("Изменить", self)
            act_edit.triggered.connect(lambda: self.doubleClicked.emit(self.indexFromItem(item)))
            menu.addAction(act_edit)

            menu.addSeparator()

            act_del = QAction("Удалить задачу", self)
            act_del.triggered.connect(lambda: self.delete_requested.emit(task_id))
            menu.addAction(act_del)

            menu.exec(event.globalPos())

class TaskEditDialog(QDialog):
    def __init__(self, task_id=None, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.setWindowTitle("Новая задача" if not task_id else "Редактирование задачи")
        self.resize(450, 380)

        layout = QVBoxLayout(self)

        row_top = QHBoxLayout()
        v_title = QVBoxLayout()
        v_title.addWidget(QLabel("Заголовок:"))
        self.inp_title = QLineEdit()
        v_title.addWidget(self.inp_title)

        v_urgency = QVBoxLayout()
        v_urgency.addWidget(QLabel("Срочность:"))
        self.cmb_urgency = QComboBox()
        self.cmb_urgency.addItems(["Низкая", "Обычная", "Высокая", "Критическая"])
        self.cmb_urgency.setCurrentText("Обычная")
        v_urgency.addWidget(self.cmb_urgency)

        row_top.addLayout(v_title, stretch=3)
        row_top.addLayout(v_urgency, stretch=1)
        layout.addLayout(row_top)

        layout.addWidget(QLabel("Описание:"))
        self.inp_desc = QTextEdit()
        layout.addWidget(self.inp_desc)
        from .task_catalog import TaskFields
        self.task_fields=TaskFields(self.task_id);layout.addWidget(self.task_fields)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setProperty("type", "primary")
        self.btn_save.clicked.connect(self.save_task)

        self.btn_archive = QPushButton("В архив")
        self.btn_archive.setProperty("type", "warning")
        self.btn_archive.clicked.connect(self.archive_task)

        self.btn_delete = QPushButton("Удалить")
        self.btn_delete.setProperty("type", "danger")
        self.btn_delete.clicked.connect(self.delete_task)

        if not self.task_id:
            self.btn_archive.hide()
            self.btn_delete.hide()

        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_archive)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

        if self.task_id:
            self.load_task()

    def load_task(self):
        row = db.fetchone("SELECT title, description, is_archived, urgency FROM kanban_tasks WHERE id=?", (self.task_id,))
        if row:
            self.inp_title.setText(row[0] or "")
            self.inp_desc.setPlainText(row[1] or "")
            self.cmb_urgency.setCurrentText(row[3] or "Обычная")
            if row[2] == 1:
                self.btn_archive.setText("Вернуть из архива")
                self.btn_archive.clicked.disconnect()
                self.btn_archive.clicked.connect(self.unarchive_task)

    def save_task(self):
        title = self.inp_title.text().strip()
        if not title: return
        desc = self.inp_desc.toPlainText().strip()
        urgency = self.cmb_urgency.currentText()

        with db.transaction():
            if self.task_id:db.execute("UPDATE kanban_tasks SET title=?, description=?, urgency=? WHERE id=?",(title,desc,urgency,self.task_id))
            else:self.task_id=db.execute("INSERT INTO kanban_tasks(title,description,status,is_archived,created_at,urgency) VALUES(?,?,?,0,?,?)",(title,desc,self.task_fields.status.currentData(),datetime.now().strftime('%Y-%m-%d %H:%M:%S'),urgency)).lastrowid
            self.task_fields.save(self.task_id)
        self.accept()

    def archive_task(self):
        db.execute("UPDATE kanban_tasks SET is_archived=1 WHERE id=?", (self.task_id,))
        self.accept()

    def unarchive_task(self):
        db.execute("UPDATE kanban_tasks SET is_archived=0 WHERE id=?", (self.task_id,))
        self.accept()

    def delete_task(self):
        if QMessageBox.question(self, "Удаление", "Точно удалить задачу безвозвратно?") == QMessageBox.StandardButton.Yes:
            db.execute("DELETE FROM kanban_tasks WHERE id=?", (self.task_id,))
            self.accept()

class ArchiveDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Архив задач")
        self.resize(500, 400)
        layout = QVBoxLayout(self)

        self.list = QListWidget()
        self.list.doubleClicked.connect(self.open_task)
        layout.addWidget(self.list)
        self.load_archived()

    def load_archived(self):
        self.list.clear()
        rows = db.fetchall("SELECT id, title FROM kanban_tasks WHERE is_archived=1 ORDER BY id DESC")
        for t_id, title in rows:
            item = QListWidgetItem(f"🗃️ {title}")
            item.setData(Qt.ItemDataRole.UserRole, t_id)
            self.list.addItem(item)

    def open_task(self):
        curr = self.list.currentRow()
        if curr >= 0:
            t_id = self.list.item(curr).data(Qt.ItemDataRole.UserRole)
            if TaskEditDialog(t_id, self).exec():
                self.load_archived()
                if self.parent() and hasattr(self.parent(), 'load_boards'):
                    self.parent().load_boards()

COLUMN_PALETTE = [
    ("#DC2626", "#FEF2F2"), ("#D97706", "#FFFBEB"), ("#16A34A", "#F0FDF4"),
    ("#2563EB", "#EFF6FF"), ("#7C3AED", "#F5F3FF"), ("#DB2777", "#FDF2F8"),
    ("#0891B2", "#ECFEFF"),
]

class KanbanTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        btn_add = QPushButton("➕ Добавить задачу")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.new_task)

        top_bar.addWidget(btn_add)
        top_bar.addSpacing(20)

        top_bar.addWidget(QLabel("Сортировка:"))
        self.cmb_sort = QComboBox()
        self.cmb_sort.addItems(["Сначала новые (по дате)", "Сначала старые (по дате)", "По срочности (сначала критические)"])
        self.cmb_sort.currentIndexChanged.connect(self.load_boards)
        top_bar.addWidget(self.cmb_sort)

        top_bar.addStretch()

        btn_columns = QPushButton("⚙️ Колонки и теги")
        btn_columns.clicked.connect(self.manage_columns)
        top_bar.addWidget(btn_columns)

        btn_archive = QPushButton("🗃️ Архив задач")
        btn_archive.clicked.connect(self.open_archive)
        top_bar.addWidget(btn_archive)

        layout.addLayout(top_bar)
        from .filters import SqlFilters
        self.filters=SqlFilters(self);self.filters.set_columns(['id','title','description','status','created_at','urgency']);self.filters.changed.connect(self.load_boards);layout.addWidget(self.filters)

        self.boards_container = QWidget()
        self.boards_layout = QHBoxLayout(self.boards_container)
        self.boards_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.boards_container)
        layout.addWidget(scroll, 1)

        self.columns = {}
        self.rebuild_columns()

    def make_col(self, title, widget, color, bg_color):
        w = QFrame()
        w.setMinimumWidth(260)
        w.setStyleSheet(f"QFrame {{ background-color: {bg_color}; border-radius: 8px; }}")
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel(title.upper())
        lbl.setStyleSheet(f"font-weight: bold; color: {color}; padding: 5px; font-size: 13px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(lbl)
        l.addWidget(widget)
        return w

    def rebuild_columns(self):
        while self.boards_layout.count():
            item = self.boards_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.columns = {}

        for i, (code, name) in enumerate(db.fetchall("SELECT code, name FROM task_statuses ORDER BY id")):
            accent, bg = COLUMN_PALETTE[i % len(COLUMN_PALETTE)]
            col = KanbanListWidget(code)
            col.status_changed.connect(self.load_boards)
            col.doubleClicked.connect(self.edit_task)
            col.delete_requested.connect(self.delete_task_from_menu)
            self.columns[code] = col
            self.boards_layout.addWidget(self.make_col(name, col, accent, bg))

    def manage_columns(self):
        from .task_catalog import CatalogDialog
        CatalogDialog(self).exec()
        self.rebuild_columns()
        self.load_boards()

    def load_boards(self):
        for col in self.columns.values():
            col.clear()

        sort_idx = self.cmb_sort.currentIndex()
        if sort_idx == 0:
            order_by = "ORDER BY id DESC"
        elif sort_idx == 1:
            order_by = "ORDER BY id ASC"
        else:
            order_by = "ORDER BY CASE urgency WHEN 'Критическая' THEN 1 WHEN 'Высокая' THEN 2 WHEN 'Обычная' THEN 3 WHEN 'Низкая' THEN 4 ELSE 5 END, id DESC"

        query,params=self.filters.apply(f'SELECT id, title, description, status, created_at, urgency FROM kanban_tasks WHERE is_archived=0 {order_by}',())
        rows=db.fetchall(query,params)

        tags_by_task = {}
        if rows:
            ids = [r[0] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            for task_id, name, color in db.fetchall(
                f"SELECT l.task_id, t.name, t.color FROM task_tag_links l JOIN task_tags t ON t.id=l.tag_id "
                f"WHERE l.task_id IN ({placeholders}) ORDER BY t.name", tuple(ids)
            ):
                tags_by_task.setdefault(task_id, []).append((name, color))

        # Tasks whose status has no matching column (e.g. a status deleted from the catalog)
        # fall back to the first column instead of silently disappearing from the board.
        fallback = next(iter(self.columns.values()), None)
        for t_id, title, desc, status, created, urgency in rows:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, t_id)

            card = TaskCardWidget(title, desc, created, urgency or "Обычная", status, tags_by_task.get(t_id))
            item.setSizeHint(card.sizeHint())

            col = self.columns.get(status, fallback)
            if col is not None:
                col.addItem(item)
                col.setItemWidget(item, card)

    def new_task(self):
        if TaskEditDialog(parent=self).exec():
            self.load_boards()

    def edit_task(self, index):
        widget = self.sender()
        if isinstance(widget, QListWidget):
            t_id = widget.itemFromIndex(index).data(Qt.ItemDataRole.UserRole)
            if TaskEditDialog(t_id, self).exec():
                self.load_boards()

    def delete_task_from_menu(self, task_id):
        if QMessageBox.question(self, "Удаление", "Точно удалить задачу безвозвратно?") == QMessageBox.StandardButton.Yes:
            db.execute("DELETE FROM kanban_tasks WHERE id=?", (task_id,))
            self.load_boards()

    def open_archive(self):
        ArchiveDialog(self).exec()

# --- КАЛЕНДАРЬ СОБЫТИЙ ---

class EventEditDialog(QDialog):
    def __init__(self, date_str, event_id=None, parent=None):
        super().__init__(parent)
        self.date_str = date_str
        self.event_id = event_id
        self.setWindowTitle(f"Событие на {date_str}")
        self.resize(350, 250)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Время:"))
        self.inp_time = QTimeEdit()
        self.inp_time.setDisplayFormat("HH:mm")
        layout.addWidget(self.inp_time)

        layout.addWidget(QLabel("Заголовок:"))
        self.inp_title = QLineEdit()
        layout.addWidget(self.inp_title)

        layout.addWidget(QLabel("Описание:"))
        self.inp_desc = QTextEdit()
        layout.addWidget(self.inp_desc)

        btn_layout = QHBoxLayout()
        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setProperty("type", "primary")
        self.btn_save.clicked.connect(self.save_event)

        self.btn_del = QPushButton("Удалить")
        self.btn_del.setProperty("type", "danger")
        self.btn_del.clicked.connect(self.del_event)

        if not self.event_id:
            self.btn_del.hide()
            self.inp_time.setTime(QTime.currentTime())

        btn_layout.addWidget(self.btn_del)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        layout.addLayout(btn_layout)

        if self.event_id:
            self.load_event()

    def load_event(self):
        row = db.fetchone("SELECT title, event_time, description FROM calendar_events WHERE id=?", (self.event_id,))
        if row:
            self.inp_title.setText(row[0] or "")
            if row[1]: self.inp_time.setTime(QTime.fromString(row[1], "HH:mm"))
            self.inp_desc.setPlainText(row[2] or "")

    def save_event(self):
        title = self.inp_title.text().strip()
        if not title: return
        e_time = self.inp_time.time().toString("HH:mm")
        desc = self.inp_desc.toPlainText().strip()

        if self.event_id:
            db.execute("UPDATE calendar_events SET title=?, event_time=?, description=? WHERE id=?",
                       (title, e_time, desc, self.event_id))
        else:
            db.execute("INSERT INTO calendar_events (title, event_date, event_time, description) VALUES (?, ?, ?, ?)",
                       (title, self.date_str, e_time, desc))
        self.accept()

    def del_event(self):
        if QMessageBox.question(self, "Удаление", "Удалить событие?") == QMessageBox.StandardButton.Yes:
            db.execute("DELETE FROM calendar_events WHERE id=?", (self.event_id,))
            self.accept()

class CalendarTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)

        left_panel = QVBoxLayout()
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.clicked.connect(self.on_date_clicked)
        left_panel.addWidget(self.calendar)
        left_panel.addStretch()

        right_panel = QVBoxLayout()
        self.lbl_date = QLabel("События")
        self.lbl_date.setStyleSheet("font-size: 14pt; font-weight: bold; color: #0284C7;")
        right_panel.addWidget(self.lbl_date)

        filterbar=QHBoxLayout();self.event_search=QLineEdit();self.event_search.setPlaceholderText('Поиск событий выбранного дня…');filterbar.addWidget(self.event_search);self.event_kind=QComboBox();self.event_kind.addItem('Все события','');self.event_kind.addItem('Сварочные работы','welding');self.event_kind.addItem('События вручную','event');self.event_kind.addItem('Договоры / оплаты / акты','readonly');filterbar.addWidget(self.event_kind);right_panel.addLayout(filterbar)
        self.event_search.textChanged.connect(self.filter_events);self.event_kind.currentIndexChanged.connect(self.filter_events)
        self.list_events = QListWidget()
        self.list_events.doubleClicked.connect(self.edit_event)
        self.list_events.setStyleSheet("QListWidget::item { padding: 8px; border-bottom: 1px solid #E2E8F0; }")
        right_panel.addWidget(self.list_events)

        self.btn_add = QPushButton("➕ Добавить событие")
        self.btn_add.setProperty("type", "primary")
        self.btn_add.clicked.connect(self.add_event)
        right_panel.addWidget(self.btn_add)

        layout.addLayout(left_panel, stretch=1)
        layout.addLayout(right_panel, stretch=1)

        self.refresh_highlights()
        self.on_date_clicked(self.calendar.selectedDate())

    def refresh_highlights(self):
        """Подсвечивает все даты, где есть хотя бы одно событие (пользовательское или системное)"""
        self.calendar.setDateTextFormat(QDate(), QTextCharFormat())

        dates = set()

        for row in db.fetchall("SELECT DISTINCT work_date FROM welding_days"):
            dates.add(row[0])

        # Пользовательские события
        for row in db.fetchall("SELECT DISTINCT event_date FROM calendar_events WHERE event_date IS NOT NULL AND event_date != ''"):
            dates.add(row[0])

        # Оплаты из смет
        for row in db.fetchall("SELECT DISTINCT date FROM payments WHERE date IS NOT NULL AND date != ''"):
            dates.add(row[0])

        # Даты договоров (модуль смет и модуль ГСВ)
        for row in db.fetchall("SELECT DISTINCT contract_date FROM contracts WHERE contract_date IS NOT NULL AND contract_date != ''"):
            dates.add(row[0])
        for row in db.fetchall("SELECT DISTINCT contract_date FROM gsv_projects WHERE contract_date IS NOT NULL AND contract_date != ''"):
            dates.add(row[0])

        # Даты актов (модуль смет и модуль ГСВ)
        for row in db.fetchall("SELECT DISTINCT acceptance_act_date FROM contracts WHERE acceptance_act_date IS NOT NULL AND acceptance_act_date != ''"):
            dates.add(row[0])
        for row in db.fetchall("SELECT DISTINCT act_date FROM gsv_projects WHERE act_date IS NOT NULL AND act_date != ''"):
            dates.add(row[0])

        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#BAE6FD"))
        fmt.setForeground(QColor("#0369A1"))
        fmt.setFontWeight(QFont.Weight.Bold)

        for d_str in dates:
            qdate = QDate.fromString(d_str, "yyyy-MM-dd")
            if qdate.isValid():
                self.calendar.setDateTextFormat(qdate, fmt)

    def on_date_clicked(self, date):
        date_str = date.toString("yyyy-MM-dd")
        self.lbl_date.setText(f"События на {date.toString('dd.MM.yyyy')}")
        self.load_events(date_str)

    def load_events(self, date_str):
        self.list_events.clear()

        # 1. Сквозная логика: Загружаем оплаты
        from .payments_domain import report
        pays=[(r['amount'],r['section']+' · '+r['object_name']) for r in report(db,date_str,date_str)]
        for amt, title in pays:
            val = float(amt) if amt else 0.0
            item = QListWidgetItem(f"💰 Оплата: {val:,.2f} руб. (Объект: {title})")
            item.setForeground(QColor("#16A34A"))
            item.setData(Qt.ItemDataRole.UserRole + 1, "readonly")
            item.setSizeHint(item.sizeHint() + QSize(0, 5))
            self.list_events.addItem(item)

        # 2. Сквозная логика: Заключенные договора
        conts = db.fetchall("SELECT contract_number, object_name FROM contracts WHERE contract_date=?", (date_str,))
        for num, obj in conts:
            item = QListWidgetItem(f"✍️ Заключен договор №{num} ({obj})")
            item.setForeground(QColor("#0284C7"))
            item.setData(Qt.ItemDataRole.UserRole + 1, "readonly")
            item.setSizeHint(item.sizeHint() + QSize(0, 5))
            self.list_events.addItem(item)

        gsv_conts = db.fetchall("SELECT pd_number, contract_number, object_name FROM gsv_projects WHERE contract_date=?", (date_str,))
        for pd_num, num, obj in gsv_conts:
            item = QListWidgetItem(f"✍️ Заключен договор ГСВ №{num} ({pd_num} / {obj})")
            item.setForeground(QColor("#0284C7"))
            item.setData(Qt.ItemDataRole.UserRole + 1, "readonly")
            item.setSizeHint(item.sizeHint() + QSize(0, 5))
            self.list_events.addItem(item)

        # 3. Сквозная логика: Подписанные акты
        acts = db.fetchall("SELECT contract_number, object_name FROM contracts WHERE acceptance_act_date=?", (date_str,))
        for num, obj in acts:
            item = QListWidgetItem(f"✅ Подписан акт: договор №{num} ({obj})")
            item.setForeground(QColor("#D97706"))
            item.setData(Qt.ItemDataRole.UserRole + 1, "readonly")
            item.setSizeHint(item.sizeHint() + QSize(0, 5))
            self.list_events.addItem(item)

        gsv_acts = db.fetchall("SELECT pd_number, contract_number, object_name FROM gsv_projects WHERE act_date=?", (date_str,))
        for pd_num, num, obj in gsv_acts:
            item = QListWidgetItem(f"✅ Подписан акт ГСВ: договор №{num} ({pd_num} / {obj})")
            item.setForeground(QColor("#D97706"))
            item.setData(Qt.ItemDataRole.UserRole + 1, "readonly")
            item.setSizeHint(item.sizeHint() + QSize(0, 5))
            self.list_events.addItem(item)

        # Welding work marks are the single source of truth for the calendar.
        from .gsv_domain import owner_label
        jobs=db.fetchall("SELECT j.id,j.title,j.owner_type,j.owner_id,coalesce(nullif(j.welder_text,''),w.name),j.object_text FROM welding_days d JOIN welding_jobs j ON j.id=d.job_id LEFT JOIN welders w ON w.id=j.welder_id WHERE d.work_date=? ORDER BY j.title",(date_str,))
        for job_id,title,owner,rid,welder,place in jobs:
            item=QListWidgetItem(f'Работы: {title} · {welder or "Сварщик не назначен"} · {place or owner_label(db,owner,rid)}')
            item.setData(Qt.ItemDataRole.UserRole,job_id);item.setData(Qt.ItemDataRole.UserRole+1,'welding');self.list_events.addItem(item)

        # 4. События, добавленные пользователем вручную в этот день
        rows = db.fetchall("SELECT id, event_time, title FROM calendar_events WHERE event_date=? ORDER BY event_time ASC", (date_str,))
        for e_id, e_time, title in rows:
            item = QListWidgetItem(f"🕒 {e_time} — {title}")
            font = item.font()
            font.setBold(True)
            item.setFont(font)
            item.setData(Qt.ItemDataRole.UserRole, e_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, "event") # Указываем, что это редактируемое событие
            item.setSizeHint(item.sizeHint() + QSize(0, 5))
            self.list_events.addItem(item)

        self.filter_events()

    def filter_events(self,*_):
        if not hasattr(self,'list_events'):return
        for i in range(self.list_events.count()):
            item=self.list_events.item(i);kind=self.event_kind.currentData();item.setHidden(self.event_search.text().casefold() not in item.text().casefold() or bool(kind and item.data(Qt.ItemDataRole.UserRole+1)!=kind))

    def add_event(self):
        date_str = self.calendar.selectedDate().toString("yyyy-MM-dd")
        if EventEditDialog(date_str, parent=self).exec():
            self.refresh_highlights()
            self.load_events(date_str)

    def edit_event(self):
        curr = self.list_events.currentRow()
        if curr >= 0:
            item = self.list_events.item(curr)
            if item.data(Qt.ItemDataRole.UserRole+1)=='welding':
                from .welding_view import JobDialog
                JobDialog(item.data(Qt.ItemDataRole.UserRole),parent=self).exec()
                self.refresh_highlights();self.load_events(self.calendar.selectedDate().toString('yyyy-MM-dd'));return
            # Системные события (оплаты, акты) изменять из календаря нельзя
            if item.data(Qt.ItemDataRole.UserRole + 1) == "readonly":
                return

            e_id = item.data(Qt.ItemDataRole.UserRole)
            date_str = self.calendar.selectedDate().toString("yyyy-MM-dd")
            if EventEditDialog(date_str, e_id, self).exec():
                self.refresh_highlights()
                self.load_events(date_str)

# --- ГЛАВНЫЙ ВИДЖЕТ ВЛАДКИ ---

class TasksView(QWidget):
    def __init__(self):
        super().__init__()
        try:
            db.execute("ALTER TABLE kanban_tasks ADD COLUMN urgency TEXT DEFAULT 'Обычная'")
        except sqlite3.OperationalError:
            pass  # колонка уже добавлена при предыдущем запуске

        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(KanbanTab(), "📋 Задачи")
        self.tabs.addTab(CalendarTab(), "📅 Календарь")
        self.tabs.currentChanged.connect(lambda _:self.load_data())

        layout.addWidget(self.tabs)

    def load_data(self):
        self.tabs.widget(0).load_boards()
        self.tabs.widget(1).refresh_highlights()
        self.tabs.widget(1).load_events(self.tabs.widget(1).calendar.selectedDate().toString('yyyy-MM-dd'))
