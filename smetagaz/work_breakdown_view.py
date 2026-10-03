"""
Расшифровка сметы: работы по статьям формулы (ЗП, ОХР/ОПР, прибыль, соцстрах,
другие затраты, налог) и обычный список материалов. Отдельно от основной сметы —
там раскрывать эти статьи не нужно.
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView
from PyQt6.QtCore import Qt

from .database import db
from . import report_templates as reports

WORK_COLUMNS = [
    ("name", "Наименование"), ("unit", "Ед."), ("quantity", "Кол-во"), ("price", "Цена/ед"),
    ("has_breakdown", "Есть данные"), ("wage_sum", "ЗП"), ("overhead_sum", "ОХР/ОПР"),
    ("profit_sum", "Прибыль"), ("social_sum", "СоцСтрах"), ("other_sum", "Другие"),
    ("tax_sum", "Налог на прибыль"), ("amount", "Сумма"),
]
MATERIAL_COLUMNS = [("name", "Наименование"), ("unit", "Ед."), ("quantity", "Кол-во"), ("price", "Цена"), ("amount", "Сумма"), ("margin_unit", "Маржа/ед"), ("margin_sum", "Маржа")]


def fmt(value):
    if isinstance(value, str):
        return value
    try:
        return f"{float(value):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


class WorkBreakdownDialog(QDialog):
    def __init__(self, estimate_id, parent=None):
        super().__init__(parent)
        self.estimate_id = estimate_id
        self.setWindowTitle("Расшифровка сметы: работы и материалы")
        self.resize(1150, 700)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Работы: заработная плата, ОХР и ОПР, плановая прибыль, соцстрах, другие затраты, налог на прибыль."))

        self.table_works = QTableWidget(0, len(WORK_COLUMNS))
        self.table_works.setHorizontalHeaderLabels([label for _, label in WORK_COLUMNS])
        self.table_works.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_works.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table_works, 2)

        self.lbl_work_totals = QLabel()
        self.lbl_work_totals.setWordWrap(True)
        layout.addWidget(self.lbl_work_totals)

        layout.addWidget(QLabel("Материалы:"))
        self.table_materials = QTableWidget(0, len(MATERIAL_COLUMNS))
        self.table_materials.setHorizontalHeaderLabels([label for _, label in MATERIAL_COLUMNS])
        self.table_materials.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_materials.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table_materials, 2)

        self.lbl_grand_total = QLabel()
        layout.addWidget(self.lbl_grand_total)

        bar = QHBoxLayout()
        btn_export = QPushButton("Экспорт в Word / Excel по шаблону…")
        btn_export.setProperty("type", "primary")
        btn_export.clicked.connect(self.export_template)
        bar.addWidget(btn_export)
        bar.addStretch()
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        bar.addWidget(btn_close)
        layout.addLayout(bar)

        self.load_data()

    def load_data(self):
        ctx, tables = reports.context(db, "estimate_breakdown", self.estimate_id)

        works = tables.get("works", [])
        self.table_works.setRowCount(len(works))
        for r, row in enumerate(works):
            for c, (key, _) in enumerate(WORK_COLUMNS):
                item = QTableWidgetItem(fmt(row.get(key)))
                if key in ("price", "wage_sum", "overhead_sum", "profit_sum", "social_sum", "other_sum", "tax_sum", "amount"):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table_works.setItem(r, c, item)

        materials = tables.get("materials", [])
        self.table_materials.setRowCount(len(materials))
        for r, row in enumerate(materials):
            for c, (key, _) in enumerate(MATERIAL_COLUMNS):
                item = QTableWidgetItem(fmt(row.get(key)))
                if key in ("price", "amount", "margin_unit", "margin_sum"):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table_materials.setItem(r, c, item)

        self.lbl_work_totals.setText(
            f"Итого по работам — ЗП: {fmt(ctx['work_wage_total'])} · ОХР/ОПР: {fmt(ctx['work_overhead_total'])} · "
            f"Прибыль: {fmt(ctx['work_profit_total'])} · СоцСтрах: {fmt(ctx['work_social_total'])} · "
            f"Другие: {fmt(ctx['work_other_total'])} · Налог на прибыль: {fmt(ctx['work_tax_total'])} · "
            f"Сумма работ: {fmt(ctx['works_total'])} руб."
        )
        self.lbl_grand_total.setText(
            f"<b>Материалы: {fmt(ctx['materials_total'])} руб. (маржа: {fmt(ctx['materials_margin_total'])} руб.) · "
            f"Работы: {fmt(ctx['works_total'])} руб. · Итого по смете: {fmt(ctx['grand_total'])} руб.</b>"
        )

    def export_template(self):
        from .report_dialog import ReportTemplateDialog
        ReportTemplateDialog("estimate_breakdown", self.estimate_id, self).exec()
