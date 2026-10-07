"""
Вкладка "Проекты ГСВ": учет проектирования, генерация договоров, контроль
сроков и аналитика по объектам газоснабжения.
"""
import os
import logging
from datetime import datetime, date

import openpyxl

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableView, QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QDateEdit, QFileDialog, QDialog, QHeaderView, QMessageBox,
    QScrollArea, QFrame, QGridLayout, QGroupBox, QDoubleSpinBox, QSplitter, QCheckBox, QTableWidget, QTableWidgetItem,
    QMenu, QApplication, QAbstractItemView, QListWidget, QListWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import Qt, QDate, QAbstractTableModel, QModelIndex, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut, QPixmap, QIcon

from .database import db
from .domain_widgets import ClientForm, OptionalDate
from . import gsv_project_domain as gsvdom
from .agenda_domain import PALETTE
from .task_catalog import chip_html
from .gsv_domain import save_client, get_client
from PyQt6.QtWidgets import QTabWidget
from .pagination import RegistryPager
from .platform_utils import open_local

from .config import DATA_DIR
APP_DIR = str(DATA_DIR)
BASE_PROJECTS_DIR = os.path.join(APP_DIR, "projects")
TEMPLATES_DIR = os.path.join(APP_DIR, "templates")
DEFAULT_TEMPLATE_PATH = os.path.join(TEMPLATES_DIR, "contract_template.docx")
BACKUP_DIR = os.path.join(APP_DIR, "backups")
BACKUP_EXCEL_DIR = os.path.join(BACKUP_DIR, "excel")

os.makedirs(BASE_PROJECTS_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(BACKUP_EXCEL_DIR, exist_ok=True)

from .gsv_project_domain import MONTHS_GENITIVE, format_date_word, get_initials_first, format_cost_rubles, num_to_words_byn

def open_file_or_dir(path):
    if path and os.path.exists(path): open_local(os.path.abspath(path))
    else: QMessageBox.warning(None, "Путь не найден", f"Указанный файл или папка не существует:\n{path}")

def print_document_file(path):
    if path and os.path.exists(path):
        try: open_local(os.path.abspath(path), "print")
        except Exception as e: QMessageBox.critical(None, "Ошибка печати", f"Не удалось отправить файл на печать:\n{e}")
    else: QMessageBox.warning(None, "Файл не найден", f"Файл для печати не существует:\n{path}")

class TemplateSettingsPanel(QWidget):
    """Шаблоны документов раздела «Проекты ГСВ». Настройки относятся только к этому разделу."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        note = QLabel("Шаблоны и теги этого раздела не смешиваются с монтажом ГСВ, монтажом ГСН и другими модулями. "
                      "Если шаблон не выбран, используется стандартный. Теги пишутся в фигурных скобках, например {НОМЕР_ДОГОВОРА}.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.edits = {}
        grp = QGroupBox("Файлы шаблонов")
        grid = QGridLayout(grp)
        for r, (kind, (title, key, _default, _prefix)) in enumerate(gsvdom.DOC_KINDS.items()):
            grid.addWidget(QLabel(title + ":"), r, 0)
            edit = QLineEdit(db.get_setting(key, ""))
            edit.setReadOnly(True)
            edit.setPlaceholderText("Стандартный шаблон")
            self.edits[kind] = edit
            grid.addWidget(edit, r, 1)
            for c, (text, fn) in enumerate((("Выбрать…", lambda _=False, k=kind: self.browse(k)),
                                             ("Открыть", lambda _=False, k=kind: self.open_template(k)),
                                             ("Стандартный", lambda _=False, k=kind: self.reset(k))), 2):
                b = QPushButton(text)
                b.clicked.connect(fn)
                grid.addWidget(b, r, c)
        layout.addWidget(grp)

        grp_tags = QGroupBox("Теги раздела «Проекты ГСВ»")
        l_tags = QVBoxLayout(grp_tags)
        self.table_tags = QTableWidget(len(gsvdom.TAGS), 3)
        self.table_tags.setHorizontalHeaderLabels(["Тег", "Что подставится", "Действие"])
        self.table_tags.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_tags.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_tags.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_tags.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_tags.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        for r, (tag, desc) in enumerate(gsvdom.TAGS):
            item_tag = QTableWidgetItem("{" + tag + "}")
            item_tag.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            self.table_tags.setItem(r, 0, item_tag)
            self.table_tags.setItem(r, 1, QTableWidgetItem(desc))
            btn_copy = QPushButton("Копировать")
            btn_copy.clicked.connect(lambda ch=False, t="{" + tag + "}", b=btn_copy: self.copy_tag(t, b))
            self.table_tags.setCellWidget(r, 2, btn_copy)
        l_tags.addWidget(self.table_tags)
        layout.addWidget(grp_tags, 1)
        self.lbl_status = QLabel("")
        layout.addWidget(self.lbl_status)

    def copy_tag(self, tag_text, btn):
        QApplication.clipboard().setText(tag_text)
        btn.setText("Скопировано!")
        QTimer.singleShot(1500, lambda: btn.setText("Копировать"))

    def browse(self, kind):
        flt = "Excel (*.xlsx)" if kind == "card" else "Word (*.docx)"
        path, _ = QFileDialog.getOpenFileName(self, "Выберите шаблон", "", flt)
        if path:
            self.set_template(kind, path)

    def set_template(self, kind, path):
        db.set_setting(gsvdom.DOC_KINDS[kind][1], path)
        self.edits[kind].setText(path)
        self.lbl_status.setText("Шаблон сохранён. Уже созданные документы пометятся для переформирования при изменении данных договора.")

    def open_template(self, kind):
        open_file_or_dir(gsvdom.template_path(db, kind))

    def reset(self, kind):
        db.set_setting(gsvdom.DOC_KINDS[kind][1], "")
        self.edits[kind].setText("")
        self.lbl_status.setText("Используется стандартный шаблон.")


class TemplateSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Шаблоны документов · Проекты ГСВ")
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(TemplateSettingsPanel(self))
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(btn_close)
        layout.addLayout(bar)


class StatusPage(QWidget):
    """Редактор одного справочника статусов (работы или клиента)."""
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.current_id = None
        self.color = PALETTE[0]
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setStyleSheet('QListWidget::item { padding: 7px 8px; border-radius: 6px; margin: 1px 2px; } QListWidget::item:hover { background: rgba(37,99,235,0.12); } QListWidget::item:selected, QListWidget::item:selected:active, QListWidget::item:selected:!active { background: #2563eb; color: #ffffff; font-weight: 600; }')
        left.addWidget(self.list, 1)
        bar = QHBoxLayout()
        self.btn_new = QPushButton("＋ Новый")
        self.btn_new.setProperty("type", "primary")
        self.btn_up = QPushButton("▲")
        self.btn_down = QPushButton("▼")
        for b in (self.btn_up, self.btn_down):
            b.setFixedWidth(36)
        for b in (self.btn_new, self.btn_up, self.btn_down):
            bar.addWidget(b)
        bar.addStretch()
        left.addLayout(bar)
        root.addLayout(left, 5)
        form = QFrame()
        form.setObjectName("metricCard")
        fl = QVBoxLayout(form)
        self.heading = QLabel()
        self.heading.setStyleSheet("font-weight: 700; font-size: 14px;")
        fl.addWidget(self.heading)
        fl.addWidget(QLabel("Название"))
        self.name = QLineEdit()
        fl.addWidget(self.name)
        fl.addWidget(QLabel("Цвет"))
        row = QHBoxLayout()
        self.swatches = []
        for color in PALETTE:
            b = QToolButton()
            b.setFixedSize(24, 24)
            b.clicked.connect(lambda _, c=color: self.set_color(c))
            self.swatches.append((color, b))
            row.addWidget(b)
        row.addStretch()
        fl.addLayout(row)
        self.preview = QLabel()
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        fl.addWidget(self.preview)
        self.usage = QLabel()
        self.usage.setStyleSheet("color: #65758b;")
        fl.addWidget(self.usage)
        fl.addStretch()
        row = QHBoxLayout()
        self.btn_delete = QPushButton("Удалить")
        self.btn_delete.setProperty("type", "danger")
        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setProperty("type", "primary")
        row.addWidget(self.btn_delete)
        row.addStretch()
        row.addWidget(self.btn_save)
        fl.addLayout(row)
        root.addWidget(form, 4)
        self.list.currentItemChanged.connect(lambda cur, _: self.select(cur))
        self.btn_new.clicked.connect(self.start_new)
        self.btn_save.clicked.connect(self.save)
        self.btn_delete.clicked.connect(self.remove)
        self.btn_up.clicked.connect(lambda: self.move(-1))
        self.btn_down.clicked.connect(lambda: self.move(1))
        self.name.textChanged.connect(self.update_preview)
        self.load()
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.start_new()

    def load(self, select=None):
        wanted = select or self.current_id
        self.list.blockSignals(True)
        self.list.clear()
        for sid, name, color in gsvdom.catalog(db, self.kind):
            pix = QPixmap(14, 14)
            pix.fill(QColor(color))
            item = QListWidgetItem(QIcon(pix), f"{name}   ·   {gsvdom.status_usage(db, sid)}")
            item.setData(Qt.ItemDataRole.UserRole, sid)
            self.list.addItem(item)
            if sid == wanted:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def set_color(self, color):
        self.color = color
        self.update_preview()

    def update_preview(self, *_):
        for color, b in self.swatches:
            b.setStyleSheet(f'QToolButton {{ background: {color}; border-radius: 12px; border: {"3px solid #0f172a" if color == self.color else "1px solid #94a3b8"}; }}')
        self.preview.setText(chip_html(self.name.text().strip() or "Статус", self.color, 13))

    def start_new(self):
        self.current_id = None
        self.list.blockSignals(True)
        self.list.setCurrentItem(None)
        self.list.blockSignals(False)
        self.heading.setText("Новый статус")
        self.name.clear()
        self.color = PALETTE[self.list.count() % len(PALETTE)]
        self.usage.setText("")
        self.btn_delete.setEnabled(False)
        self.update_preview()
        self.name.setFocus()

    def select(self, item):
        if not item:
            return
        sid = item.data(Qt.ItemDataRole.UserRole)
        self.current_id = sid
        name, color = db.fetchone("SELECT name,coalesce(color,'#2563EB') FROM gsv_status_catalog WHERE id=?", (sid,))
        self.heading.setText(f"Статус «{name}»")
        self.name.setText(name)
        self.color = color
        self.usage.setText(f"Используется в проектах: {gsvdom.status_usage(db, sid)}")
        self.btn_delete.setEnabled(True)
        self.update_preview()

    def save(self):
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Статусы", "Введите название")
            return
        try:
            with db.transaction():
                if self.current_id:
                    db.execute("UPDATE gsv_status_catalog SET name=?,color=? WHERE id=?", (name, self.color, self.current_id))
                else:
                    order = (db.fetchone("SELECT max(sort_order) FROM gsv_status_catalog WHERE kind=?", (self.kind,))[0] or 0) + 1
                    self.current_id = db.execute("INSERT INTO gsv_status_catalog(kind,name,color,sort_order) VALUES(?,?,?,?)", (self.kind, name, self.color, order)).lastrowid
                db.execute("UPDATE gsv_projects SET work_status=(SELECT coalesce(group_concat(name,', '),'') FROM (SELECT c.name FROM gsv_project_statuses p JOIN gsv_status_catalog c ON c.id=p.status_id WHERE p.project_id=gsv_projects.id AND c.kind='work' ORDER BY c.sort_order,c.id)),"
                           "client_status=(SELECT coalesce(group_concat(name,', '),'') FROM (SELECT c.name FROM gsv_project_statuses p JOIN gsv_status_catalog c ON c.id=p.status_id WHERE p.project_id=gsv_projects.id AND c.kind='client' ORDER BY c.sort_order,c.id))")
        except Exception as e:
            QMessageBox.warning(self, "Статусы", "Такой статус уже есть" if "UNIQUE" in str(e) else str(e))
            return
        self.load(select=self.current_id)
        self.select(self.list.currentItem())

    def move(self, direction):
        sid = self.current_id
        if not sid:
            return
        ids = [r[0] for r in gsvdom.catalog(db, self.kind)]
        i = ids.index(sid)
        j = i + direction
        if not 0 <= j < len(ids):
            return
        ids[i], ids[j] = ids[j], ids[i]
        with db.transaction():
            for order, rid in enumerate(ids, 1):
                db.execute("UPDATE gsv_status_catalog SET sort_order=? WHERE id=?", (order, rid))
        self.load(select=sid)

    def remove(self):
        sid = self.current_id
        if not sid:
            return
        if gsvdom.status_usage(db, sid):
            QMessageBox.warning(self, "Используется", "Сначала снимите этот статус с проектов, где он выбран.")
            return
        if QMessageBox.question(self, "Удаление", "Удалить статус из справочника?") == QMessageBox.StandardButton.Yes:
            db.execute("DELETE FROM gsv_status_catalog WHERE id=?", (sid,))
            self.current_id = None
            self.load()
            if self.list.count():
                self.list.setCurrentRow(0)
            else:
                self.start_new()


class StatusEditorDialog(QDialog):
    """Редактор статусов работы и клиента для проектов ГСВ."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Статусы проектов ГСВ")
        self.resize(780, 480)
        layout = QVBoxLayout(self)
        hint = QLabel("На одном проекте можно выбрать несколько статусов работы и несколько статусов клиента. Здесь они добавляются, переименовываются и перекрашиваются.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #65758b;")
        layout.addWidget(hint)
        self.tabs = QTabWidget()
        self.tabs.addTab(StatusPage("work"), "Статусы работы")
        self.tabs.addTab(StatusPage("client"), "Статусы клиента")
        layout.addWidget(self.tabs, 1)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)


def export_all_to_excel(parent_window):
    save_path, _ = QFileDialog.getSaveFileName(parent_window, "Сохранить карточки договоров в Excel", f"Проекты_ГСВ_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", "Excel (*.xlsx)")
    if not save_path: return
    try:
        count = gsvdom.export_cards(db, save_path)
        QMessageBox.information(parent_window, "Экспорт", f"Выгружено карточек: {count}.")
        open_file_or_dir(save_path)
    except Exception as e: QMessageBox.critical(parent_window, "Ошибка", str(e))

class ReportsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Отчёты и Аналитика")
        self.resize(1150, 720)
        self.setup_ui()
        self.set_period_preset("Текущий месяц")
        self.generate_report()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        filter_card = QFrame()
        f_layout = QGridLayout(filter_card)
        f_layout.addWidget(QLabel("Тип аналитики:"), 0, 0)
        self.cmb_report_type = QComboBox()
        self.cmb_report_type.addItems(["Сдано (акт подписан)", "Оплачено", "Договор и акт подписаны", "Сводный отчет"])
        f_layout.addWidget(self.cmb_report_type, 0, 1, 1, 3)
        self.cmb_period_preset = QComboBox()
        self.cmb_period_preset.addItems(["Сегодня", "Текущая неделя", "Текущий месяц", "Текущий год"])
        self.cmb_period_preset.currentTextChanged.connect(self.set_period_preset)
        f_layout.addWidget(self.cmb_period_preset, 1, 1)
        self.dt_from = QDateEdit(calendarPopup=True)
        self.dt_to = QDateEdit(calendarPopup=True)
        f_layout.addWidget(self.dt_from, 1, 3)
        f_layout.addWidget(self.dt_to, 1, 5)
        self.btn_run_report = QPushButton("Сформировать")
        self.btn_run_report.clicked.connect(self.generate_report)
        f_layout.addWidget(self.btn_run_report, 1, 6)
        layout.addWidget(filter_card)

        kpi_layout = QHBoxLayout()
        self.lbl_kpi_count_val = QLabel("0")
        self.lbl_kpi_sum_val = QLabel("0,00 рублей")
        kpi_layout.addWidget(QLabel("Объектов в выборке:")); kpi_layout.addWidget(self.lbl_kpi_count_val)
        kpi_layout.addWidget(QLabel("Сумма:")); kpi_layout.addWidget(self.lbl_kpi_sum_val)
        layout.addLayout(kpi_layout)

        self.table_report = QTableWidget()
        self.table_report.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_report.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_report.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table_report.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table_report)

        bottom_bar = QHBoxLayout()
        self.btn_export = QPushButton("Экспорт в Excel")
        self.btn_export.clicked.connect(self.export_report_to_excel)
        bottom_bar.addWidget(self.btn_export)
        bottom_bar.addStretch()
        layout.addLayout(bottom_bar)

    def set_period_preset(self, preset_name):
        today = QDate.currentDate()
        if preset_name == "Сегодня":
            self.dt_from.setDate(today); self.dt_to.setDate(today)
        elif preset_name == "Текущая неделя":
            start = today.addDays(-(today.dayOfWeek() - 1))
            self.dt_from.setDate(start); self.dt_to.setDate(start.addDays(6))
        elif preset_name == "Текущий месяц":
            self.dt_from.setDate(QDate(today.year(), today.month(), 1))
            self.dt_to.setDate(QDate(today.year(), today.month(), today.daysInMonth()))
        elif preset_name == "Текущий год":
            self.dt_from.setDate(QDate(today.year(), 1, 1)); self.dt_to.setDate(QDate(today.year(), 12, 31))

    def generate_report(self):
        d_from, d_to = self.dt_from.date().toString("yyyy-MM-dd"), self.dt_to.date().toString("yyyy-MM-dd")
        rep_type = self.cmb_report_type.currentIndex()
        sql = "SELECT pd_number, object_name, coalesce(nullif(client_name,''),party_name), contract_number, contract_date, due_date, act_date, cost, work_status, client_status FROM gsv_projects WHERE 1=1"
        params = []
        # «Сдано» — только с подписанным актом; «Оплачено» — выбран статус клиента «Оплачено»
        if rep_type == 0: sql += " AND act_signed = 1 AND act_date BETWEEN ? AND ?"; params.extend([d_from, d_to])
        elif rep_type == 1: sql += " AND EXISTS(SELECT 1 FROM gsv_project_statuses s JOIN gsv_status_catalog c ON c.id=s.status_id WHERE s.project_id=gsv_projects.id AND c.kind='client' AND c.name='Оплачено') AND act_date IS NOT NULL AND act_date BETWEEN ? AND ?"; params.extend([d_from, d_to])
        elif rep_type == 2: sql += " AND contract_signed = 1 AND act_signed = 1 AND act_date BETWEEN ? AND ?"; params.extend([d_from, d_to])
        else: sql += " AND contract_date BETWEEN ? AND ?"; params.extend([d_from, d_to])

        sql += " ORDER BY contract_date DESC"
        self.current_report_rows = db.fetchall(sql, tuple(params))

        headers = ["Номер ПД", "Объект", "Заказчик", "Договор", "Дата закл.", "Срок исп.", "Дата акта", "Стоимость", "Статус работы", "Статус клиента"]
        self.table_report.setColumnCount(len(headers))
        self.table_report.setHorizontalHeaderLabels(headers)
        self.table_report.setRowCount(0)

        total_sum = 0.0
        for r, row in enumerate(self.current_report_rows):
            self.table_report.insertRow(r)
            cost_val = row[7] if row[7] else 0.0
            total_sum += cost_val
            data = [row[0], row[1], row[2], row[3], format_date_word(row[4]), format_date_word(row[5]), format_date_word(row[6]) if row[6] else "—", format_cost_rubles(cost_val), row[8], row[9]]
            for c, val in enumerate(data):
                item = QTableWidgetItem(str(val or ""))
                if c == 7: item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table_report.setItem(r, c, item)
        self.lbl_kpi_count_val.setText(str(len(self.current_report_rows)))
        self.lbl_kpi_sum_val.setText(format_cost_rubles(total_sum))
        self.current_total_sum = total_sum

    def export_report_to_excel(self):
        if not hasattr(self, "current_report_rows") or not self.current_report_rows: return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить отчет", f"Отчет_ГСВ_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", "Excel (*.xlsx)")
        if not path: return
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Номер ПД", "Объект", "Заказчик", "Номер договора", "Дата", "Срок", "Дата акта", "Стоимость", "Статус работы", "Статус клиента"])
        for row in self.current_report_rows:
            ws.append([row[0], row[1], row[2], row[3], row[4], row[5], row[6] or "—", row[7] or 0.0, row[8], row[9]])
        for sheet in wb.worksheets:
            for row_cells in sheet:
                for cell in row_cells:
                    if isinstance(cell.value, str): cell.data_type = "s"
        wb.save(path)
        open_file_or_dir(path)

class FastCompactTableModel(QAbstractTableModel):
    HEADERS = ["Номер ПД", "Объект строительства", "Заказчик", "Срок сдачи", "Стоимость", "Статус клиента"]
    def __init__(self, data=None, dark_mode=False):
        super().__init__()
        self._data = data or []
        self.dark_mode = dark_mode

    def rowCount(self, parent=QModelIndex()): return len(self._data)
    def columnCount(self, parent=QModelIndex()): return len(self.HEADERS)
    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole: return self.HEADERS[section]
        return None

    def set_dark_mode(self, dark_mode):
        self.dark_mode = dark_mode
        self.layoutChanged.emit()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        row = self._data[index.row()]
        col = index.column()
        # столбцы: 0 id, 1 № ПД, 2 объект, 3 клиент, 4 стоимость, 5 статусы клиента, 6 статусы работы, 7 папка, 8 срок, 9 акт подписан, 10 дата акта
        client_status, due_date_str = row[5], row[8]
        delivered = bool(row[9])
        days_left, is_overdue, is_urgent = None, False, False

        # Работа считается сданной только после подписания акта.
        if due_date_str and not delivered:
            try:
                due_dt = datetime.strptime(due_date_str[:10], "%Y-%m-%d").date()
                delta_days = (due_dt - date.today()).days
                days_left = delta_days
                if delta_days < 0: is_overdue = True
                elif delta_days <= 5: is_urgent = True
            except (ValueError, TypeError): pass

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0: return row[1]
            if col == 1: return row[2] or "—"
            if col == 2: return row[3] or "—"
            if col == 3:
                if delivered: return f"✅ Сдан ({format_date_word(row[10] or due_date_str)})"
                if is_overdue: return f"⚠️ Просрочен на {abs(days_left)} дн."
                if is_urgent: return f"⏳ Осталось {days_left} дн."
                return format_date_word(due_date_str)
            if col == 4: return format_cost_rubles(row[4] if row[4] is not None else 250.0)
            if col == 5: return client_status or "—"

        if role == Qt.ItemDataRole.ToolTipRole and col == 5:
            return f"Статус работы: {row[6] or '—'}\nСтатус клиента: {client_status or '—'}"

        if role == Qt.ItemDataRole.BackgroundRole:
            if delivered: return QColor(16, 185, 129, 35) if self.dark_mode else QColor(220, 252, 231)
            if is_overdue: return QColor(239, 68, 68, 45) if self.dark_mode else QColor(254, 205, 205)
            if is_urgent: return QColor(245, 158, 11, 40) if self.dark_mode else QColor(254, 243, 199)
            return QColor(239, 68, 68, 20) if self.dark_mode else QColor(254, 242, 242)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0: return QColor(96, 165, 250) if self.dark_mode else QColor(37, 99, 235)
            if self.dark_mode:
                if delivered: return QColor(167, 243, 208)
                if is_overdue: return QColor(254, 202, 202)
                if is_urgent: return QColor(253, 230, 138)
                return QColor(248, 250, 252)
            else:
                if delivered: return QColor(22, 101, 52)
                if is_overdue: return QColor(153, 27, 27)
                if is_urgent: return QColor(146, 64, 14)
                return QColor(15, 23, 42)

        if role == Qt.ItemDataRole.FontRole and col in (0, 3):
            font = QFont()
            font.setBold(True)
            return font
        return None

    def update_data(self, new_data):
        self.beginResetModel()
        self._data = new_data
        self.endResetModel()

    def get_row_record(self, row_idx):
        return self._data[row_idx] if 0 <= row_idx < len(self._data) else None

class ProjectEditDialog(QDialog):
    """Договор на проект ГСВ: первичный документ раздела. После первого сохранения поля закрыты до нажатия «Изменить»."""
    def __init__(self, project_id=None, parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self.is_new = project_id is None
        self.is_editing_enabled = self.is_new
        self.resize(1200, 890)
        self.setup_ui()
        self.reload_status_lists()
        if not self.is_new:
            self.load_data()
            self.set_fields_enabled(False)
        else:
            self.setWindowTitle("Новый договор · проект ГСВ")
            self.setup_new_record()
            self.refresh_docs()
            self.refresh_folder()

    # --- интерфейс ---
    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        grp_sys = QGroupBox("Идентификация проекта и стоимость")
        l_sys = QGridLayout(grp_sys)
        l_sys.addWidget(QLabel("Номер ПД:"), 0, 0)
        self.txt_pd = QLineEdit()
        self.txt_pd.setReadOnly(True)
        l_sys.addWidget(self.txt_pd, 0, 1)
        l_sys.addWidget(QLabel("Номер договора:"), 0, 2)
        self.txt_contract_num = QLineEdit()
        self.txt_contract_num.setReadOnly(True)
        l_sys.addWidget(self.txt_contract_num, 0, 3)
        l_sys.addWidget(QLabel("Стоимость:"), 1, 0)
        self.spn_cost = QDoubleSpinBox()
        self.spn_cost.setRange(0.0, 1000000.0)
        self.spn_cost.setDecimals(2)
        self.spn_cost.setSuffix(" BYN")
        self.spn_cost.setValue(250.0)
        l_sys.addWidget(self.spn_cost, 1, 1)
        l_sys.addWidget(QLabel("Номера присваиваются автоматически при первом сохранении."), 1, 2, 1, 2)
        layout.addWidget(grp_sys)

        grp_info = QGroupBox("Объект проектирования")
        l_info = QGridLayout(grp_info)
        self.txt_object = QLineEdit()
        self.txt_object.setPlaceholderText("Наименование объекта согласно техническим условиям")
        self.txt_address = QLineEdit()
        l_info.addWidget(QLabel("Объект:"), 0, 0)
        l_info.addWidget(self.txt_object, 0, 1)
        l_info.addWidget(QLabel("Адрес объекта:"), 1, 0)
        l_info.addWidget(self.txt_address, 1, 1)
        self.txt_tu = QLineEdit()
        self.txt_tu.setPlaceholderText("Номер и дата технических условий, выданных клиенту, например: № 123 от 01.02.2026")
        l_info.addWidget(QLabel("ТУ:"), 2, 0)
        l_info.addWidget(self.txt_tu, 2, 1)
        layout.addWidget(grp_info)

        from .counterparty_ui import CustomerSwitch
        self.customer = CustomerSwitch('gsv_projects', lambda: self.project_id, self.save_data)
        self.customer.changed.connect(self.apply_customer_mode)
        layout.addWidget(self.customer)
        self.client_form = ClientForm()
        layout.addWidget(self.client_form)
        self.txt_client = self.client_form.name
        self.txt_phone = self.client_form.phone
        self.txt_passport = self.client_form.passport
        self.txt_notes = QTextEdit()
        self.txt_notes.setMaximumHeight(65)
        self.txt_notes.setPlaceholderText("Примечания по объекту")
        layout.addWidget(self.txt_notes)

        grp_dates = QGroupBox("Сроки")
        l_dates = QGridLayout(grp_dates)
        l_dates.addWidget(QLabel("Дата заключения:"), 0, 0)
        self.dt_contract = QDateEdit(calendarPopup=True)
        self.dt_contract.setDisplayFormat("dd.MM.yyyy")
        self.dt_contract.setDate(QDate.currentDate())
        self.prev_contract = QDate.currentDate()
        self.dt_contract.dateChanged.connect(self.on_contract_date)
        l_dates.addWidget(self.dt_contract, 0, 1)
        self.chk_contract_signed = QCheckBox("Договор подписан")
        l_dates.addWidget(self.chk_contract_signed, 0, 2)
        l_dates.addWidget(QLabel("Срок исполнения:"), 1, 0)
        self.dt_due = QDateEdit(calendarPopup=True)
        self.dt_due.setDisplayFormat("dd.MM.yyyy")
        self.dt_due.setDate(QDate.currentDate().addDays(30))
        l_dates.addWidget(self.dt_due, 1, 1)
        self.lbl_due_hint = QLabel("по умолчанию 30 дней с даты заключения, можно изменить вручную")
        self.lbl_due_hint.setStyleSheet("color: #65758b;")
        l_dates.addWidget(self.lbl_due_hint, 1, 2)
        l_dates.addWidget(QLabel("Дата акта:"), 2, 0)
        self.dt_act = OptionalDate()
        l_dates.addWidget(self.dt_act, 2, 1)
        self.chk_act = QCheckBox("Акт подписан")
        self.chk_act.setToolTip("Пока акт не подписан, работа считается не сданной")
        l_dates.addWidget(self.chk_act, 2, 2)
        layout.addWidget(grp_dates)

        grp_status = QGroupBox("Статусы (можно выбрать несколько)")
        l_status = QGridLayout(grp_status)
        l_status.addWidget(QLabel("Статус работы:"), 0, 0)
        l_status.addWidget(QLabel("Статус клиента:"), 0, 1)
        self.lst_work = QListWidget()
        self.lst_client = QListWidget()
        for lst in (self.lst_work, self.lst_client):
            lst.setMaximumHeight(150)
        l_status.addWidget(self.lst_work, 1, 0)
        l_status.addWidget(self.lst_client, 1, 1)
        self.btn_status_editor = QPushButton("Редактор статусов…")
        self.btn_status_editor.clicked.connect(self.edit_statuses)
        l_status.addWidget(self.btn_status_editor, 2, 0)
        layout.addWidget(grp_status)

        grp_docs = QGroupBox("Документы по тегам")
        l_docs = QGridLayout(grp_docs)
        self.doc_state = {}
        self.doc_make = {}
        self.doc_open = {}
        for r, (kind, (title, *_rest)) in enumerate(gsvdom.DOC_KINDS.items()):
            l_docs.addWidget(QLabel(title), r, 0)
            state = QLabel()
            self.doc_state[kind] = state
            l_docs.addWidget(state, r, 1)
            make = QPushButton()
            make.clicked.connect(lambda _=False, k=kind: self.make_document(k))
            self.doc_make[kind] = make
            l_docs.addWidget(make, r, 2)
            opn = QPushButton("Открыть")
            opn.clicked.connect(lambda _=False, k=kind: self.open_document(k))
            self.doc_open[kind] = opn
            l_docs.addWidget(opn, r, 3)
        self.lbl_folder = QLabel()
        self.lbl_folder.setStyleSheet("color: #65758b;")
        self.lbl_folder.setWordWrap(True)
        l_docs.addWidget(self.lbl_folder, len(gsvdom.DOC_KINDS), 0, 1, 4)
        l_docs.setColumnStretch(1, 1)
        layout.addWidget(grp_docs)
        layout.addStretch()

        scroll.setWidget(container)
        self.record_tabs = QTabWidget()
        main_layout.addWidget(self.record_tabs, 1)
        self.record_tabs.addTab(scroll, "Договор и клиент")
        self.record_tabs.addTab(TemplateSettingsPanel(self), "Шаблоны и теги")

        btn_layout = QHBoxLayout()
        self.save_status = QLabel("")
        btn_layout.addWidget(self.save_status, 1)
        self.btn_payments = QPushButton("Оплаты")
        self.btn_payments.clicked.connect(self.open_payments)
        btn_layout.addWidget(self.btn_payments)
        self.btn_folder = QPushButton("Папка договора")
        self.btn_folder.clicked.connect(self.open_folder)
        btn_layout.addWidget(self.btn_folder)
        self.btn_folder_change = QPushButton("Сменить папку…")
        self.btn_folder_change.clicked.connect(self.change_folder)
        btn_layout.addWidget(self.btn_folder_change)
        self.btn_edit_toggle = QPushButton("Изменить")
        self.btn_edit_toggle.clicked.connect(self.toggle_edit)
        if self.is_new:
            self.btn_edit_toggle.setVisible(False)
        btn_layout.addWidget(self.btn_edit_toggle)
        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setProperty("type", "primary")
        self.btn_save.clicked.connect(self.save_clicked)
        btn_layout.addWidget(self.btn_save)
        self.btn_cancel = QPushButton("Закрыть")
        self.btn_cancel.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(btn_layout)

    # --- справочники и сроки ---
    def reload_status_lists(self):
        selected = self.checked_status_ids() if hasattr(self, "lst_work") else set()
        if self.project_id:
            selected |= gsvdom.project_status_ids(db, self.project_id)
        for lst, kind in ((self.lst_work, "work"), (self.lst_client, "client")):
            lst.clear()
            for sid, name, color in gsvdom.catalog(db, kind):
                pix = QPixmap(12, 12)
                pix.fill(QColor(color))
                item = QListWidgetItem(QIcon(pix), name)
                item.setData(Qt.ItemDataRole.UserRole, sid)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if sid in selected else Qt.CheckState.Unchecked)
                lst.addItem(item)

    def checked_status_ids(self):
        ids = set()
        for lst in (self.lst_work, self.lst_client):
            for i in range(lst.count()):
                if lst.item(i).checkState() == Qt.CheckState.Checked:
                    ids.add(lst.item(i).data(Qt.ItemDataRole.UserRole))
        return ids

    def edit_statuses(self):
        keep = self.checked_status_ids()
        StatusEditorDialog(self).exec()
        self.reload_status_lists()
        for lst in (self.lst_work, self.lst_client):
            for i in range(lst.count()):
                if lst.item(i).data(Qt.ItemDataRole.UserRole) in keep:
                    lst.item(i).setCheckState(Qt.CheckState.Checked)

    def on_contract_date(self, qdate):
        """Срок следует за датой заключения (+30 дней), пока его не изменили вручную."""
        if self.dt_due.date() == self.prev_contract.addDays(30):
            self.dt_due.setDate(qdate.addDays(30))
        self.prev_contract = qdate

    # --- блокировка карточки ---
    def setup_new_record(self):
        curr_year = datetime.now().year % 100
        self.txt_pd.setText(f"XX-{curr_year:02d} ГСВ (авто)")
        self.txt_contract_num.setText(f"XX-03/{curr_year:02d} (авто)")

    def editable_widgets(self):
        return [self.txt_object, self.txt_address, self.txt_tu, self.txt_notes, self.dt_contract, self.chk_contract_signed, self.dt_due,
                self.dt_act, self.chk_act, self.spn_cost, self.lst_work, self.lst_client, self.client_form, self.customer.rb_person, self.customer.rb_legal, self.customer.combo]

    def set_fields_enabled(self, enabled):
        for w in self.editable_widgets():
            w.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)

    def toggle_edit(self):
        if self.is_editing_enabled and not self.save_data():
            return
        self.is_editing_enabled = not self.is_editing_enabled
        self.set_fields_enabled(self.is_editing_enabled)
        self.btn_edit_toggle.setText("Заблокировать" if self.is_editing_enabled else "Изменить")

    # --- загрузка и сохранение ---
    def load_data(self):
        cur = db.execute("SELECT * FROM gsv_projects WHERE id = ?", (self.project_id,))
        found = cur.fetchone()
        if not found:
            return
        row = dict(zip([c[0] for c in cur.description], found))
        self.txt_pd.setText(row["pd_number"] or "")
        self.txt_contract_num.setText(row["contract_number"] or "")
        self.txt_object.setText(row["object_name"] or "")
        self.txt_address.setText(row["address"] or "")
        self.txt_notes.setPlainText(row["notes"] or "")
        self.txt_tu.setText(row.get("tu_text") or "")
        if row["contract_date"]:
            self.dt_contract.blockSignals(True)
            self.dt_contract.setDate(QDate.fromString(row["contract_date"], "yyyy-MM-dd"))
            self.prev_contract = self.dt_contract.date()
            self.dt_contract.blockSignals(False)
        if row["due_date"]:
            self.dt_due.setDate(QDate.fromString(row["due_date"], "yyyy-MM-dd"))
        self.dt_act.set_value(row["act_date"] or "")
        self.chk_contract_signed.setChecked(bool(row["contract_signed"]))
        self.chk_act.setChecked(bool(row["act_signed"]))
        self.spn_cost.setValue(row["cost"] if row["cost"] is not None else 250.0)
        cid = row["client_id"]
        client = get_client(db, cid) or dict(name=row["client_name"], phone=row["phone"], passport=row["passport"])
        self.client_form.fill(client, cid)
        self.customer.set_legal(row.get("le_client_id"))
        self.reload_status_lists()
        self.setWindowTitle(f"{row['pd_number']} | {row['object_name'] or 'Без объекта'} | {row['client_name'] or row.get('party_name') or 'Без заказчика'}")
        self.refresh_docs()
        self.refresh_folder()

    def apply_customer_mode(self):
        legal = self.customer.is_legal()
        self.client_form.setVisible(not legal)
        for kind in gsvdom.DOC_KINDS:
            self.doc_make[kind].setEnabled(not legal)
            self.doc_open[kind].setEnabled(not legal)
        if not legal:
            self.refresh_docs()
        self.btn_payments.setEnabled(not legal)
        if legal:
            self.save_status.setText('Заказчик — юрлицо: договор, акт, справка и оплаты оформляются в разделе «Юрлица».')

    def save_clicked(self):
        if self.is_new and not self.customer.is_legal() and not self.client_form.confirm_duplicate():
            return
        self.save_data()

    def save_data(self):
        try:
            legal = self.customer.is_legal()
            if legal and not self.customer.legal_id():
                raise ValueError('Выберите юрлицо-заказчика')
            client = dict(name='', phone='', passport='', address='') if legal else self.client_form.values()
            with db.transaction():
                cid = None if legal else save_client(db, client, self.client_form.client_id)
                party_name = db.fetchone('SELECT name FROM le_clients WHERE id=?', (self.customer.legal_id(),))[0] if legal else ''
                fields = ['object_name', 'address', 'client_name', 'phone', 'passport', 'contract_date', 'due_date', 'act_date', 'cost', 'notes',
                          'client_id', 'client_address', 'contract_signed', 'act_signed', 'tu_text', 'le_client_id', 'party_name']
                values = [self.txt_object.text().strip(), self.txt_address.text().strip(), client['name'], client['phone'], client['passport'],
                          self.dt_contract.date().toString('yyyy-MM-dd'), self.dt_due.date().toString('yyyy-MM-dd'), self.dt_act.value() or None,
                          self.spn_cost.value(), self.txt_notes.toPlainText(), cid, client['address'],
                          int(self.chk_contract_signed.isChecked()), int(self.chk_act.isChecked()), self.txt_tu.text().strip(), self.customer.legal_id(), party_name]
                rid = self.project_id
                if rid:
                    db.execute('UPDATE gsv_projects SET ' + ','.join(f'{f}=?' for f in fields) + ' WHERE id=?', (*values, rid))
                else:
                    year = datetime.now().year % 100
                    seq = db.fetchone('SELECT coalesce(max(seq_num),0)+1 FROM gsv_projects WHERE year_num=?', (year,))[0]
                    fields += ['pd_number', 'seq_num', 'year_num', 'contract_number']
                    values += [f'{seq:02}-{year:02} ГСВ', seq, year, f'{seq:02}-03/{year:02}']
                    rid = db.execute('INSERT INTO gsv_projects(' + ','.join(fields) + ') VALUES(' + ','.join('?' for _ in fields) + ')', values).lastrowid
                gsvdom.set_project_statuses(db, rid, self.checked_status_ids())
            self.project_id = rid
            self.is_new = False
            if not legal:
                self.client_form.client_id = cid
                self.client_form.info.setText(f'Клиент №{cid}. Данные сохранены.')
            row = db.fetchone('SELECT pd_number,contract_number FROM gsv_projects WHERE id=?', (rid,))
            self.txt_pd.setText(row[0])
            self.txt_contract_num.setText(row[1])
            self.btn_edit_toggle.setVisible(True)
            self.save_status.setText(f'Сохранено · {row[0]} · ' + (f'заказчик: {party_name}' if legal else f'клиент №{cid}'))
            self.refresh_docs()
            self.refresh_folder()
            return True
        except Exception as e:
            QMessageBox.warning(self, 'Договор не сохранён', str(e))
            return False

    # --- документы ---
    def refresh_docs(self):
        labels = {'none': ('не создан', '#65758b', 'Сформировать'), 'fresh': ('актуален', '#16A34A', 'Переформировать'),
                  'stale': ('данные изменились — переформируйте', '#D97706', '⟳ Переформировать'),
                  'missing': ('файл не найден — сформируйте заново', '#DC2626', 'Сформировать')}
        for kind in gsvdom.DOC_KINDS:
            state = gsvdom.doc_state(db, self.project_id, kind) if self.project_id else 'none'
            text, color, button = labels[state]
            self.doc_state[kind].setText(text)
            self.doc_state[kind].setStyleSheet(f'color: {color}; font-weight: 600;')
            self.doc_make[kind].setText(button)
            self.doc_make[kind].setProperty('type', 'primary' if state in ('stale', 'none', 'missing') else '')
            self.doc_make[kind].style().unpolish(self.doc_make[kind])
            self.doc_make[kind].style().polish(self.doc_make[kind])
            self.doc_open[kind].setEnabled(state in ('fresh', 'stale'))

    def make_document(self, kind):
        if (self.is_new or self.is_editing_enabled) and not self.save_data():
            return
        from . import preflight, preflight_ui
        if not preflight_ui.confirm(self, f'«{gsvdom.DOC_KINDS[kind][0]}»', preflight.check_project(db, self.project_id, kind)):
            return
        from .folder_ui import ensure_project_folder
        if not ensure_project_folder(self, db, self.project_id):
            return
        self.refresh_folder()
        try:
            path = gsvdom.generate(db, self.project_id, kind)
        except Exception as e:
            QMessageBox.warning(self, 'Документ не создан', str(e))
            return
        self.refresh_docs()
        self.save_status.setText(f'Создан файл: {path}')
        open_file_or_dir(path)

    def open_document(self, kind):
        open_file_or_dir(gsvdom.doc_path(db, self.project_id, kind))

    def open_folder(self):
        """Папка договора: если не привязана — предлагает привязать существующую или создать новую; иначе открывает."""
        if (self.is_new or self.is_editing_enabled) and not self.save_data():
            return
        from .folder_ui import ensure_project_folder
        folder = ensure_project_folder(self, db, self.project_id)
        self.refresh_folder()
        if folder:
            open_file_or_dir(folder)

    def change_folder(self):
        if (self.is_new or self.is_editing_enabled) and not self.save_data():
            return
        from .folder_ui import change_project_folder
        change_project_folder(self, db, self.project_id)
        self.refresh_folder()

    def refresh_folder(self):
        folder = gsvdom.project_folder(db, self.project_id) if self.project_id else ''
        self.lbl_folder.setText(f"Папка договора: {folder}" if folder else "Папка договора не привязана — нажмите «Папка договора»")
        self.lbl_folder.setToolTip(folder)

    def open_payments(self):
        if (self.is_new or self.is_editing_enabled) and not self.save_data():
            return
        from .payments_view import PaymentsDialog
        PaymentsDialog('gsv_projects', self.project_id, self).exec()
        self.refresh_docs()


class SideStatusBoard(QWidget):
    """Дерево статусов: «Статус работы / Статус клиента» → статус (число проектов) → проекты по порядку № ПД."""
    project_selected = pyqtSignal(int)
    hide_requested = pyqtSignal()
    PROJECT_ROLE = Qt.ItemDataRole.UserRole
    STATUS_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(230)
        self.setMaximumWidth(420)
        self.dark_mode = False
        self.expanded = set()
        layout = QVBoxLayout(self)
        head = QHBoxLayout()
        title = QLabel("<b>Статусы</b>")
        head.addWidget(title)
        head.addStretch()
        collapse = QPushButton("Свернуть всё")
        collapse.setFlat(True)
        collapse.clicked.connect(self.collapse_all)
        hide = QPushButton("◀ Скрыть")
        hide.setFlat(True)
        hide.setToolTip("Скрыть дерево статусов (вернуть — кнопкой «Дерево статусов» в панели)")
        hide.clicked.connect(self.hide_requested.emit)
        head.addWidget(collapse)
        head.addWidget(hide)
        layout.addLayout(head)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Найти проект по № ПД или заказчику…")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self.reload_data)
        layout.addWidget(self.txt_search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setUniformRowHeights(True)
        self.tree.setStyleSheet("QTreeWidget::item { padding: 4px 2px; } QTreeWidget::item:selected, QTreeWidget::item:selected:!active { background: #2563eb; color: #ffffff; }")
        self.tree.itemClicked.connect(self.on_clicked)
        self.tree.itemDoubleClicked.connect(self.on_double_clicked)
        self.tree.itemExpanded.connect(self.on_expanded)
        self.tree.itemCollapsed.connect(self.on_collapsed)
        layout.addWidget(self.tree, 1)
        hint = QLabel("Нажмите на статус — раскроется список проектов. Двойной щелчок по проекту открывает договор.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(hint)

    def set_dark_mode(self, dark_mode):
        self.dark_mode = dark_mode
        self.reload_data()

    def status_counts(self):
        search = self.txt_search.text().strip().lower()
        sql = ("SELECT s.status_id, count(*) FROM gsv_project_statuses s JOIN gsv_projects p ON p.id=s.project_id")
        params = []
        if search:
            sql += " WHERE (LOWER(p.pd_number) LIKE ? OR LOWER(coalesce(nullif(p.client_name,''),p.party_name)) LIKE ?)"
            params = [f"%{search}%"] * 2
        return dict(db.fetchall(sql + " GROUP BY s.status_id", tuple(params)))

    def reload_data(self, *_):
        self.tree.blockSignals(True)
        self.tree.clear()
        counts = self.status_counts()
        searching = bool(self.txt_search.text().strip())
        for kind, title in (("work", "Статус работы"), ("client", "Статус клиента")):
            group = QTreeWidgetItem([title])
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            self.tree.addTopLevelItem(group)
            for sid, name, color in gsvdom.catalog(db, kind):
                n = counts.get(sid, 0)
                if searching and not n:
                    continue
                pix = QPixmap(12, 12)
                pix.fill(QColor(color))
                item = QTreeWidgetItem([f"{name}  ({n})"])
                item.setIcon(0, QIcon(pix))
                item.setData(0, self.STATUS_ROLE, sid)
                if not n:
                    item.setForeground(0, QColor("#94a3b8"))
                else:
                    item.addChild(QTreeWidgetItem(["…"]))      # раскрывающая стрелка; проекты подгружаются при открытии
                group.addChild(item)
            group.setExpanded(True)
        self.tree.blockSignals(False)
        # раскрытые статусы остаются раскрытыми после обновления
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            for i in range(group.childCount()):
                item = group.child(i)
                sid = item.data(0, self.STATUS_ROLE)
                if (sid in self.expanded or (searching and item.childCount())) and item.childCount():
                    item.setExpanded(True)

    def fill_projects(self, item):
        sid = item.data(0, self.STATUS_ROLE)
        item.takeChildren()
        search = self.txt_search.text().strip().lower()
        sql = ("SELECT p.id, p.pd_number, coalesce(nullif(p.client_name,''),p.party_name) FROM gsv_projects p JOIN gsv_project_statuses s ON s.project_id=p.id WHERE s.status_id = ?")
        params = [sid]
        if search:
            sql += " AND (LOWER(p.pd_number) LIKE ? OR LOWER(coalesce(nullif(p.client_name,''),p.party_name)) LIKE ?)"
            params.extend([f"%{search}%"] * 2)
        rows = db.fetchall(sql + " ORDER BY coalesce(p.year_num,0) DESC, coalesce(p.seq_num,0) DESC, p.id DESC LIMIT 301", tuple(params))
        for pid, pd, client in rows[:300]:
            child = QTreeWidgetItem([f"{pd} · {client or 'Без имени'}"])
            child.setData(0, self.PROJECT_ROLE, pid)
            item.addChild(child)
        if len(rows) > 300:
            more = QTreeWidgetItem(["… показаны первые 300, остальные — в реестре"])
            more.setFlags(Qt.ItemFlag.NoItemFlags)
            item.addChild(more)

    def on_expanded(self, item):
        sid = item.data(0, self.STATUS_ROLE)
        if sid is None:
            return
        self.expanded.add(sid)
        self.tree.blockSignals(True)
        self.fill_projects(item)
        self.tree.blockSignals(False)

    def on_collapsed(self, item):
        sid = item.data(0, self.STATUS_ROLE)
        if sid is not None:
            self.expanded.discard(sid)

    def on_clicked(self, item, _column=0):
        if item.data(0, self.STATUS_ROLE) is not None and item.childCount():
            item.setExpanded(not item.isExpanded())

    def on_double_clicked(self, item, _column=0):
        pid = item.data(0, self.PROJECT_ROLE)
        if pid:
            self.project_selected.emit(pid)

    def collapse_all(self):
        self.expanded.clear()
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            for i in range(group.childCount()):
                group.child(i).setExpanded(False)


class GsvProjectsView(QWidget):
    def __init__(self):
        super().__init__()
        self.pager=RegistryPager(self)
        self.dark_mode = db.get_setting("is_dark", "0") == "1"
        self.urgent_filter_active = False
        self.model = FastCompactTableModel(dark_mode=self.dark_mode)

        layout = QVBoxLayout(self)
        top_bar = QHBoxLayout()
        btn_add = QPushButton("Новый проект ПД")
        btn_add.setProperty("type", "primary")
        btn_add.clicked.connect(self.open_new_dialog)
        btn_reports = QPushButton("Отчёты")
        btn_reports.clicked.connect(lambda: ReportsDialog(self).exec())

        self.btn_urgent = QPushButton("Горящие сроки")
        self.btn_urgent.setCheckable(True)
        self.btn_urgent.clicked.connect(self.toggle_urgent)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Поиск по № ПД, объекту, заказчику…")
        self.txt_search.textChanged.connect(self.load_data)

        btn_tpl = QPushButton("Шаблоны документов")
        btn_tpl.clicked.connect(lambda: TemplateSettingsDialog(self).exec())
        btn_excel = QPushButton("Выгрузка Excel")
        btn_excel.clicked.connect(lambda: export_all_to_excel(self))
        btn_tags = QPushButton("Теги")
        btn_tags.clicked.connect(self.show_tag_reference)
        btn_import = QPushButton("Импорт из Excel…")
        btn_import.clicked.connect(self.import_excel)
        btn_statuses = QPushButton("Статусы…")
        btn_statuses.clicked.connect(self.edit_statuses)

        # Реестр всегда упорядочен по номеру проектной документации (год, затем порядковый номер)
        self.order_desc = db.get_setting("gsvp_order_desc", "1") == "1"
        self.btn_order = QPushButton()
        self.btn_order.setToolTip("Реестр всегда упорядочен по номеру ПД. Нажмите, чтобы изменить направление.")
        self.btn_order.clicked.connect(self.toggle_order)
        self.btn_tree = QPushButton("Дерево статусов")
        self.btn_tree.setCheckable(True)
        self.btn_tree.setToolTip("Показать / скрыть дерево статусов слева")
        self.btn_tree.toggled.connect(self.set_tree_visible)
        self.txt_search.setMinimumWidth(260)
        for w in [btn_add, btn_reports, self.btn_urgent, self.btn_order, self.btn_tree]: top_bar.addWidget(w)
        top_bar.addWidget(self.txt_search, 1)
        layout.addLayout(top_bar)
        tools_bar = QHBoxLayout()
        payments=QPushButton("Оплаты");payments.clicked.connect(self.open_payments)
        btn_acts = QPushButton("Ведомость актов…")
        btn_acts.setToolTip("Подписанные акты за календарный месяц для бухгалтерии")
        btn_acts.clicked.connect(lambda: __import__("smetagaz.acts_statement_view", fromlist=["x"]).ActsStatementDialog("gsv_projects", self).exec())
        for w in (btn_acts, btn_import, btn_statuses, btn_tpl, btn_tags, btn_excel, payments): tools_bar.addWidget(w)
        tools_bar.addStretch()
        layout.addLayout(tools_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.side_board = SideStatusBoard()
        self.side_board.set_dark_mode(self.dark_mode)
        self.side_board.project_selected.connect(self.open_edit_dialog)
        self.side_board.hide_requested.connect(lambda: self.btn_tree.setChecked(False))
        splitter.addWidget(self.side_board)

        self.view_table = QTableView()
        self.view_table.setModel(self.model)
        self.view_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.view_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.view_table.doubleClicked.connect(lambda i: self.open_edit_dialog(self.model.get_row_record(i.row())[0]))

        self.view_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view_table.customContextMenuRequested.connect(self.open_context_menu)
        QShortcut(QKeySequence.StandardKey.Delete, self.view_table).activated.connect(self.delete_row)
        splitter.addWidget(self.view_table)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
        self.update_order_button()
        self.btn_tree.setChecked(db.get_setting("gsvp_tree_visible", "1") == "1")
        self.set_tree_visible(self.btn_tree.isChecked())

        # Full backups are managed by AutoBackupService in the main window.

    def refresh_ui(self):
        self.dark_mode = db.get_setting("is_dark", "0") == "1"
        self.model.set_dark_mode(self.dark_mode)
        self.side_board.set_dark_mode(self.dark_mode)

    def set_tree_visible(self, visible):
        self.side_board.setVisible(visible)
        db.set_setting("gsvp_tree_visible", "1" if visible else "0")

    def update_order_button(self):
        self.btn_order.setText("№ ПД ↓ новые сверху" if self.order_desc else "№ ПД ↑ старые сверху")

    def toggle_order(self):
        self.order_desc = not self.order_desc
        db.set_setting("gsvp_order_desc", "1" if self.order_desc else "0")
        self.update_order_button()
        self.load_data()

    def toggle_urgent(self):
        self.urgent_filter_active = self.btn_urgent.isChecked()
        self.load_data()

    def open_payments(self):
        row=self.view_table.currentIndex().row()
        if row>=0:
            from .payments_view import PaymentsDialog
            PaymentsDialog('gsv_projects',self.model.get_row_record(row)[0],self).exec();self.load_data()
    def show_tag_reference(self):
        TemplateSettingsDialog(self).exec()

    def import_excel(self):
        from .gsv_import_view import ImportProjectsDialog
        ImportProjectsDialog(self).exec()
        self.load_data()

    def edit_statuses(self):
        StatusEditorDialog(self).exec()
        self.side_board.reload_data()
        self.load_data()
    def open_new_dialog(self):
        ProjectEditDialog(parent=self).exec();self.load_data()

    def open_edit_dialog(self, p_id):
        ProjectEditDialog(project_id=p_id, parent=self).exec();self.load_data()

    def open_context_menu(self, pos):
        idx = self.view_table.indexAt(pos)
        if not idx.isValid(): return
        menu = QMenu(self)
        menu.addAction("Изменить").triggered.connect(lambda: self.open_edit_dialog(self.model.get_row_record(idx.row())[0]))
        menu.addAction("Удалить").triggered.connect(self.delete_row)
        menu.exec(self.view_table.viewport().mapToGlobal(pos))

    def delete_row(self):
        sel = self.view_table.selectionModel().selectedRows()
        if not sel: return
        r = self.model.get_row_record(sel[0].row())
        if QMessageBox.question(self, "Удаление", f"Удалить проект {r[1]}?") == QMessageBox.StandardButton.Yes:
            try:
                db.execute("DELETE FROM gsv_projects WHERE id=?", (r[0],))
            except Exception as e:
                QMessageBox.warning(self, "Удаление невозможно", str(e))
            self.load_data()

    def load_data(self):
        q=self.txt_search.text().strip().casefold()
        sql="SELECT id,pd_number,object_name,coalesce(nullif(client_name,''),party_name),cost,client_status,work_status,project_folder,due_date,coalesce(act_signed,0),act_date FROM gsv_projects"
        conditions=[];params=[]
        if q:
            conditions.append('(LOWER(pd_number) LIKE ? OR LOWER(object_name) LIKE ? OR LOWER(coalesce(nullif(client_name,''),party_name)) LIKE ?)');params.extend(['%'+q+'%']*3)
        if self.urgent_filter_active:conditions.append("coalesce(act_signed,0)=0 AND date(due_date) <= date('now','+5 days')")
        if conditions:sql+=' WHERE '+' AND '.join(conditions)
        direction='DESC' if self.order_desc else 'ASC'
        rows=self.pager.fetch(sql+f' ORDER BY coalesce(year_num,0) {direction}, coalesce(seq_num,0) {direction}, id {direction}',params)
        self.model.update_data(rows);self.side_board.reload_data()
