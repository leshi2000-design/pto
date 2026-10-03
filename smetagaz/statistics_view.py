"""
Вкладка "Статистика": сводки по выручке/оплатам/материалам/работам за период,
график по месяцам (pyqtgraph) и таблица расхода позиций с фильтром по разделу
справочника и поиском.
"""
import pyqtgraph as pg

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QFrame, QTableWidget, QTableWidgetItem, QAbstractItemView,
                              QLineEdit, QComboBox, QDateEdit, QGridLayout, QProgressBar)
from PyQt6.QtCore import Qt, QDate

from .database import db
from .widgets import SmartTableManager


class StatisticsView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Период:"))

        self.combo_period = QComboBox()
        self.combo_period.addItems(["За всё время", "Сегодня", "Текущая неделя", "Текущий месяц", "Прошлый месяц", "Произвольный период"])
        self.combo_period.currentIndexChanged.connect(self.on_period_change)
        filter_bar.addWidget(self.combo_period)

        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)

        filter_bar.addWidget(QLabel("с"))
        filter_bar.addWidget(self.date_start)
        filter_bar.addWidget(QLabel("по"))
        filter_bar.addWidget(self.date_end)

        btn_calc = QPushButton("Рассчитать")
        btn_calc.setProperty("type", "primary")
        btn_calc.clicked.connect(self.calculate)
        filter_bar.addWidget(btn_calc)
        btn_report=QPushButton('Отчёт по шаблону');btn_report.clicked.connect(self.export_template);filter_bar.addWidget(btn_report)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)
        payment_bar=QHBoxLayout();self.payment_section=QComboBox();self.payment_section.addItem('Оплаты: все разделы','')
        for key,title in [('gsn_projects','ГСН'),('contracts','ГСВ'),('gsv_projects','Проектирование ГСВ'),('estimates','Сметы без договора')]:self.payment_section.addItem(title,key)
        payment_bar.addWidget(self.payment_section);payment_report=QPushButton('Отчёт по оплатам за выбранный период');payment_report.clicked.connect(self.export_payments);payment_bar.addWidget(payment_report);payment_bar.addStretch();layout.addLayout(payment_bar)

        cards_layout = QGridLayout()
        self.lbl_total_est = QLabel("0 руб.")
        self.lbl_total_paid = QLabel("0 руб.")
        self.lbl_materials = QLabel("0 руб.")
        self.lbl_works = QLabel("0 руб.")

        def make_card(title, value_widget):
            f = QFrame();f.setObjectName("metricCard")
            main_l = QVBoxLayout(f)
            t = QLabel(title)
            main_l.addWidget(t)
            value_widget.setStyleSheet("font-size: 18pt; font-weight: bold;")
            main_l.addWidget(value_widget)
            return f

        cards_layout.addWidget(make_card("Сумма заключенных смет:", self.lbl_total_est), 0, 0)
        cards_layout.addWidget(make_card("Фактически оплачено:", self.lbl_total_paid), 0, 1)
        cards_layout.addWidget(make_card("Себестоимость материалов:", self.lbl_materials), 1, 0)
        cards_layout.addWidget(make_card("Прямая стоимость работ:", self.lbl_works), 1, 1)
        layout.addLayout(cards_layout)

        dashboard_layout = QHBoxLayout()

        left_dash = QVBoxLayout()
        self.progress_pay = QProgressBar()
        self.progress_pay.setTextVisible(True)
        self.progress_pay.setFixedHeight(24)
        left_dash.addWidget(QLabel("Процент оплат от заключенных смет:"))
        left_dash.addWidget(self.progress_pay)
        left_dash.addSpacing(10)

        left_dash.addWidget(QLabel("Динамика выручки (сметы) за последние 6 месяцев:"))
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('transparent')
        self.plot_widget.setMenuEnabled(False)
        self.plot_widget.getAxis('left').setPen(pg.mkPen(color='#94A3B8'))
        self.plot_widget.getAxis('bottom').setPen(pg.mkPen(color='#94A3B8'))
        left_dash.addWidget(self.plot_widget)

        dashboard_layout.addLayout(left_dash, stretch=1)

        right_dash = QVBoxLayout()
        tools_layout = QHBoxLayout()
        tools_layout.addWidget(QLabel("Топ позиций. Фильтр:"))
        self.combo_cat = QComboBox()
        self.load_categories_to_combo()
        self.combo_cat.currentIndexChanged.connect(self.filter_stat_table)
        tools_layout.addWidget(self.combo_cat)

        self.search_inp = QLineEdit()
        self.search_inp.setPlaceholderText("Название...")
        self.search_inp.textChanged.connect(self.filter_stat_table)
        tools_layout.addWidget(self.search_inp)
        right_dash.addLayout(tools_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Наименование", "Ед.", "Расход", "Сумма (руб)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table_manager = SmartTableManager(self.table, main_col=0, default_widths={1: 60, 2: 80, 3: 120})
        right_dash.addWidget(self.table)

        dashboard_layout.addLayout(right_dash, stretch=1)
        layout.addLayout(dashboard_layout)

        self.combo_period.setCurrentIndex(3)
        self.calculate()

    def export_payments(self):
        from .report_dialog import ReportTemplateDialog
        ReportTemplateDialog('payment_report',parent=self,filters={'start':self.date_start.date().toString('yyyy-MM-dd'),'end':self.date_end.date().toString('yyyy-MM-dd'),'section':self.payment_section.currentData()}).exec()

    def export_template(self):
        from .report_dialog import ReportTemplateDialog
        ReportTemplateDialog('statistics',parent=self,filters={'start':self.date_start.date().toString('yyyy-MM-dd'),'end':self.date_end.date().toString('yyyy-MM-dd')}).exec()

    def load_categories_to_combo(self):
        self.combo_cat.addItem("📁 Все разделы", None)
        roots = db.fetchall("SELECT id, name FROM categories WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            self.combo_cat.addItem(f"📁 {r_name}", r_id)
            subs = db.fetchall("SELECT id, name FROM categories WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                self.combo_cat.addItem(f"   📂 {s_name}", s_id)

    def on_period_change(self):
        idx = self.combo_period.currentIndex()
        today = QDate.currentDate()
        if idx == 0:
            self.date_start.setDate(QDate(2020, 1, 1))
            self.date_end.setDate(today)
        elif idx == 1:
            self.date_start.setDate(today)
            self.date_end.setDate(today)
        elif idx == 2:
            self.date_start.setDate(today.addDays(-(today.dayOfWeek() - 1)))
            self.date_end.setDate(today)
        elif idx == 3:
            self.date_start.setDate(QDate(today.year(), today.month(), 1))
            self.date_end.setDate(today)
        elif idx == 4:
            prev = today.addMonths(-1)
            self.date_start.setDate(QDate(prev.year(), prev.month(), 1))
            self.date_end.setDate(QDate(prev.year(), prev.month(), prev.daysInMonth()))

    def calculate(self):
        d_start = self.date_start.date().toString("yyyy-MM-dd")
        d_end = self.date_end.date().toString("yyyy-MM-dd")

        est_data = db.fetchone("SELECT SUM(total), SUM(paid) FROM estimates WHERE date >= ? AND date <= ?", (d_start, d_end))
        t_est = est_data[0] or 0.0
        t_paid = est_data[1] or 0.0
        self.lbl_total_est.setText(f"{t_est:,.2f} руб.".replace(",", " "))
        self.lbl_total_paid.setText(f"{t_paid:,.2f} руб.".replace(",", " "))

        if t_est > 0:
            percent = int((t_paid / t_est) * 100)
            self.progress_pay.setValue(min(percent, 100))
        else:
            self.progress_pay.setValue(0)

        types_data = db.fetchall("SELECT item_type, SUM(sum) FROM estimate_items JOIN estimates ON estimate_items.estimate_id = estimates.id WHERE date >= ? AND date <= ? GROUP BY item_type", (d_start, d_end))
        t_mat = 0.0
        t_work = 0.0
        for t, s in types_data:
            if t == "Работа": t_work += s or 0
            else: t_mat += s or 0

        self.lbl_materials.setText(f"{t_mat:,.2f} руб.".replace(",", " "))
        self.lbl_works.setText(f"{t_work:,.2f} руб.".replace(",", " "))

        self.plot_widget.clear()
        six_months_ago = QDate.currentDate().addMonths(-5)
        d_start_chart = QDate(six_months_ago.year(), six_months_ago.month(), 1).toString("yyyy-MM-dd")
        chart_data = db.fetchall("SELECT strftime('%Y-%m', date) as m, SUM(total) FROM estimates WHERE date >= ? GROUP BY m ORDER BY m ASC", (d_start_chart,))

        if chart_data:
            x_pos = range(len(chart_data))
            y_vals = [row[1] for row in chart_data]
            labels = [row[0] for row in chart_data]

            accent = db.get_setting("accent_color", "#0284C7")
            bg = pg.BarGraphItem(x=list(x_pos), height=y_vals, width=0.5, brush=accent)
            self.plot_widget.addItem(bg)

            ax = self.plot_widget.getAxis('bottom')
            ax.setTicks([list(zip(x_pos, labels))])

        query = """
            SELECT ei.name, ei.unit, SUM(ei.quantity), SUM(ei.sum), MAX(m.category_id)
            FROM estimate_items ei 
            JOIN estimates e ON ei.estimate_id = e.id 
            LEFT JOIN (SELECT name, MAX(category_id) AS category_id FROM materials WHERE item_type='Материал' GROUP BY name) m ON ei.name = m.name
            WHERE e.date >= ? AND e.date <= ? AND ei.item_type = 'Материал' 
            GROUP BY ei.name, ei.unit 
            ORDER BY SUM(ei.sum) DESC
        """
        rows = db.fetchall(query, (d_start, d_end))

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for r, (name, unit, qty, sm, cat_id) in enumerate(rows):
            item_name = QTableWidgetItem(name)
            item_name.setData(Qt.ItemDataRole.UserRole, cat_id)
            self.table.setItem(r, 0, item_name)

            i_u = QTableWidgetItem(unit)
            i_u.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(r, 1, i_u)

            q_val = float(qty) if qty is not None else 0.0
            i_qty = QTableWidgetItem(f"{q_val:.2f}")
            i_qty.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 2, i_qty)

            s_val = float(sm) if sm is not None else 0.0
            i_sm = QTableWidgetItem(f"{s_val:,.2f}".replace(",", " "))
            i_sm.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 3, i_sm)

        self.table.setUpdatesEnabled(True)
        self.table_manager.adjust_main_column()
        self.filter_stat_table()

    def filter_stat_table(self):
        search_text = self.search_inp.text().lower()
        sel_cat = self.combo_cat.currentData()

        valid_cats = set()
        if sel_cat is not None:
            valid_cats.add(sel_cat)
            subs = db.fetchall("SELECT id FROM categories WHERE parent_id=?", (sel_cat,))
            for s in subs: valid_cats.add(s[0])

        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            if not name_item: continue
            name_val = name_item.text().lower()
            cat_id = name_item.data(Qt.ItemDataRole.UserRole)
            match_search = search_text in name_val
            match_cat = True
            if sel_cat is not None: match_cat = cat_id in valid_cats
            self.table.setRowHidden(row, not (match_search and match_cat))

