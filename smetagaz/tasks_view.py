"""
Доска задач: карточки со сроком выполнения, перетаскивание между статусами,
сортировка, быстрые фильтры и архив. Календарь и стартовый экран — в today_view.py.
"""
from datetime import datetime, date, timedelta

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QListWidget, QListWidgetItem, QAbstractItemView, QDialog,
                              QLineEdit, QTextEdit, QScrollArea, QCheckBox, QDateEdit,
                              QMessageBox, QTimeEdit, QComboBox, QFrame, QMenu)
from PyQt6.QtCore import Qt, QDate, QLocale, pyqtSignal, QTime
from PyQt6.QtGui import QColor, QAction

from .database import db
from .agenda_domain import due_state, due_label, norm_date
from .task_catalog import status_rows, chip_html
from . import board_domain as board

URGENCY_COLORS = {'Критическая': '#DC2626', 'Высокая': '#D97706', 'Обычная': '#2563EB', 'Низкая': '#16A34A'}
DUE_COLORS = {'overdue': '#DC2626', 'today': '#D97706', 'soon': '#D97706', 'later': '#65758B'}


def is_dark():
    return db.get_setting('is_dark', '0') == '1'


def rgba(color, alpha):
    c = QColor(color)
    return f'rgba({c.red()},{c.green()},{c.blue()},{alpha})'


# --- ВИЗУАЛЬНАЯ КАРТОЧКА ЗАДАЧИ ---

class TaskCardWidget(QFrame):
    def __init__(self, title, desc, created_at, urgency, status, tags=None, due='', done=False, link=None, on_link=None):
        super().__init__()
        self.setObjectName('taskCard')
        dark = is_dark()
        stripe = '#94A3B8' if done else URGENCY_COLORS.get(urgency, '#2563EB')
        state, _ = due_state(due, done=done)
        bg = ('#1b2638' if dark else '#FFFFFF')
        border = '#344155' if dark else '#CBD5E1'
        if state == 'overdue':
            bg, border = ('#3b1d24', '#7f1d1d') if dark else ('#FEF2F2', '#FCA5A5')
        elif done:
            bg = '#202d40' if dark else '#F8FAFC'
        self.setStyleSheet(f"QFrame#taskCard {{ background-color: {bg}; border: 1px solid {border}; "
                           f"border-left: 4px solid {stripe}; border-radius: 8px; }} QLabel {{ border: none; background: transparent; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(5)

        lbl_title = QLabel(title)
        title_color = '#94A3B8' if done else ('#E5EDF8' if dark else '#0F172A')
        lbl_title.setStyleSheet(f"font-weight: bold; font-size: 13px; color: {title_color};" + (' text-decoration: line-through;' if done else ''))
        lbl_title.setWordWrap(True)
        layout.addWidget(lbl_title)

        if desc:
            short_desc = desc.replace('\n', ' ')
            lbl_desc = QLabel(short_desc if len(short_desc) <= 65 else short_desc[:62] + '...')
            lbl_desc.setStyleSheet('color: #64748B; font-size: 11px;')
            lbl_desc.setWordWrap(True)
            layout.addWidget(lbl_desc)

        label = due_label(due, done=done)
        if label:
            badge = QLabel(('⚠ ' if state == 'overdue' else '📅 ') + label)
            color = DUE_COLORS.get(state, '#65758B')
            if state == 'overdue':
                badge.setStyleSheet('color: #FFFFFF; background-color: #DC2626; border-radius: 6px; padding: 2px 8px; font-weight: bold; font-size: 11px;')
            else:
                badge.setStyleSheet(f'color: {color}; font-weight: 600; font-size: 11px;')
            badge.setAlignment(Qt.AlignmentFlag.AlignLeft)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(badge)
            row.addStretch()
            layout.addLayout(row)

        if link:
            from html import escape
            lbl_link = QLabel(f'<a href="open" style="color:#2563EB;text-decoration:none;">🔗 {escape(link)}</a>')
            lbl_link.setTextFormat(Qt.TextFormat.RichText)
            lbl_link.setWordWrap(True)
            lbl_link.setToolTip('Открыть связанную карточку')
            lbl_link.setStyleSheet('font-size: 11px;')
            if on_link:
                lbl_link.linkActivated.connect(lambda _=None: on_link())
            layout.addWidget(lbl_link)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        try:
            date_str = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
        except (ValueError, TypeError):
            date_str = created_at or ''
        lbl_date = QLabel(f'🕒 {date_str}')
        lbl_date.setStyleSheet('color: #94A3B8; font-size: 10px;')
        lbl_urgency = QLabel(urgency)
        lbl_urgency.setStyleSheet(f"color: {'#94A3B8' if done else URGENCY_COLORS.get(urgency, '#2563EB')}; font-weight: bold; font-size: 10px;")
        footer.addWidget(lbl_date)
        footer.addStretch()
        footer.addWidget(lbl_urgency)
        layout.addLayout(footer)

        if tags:
            lbl_tags = QLabel('&nbsp;'.join(chip_html(name, color, 10) for name, color in tags))
            lbl_tags.setTextFormat(Qt.TextFormat.RichText)
            lbl_tags.setWordWrap(True)
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
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setStyleSheet("QListWidget { background-color: transparent; border: none; } QListWidget::item { margin-bottom: 8px; } "
                           "QListWidget::item:selected { background: transparent; }")

    def dropEvent(self, event):
        super().dropEvent(event)
        for i in range(self.count()):
            task_id = self.item(i).data(Qt.ItemDataRole.UserRole)
            if task_id is not None:
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
    def __init__(self, task_id=None, parent=None, due=None, title='', link=None):
        super().__init__(parent)
        initial_title = title
        self.task_id = task_id
        self.setWindowTitle("Новая задача" if not task_id else "Редактирование задачи")
        self.resize(520, 520)

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

        # Срок выполнения
        row_due = QHBoxLayout()
        self.chk_due = QCheckBox("Срок выполнения:")
        self.dt_due = QDateEdit(QDate.currentDate())
        self.dt_due.setCalendarPopup(True)
        self.dt_due.setLocale(QLocale(QLocale.Language.Russian))
        self.dt_due.setDisplayFormat("dd.MM.yyyy")
        self.lbl_due = QLabel()
        row_due.addWidget(self.chk_due)
        row_due.addWidget(self.dt_due)
        for title, days in (("Сегодня", 0), ("Завтра", 1), ("+ неделя", 7)):
            b = QPushButton(title)
            b.clicked.connect(lambda _, d=days: self.set_due(QDate.currentDate().addDays(d)))
            row_due.addWidget(b)
        row_due.addWidget(self.lbl_due, 1)
        layout.addLayout(row_due)
        self.chk_due.toggled.connect(self.refresh_due)
        self.dt_due.dateChanged.connect(self.refresh_due)

        # связь с договором / проектом
        row_link = QHBoxLayout()
        row_link.addWidget(QLabel("Связать с:"))
        self.cmb_link_section = QComboBox()
        self.cmb_link_section.addItem("— без связи —", '')
        for table, name in board.LINK_SECTIONS.items():
            self.cmb_link_section.addItem(name, table)
        row_link.addWidget(self.cmb_link_section)
        self.cmb_link_record = QComboBox()
        self.cmb_link_record.setMinimumWidth(260)
        self.cmb_link_record.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row_link.addWidget(self.cmb_link_record, 1)
        layout.addLayout(row_link)
        self.cmb_link_section.currentIndexChanged.connect(lambda *_: self.fill_link_records())

        layout.addWidget(QLabel("Описание:"))
        self.inp_desc = QTextEdit()
        layout.addWidget(self.inp_desc)
        from .task_catalog import TaskFields
        self.task_fields = TaskFields(self.task_id)
        layout.addWidget(self.task_fields)

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
        else:
            if due:
                self.set_due(QDate.fromString(due, "yyyy-MM-dd"))
            if initial_title:
                self.inp_title.setText(initial_title)
            if link:
                self.set_link(*link)
        self.refresh_due()

    def fill_link_records(self, selected=None):
        table = self.cmb_link_section.currentData()
        self.cmb_link_record.clear()
        self.cmb_link_record.setEnabled(bool(table))
        if not table:
            return
        for rid, label in board.records(db, table):
            self.cmb_link_record.addItem(label, rid)
        if selected is not None:
            index = self.cmb_link_record.findData(selected)
            if index < 0:
                label = board.link_label(db, table, selected)
                if label:
                    self.cmb_link_record.addItem(label, selected)
                    index = self.cmb_link_record.count() - 1
            self.cmb_link_record.setCurrentIndex(max(0, index))

    def set_link(self, table, rid):
        self.cmb_link_section.blockSignals(True)
        self.cmb_link_section.setCurrentIndex(max(0, self.cmb_link_section.findData(table or '')))
        self.cmb_link_section.blockSignals(False)
        self.fill_link_records(rid)

    def link_value(self):
        table = self.cmb_link_section.currentData()
        return (table, self.cmb_link_record.currentData()) if table and self.cmb_link_record.currentData() else ('', None)

    def set_due(self, qdate):
        self.dt_due.setDate(qdate)
        self.chk_due.setChecked(True)

    def due_value(self):
        return self.dt_due.date().toString("yyyy-MM-dd") if self.chk_due.isChecked() else ''

    def refresh_due(self, *_):
        self.dt_due.setEnabled(self.chk_due.isChecked())
        label = due_label(self.due_value())
        state, _ = due_state(self.due_value())
        self.lbl_due.setText(label)
        self.lbl_due.setStyleSheet(f"color: {DUE_COLORS.get(state, '#65758B')}; font-weight: bold;")

    def load_task(self):
        row = db.fetchone("SELECT title, description, is_archived, urgency, due_date, link_table, link_id FROM kanban_tasks WHERE id=?", (self.task_id,))
        if row:
            self.set_link(row[5], row[6])
            self.inp_title.setText(row[0] or "")
            self.inp_desc.setPlainText(row[1] or "")
            self.cmb_urgency.setCurrentText(row[3] or "Обычная")
            due = norm_date(row[4])
            if due:
                self.set_due(QDate.fromString(due, "yyyy-MM-dd"))
            if row[2] == 1:
                self.btn_archive.setText("Вернуть из архива")
                self.btn_archive.clicked.disconnect()
                self.btn_archive.clicked.connect(self.unarchive_task)

    def save_task(self):
        title = self.inp_title.text().strip()
        if not title: return
        desc = self.inp_desc.toPlainText().strip()
        urgency = self.cmb_urgency.currentText()
        due = self.due_value()
        link_table, link_id = self.link_value()

        with db.transaction():
            if self.task_id:
                db.execute("UPDATE kanban_tasks SET title=?, description=?, urgency=?, due_date=?, link_table=?, link_id=? WHERE id=?",
                           (title, desc, urgency, due, link_table, link_id, self.task_id))
            else:
                self.task_id = db.execute("INSERT INTO kanban_tasks(title,description,status,is_archived,created_at,urgency,due_date,link_table,link_id) VALUES(?,?,?,0,?,?,?,?,?)",
                                          (title, desc, self.task_fields.status.currentData(), datetime.now().strftime('%Y-%m-%d %H:%M:%S'), urgency, due, link_table, link_id)).lastrowid
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


class KanbanTab(QWidget):
    changed = pyqtSignal()
    COLUMN_LIMIT = 50      # карточек в колонке; остальные открываются кнопкой «Показать ещё», иначе доска на тысячи задач открывается минутами

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        quick = QHBoxLayout()
        self.quick = QLineEdit()
        self.quick.setPlaceholderText("Новая задача… например: Сдать акт Иванова завтра #акт !   (Enter — добавить; срок: завтра, пт, 15.10, до 10-го; ! — важно)")
        self.quick.setClearButtonEnabled(True)
        self.quick.returnPressed.connect(self.quick_add)
        quick.addWidget(self.quick, 1)
        layout.addLayout(quick)

        top_bar = QHBoxLayout()
        btn_add = QPushButton("➕ Подробная задача")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.new_task)
        top_bar.addWidget(btn_add)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по задачам и тегам…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(180)
        self.search.textChanged.connect(self.load_boards)
        top_bar.addWidget(self.search, 1)

        self.cmb_sort = QComboBox()
        self.cmb_sort.addItems(["Сначала новые (по дате)", "Сначала старые (по дате)", "По срочности (сначала критические)", "По сроку выполнения"])
        self.cmb_sort.currentIndexChanged.connect(self.load_boards)
        top_bar.addWidget(self.cmb_sort)
        layout.addLayout(top_bar)

        second = QHBoxLayout()
        self.chk_overdue = QPushButton("⚠ Просроченные")
        self.chk_overdue.setCheckable(True)
        self.chk_overdue.toggled.connect(self.load_boards)
        second.addWidget(self.chk_overdue)
        self.chk_week = QPushButton("📅 На этой неделе")
        self.chk_week.setCheckable(True)
        self.chk_week.setToolTip("Срок в ближайшие 7 дней (просроченные тоже)")
        self.chk_week.toggled.connect(self.load_boards)
        second.addWidget(self.chk_week)
        self.btn_tags = QPushButton("🏷 Мои теги")
        self.btn_tags.setToolTip("Показывать только задачи с выбранными тегами")
        self.tag_menu = QMenu(self)
        self.tag_menu.aboutToShow.connect(self.fill_tag_menu)
        self.btn_tags.setMenu(self.tag_menu)
        self.selected_tags = set()
        second.addWidget(self.btn_tags)
        from .filters import SqlFilters
        self.filters = SqlFilters(self)
        self.filters.set_columns(['id', 'title', 'description', 'status', 'created_at', 'urgency', 'due_date'])
        self.filters.changed.connect(self.load_boards)
        second.addWidget(self.filters)
        second.addStretch()
        self.btn_suggest = QPushButton("💡 Предложения")
        self.btn_suggest.setToolTip("Задачи, которые программа предлагает создать: неподписанные договоры и акты, ведомость, устаревшие сметы")
        self.btn_suggest.clicked.connect(self.open_suggestions)
        second.addWidget(self.btn_suggest)
        btn_columns = QPushButton("⚙️ Теги и статусы")
        btn_columns.clicked.connect(self.manage_columns)
        second.addWidget(btn_columns)
        btn_archive = QPushButton("🗃️ Архив")
        btn_archive.clicked.connect(self.open_archive)
        second.addWidget(btn_archive)
        layout.addLayout(second)

        self.boards_container = QWidget()
        self.boards_layout = QHBoxLayout(self.boards_container)
        self.boards_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.boards_container)
        layout.addWidget(scroll, 1)

        self.columns = {}
        self.titles = {}
        self.expanded = set()
        self.rebuild_columns()

    def make_col(self, title, widget, color):
        w = QFrame()
        w.setObjectName('kanbanColumn')
        w.setMinimumWidth(235)
        w.setStyleSheet(f"QFrame#kanbanColumn {{ background-color: {rgba(color, 0.12)}; border-radius: 10px; }}")
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        lbl = QLabel()
        lbl.setStyleSheet(f"font-weight: bold; color: {color}; padding: 5px; font-size: 13px; background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(lbl)
        l.addWidget(widget)
        return w, lbl

    def rebuild_columns(self):
        while self.boards_layout.count():
            item = self.boards_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.columns = {}
        self.titles = {}
        self.status_info = {}

        for code, name, color, done in status_rows():
            col = KanbanListWidget(code)
            col.status_changed.connect(self.on_moved)
            col.doubleClicked.connect(self.edit_task)
            col.itemClicked.connect(self.on_item_clicked)
            col.delete_requested.connect(self.delete_task_from_menu)
            self.columns[code] = col
            self.status_info[code] = (name, color, bool(done))
            frame, lbl = self.make_col(name, col, color)
            self.titles[code] = lbl
            self.boards_layout.addWidget(frame)

    def on_item_clicked(self, item):
        if item.data(Qt.ItemDataRole.UserRole + 1) == 'more':
            self.expanded.add(self.sender().status_code)
            self.load_boards()

    def on_moved(self):
        self.load_boards()
        self.changed.emit()

    def manage_columns(self):
        from .task_catalog import CatalogDialog
        CatalogDialog(self).exec()
        self.rebuild_columns()
        self.load_boards()
        self.changed.emit()

    def load_boards(self, *_):
        for col in self.columns.values():
            col.clear()

        order_by = {
            0: "ORDER BY id DESC",
            1: "ORDER BY id ASC",
            2: "ORDER BY CASE urgency WHEN 'Критическая' THEN 1 WHEN 'Высокая' THEN 2 WHEN 'Обычная' THEN 3 WHEN 'Низкая' THEN 4 ELSE 5 END, id DESC",
            3: "ORDER BY CASE WHEN coalesce(due_date,'')='' THEN 1 ELSE 0 END, due_date, id DESC",
        }[self.cmb_sort.currentIndex()]

        base = ("SELECT id, title, description, status, created_at, urgency, coalesce(due_date,'') AS due_date, coalesce(link_table,''), link_id FROM kanban_tasks WHERE is_archived=0")
        params = []
        needle = self.search.text().strip().casefold()
        if needle:
            base += (" AND LOWER(title||' '||coalesce(description,'')||' '||coalesce(tags,'')) LIKE ?")
            params.append('%' + needle + '%')
        query, params = self.filters.apply(base, params)
        rows = db.fetchall(f"{query} {order_by}", params)

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
        fallback_code = next(iter(self.columns), None)
        counts = {code: 0 for code in self.columns}
        only_overdue = self.chk_overdue.isChecked()
        only_week = self.chk_week.isChecked()
        hidden = {}
        week_end = date.today() + timedelta(days=6)
        for t_id, title, desc, status, created, urgency, due, link_table, link_id in rows:
            col_code = status if status in self.columns else fallback_code
            done = self.status_info.get(col_code, ('', '', False))[2]
            if only_overdue and due_state(due, done=done)[0] != 'overdue':
                continue
            if only_week and (done or not norm_date(due) or norm_date(due) > week_end.isoformat()):
                continue
            if self.selected_tags and not self.selected_tags & {n.casefold() for n, _c in tags_by_task.get(t_id, [])}:
                continue
            if counts[col_code] >= self.COLUMN_LIMIT and col_code not in self.expanded:
                hidden[col_code] = hidden.get(col_code, 0) + 1
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, t_id)

            link = board.link_label(db, link_table, link_id)
            card = TaskCardWidget(title, desc, created, urgency or "Обычная", status, tags_by_task.get(t_id), due, done, link,
                                  (lambda t=link_table, i=link_id: self.open_linked(t, i)) if link else None)
            hint = card.sizeHint()
            hint.setHeight(hint.height() + 6)
            item.setSizeHint(hint)

            if col_code is not None:
                col = self.columns[col_code]
                col.addItem(item)
                col.setItemWidget(item, card)
                counts[col_code] += 1
        for code, extra in hidden.items():
            more = QListWidgetItem(f"▼ Показать ещё {extra} (всего {counts[code] + extra})")
            more.setData(Qt.ItemDataRole.UserRole, None)
            more.setData(Qt.ItemDataRole.UserRole + 1, 'more')
            more.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            more.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.columns[code].addItem(more)
            counts[code] += extra
        for code, lbl in self.titles.items():
            lbl.setText(f"{self.status_info[code][0].upper()}  ·  {counts[code]}")
        self.update_suggest_button()

    def refresh_ui(self):
        self.load_boards()
        self.update_suggest_button()

    def quick_add(self):
        text = self.quick.text().strip()
        if not text:
            return
        try:
            task = board.add_quick(db, text)
        except ValueError as e:
            QMessageBox.warning(self, "Задача", str(e))
            return
        self.quick.clear()
        self.load_boards()
        self.changed.emit()
        bits = [f"срок {datetime.strptime(task['due'], '%Y-%m-%d').strftime('%d.%m.%Y')}" if task['due'] else '', ' '.join('#' + t for t in task['tags']),
                task['urgency'] if task['urgency'] != 'Обычная' else '']
        self.quick.setPlaceholderText("Добавлено: " + task['title'] + ' · ' + ' · '.join(b for b in bits if b))

    def fill_tag_menu(self):
        self.tag_menu.clear()
        for (name,) in db.fetchall('SELECT name FROM task_tags ORDER BY name'):
            act = self.tag_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(name.casefold() in self.selected_tags)
            act.toggled.connect(lambda on, n=name.casefold(): self.toggle_tag(n, on))
        if self.selected_tags:
            self.tag_menu.addSeparator()
            self.tag_menu.addAction("Сбросить выбор").triggered.connect(self.clear_tags)

    def toggle_tag(self, name, on):
        (self.selected_tags.add if on else self.selected_tags.discard)(name)
        self.btn_tags.setText(f"🏷 Мои теги ({len(self.selected_tags)})" if self.selected_tags else "🏷 Мои теги")
        self.load_boards()

    def clear_tags(self):
        self.selected_tags.clear()
        self.btn_tags.setText("🏷 Мои теги")
        self.load_boards()

    def open_linked(self, table, rid):
        from .workspace_view import open_record
        open_record(table, rid, self)
        self.load_boards()
        self.changed.emit()

    def update_suggest_button(self):
        try:
            n = len(board.suggestions(db))
        except Exception:
            n = 0
        self.btn_suggest.setText(f"💡 Предложения ({n})" if n else "💡 Предложения")

    def open_suggestions(self):
        SuggestionsDialog(self).exec()
        self.load_boards()
        self.changed.emit()

    def new_task(self):
        if TaskEditDialog(parent=self).exec():
            self.load_boards()
            self.changed.emit()

    def edit_task(self, index):
        widget = self.sender()
        if isinstance(widget, QListWidget):
            t_id = widget.itemFromIndex(index).data(Qt.ItemDataRole.UserRole)
            if TaskEditDialog(t_id, self).exec():
                self.load_boards()
                self.changed.emit()

    def delete_task_from_menu(self, task_id):
        if QMessageBox.question(self, "Удаление", "Точно удалить задачу безвозвратно?") == QMessageBox.StandardButton.Yes:
            db.execute("DELETE FROM kanban_tasks WHERE id=?", (task_id,))
            self.load_boards()
            self.changed.emit()

    def open_archive(self):
        ArchiveDialog(self).exec()
        self.changed.emit()


class SuggestionsDialog(QDialog):
    """Предложения автозадач: отметить нужные и создать, остальные — скрыть."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Предложения задач")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Программа заметила, что стоит сделать. Отметьте нужные и нажмите «Создать» — они появятся на доске. «Скрыть» убирает предложение насовсем."))
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        bar = QHBoxLayout()
        all_btn = QPushButton("Отметить все")
        all_btn.clicked.connect(lambda: self.mark(Qt.CheckState.Checked))
        bar.addWidget(all_btn)
        bar.addStretch()
        hide = QPushButton("Скрыть отмеченные")
        hide.clicked.connect(self.hide_checked)
        bar.addWidget(hide)
        create = QPushButton("Создать отмеченные")
        create.setProperty("type", "primary")
        create.clicked.connect(self.create_checked)
        bar.addWidget(create)
        layout.addLayout(bar)
        self.load()

    def load(self):
        self.list.clear()
        self.items = board.suggestions(db)
        for s in self.items:
            text = s['title'] + (f"  —  {s['reason']}" if s.get('reason') else '') + (f"  (срок {datetime.strptime(s['due'], '%Y-%m-%d').strftime('%d.%m.%Y')})" if s.get('due') else '')
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, s['key'])
            self.list.addItem(item)
        if not self.items:
            self.list.addItem("Предложений нет — всё под контролем.")

    def mark(self, state):
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)

    def checked(self):
        keys = {self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.CheckState.Checked}
        return [s for s in self.items if s['key'] in keys]

    def create_checked(self):
        for s in self.checked():
            board.create_from_suggestion(db, s)
        self.load()

    def hide_checked(self):
        for s in self.checked():
            board.dismiss(db, s['key'])
        self.load()


def new_task_for(parent, table, rid):
    """Кнопка «Создать задачу» в карточках договоров и проектов: задача уже связана с карточкой."""
    title, due = board.default_task_for(db, table, rid)
    return TaskEditDialog(parent=parent, due=due, title=title, link=(table, rid)).exec()


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

