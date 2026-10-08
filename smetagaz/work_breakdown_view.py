"""Окно «Расшифровка и маржа»: работы по статьям формулы справочника, материалы с маржой и итоги в одном окне. Экспорт — по шаблону."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QTabWidget, QWidget
from PyQt6.QtCore import Qt

from .database import db
from . import estimates_domain as ed

WORK_COLUMNS = [
    ("name", "Наименование"), ("unit", "Ед."), ("quantity", "Кол-во"), ("price", "Цена/ед"), ("amount", "Сумма"),
    ("has_breakdown", "Есть данные"), ("wage_sum", "ЗП"), ("overhead_sum", "ОХР/ОПР"), ("profit_sum", "Прибыль"), ("social_sum", "СоцСтрах"),
    ("other_sum", "Другие"), ("tax_sum", "Налог на прибыль"), ("cost_sum", "Себестоимость"), ("margin_sum", "Маржа"),
]
MATERIAL_COLUMNS = [("name", "Наименование"), ("unit", "Ед."), ("quantity", "Кол-во"), ("price", "Цена"), ("purchase_price", "Закупка"), ("amount", "Сумма"),
                    ("cost_sum", "Себестоимость"), ("margin_unit", "Маржа/ед"), ("margin_sum", "Маржа")]
RIGHT = {"price", "amount", "purchase_price", "wage_sum", "overhead_sum", "profit_sum", "social_sum", "other_sum", "tax_sum", "cost_sum", "margin_sum", "margin_unit", "quantity"}


def fmt(value):
    if isinstance(value, str):
        return value
    try:
        return f"{float(value):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _table(columns):
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels([label for _, label in columns])
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.horizontalHeader().setStretchLastSection(True)
    t.setColumnWidth(0, 260)
    return t


def _fill(table, columns, rows):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, (key, _) in enumerate(columns):
            item = QTableWidgetItem(fmt(row.get(key)))
            if key in RIGHT:
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(r, c, item)


class WorkBreakdownDialog(QDialog):
    def __init__(self, estimate_id, parent=None):
        super().__init__(parent)
        self.estimate_id = estimate_id
        self.setWindowTitle("Расшифровка и маржа")
        self.resize(1250, 740)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel("Работы по статьям формулы справочника: заработная плата, ОХР и ОПР, плановая прибыль, соцстрах, другие затраты, налог на прибыль."))
        self.table_works = _table(WORK_COLUMNS)
        pl.addWidget(self.table_works, 1)
        self.lbl_work_totals = QLabel()
        self.lbl_work_totals.setWordWrap(True)
        pl.addWidget(self.lbl_work_totals)
        tabs.addTab(page, "Работы")

        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel("Материалы: цена продажи, закупка и маржа по каждой позиции."))
        self.table_materials = _table(MATERIAL_COLUMNS)
        pl.addWidget(self.table_materials, 1)
        self.lbl_materials = QLabel()
        pl.addWidget(self.lbl_materials)
        tabs.addTab(page, "Материалы и маржа")

        page = QWidget()
        pl = QVBoxLayout(page)
        self.table_summary = QTableWidget(0, 2)
        self.table_summary.setHorizontalHeaderLabels(["Показатель", "Значение"])
        self.table_summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_summary.horizontalHeader().setStretchLastSection(True)
        self.table_summary.setColumnWidth(0, 460)
        pl.addWidget(self.table_summary, 1)
        self.lbl_summary = QLabel()
        self.lbl_summary.setWordWrap(True)
        pl.addWidget(self.lbl_summary)
        tabs.addTab(page, "Итоги и маржа")
        self.tabs = tabs

        bar = QHBoxLayout()
        btn_export = QPushButton("Экспорт по шаблону…")
        btn_export.setProperty("type", "primary")
        btn_export.clicked.connect(self.export_template)
        bar.addWidget(btn_export)
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self.load_data)
        bar.addWidget(btn_refresh)
        bar.addStretch()
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        bar.addWidget(btn_close)
        layout.addLayout(bar)
        self.load_data()

    def load_data(self):
        works, materials, info = ed.breakdown(db, self.estimate_id)
        m = ed.margin_summary(db, self.estimate_id)
        _fill(self.table_works, WORK_COLUMNS, works)
        _fill(self.table_materials, MATERIAL_COLUMNS, materials)
        self.lbl_work_totals.setText(
            f"Итого по работам — ЗП: {fmt(info['work_wage_total'])} · ОХР/ОПР: {fmt(info['work_overhead_total'])} · Прибыль: {fmt(info['work_profit_total'])} · "
            f"СоцСтрах: {fmt(info['work_social_total'])} · Другие: {fmt(info['work_other_total'])} · Налог на прибыль: {fmt(info['work_tax_total'])} · "
            f"Сумма работ: {fmt(info['works_total'])} руб.")
        self.lbl_materials.setText(f"<b>Материалы: {fmt(info['materials_total'])} руб. · маржа по материалам: {fmt(info['materials_margin_total'])} руб.</b>")
        rows = [
            ("Закупка материалов (себестоимость)", m['cost_materials']), ("Себестоимость работ", m['cost_works']), ("Себестоимость всего", m['cost_total']),
            ("Продажа по смете (базовая, без скидок и наценок)", m['sale_base']), ("Продажа: материалы (со скидками и наценками)", m['sale_materials']),
            ("Продажа: работы (со скидками и наценками)", m['sale_works']), ("Продажа всего (итого по смете)", m['sale_total']),
            ("Маржа по материалам", m['margin_materials']), ("Маржа по работам", m['margin_works']), ("ЧИСТАЯ МАРЖА", m['margin_total']),
            ("Маржа, % от продажи", m['margin_pct']),
        ]
        self.table_summary.setRowCount(len(rows))
        for r, (name, value) in enumerate(rows):
            self.table_summary.setItem(r, 0, QTableWidgetItem(name))
            item = QTableWidgetItem(f"{fmt(value)} %" if name.startswith("Маржа, %") else f"{fmt(value)} руб.")
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if name == "ЧИСТАЯ МАРЖА":
                font = item.font(); font.setBold(True); item.setFont(font)
            self.table_summary.setItem(r, 1, item)
        self.lbl_summary.setText(f"<b>Чистая маржа: {fmt(m['margin_total'])} руб. ({fmt(m['margin_pct'])} %)</b> · итого по смете: {fmt(m['sale_total'])} руб.")

    def export_template(self):
        from .report_dialog import ReportTemplateDialog
        ReportTemplateDialog("estimate_breakdown", self.estimate_id, self).exec()
