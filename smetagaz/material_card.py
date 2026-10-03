"""
Карточка материала/работы справочника — просмотр и редактирование одной позиции.
"""
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
                              QMessageBox, QDialog, QLineEdit, QComboBox, QTextEdit,
                              QGroupBox, QDoubleSpinBox)

from .database import db
from .work_pricing import compute_work_price

class MaterialCardDialog(QDialog):
    def __init__(self, material_id, parent=None):
        super().__init__(parent)
        self.material_id = material_id
        self.setWindowTitle("Карточка позиции")
        self.resize(560, 720)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Тип позиции:"))
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Материал", "Работа"])
        layout.addWidget(self.combo_type)

        layout.addWidget(QLabel("Раздел справочника:"))
        self.combo_category = QComboBox()
        self.load_categories()
        layout.addWidget(self.combo_category)

        layout.addWidget(QLabel("Наименование:"))
        self.input_name = QLineEdit()
        layout.addWidget(self.input_name)

        h_opts = QHBoxLayout()
        v_unit = QVBoxLayout()
        v_unit.addWidget(QLabel("Ед. измерения:"))
        self.input_unit = QLineEdit()
        v_unit.addWidget(self.input_unit)

        v_price = QVBoxLayout()
        v_price.addWidget(QLabel("Цена продажи (руб):"))
        self.input_price = QLineEdit()
        v_price.addWidget(self.input_price)

        v_purch = QVBoxLayout()
        v_purch.addWidget(QLabel("Цена закупки (скрытая):"))
        self.input_purchase = QLineEdit()
        v_purch.addWidget(self.input_purchase)

        h_opts.addLayout(v_unit)
        h_opts.addLayout(v_purch)
        h_opts.addLayout(v_price)
        layout.addLayout(h_opts)

        self.grp_formula = QGroupBox("Расчёт стоимости работы за 1 единицу")
        f = QGridLayout(self.grp_formula)
        self.spin_labor_hours = QDoubleSpinBox(); self.spin_labor_hours.setRange(0, 10000); self.spin_labor_hours.setDecimals(3)
        self.spin_hourly_rate = QDoubleSpinBox(); self.spin_hourly_rate.setRange(0, 1000000); self.spin_hourly_rate.setDecimals(2)
        self.spin_overhead_pct = QDoubleSpinBox(); self.spin_overhead_pct.setRange(0, 1000); self.spin_overhead_pct.setDecimals(2); self.spin_overhead_pct.setSuffix(" %")
        self.spin_profit_pct = QDoubleSpinBox(); self.spin_profit_pct.setRange(0, 1000); self.spin_profit_pct.setDecimals(2); self.spin_profit_pct.setSuffix(" %")
        self.spin_other_costs = QDoubleSpinBox(); self.spin_other_costs.setRange(0, 1000000); self.spin_other_costs.setDecimals(2)
        f.addWidget(QLabel("Трудозатраты, чел-час:"), 0, 0); f.addWidget(self.spin_labor_hours, 0, 1)
        f.addWidget(QLabel("Часовая ставка, руб/час:"), 0, 2); f.addWidget(self.spin_hourly_rate, 0, 3)
        f.addWidget(QLabel("ОХР и ОПР:"), 1, 0); f.addWidget(self.spin_overhead_pct, 1, 1)
        f.addWidget(QLabel("Плановая прибыль:"), 1, 2); f.addWidget(self.spin_profit_pct, 1, 3)
        f.addWidget(QLabel("Другие затраты, руб:"), 2, 0); f.addWidget(self.spin_other_costs, 2, 1)
        self.lbl_preview = QLabel(); self.lbl_preview.setWordWrap(True)
        f.addWidget(self.lbl_preview, 3, 0, 1, 4)
        self.btn_apply_formula = QPushButton("Подставить расчёт в цену продажи")
        self.btn_apply_formula.clicked.connect(self.apply_formula_to_price)
        f.addWidget(self.btn_apply_formula, 4, 0, 1, 4)
        layout.addWidget(self.grp_formula)
        for w in (self.spin_labor_hours, self.spin_hourly_rate, self.spin_overhead_pct, self.spin_profit_pct, self.spin_other_costs):
            w.valueChanged.connect(self.update_formula_preview)
        self.combo_type.currentTextChanged.connect(self.refresh_formula_visibility)

        layout.addWidget(QLabel("Ссылка поставщика для мониторинга (опционально):"))
        self.input_url = QLineEdit()
        layout.addWidget(self.input_url)

        layout.addWidget(QLabel("Примечание (ГОСТ, ТУ, марка):"))
        self.input_note = QTextEdit()
        self.input_note.setFixedHeight(80)
        layout.addWidget(self.input_note)

        self.certificate_id=None;self.cert_label=QLabel();layout.addWidget(self.cert_label)
        cert_button=QPushButton('Сертификат материала…');cert_button.clicked.connect(self.pick_certificate);layout.addWidget(cert_button)
        clear=QPushButton('Убрать связь с сертификатом');clear.clicked.connect(self.clear_certificate);layout.addWidget(clear)
        btn_bar = QHBoxLayout()
        btn_save = QPushButton("Сохранить изменения")
        btn_save.setProperty("type", "primary")
        btn_cancel = QPushButton("Отмена")
        btn_save.clicked.connect(self.save_data)
        btn_cancel.clicked.connect(self.reject)

        btn_bar.addStretch()
        btn_bar.addWidget(btn_cancel)
        btn_bar.addWidget(btn_save)
        layout.addLayout(btn_bar)

        self.load_material_data()

    def refresh_certificate(self):
        row=db.fetchone('SELECT name,cert_number FROM certificates WHERE id=?',(self.certificate_id,))
        self.cert_label.setText('Сертификат: '+(' · '.join(str(v or '') for v in row) if row else 'не выбран'))
    def pick_certificate(self):
        from .gsv_catalog import CertificatePicker
        d=CertificatePicker(self)
        if d.exec():self.certificate_id=d.cert_id;self.refresh_certificate()
    def clear_certificate(self):self.certificate_id=None;self.refresh_certificate()

    def load_categories(self):
        self.combo_category.clear()
        self.combo_category.addItem(" Без раздела", None)
        roots = db.fetchall("SELECT id, name FROM categories WHERE parent_id IS NULL ORDER BY name")
        for r_id, r_name in roots:
            self.combo_category.addItem(f"📁 {r_name}", r_id)
            subs = db.fetchall("SELECT id, name FROM categories WHERE parent_id=? ORDER BY name", (r_id,))
            for s_id, s_name in subs:
                self.combo_category.addItem(f"   📂 {s_name}", s_id)

    def load_material_data(self):
        cert=db.fetchone("SELECT certificate_id FROM materials WHERE id=?",(self.material_id,));self.certificate_id=cert[0] if cert else None;self.refresh_certificate()
        row = db.fetchone("""SELECT category_id, name, unit, price, url, note, item_type, purchase_price,
                              labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs
                              FROM materials WHERE id=?""", (self.material_id,))
        if row:
            cat_id, name, unit, price, url, note, item_type, purch, labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs = row
            if cat_id is not None:
                idx = self.combo_category.findData(cat_id)
                if idx >= 0: self.combo_category.setCurrentIndex(idx)

            self.combo_type.setCurrentText(item_type if item_type else "Материал")
            self.input_name.setText(name or "")
            self.input_unit.setText(unit or "шт")
            try:
                self.input_price.setText(f"{float(price or 0.0):.2f}")
                self.input_purchase.setText(f"{float(purch or 0.0):.2f}")
            except (ValueError, TypeError):
                self.input_price.setText("0.00")
                self.input_purchase.setText("0.00")
            self.input_url.setText(url or "")
            self.input_note.setPlainText(note or "")
            self.spin_labor_hours.setValue(float(labor_hours or 0.0))
            self.spin_hourly_rate.setValue(float(hourly_rate or 0.0))
            self.spin_overhead_pct.setValue(float(overhead_pct or 0.0))
            self.spin_profit_pct.setValue(float(profit_pct or 0.0))
            self.spin_other_costs.setValue(float(other_costs or 0.0))
        self.refresh_formula_visibility()
        self.update_formula_preview()

    def refresh_formula_visibility(self):
        self.grp_formula.setVisible(self.combo_type.currentText() == "Работа")

    def current_breakdown(self):
        return compute_work_price(self.spin_labor_hours.value(), self.spin_hourly_rate.value(),
                                   self.spin_overhead_pct.value(), self.spin_profit_pct.value(), self.spin_other_costs.value())

    def update_formula_preview(self):
        b = self.current_breakdown()
        self.lbl_preview.setText(
            f"ЗП: {b['wage']:.2f} · ОХР/ОПР: {b['overhead']:.2f} · Прибыль: {b['profit']:.2f} · "
            f"СоцСтрах (34,6%): {b['social']:.2f} · Другие: {b['other']:.2f} · "
            f"Налог на прибыль (20%): {b['tax']:.2f} · Итого за единицу: {b['total']:.2f} руб."
        )

    def apply_formula_to_price(self):
        self.input_price.setText(f"{self.current_breakdown()['total']:.2f}")

    def save_data(self):
        name = self.input_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Ошибка", "Наименование не может быть пустым.")
            return

        try:
            p_str = self.input_price.text().replace(' ', '').replace(',', '.').strip()
            price = float(p_str) if p_str else 0.0

            pu_str = self.input_purchase.text().replace(' ', '').replace(',', '.').strip()
            purch = float(pu_str) if pu_str else 0.0
            import math
            if not math.isfinite(price) or not math.isfinite(purch) or price<0 or purch<0:raise ValueError()
        except ValueError:
            QMessageBox.warning(self,"Цена","Введите неотрицательную числовую цену.")
            return

        cat_id = self.combo_category.currentData()
        unit = self.input_unit.text().strip() or "шт"
        url = self.input_url.text().strip()
        note = self.input_note.toPlainText().strip()
        item_type = self.combo_type.currentText()

        db.execute("""UPDATE materials
                      SET category_id=?, name=?, unit=?, price=?, url=?, note=?, item_type=?, purchase_price=?, certificate_id=?,
                          labor_hours=?, hourly_rate=?, overhead_pct=?, profit_pct=?, other_costs=?
                      WHERE id=?""", (cat_id, name, unit, price, url, note, item_type, purch, self.certificate_id,
                                       self.spin_labor_hours.value(), self.spin_hourly_rate.value(),
                                       self.spin_overhead_pct.value(), self.spin_profit_pct.value(), self.spin_other_costs.value(),
                                       self.material_id))
        self.accept()
