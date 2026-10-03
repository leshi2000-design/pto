"""
Дополнительные модули приложения: ГСН, Сварщики, Калькуляторы, Списание.
"""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout, QComboBox, QDoubleSpinBox,
                             QFrame, QPushButton, QDialog)
from PyQt6.QtCore import Qt
from .database import db

# Реэкспорт для main_window/report_dialog: сюда сведены вкладки "Доп. модули".
from .workspace_view import WorkspaceView  # noqa: F401
from .gsn_view import GsnProjectsView  # noqa: F401
from .welding_view import WeldersView  # noqa: F401
from .stock_view import WriteoffView  # noqa: F401

# --- ДИАЛОГИ КАЛЬКУЛЯТОРОВ ---

class VatCalcDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выделение НДС")
        self.resize(400, 200)
        layout = QVBoxLayout(self)

        grid = QGridLayout()
        grid.addWidget(QLabel("Сумма с НДС:"), 0, 0)
        self.spin_total = QDoubleSpinBox()
        self.spin_total.setRange(0, 1000000000)
        self.spin_total.setDecimals(2)
        self.spin_total.setSuffix(" руб.")
        self.spin_total.valueChanged.connect(self.calculate)
        grid.addWidget(self.spin_total, 0, 1)

        grid.addWidget(QLabel("Ставка НДС:"), 1, 0)
        self.spin_rate = QDoubleSpinBox()
        self.spin_rate.setRange(0, 100)
        self.spin_rate.setDecimals(1)
        self.spin_rate.setSuffix(" %")
        self.spin_rate.setValue(20.0)
        self.spin_rate.valueChanged.connect(self.calculate)
        grid.addWidget(self.spin_rate, 1, 1)

        grid.addWidget(QLabel("Сумма без НДС:"), 2, 0)
        self.lbl_net = QLabel("0.00 руб.")
        self.lbl_net.setStyleSheet("font-weight: bold; color: #0284C7; font-size: 12pt;")
        grid.addWidget(self.lbl_net, 2, 1)

        grid.addWidget(QLabel("Сумма НДС:"), 3, 0)
        self.lbl_tax = QLabel("0.00 руб.")
        self.lbl_tax.setStyleSheet("font-weight: bold; color: #DC2626; font-size: 12pt;")
        grid.addWidget(self.lbl_tax, 3, 1)

        layout.addLayout(grid)

    def calculate(self):
        total = self.spin_total.value()
        rate = self.spin_rate.value()
        net = total / (1 + (rate / 100))
        tax = total - net
        self.lbl_net.setText(f"{net:,.2f} руб.".replace(",", " "))
        self.lbl_tax.setText(f"{tax:,.2f} руб.".replace(",", " "))

class ConverterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Конвертер величин")
        self.resize(450, 200)
        layout = QVBoxLayout(self)

        grid = QGridLayout()
        grid.addWidget(QLabel("Длина:"), 0, 0)
        self.spin_len = QDoubleSpinBox()
        self.spin_len.setRange(0, 10000000)
        self.spin_len.setDecimals(3)
        self.spin_len.valueChanged.connect(self.calc_len)
        grid.addWidget(self.spin_len, 0, 1)

        self.cmb_len_from = QComboBox()
        self.cmb_len_from.addItems(["м", "мм", "см", "км"])
        self.cmb_len_from.currentIndexChanged.connect(self.calc_len)
        grid.addWidget(self.cmb_len_from, 0, 2)

        grid.addWidget(QLabel("➔"), 0, 3, alignment=Qt.AlignmentFlag.AlignCenter)

        self.cmb_len_to = QComboBox()
        self.cmb_len_to.addItems(["мм", "м", "см", "км"])
        self.cmb_len_to.currentIndexChanged.connect(self.calc_len)
        grid.addWidget(self.cmb_len_to, 0, 4)

        self.lbl_len_res = QLabel("0.000")
        self.lbl_len_res.setStyleSheet("font-weight: bold; color: #16A34A;")
        grid.addWidget(self.lbl_len_res, 0, 5)

        grid.addWidget(QLabel("Масса:"), 1, 0)
        self.spin_mass = QDoubleSpinBox()
        self.spin_mass.setRange(0, 10000000)
        self.spin_mass.setDecimals(3)
        self.spin_mass.valueChanged.connect(self.calc_mass)
        grid.addWidget(self.spin_mass, 1, 1)

        self.cmb_mass_from = QComboBox()
        self.cmb_mass_from.addItems(["кг", "г", "т"])
        self.cmb_mass_from.currentIndexChanged.connect(self.calc_mass)
        grid.addWidget(self.cmb_mass_from, 1, 2)

        grid.addWidget(QLabel("➔"), 1, 3, alignment=Qt.AlignmentFlag.AlignCenter)

        self.cmb_mass_to = QComboBox()
        self.cmb_mass_to.addItems(["т", "кг", "г"])
        self.cmb_mass_to.currentIndexChanged.connect(self.calc_mass)
        grid.addWidget(self.cmb_mass_to, 1, 4)

        self.lbl_mass_res = QLabel("0.000")
        self.lbl_mass_res.setStyleSheet("font-weight: bold; color: #16A34A;")
        grid.addWidget(self.lbl_mass_res, 1, 5)

        layout.addLayout(grid)

    def calc_len(self):
        val = self.spin_len.value()
        mults_from = [1.0, 0.001, 0.01, 1000.0]
        mults_to = [1000.0, 1.0, 100.0, 0.001]
        res = (val * mults_from[self.cmb_len_from.currentIndex()]) * mults_to[self.cmb_len_to.currentIndex()]
        self.lbl_len_res.setText(f"{res:,.3f}".replace(",", " "))

    def calc_mass(self):
        val = self.spin_mass.value()
        mults_from = [1.0, 0.001, 1000.0]
        mults_to = [0.001, 1.0, 1000.0]
        res = (val * mults_from[self.cmb_mass_from.currentIndex()]) * mults_to[self.cmb_mass_to.currentIndex()]
        self.lbl_mass_res.setText(f"{res:,.3f}".replace(",", " "))

class EarthworksCalcDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Объем земляных работ")
        self.resize(350, 250)
        layout = QVBoxLayout(self)
        grid = QGridLayout()

        grid.addWidget(QLabel("Длина (м):"), 0, 0)
        self.spin_l = QDoubleSpinBox(); self.spin_l.setRange(0, 100000); self.spin_l.valueChanged.connect(self.calc)
        grid.addWidget(self.spin_l, 0, 1)

        grid.addWidget(QLabel("Глубина (м):"), 1, 0)
        self.spin_h = QDoubleSpinBox(); self.spin_h.setRange(0, 100); self.spin_h.valueChanged.connect(self.calc)
        grid.addWidget(self.spin_h, 1, 1)

        grid.addWidget(QLabel("Ширина по дну (м):"), 2, 0)
        self.spin_wb = QDoubleSpinBox(); self.spin_wb.setRange(0, 100); self.spin_wb.valueChanged.connect(self.calc)
        grid.addWidget(self.spin_wb, 2, 1)

        grid.addWidget(QLabel("Ширина по верху (м):"), 3, 0)
        self.spin_wt = QDoubleSpinBox(); self.spin_wt.setRange(0, 100); self.spin_wt.valueChanged.connect(self.calc)
        grid.addWidget(self.spin_wt, 3, 1)

        grid.addWidget(QLabel("Объем грунта:"), 4, 0)
        self.lbl_res = QLabel("0.00 м³")
        self.lbl_res.setStyleSheet("font-weight: bold; color: #D97706; font-size: 14pt;")
        grid.addWidget(self.lbl_res, 4, 1)

        layout.addLayout(grid)

    def calc(self):
        v = self.spin_l.value() * ((self.spin_wb.value() + self.spin_wt.value()) / 2.0) * self.spin_h.value()
        self.lbl_res.setText(f"{v:,.2f} м³".replace(",", " "))


# --- НАСТРОЙКИ ПРИБЫЛИ ---
class ProfitSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать формулы расчета")
        self.resize(350, 200)
        layout = QVBoxLayout(self)
        grid = QGridLayout()

        self.sp_nds = QDoubleSpinBox()
        self.sp_nds.setRange(0, 100)
        self.sp_nds.setValue(float(db.get_setting("calc_nds_pct", 20.0)))

        self.sp_tax = QDoubleSpinBox()
        self.sp_tax.setRange(0, 100)
        self.sp_tax.setValue(float(db.get_setting("calc_tax_pct", 20.0)))

        self.sp_soc = QDoubleSpinBox()
        self.sp_soc.setRange(0, 100)
        self.sp_soc.setValue(float(db.get_setting("calc_soc_pct", 34.6)))

        grid.addWidget(QLabel("Ставка НДС (в т.ч.) %:"), 0, 0); grid.addWidget(self.sp_nds, 0, 1)
        grid.addWidget(QLabel("Налог на прибыль %:"), 1, 0); grid.addWidget(self.sp_tax, 1, 1)
        grid.addWidget(QLabel("СоцСтрах (от ЗП) %:"), 2, 0); grid.addWidget(self.sp_soc, 2, 1)

        layout.addLayout(grid)
        btn_save = QPushButton("Сохранить и пересчитать")
        btn_save.setProperty("type", "primary")
        btn_save.clicked.connect(self.save_cfg)
        layout.addWidget(btn_save)

    def save_cfg(self):
        db.set_setting("calc_nds_pct", self.sp_nds.value())
        db.set_setting("calc_tax_pct", self.sp_tax.value())
        db.set_setting("calc_soc_pct", self.sp_soc.value())
        self.accept()

class ProfitCalcDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Калькулятор плановой прибыли")
        self.resize(500, 420)
        layout = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        btn_cfg = QPushButton("⚙️ Редактировать формулы расчета")
        btn_cfg.clicked.connect(self.open_settings)
        top_bar.addStretch()
        top_bar.addWidget(btn_cfg)
        layout.addLayout(top_bar)

        grid = QGridLayout()
        grid.addWidget(QLabel("Итоговая стоимость (с НДС):"), 0, 0)
        self.spin_cost = QDoubleSpinBox()
        self.spin_cost.setRange(0, 1000000000)
        self.spin_cost.setDecimals(2)
        self.spin_cost.setSuffix(" руб.")
        self.spin_cost.valueChanged.connect(self.calculate)
        grid.addWidget(self.spin_cost, 0, 1)

        grid.addWidget(QLabel("Зарплата исполнителей:"), 1, 0)
        self.spin_zp = QDoubleSpinBox()
        self.spin_zp.setRange(0, 1000000000)
        self.spin_zp.setDecimals(2)
        self.spin_zp.setSuffix(" руб.")
        self.spin_zp.valueChanged.connect(self.calculate)
        grid.addWidget(self.spin_zp, 1, 1)

        grid.addWidget(QLabel("ОХР и ОПР (% от ЗП):"), 2, 0)
        self.spin_ohr = QDoubleSpinBox()
        self.spin_ohr.setRange(0, 100)
        self.spin_ohr.setDecimals(1)
        self.spin_ohr.setSuffix(" %")
        self.spin_ohr.setValue(15.0)
        self.spin_ohr.valueChanged.connect(self.calculate)
        grid.addWidget(self.spin_ohr, 2, 1)

        layout.addLayout(grid)
        layout.addWidget(QFrame(frameShape=QFrame.Shape.HLine))

        res_grid = QGridLayout()
        self.lbl_nds_title = QLabel("НДС (в т.ч.):"); self.lbl_nds = QLabel("0.00 руб.")
        res_grid.addWidget(self.lbl_nds_title, 0, 0); res_grid.addWidget(self.lbl_nds, 0, 1)

        self.lbl_soc_title = QLabel("СоцСтрах от ЗП:"); self.lbl_soc = QLabel("0.00 руб.")
        res_grid.addWidget(self.lbl_soc_title, 1, 0); res_grid.addWidget(self.lbl_soc, 1, 1)

        self.lbl_ohr_title = QLabel("ОХР и ОПР:"); self.lbl_ohr = QLabel("0.00 руб.")
        res_grid.addWidget(self.lbl_ohr_title, 2, 0); res_grid.addWidget(self.lbl_ohr, 2, 1)

        self.lbl_tax_title = QLabel("Налог на прибыль:"); self.lbl_tax = QLabel("0.00 руб.")
        res_grid.addWidget(self.lbl_tax_title, 3, 0); res_grid.addWidget(self.lbl_tax, 3, 1)

        res_grid.addWidget(QLabel("ПЛАНОВАЯ ПРИБЫЛЬ:"), 4, 0)
        self.lbl_profit = QLabel("0.00 руб.")
        self.lbl_profit.setStyleSheet("font-weight: bold; color: #16A34A; font-size: 14pt;")
        res_grid.addWidget(self.lbl_profit, 4, 1)

        layout.addLayout(res_grid)
        self.calculate()

    def open_settings(self):
        if ProfitSettingsDialog(self).exec():
            self.calculate()

    def calculate(self):
        s = self.spin_cost.value()
        zp = self.spin_zp.value()
        ohr_pct = self.spin_ohr.value()

        nds_pct = float(db.get_setting("calc_nds_pct", 20.0))
        tax_pct = float(db.get_setting("calc_tax_pct", 20.0))
        soc_pct = float(db.get_setting("calc_soc_pct", 34.6))

        self.lbl_nds_title.setText(f"НДС ({nds_pct}% в т.ч.):")
        self.lbl_soc_title.setText(f"СоцСтрах ({soc_pct}% от ЗП):")
        self.lbl_tax_title.setText(f"Налог на прибыль ({tax_pct}%):")

        # Расчет
        nds = s * nds_pct / (100 + nds_pct)
        s_net = s - nds
        soc = zp * (soc_pct / 100)
        ohr = zp * (ohr_pct / 100)

        expenses = zp + soc + ohr
        profit_before_tax = s_net - expenses

        tax = profit_before_tax * (tax_pct / 100) if profit_before_tax > 0 else 0.0
        net_profit = profit_before_tax - tax

        self.lbl_nds.setText(f"{nds:,.2f} руб.".replace(",", " "))
        self.lbl_soc.setText(f"{soc:,.2f} руб.".replace(",", " "))
        self.lbl_ohr.setText(f"{ohr:,.2f} руб.".replace(",", " "))
        self.lbl_tax.setText(f"{tax:,.2f} руб.".replace(",", " "))

        color = "#16A34A" if net_profit >= 0 else "#DC2626"
        self.lbl_profit.setStyleSheet(f"font-weight: bold; color: {color}; font-size: 14pt;")
        self.lbl_profit.setText(f"{net_profit:,.2f} руб.".replace(",", " "))


# --- ГЛАВНЫЙ ВИДЖЕТ ВКЛАДКИ КАЛЬКУЛЯТОРОВ ---

class CalculatorsView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        lbl = QLabel("Инженерные и финансовые калькуляторы")
        lbl.setStyleSheet("font-size: 16pt; font-weight: bold; color: #0F172A; margin-bottom: 20px;")
        layout.addWidget(lbl)

        grid = QGridLayout()

        btn_profit = QPushButton("💰 Калькулятор плановой прибыли")
        btn_profit.setMinimumHeight(60)
        btn_profit.setProperty("type", "primary")
        btn_profit.clicked.connect(lambda: ProfitCalcDialog(self).exec())
        grid.addWidget(btn_profit, 0, 0)

        btn_vat = QPushButton("🧾 Выделение НДС")
        btn_vat.setMinimumHeight(60)
        btn_vat.clicked.connect(lambda: VatCalcDialog(self).exec())
        grid.addWidget(btn_vat, 0, 1)

        btn_conv = QPushButton("⚖️ Конвертер величин")
        btn_conv.setMinimumHeight(60)
        btn_conv.clicked.connect(lambda: ConverterDialog(self).exec())
        grid.addWidget(btn_conv, 1, 0)

        btn_earth = QPushButton("🚜 Объем земляных работ")
        btn_earth.setMinimumHeight(60)
        btn_earth.clicked.connect(lambda: EarthworksCalcDialog(self).exec())
        grid.addWidget(btn_earth, 1, 1)

        layout.addLayout(grid)
        layout.addStretch()

    def load_data(self): pass
