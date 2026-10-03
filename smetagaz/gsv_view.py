"""
Вкладка "Проекты ГСВ": учет проектирования, генерация договоров, контроль
сроков и аналитика по объектам газоснабжения.
"""
import os
import logging
from datetime import datetime, date

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH

import openpyxl

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableView, QPushButton, QLabel, QLineEdit, QTextEdit, QComboBox,
    QDateEdit, QFileDialog, QDialog, QHeaderView, QMessageBox,
    QScrollArea, QFrame, QGridLayout, QGroupBox, QDoubleSpinBox, QSplitter, QCheckBox, QTableWidget, QTableWidgetItem,
    QMenu, QApplication, QAbstractItemView
)
from PyQt6.QtCore import Qt, QDate, QAbstractTableModel, QModelIndex, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut

from .database import db
from .domain_widgets import ClientForm
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

MONTHS_GENITIVE = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]

def format_date_word(qdate_or_str) -> str:
    if not qdate_or_str: return "—"
    if isinstance(qdate_or_str, QDate):
        if not qdate_or_str.isValid(): return "—"
        d, m, y = qdate_or_str.day(), qdate_or_str.month(), qdate_or_str.year()
    else:
        try:
            dt = datetime.strptime(str(qdate_or_str)[:10], "%Y-%m-%d")
            d, m, y = dt.day, dt.month, dt.year
        except Exception: return str(qdate_or_str)

    if 1 <= m <= 12: return f"{d:02d} {MONTHS_GENITIVE[m]} {y} г."
    return str(qdate_or_str)

def get_initials_first(full_name: str) -> str:
    parts = full_name.strip().split()
    if not parts: return "—"
    if len(parts) == 1: return parts[0]
    if len(parts) == 2: return f"{parts[1][0].upper()}. {parts[0]}"
    return f"{parts[1][0].upper()}.{parts[2][0].upper()}. {parts[0]}"

def format_cost_rubles(amount: float) -> str:
    int_part = int(amount)
    cents_part = int(round((amount - int_part) * 100))
    formatted_int = f"{int_part:,}".replace(",", " ")

    last_two = int_part % 100
    last_digit = int_part % 10
    if 11 <= last_two <= 19: rub_word = "рублей"
    elif last_digit == 1: rub_word = "рубль"
    elif 2 <= last_digit <= 4: rub_word = "рубля"
    else: rub_word = "рублей"

    return f"{formatted_int},{cents_part:02d} {rub_word}"

def num_to_words_byn(amount: float) -> str:
    units_m = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    units_f = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    teens = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
             "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
    tens = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
    hundreds = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]

    int_part = int(amount)
    cents_part = int(round((amount - int_part) * 100))

    if int_part == 0: words = "ноль"
    else:
        words_list = []
        millions = (int_part // 1_000_000) % 1_000
        if millions > 0:
            h, t = hundreds[millions // 100], millions % 100
            if h: words_list.append(h)
            if 10 <= t <= 19:
                words_list.append(teens[t - 10])
                m_word = "миллионов"
            else:
                if t // 10 > 1: words_list.append(tens[t // 10])
                u = t % 10
                if u > 0: words_list.append(units_m[u])
                if u == 1: m_word = "миллион"
                elif 2 <= u <= 4: m_word = "миллиона"
                else: m_word = "миллионов"
            words_list.append(m_word)

        thousands = (int_part // 1_000) % 1_000
        if thousands > 0:
            h, t = hundreds[thousands // 100], thousands % 100
            if h: words_list.append(h)
            if 10 <= t <= 19:
                words_list.append(teens[t - 10])
                th_word = "тысяч"
            else:
                if t // 10 > 1: words_list.append(tens[t // 10])
                u = t % 10
                if u > 0: words_list.append(units_f[u])
                if u == 1: th_word = "тысяча"
                elif 2 <= u <= 4: th_word = "тысячи"
                else: th_word = "тысяч"
            words_list.append(th_word)

        rem = int_part % 1_000
        if rem > 0:
            h, t = hundreds[rem // 100], rem % 100
            if h: words_list.append(h)
            if 10 <= t <= 19: words_list.append(teens[t - 10])
            else:
                if t // 10 > 1: words_list.append(tens[t // 10])
                u = t % 10
                if u > 0: words_list.append(units_m[u])
        words = " ".join(words_list).capitalize()

    last_two_int, last_digit = int_part % 100, int_part % 10
    if 11 <= last_two_int <= 19: rub_word = "белорусских рублей"
    elif last_digit == 1: rub_word = "белорусский рубль"
    elif 2 <= last_digit <= 4: rub_word = "белорусских рубля"
    else: rub_word = "белорусских рублей"

    last_two_cents, last_cent_digit = cents_part % 100, cents_part % 10
    if 11 <= last_two_cents <= 19: cent_word = "копеек"
    elif last_cent_digit == 1: cent_word = "копейка"
    elif 2 <= last_cent_digit <= 4: cent_word = "копейки"
    else: cent_word = "копеек"

    return f"{words} {rub_word} {cents_part:02d} {cent_word}"

def open_file_or_dir(path):
    if path and os.path.exists(path): open_local(os.path.abspath(path))
    else: QMessageBox.warning(None, "Путь не найден", f"Указанный файл или папка не существует:\n{path}")

def print_document_file(path):
    if path and os.path.exists(path):
        try: open_local(os.path.abspath(path), "print")
        except Exception as e: QMessageBox.critical(None, "Ошибка печати", f"Не удалось отправить файл на печать:\n{e}")
    else: QMessageBox.warning(None, "Файл не найден", f"Файл для печати не существует:\n{path}")

def ensure_default_contract_template():
    if not os.path.exists(DEFAULT_TEMPLATE_PATH):
        doc = docx.Document()
        title = doc.add_heading("ДОГОВОР № {НОМЕР_ДОГОВОРА}", 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph("на разработку проектной документации: {НОМЕР_ПД}")
        doc.add_paragraph("Дата заключения: {ДАТА_ЗАКЛЮЧЕНИЯ}")
        doc.add_paragraph("Срок исполнения: {СРОК_ИСПОЛНЕНИЯ}")
        doc.add_paragraph("Стоимость работ: {СТОИМОСТЬ} ({СУММА_ПРОПИСЬЮ})")
        doc.add_heading("1. Сведения о сторонах и объекте", level=1)
        doc.add_paragraph("Заказчик: {ЗАКАЗЧИК} ({ЗАКАЗЧИК_СОКР})")
        doc.add_paragraph("Телефон: {ТЕЛЕФОН}")
        doc.add_paragraph("Паспортные данные: {ПАСПОРТ}")
        doc.add_paragraph("Объект строительства: {ОБЪЕКТ}")
        doc.add_paragraph("Адрес объекта: {АДРЕС}")
        doc.save(DEFAULT_TEMPLATE_PATH)

def replace_text_preserve_formatting(paragraph, replacements):
    p_text = "".join(run.text for run in paragraph.runs)
    if not any(key in p_text for key in replacements): return

    if paragraph.runs:
        first_run = paragraph.runs[0]
        font_name, font_size = first_run.font.name, first_run.font.size
        bold, italic, underline = first_run.bold, first_run.italic, first_run.underline
        color = first_run.font.color.rgb if first_run.font.color else None

        new_text = p_text
        for key, val in replacements.items(): new_text = new_text.replace(key, str(val))
        for run in paragraph.runs: run.text = ""

        first_run.text = new_text
        first_run.font.name, first_run.font.size = font_name, font_size
        first_run.bold, first_run.italic, first_run.underline = bold, italic, underline
        if color: first_run.font.color.rgb = color

def generate_contract_from_template(project_dir, pd_num, contract_num, c_date_str, d_date_str, act_date_str, cost_val, client, phone, passport, obj, address, notes_val=""):
    os.makedirs(project_dir, exist_ok=True)
    custom_template = db.get_setting("custom_template_path", "")
    template_to_use = custom_template if (custom_template and os.path.exists(custom_template)) else DEFAULT_TEMPLATE_PATH
    ensure_default_contract_template()
    doc = docx.Document(template_to_use)

    amount_in_words = num_to_words_byn(cost_val)
    client_short = get_initials_first(client or "")
    cost_in_rubles = format_cost_rubles(cost_val)

    replacements = {
        "{НОМЕР_ДОГОВОРА}": contract_num, "{НОМЕР_ПД}": pd_num, "{ДАТА_ЗАКЛЮЧЕНИЯ}": c_date_str,
        "{СРОК_ИСПОЛНЕНИЯ}": d_date_str, "{ДАТА_АКТА}": act_date_str, "{СТОИМОСТЬ}": cost_in_rubles,
        "{СУММА_ПРОПИСЬЮ}": amount_in_words, "{СТОИМОСТЬ_ПРОПИСЬЮ}": amount_in_words,
        "{ЗАКАЗЧИК}": client or "—", "{ЗАКАЗЧИК_СОКР}": client_short, "{ЗАКАЗЧИК_ИНИЦИАЛЫ}": client_short,
        "{ТЕЛЕФОН}": phone or "—", "{ПАСПОРТ}": passport or "—", "{ОБЪЕКТ}": obj or "—",
        "{АДРЕС}": address or "—", "{ПРИМЕЧАНИЯ}": notes_val or ""
    }

    for p in doc.paragraphs: replace_text_preserve_formatting(p, replacements)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs: replace_text_preserve_formatting(p, replacements)
    for section in doc.sections:
        for p in section.header.paragraphs: replace_text_preserve_formatting(p, replacements)
        for p in section.footer.paragraphs: replace_text_preserve_formatting(p, replacements)

    file_path = os.path.join(project_dir, f"Договор_{contract_num.replace('/', '_')}.docx")
    doc.save(file_path)
    return file_path

class TemplateSettingsPanel(QWidget):
    """Global contract-template (.docx) settings; usable standalone or embedded as a tab."""
    TAGS = [
        ("{НОМЕР_ДОГОВОРА}", "Номер договора"), ("{НОМЕР_ПД}", "Номер ПД"),
        ("{ДАТА_ЗАКЛЮЧЕНИЯ}", "Дата заключения"), ("{СРОК_ИСПОЛНЕНИЯ}", "Срок исполнения"),
        ("{ДАТА_АКТА}", "Дата акта"), ("{СТОИМОСТЬ}", "Стоимость цифрами"),
        ("{СУММА_ПРОПИСЬЮ}", "Сумма прописью"), ("{ЗАКАЗЧИК}", "Полное наименование заказчика"),
        ("{ЗАКАЗЧИК_СОКР}", "Инициалы и фамилия"), ("{ТЕЛЕФОН}", "Телефон"),
        ("{ПАСПОРТ}", "Паспортные данные"), ("{ОБЪЕКТ}", "Объект строительства"),
        ("{АДРЕС}", "Адрес объекта"), ("{ПРИМЕЧАНИЯ}", "Примечания")
    ]
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Шаблон общий для всех проектов ГСВ; действует сразу после сохранения."))
        grp_path = QGroupBox("Файл шаблона Word (.docx)")
        l_path = QGridLayout(grp_path)
        self.txt_path = QLineEdit()
        self.txt_path.setText(db.get_setting("custom_template_path", DEFAULT_TEMPLATE_PATH))
        self.txt_path.setReadOnly(True)
        self.btn_browse = QPushButton("Выбрать свой шаблон...")
        self.btn_browse.clicked.connect(self.browse_template)
        self.btn_open_tpl = QPushButton("Открыть в Word")
        self.btn_open_tpl.clicked.connect(self.open_current_template)
        self.btn_reset = QPushButton("Сброс (По умолчанию)")
        self.btn_reset.clicked.connect(self.reset_to_default)

        l_path.addWidget(self.txt_path, 0, 0, 1, 3)
        l_path.addWidget(self.btn_browse, 1, 0)
        l_path.addWidget(self.btn_open_tpl, 1, 1)
        l_path.addWidget(self.btn_reset, 1, 2)
        layout.addWidget(grp_path)

        grp_tags = QGroupBox("Доступные метки")
        l_tags = QVBoxLayout(grp_tags)
        self.table_tags = QTableWidget(len(self.TAGS), 3)
        self.table_tags.setHorizontalHeaderLabels(["Метка", "Описание", "Действие"])
        self.table_tags.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_tags.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_tags.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_tags.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_tags.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        for r, (tag, desc) in enumerate(self.TAGS):
            item_tag = QTableWidgetItem(tag)
            item_tag.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            self.table_tags.setItem(r, 0, item_tag)
            self.table_tags.setItem(r, 1, QTableWidgetItem(desc))
            btn_copy = QPushButton("Копировать")
            btn_copy.clicked.connect(lambda ch=False, t=tag, b=btn_copy: self.copy_tag(t, b))
            self.table_tags.setCellWidget(r, 2, btn_copy)
        l_tags.addWidget(self.table_tags)
        layout.addWidget(grp_tags)

        btn_box = QHBoxLayout()
        self.lbl_status = QLabel("")
        btn_box.addWidget(self.lbl_status, 1)
        btn_save = QPushButton("Сохранить настройки")
        btn_save.setProperty("type", "primary")
        btn_save.clicked.connect(self.save_settings)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)

    def copy_tag(self, tag_text, btn):
        QApplication.clipboard().setText(tag_text)
        btn.setText("Скопировано!")
        QTimer.singleShot(1500, lambda: btn.setText("Копировать"))

    def browse_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите шаблон Word", "", "Word (*.docx)")
        if path: self.txt_path.setText(path)

    def open_current_template(self):
        path = self.txt_path.text().strip()
        open_file_or_dir(path if os.path.exists(path) else DEFAULT_TEMPLATE_PATH)

    def reset_to_default(self):
        ensure_default_contract_template()
        self.txt_path.setText(DEFAULT_TEMPLATE_PATH)

    def save_settings(self):
        db.set_setting("custom_template_path", self.txt_path.text().strip())
        self.lbl_status.setText("Настройки сохранены.")

class TemplateSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка шаблона договора (.docx)")
        self.resize(760, 600)
        layout = QVBoxLayout(self)
        layout.addWidget(TemplateSettingsPanel(self))
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        bar = QHBoxLayout()
        bar.addStretch()
        bar.addWidget(btn_close)
        layout.addLayout(bar)

def perform_daily_excel_backup():
    try:
        os.makedirs(BACKUP_EXCEL_DIR, exist_ok=True)
        daily_file = os.path.join(BACKUP_EXCEL_DIR, "Ежедневный_бэкап_ГСВ.xlsx")
        archive_date_file = os.path.join(BACKUP_EXCEL_DIR, f"backup_ГСВ_{datetime.now().strftime('%Y-%m-%d')}.xlsx")

        rows = db.fetchall("""SELECT id, pd_number, object_name, address, client_name, phone, passport, contract_number, 
                                     contract_date, due_date, act_date, cost, work_status, client_status, tu_path, 
                                     project_folder, attachments, notes FROM gsv_projects ORDER BY id DESC""")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Резервная копия ГСВ"
        headers = ["ID", "Номер ПД", "Объект", "Адрес", "Заказчик", "Телефон", "Паспорт", "Договор", "Дата закл.",
                   "Срок исп.", "Дата акта", "Стоимость", "Статус работы", "Статус клиента", "ТУ", "Папка", "Вложения", "Примечания"]
        ws.append(headers)

        for r_idx, row in enumerate(rows, start=2):
            row_data = list(row)
            row_data[8] = format_date_word(row_data[8])
            row_data[9] = format_date_word(row_data[9])
            row_data[10] = format_date_word(row_data[10]) if row_data[10] else "Не подписан"
            row_data[11] = format_cost_rubles(row_data[11]) if row_data[11] is not None else "0,00 рублей"
            ws.append(row_data)

        for sheet in wb.worksheets:

            for row_cells in sheet:

                for cell in row_cells:

                    if isinstance(cell.value, str): cell.data_type = "s"

        wb.save(daily_file)
        for sheet in wb.worksheets:
            for row_cells in sheet:
                for cell in row_cells:
                    if isinstance(cell.value, str): cell.data_type = "s"
        wb.save(archive_date_file)
    except Exception as e: logging.exception(f"Ошибка бэкапа Excel: {e}")

def export_all_to_excel(parent_window):
    save_path, _ = QFileDialog.getSaveFileName(parent_window, "Сохранить базу в Excel", f"База_ГСВ_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", "Excel (*.xlsx)")
    if not save_path: return
    try:
        rows = db.fetchall("""SELECT id, pd_number, object_name, address, client_name, phone, passport, contract_number, 
                                     contract_date, due_date, act_date, cost, work_status, client_status, tu_path, 
                                     project_folder, attachments, notes FROM gsv_projects ORDER BY id DESC""")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Проектирование ГСВ"
        headers = ["ID", "Номер ПД", "Объект", "Адрес", "Заказчик", "Телефон", "Паспорт", "Договор", "Дата закл.",
                   "Срок исп.", "Дата акта", "Стоимость", "Статус работы", "Статус клиента", "ТУ", "Папка", "Вложения", "Примечания"]
        ws.append(headers)

        for r_idx, row in enumerate(rows, start=2):
            row_data = list(row)
            row_data[8] = format_date_word(row_data[8])
            row_data[9] = format_date_word(row_data[9])
            row_data[10] = format_date_word(row_data[10]) if row_data[10] else "Не подписан"
            row_data[11] = format_cost_rubles(row_data[11]) if row_data[11] is not None else "0,00 рублей"
            ws.append(row_data)
        for sheet in wb.worksheets:
            for row_cells in sheet:
                for cell in row_cells:
                    if isinstance(cell.value, str): cell.data_type = "s"
        wb.save(save_path)
        QMessageBox.information(parent_window, "Экспорт", "База выгружена успешно.")
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
        self.cmb_report_type.addItems(["Сделано", "Оплачено", "Подписано/Оплачено", "Сводный отчет"])
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
        sql = "SELECT pd_number, object_name, client_name, contract_number, contract_date, due_date, act_date, cost, work_status, client_status FROM gsv_projects WHERE 1=1"
        params = []
        if rep_type == 0: sql += " AND work_status = 'Сделано' AND contract_date BETWEEN ? AND ?"; params.extend([d_from, d_to])
        elif rep_type == 1: sql += " AND client_status = 'Оплачен' AND act_date IS NOT NULL AND act_date BETWEEN ? AND ?"; params.extend([d_from, d_to])
        elif rep_type == 2: sql += " AND client_status IN ('Подписан', 'Оплачен') AND act_date IS NOT NULL AND act_date BETWEEN ? AND ?"; params.extend([d_from, d_to])
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
        work_status, client_status, due_date_str = row[6], row[5], row[8] if len(row) > 8 else None
        days_left, is_overdue, is_urgent = None, False, False

        if due_date_str and work_status != "Сделано":
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
                if work_status == "Сделано": return f"✅ Сдан ({format_date_word(due_date_str)})"
                if is_overdue: return f"⚠️ Просрочен на {abs(days_left)} дн."
                if is_urgent: return f"⏳ Осталось {days_left} дн."
                return format_date_word(due_date_str)
            if col == 4: return format_cost_rubles(row[4] if row[4] is not None else 250.0)
            if col == 5:
                if client_status == "Подписан": return "✍️ Подписан"
                if client_status == "Оплачен": return "💰 Оплачен"
                return "❌ Не подписан"

        if role == Qt.ItemDataRole.BackgroundRole:
            if work_status == "Сделано": return QColor(16, 185, 129, 35) if self.dark_mode else QColor(220, 252, 231)
            if is_overdue: return QColor(239, 68, 68, 45) if self.dark_mode else QColor(254, 205, 205)
            if is_urgent or work_status == "🔥 Приоритет": return QColor(245, 158, 11, 40) if self.dark_mode else QColor(254, 243, 199)
            return QColor(239, 68, 68, 20) if self.dark_mode else QColor(254, 242, 242)

        if role == Qt.ItemDataRole.ForegroundRole:
            if col == 0: return QColor(96, 165, 250) if self.dark_mode else QColor(37, 99, 235)
            if self.dark_mode:
                if work_status == "Сделано": return QColor(167, 243, 208)
                if is_overdue: return QColor(254, 202, 202)
                if is_urgent or work_status == "🔥 Приоритет": return QColor(253, 230, 138)
                return QColor(248, 250, 252)
            else:
                if work_status == "Сделано": return QColor(22, 101, 52)
                if is_overdue: return QColor(153, 27, 27)
                if is_urgent or work_status == "🔥 Приоритет": return QColor(146, 64, 14)
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
    def __init__(self, project_id=None, parent=None):
        super().__init__(parent)
        self.project_id = project_id
        self.is_new = project_id is None
        self.is_editing_enabled = self.is_new
        self.attachments_list = []
        self.resize(1200, 890)
        self.setup_ui()
        if not self.is_new:
            self.load_data()
            self.set_fields_enabled(False)
            self.btn_contract_action.setText("Просмотр договора")
            self.btn_regenerate_doc.setVisible(False)
        else:
            self.setWindowTitle("Новый проект ГСВ")
            self.setup_new_record()

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
        self.spn_cost.setValue(250.0)
        l_sys.addWidget(self.spn_cost, 1, 1)
        layout.addWidget(grp_sys)

        grp_info=QGroupBox('Объект проектирования');l_info=QGridLayout(grp_info)
        self.txt_object=QLineEdit();self.txt_address=QLineEdit()
        l_info.addWidget(QLabel('Объект:'),0,0);l_info.addWidget(self.txt_object,0,1)
        l_info.addWidget(QLabel('Адрес объекта:'),1,0);l_info.addWidget(self.txt_address,1,1)
        layout.addWidget(grp_info)
        self.client_form=ClientForm();layout.addWidget(self.client_form)
        self.txt_client=self.client_form.name;self.txt_phone=self.client_form.phone;self.txt_passport=self.client_form.passport
        self.txt_notes=QTextEdit();self.txt_notes.setMaximumHeight(65);self.txt_notes.setPlaceholderText('Примечания к объекту');layout.addWidget(self.txt_notes)

        grp_dates = QGroupBox("Сроки")
        l_dates = QGridLayout(grp_dates)
        l_dates.addWidget(QLabel("Дата заключения:"), 0, 0)
        self.dt_contract = QDateEdit(calendarPopup=True)
        self.dt_contract.setDate(QDate.currentDate())
        self.dt_contract.dateChanged.connect(lambda: self.dt_due.setDate(self.dt_contract.date().addMonths(1)))
        l_dates.addWidget(self.dt_contract, 0, 1)
        l_dates.addWidget(QLabel("Срок исполнения:"), 0, 2)
        self.dt_due = QDateEdit(calendarPopup=True)
        self.dt_due.setDate(QDate.currentDate().addMonths(1))
        l_dates.addWidget(self.dt_due, 0, 3)
        self.chk_act = QCheckBox("Акт подписан (Дата):")
        self.chk_act.toggled.connect(lambda c: self.dt_act.setEnabled(c and self.is_editing_enabled))
        l_dates.addWidget(self.chk_act, 1, 0)
        self.dt_act = QDateEdit(calendarPopup=True)
        self.dt_act.setDate(QDate.currentDate())
        self.dt_act.setEnabled(False)
        l_dates.addWidget(self.dt_act, 1, 1)
        layout.addWidget(grp_dates)

        grp_status = QGroupBox("Статусы")
        l_status = QGridLayout(grp_status)
        l_status.addWidget(QLabel("Статус работы:"), 0, 0); self.cmb_work_status = QComboBox(); self.cmb_work_status.addItems(["Не сделано", "🔥 Приоритет", "Сделано"]); l_status.addWidget(self.cmb_work_status, 0, 1)
        l_status.addWidget(QLabel("Статус клиента:"), 0, 2); self.cmb_client_status = QComboBox(); self.cmb_client_status.addItems(["Не подписан", "Подписан", "Оплачен"]); l_status.addWidget(self.cmb_client_status, 0, 3)
        layout.addWidget(grp_status)

        scroll.setWidget(container)
        self.record_tabs=QTabWidget();main_layout.addWidget(self.record_tabs,1)
        self.record_tabs.addTab(scroll,'Договор и клиенты')
        self.record_tabs.addTab(TemplateSettingsPanel(self),'Настройка шаблона')

        btn_layout = QHBoxLayout()
        self.save_status=QLabel('');btn_layout.addWidget(self.save_status,1)
        self.btn_edit_toggle = QPushButton("Изменить")
        self.btn_edit_toggle.clicked.connect(self.toggle_edit)
        if self.is_new: self.btn_edit_toggle.setVisible(False)

        self.btn_contract_action = QPushButton("Просмотр договора")
        self.btn_contract_action.setProperty("type", "primary")
        self.btn_contract_action.clicked.connect(self.handle_contract_action)

        self.btn_regenerate_doc = QPushButton("Пересоздать договор")
        self.btn_regenerate_doc.clicked.connect(self.force_regenerate_contract)

        payments=QPushButton('Оплаты');payments.clicked.connect(self.open_payments);btn_layout.addWidget(payments)
        self.btn_save = QPushButton("Сохранить")
        self.btn_save.setProperty("type", "primary")
        self.btn_save.clicked.connect(self.save_data)

        self.btn_cancel = QPushButton("Закрыть")
        self.btn_cancel.clicked.connect(self.accept)

        btn_layout.addWidget(self.btn_edit_toggle)
        template_button=QPushButton('Договор по шаблону');template_button.setProperty('type','primary');template_button.clicked.connect(self.export_template);btn_layout.addWidget(template_button)
        btn_layout.addWidget(self.btn_contract_action)
        btn_layout.addWidget(self.btn_regenerate_doc)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_save)
        btn_layout.addWidget(self.btn_cancel)
        main_layout.addLayout(btn_layout)

    def get_effective_project_folder(self):
        if self.project_id:
            row=db.fetchone('SELECT project_folder FROM gsv_projects WHERE id=?',(self.project_id,))
            if row and row[0]:return row[0]
        import re
        return os.path.join(BASE_PROJECTS_DIR, re.sub(r'[\\/:*?"<>|]', '_', self.txt_pd.text()))

    def handle_contract_action(self):
        if self.is_new and not self.save_data():return
        project_dir = self.get_effective_project_folder()
        c_num = self.txt_contract_num.text().replace('/', '_')
        c_path = os.path.join(project_dir, f"Договор_{c_num}.docx")
        if os.path.exists(c_path): open_file_or_dir(c_path)
        else: self.force_regenerate_contract()

    def force_regenerate_contract(self):
        if not self.save_data():return
        c_path = generate_contract_from_template(
            self.get_effective_project_folder(), self.txt_pd.text(), self.txt_contract_num.text(),
            format_date_word(self.dt_contract.date()), format_date_word(self.dt_due.date()),
            format_date_word(self.dt_act.date()) if self.chk_act.isChecked() else "Не подписан",
            self.spn_cost.value(), self.txt_client.text(), self.txt_phone.text(),
            self.txt_passport.toPlainText(), self.txt_object.text(), self.txt_address.text(), self.txt_notes.toPlainText()
        )
        db.execute("UPDATE gsv_projects SET project_folder=?, custom_contract_path=? WHERE id=?",(self.get_effective_project_folder(),c_path,self.project_id))
        QMessageBox.information(self, "Успех", "Договор сгенерирован!")
        open_file_or_dir(c_path)

    def setup_new_record(self):
        curr_year = datetime.now().year % 100
        self.txt_pd.setText(f"XX-{curr_year:02d} ГСВ (авто)")
        self.txt_contract_num.setText(f"XX-03/{curr_year:02d} (авто)")

    def set_fields_enabled(self, enabled):
        for w in [self.txt_object, self.txt_address, self.txt_client, self.txt_phone, self.txt_passport,
                  self.txt_notes, self.dt_contract, self.dt_due, self.chk_act, self.cmb_work_status,
                  self.cmb_client_status, self.spn_cost]: w.setEnabled(enabled)
        self.client_form.setEnabled(enabled)
        self.dt_act.setEnabled(enabled and self.chk_act.isChecked())
        self.btn_save.setEnabled(enabled)
        self.btn_regenerate_doc.setVisible(enabled and not self.is_new)

    def toggle_edit(self):
        self.is_editing_enabled = not self.is_editing_enabled
        self.set_fields_enabled(self.is_editing_enabled)
        self.btn_edit_toggle.setText("Заблокировать" if self.is_editing_enabled else "Изменить")

    def load_data(self):
        row = db.fetchone("SELECT * FROM gsv_projects WHERE id = ?", (self.project_id,))
        if not row: return
        self.txt_pd.setText(row[1])
        self.txt_object.setText(row[4] or "")
        self.txt_address.setText(row[5] or "")
        self.txt_client.setText(row[6] or "")
        self.txt_phone.setText(row[7] or "")
        self.txt_passport.setText(row[8] or "")
        self.txt_contract_num.setText(row[9] or "")
        if row[10]: self.dt_contract.setDate(QDate.fromString(row[10], "yyyy-MM-dd"))
        if row[11]: self.dt_due.setDate(QDate.fromString(row[11], "yyyy-MM-dd"))
        if row[12]:
            self.chk_act.setChecked(True)
            self.dt_act.setDate(QDate.fromString(row[12], "yyyy-MM-dd"))
        self.cmb_work_status.setCurrentText(row[14] or "Не сделано")
        self.cmb_client_status.setCurrentText(row[15] or "Не подписан")
        self.spn_cost.setValue(row[17] if len(row) > 17 and row[17] is not None else 250.0)
        self.txt_notes.setPlainText(row[20] if len(row) > 20 and row[20] else "")
        cid=db.fetchone('SELECT client_id FROM gsv_projects WHERE id=?',(self.project_id,))[0]
        client=get_client(db,cid) or dict(name=row[6],phone=row[7],passport=row[8])
        self.client_form.fill(client,cid)
        self.setWindowTitle(f"{row[4] or 'Без объекта'} | {row[6] or 'Без заказчика'}")

    def export_template(self):
        if self.save_data():
            from .report_dialog import ReportTemplateDialog
            ReportTemplateDialog('gsv_projects',self.project_id,self).exec()

    def open_payments(self):
        if self.save_data():
            from .payments_view import PaymentsDialog
            PaymentsDialog('gsv_projects',self.project_id,self).exec()
    def save_data(self):
        try:
            client=self.client_form.values()
            with db.transaction():
                cid=save_client(db,client,self.client_form.client_id)
                fields=['object_name','address','client_name','phone','passport','contract_date','due_date','act_date','work_status','client_status','cost','notes','client_id','client_address']
                values=[self.txt_object.text(),self.txt_address.text(),client['name'],client['phone'],client['passport'],self.dt_contract.date().toString('yyyy-MM-dd'),self.dt_due.date().toString('yyyy-MM-dd'),self.dt_act.date().toString('yyyy-MM-dd') if self.chk_act.isChecked() else None,self.cmb_work_status.currentText(),self.cmb_client_status.currentText(),self.spn_cost.value(),self.txt_notes.toPlainText(),cid,client['address']]
                rid=self.project_id
                if rid:db.execute('UPDATE gsv_projects SET '+','.join(f'{f}=?' for f in fields)+' WHERE id=?',(*values,rid))
                else:
                    year=datetime.now().year%100;seq=db.fetchone('SELECT coalesce(max(seq_num),0)+1 FROM gsv_projects WHERE year_num=?',(year,))[0]
                    pd_num=f'{seq:02}-{year:02} ГСВ';number=f'{seq:02}-03/{year:02}'
                    fields+=['pd_number','seq_num','year_num','contract_number'];values += [pd_num,seq,year,number]
                    rid=db.execute('INSERT INTO gsv_projects('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',values).lastrowid
            self.project_id=rid;self.is_new=False;self.client_form.client_id=cid;self.client_form.info.setText(f'Клиент №{cid}. Данные сохранены.')
            row=db.fetchone('SELECT pd_number,contract_number FROM gsv_projects WHERE id=?',(rid,));self.txt_pd.setText(row[0]);self.txt_contract_num.setText(row[1])
            self.btn_edit_toggle.setVisible(True);self.btn_regenerate_doc.setVisible(True);self.btn_contract_action.setText('Просмотр договора')
            self.save_status.setText(f'Сохранено · клиент №{cid}')
            return True
        except Exception as e:QMessageBox.warning(self,'Договор не сохранён',str(e));return False

class SideStatusBoard(QWidget):
    project_selected = pyqtSignal(int)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(280)
        layout = QVBoxLayout(self)
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Поиск по статусам...")
        self.txt_search.textChanged.connect(self.reload_data)
        layout.addWidget(self.txt_search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.box_layout = QVBoxLayout(container)
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def set_dark_mode(self, dark_mode):
        self.dark_mode = dark_mode
        self.reload_data()

    def reload_data(self):
        while self.box_layout.count():
            item = self.box_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        grp_work = QGroupBox("СТАТУС ВЫПОЛНЕНИЯ")
        l_work = QVBoxLayout(grp_work)
        l_work.addWidget(self.build_section("В работе", "work_status", "Не сделано"))
        l_work.addWidget(self.build_section("Приоритет", "work_status", "🔥 Приоритет"))
        l_work.addWidget(self.build_section("Выполнено", "work_status", "Сделано"))
        self.box_layout.addWidget(grp_work)

        grp_client = QGroupBox("СТАТУС ДОГОВОРА")
        l_client = QVBoxLayout(grp_client)
        l_client.addWidget(self.build_section("Не подписан", "client_status", "Не подписан"))
        l_client.addWidget(self.build_section("Подписан", "client_status", "Подписан"))
        l_client.addWidget(self.build_section("Оплачен", "client_status", "Оплачен"))
        self.box_layout.addWidget(grp_client)
        self.box_layout.addStretch()

    def build_section(self, title, field, value):
        frame = QFrame()
        l = QVBoxLayout(frame)
        l.addWidget(QLabel(f"<b>{title}</b>"))

        query = f"SELECT id, pd_number, client_name FROM gsv_projects WHERE {field} = ?"
        params = [value]
        search = self.txt_search.text().strip().lower()
        if search:
            query += " AND (LOWER(pd_number) LIKE ? OR LOWER(client_name) LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY id DESC"

        rows = db.fetchall(query + " LIMIT 51", tuple(params))
        if len(rows)>50: l.addWidget(QLabel("Первые 50 · все записи в реестре"))
        rows=rows[:50]
        for r in rows:
            btn = QPushButton(f"{r[1]}\n{r[2] or 'Без имени'}")
            btn.clicked.connect(lambda ch=False, pid=r[0]: self.project_selected.emit(pid))
            l.addWidget(btn)
        return frame

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
        self.txt_search.setPlaceholderText("Поиск...")
        self.txt_search.textChanged.connect(self.load_data)

        btn_tpl = QPushButton("Шаблон Word")
        btn_tpl.clicked.connect(lambda: TemplateSettingsDialog(self).exec())
        btn_excel = QPushButton("Выгрузка Excel")
        btn_excel.clicked.connect(lambda: export_all_to_excel(self))
        btn_tags = QPushButton("Теги для шаблонов")
        btn_tags.clicked.connect(self.show_tag_reference)

        for w in [btn_add, btn_reports, self.btn_urgent, self.txt_search]: top_bar.addWidget(w)
        top_bar.addStretch()
        top_bar.addWidget(btn_tpl)
        top_bar.addWidget(btn_tags)
        top_bar.addWidget(btn_excel)
        payments=QPushButton("Оплаты");payments.clicked.connect(self.open_payments);top_bar.addWidget(payments)
        layout.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.side_board = SideStatusBoard()
        self.side_board.set_dark_mode(self.dark_mode)
        self.side_board.project_selected.connect(self.open_edit_dialog)
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

        # Full backups are managed by AutoBackupService in the main window.

    def refresh_ui(self):
        self.dark_mode = db.get_setting("is_dark", "0") == "1"
        self.model.set_dark_mode(self.dark_mode)
        self.side_board.set_dark_mode(self.dark_mode)

    def toggle_urgent(self):
        self.urgent_filter_active = self.btn_urgent.isChecked()
        self.load_data()

    def open_payments(self):
        row=self.view_table.currentIndex().row()
        if row>=0:
            from .payments_view import PaymentsDialog
            PaymentsDialog('gsv_projects',self.model.get_row_record(row)[0],self).exec();self.load_data()
    def show_tag_reference(self):
        from .executive_workspace import TagReferenceDialog
        TagReferenceDialog('gsv_projects',self).exec()
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
            db.execute("DELETE FROM gsv_projects WHERE id=?", (r[0],))
            self.load_data()

    def load_data(self):
        q=self.txt_search.text().strip().casefold()
        sql="SELECT id,pd_number,object_name,client_name,cost,client_status,work_status,project_folder,due_date FROM gsv_projects"
        conditions=[];params=[]
        if q:
            conditions.append('(LOWER(pd_number) LIKE ? OR LOWER(object_name) LIKE ? OR LOWER(client_name) LIKE ?)');params.extend(['%'+q+'%']*3)
        if self.urgent_filter_active:conditions.append("work_status <> 'Сделано' AND date(due_date) <= date('now','+5 days')")
        if conditions:sql+=' WHERE '+' AND '.join(conditions)
        rows=self.pager.fetch(sql+' ORDER BY id DESC',params)
        self.model.update_data(rows);self.side_board.reload_data()
