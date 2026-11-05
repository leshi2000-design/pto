"""
Карточка материала/работы справочника — просмотр и редактирование одной позиции.
"""
from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
                              QMessageBox, QDialog, QLineEdit, QComboBox, QTextEdit,
                              QGroupBox, QDoubleSpinBox, QApplication, QCheckBox)

from .database import db
from .work_pricing import compute_work_price
from . import material_pricing as mp
from .edit_lock_ui import guarded

@guarded('material', lambda d: d.material_id, 'Карточка позиции')
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

        # цена материала: закупка + НДС + надбавка = продажа
        self.grp_price = QGroupBox("Цена материала: закупка + НДС + надбавка = продажа")
        pg = QGridLayout(self.grp_price)
        self.chk_vat = QCheckBox("Начислять НДС на закупку")
        self.spin_vat = QDoubleSpinBox(); self.spin_vat.setRange(0, 100); self.spin_vat.setDecimals(2); self.spin_vat.setValue(20.0); self.spin_vat.setSuffix(" %")
        self.lbl_vat = QLabel("НДС: 0.00")
        self.combo_markup = QComboBox()
        for key, label in mp.MODES.items():
            self.combo_markup.addItem(label, key)
        self.input_markup = QLineEdit(); self.input_markup.setPlaceholderText("надбавка, руб")
        self.input_markup_pct = QLineEdit(); self.input_markup_pct.setPlaceholderText("надбавка, %")
        self.lbl_formula = QLabel(); self.lbl_formula.setWordWrap(True)
        pg.addWidget(self.chk_vat, 0, 0); pg.addWidget(self.spin_vat, 0, 1); pg.addWidget(self.lbl_vat, 0, 2, 1, 2)
        pg.addWidget(self.combo_markup, 1, 0, 1, 4)
        pg.addWidget(QLabel("Надбавка, руб:"), 2, 0); pg.addWidget(self.input_markup, 2, 1)
        pg.addWidget(QLabel("Надбавка, % от закупки:"), 2, 2); pg.addWidget(self.input_markup_pct, 2, 3)
        pg.addWidget(self.lbl_formula, 3, 0, 1, 4)
        layout.addWidget(self.grp_price)
        self._pricing = False
        self.chk_vat.toggled.connect(lambda *_: self.recalc_price("vat"))
        self.spin_vat.valueChanged.connect(lambda *_: self.recalc_price("vat"))
        self.combo_markup.currentIndexChanged.connect(lambda *_: self.recalc_price("mode"))
        self.input_purchase.textEdited.connect(lambda *_: self.recalc_price("purchase"))
        self.input_price.textEdited.connect(lambda *_: self.recalc_price("price"))
        self.input_markup.textEdited.connect(lambda *_: self.recalc_price("markup"))
        self.input_markup_pct.textEdited.connect(lambda *_: self.recalc_price("markup_pct"))
        self.combo_type.currentTextChanged.connect(lambda *_: self.refresh_price_group())

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

        layout.addWidget(QLabel("Ссылка на позицию на сайте поставщика (цена будет обновляться по кнопке «Обновить цены по ссылкам»):"))
        self.input_url = QLineEdit()
        layout.addWidget(self.input_url)
        layout.addWidget(QLabel("Селектор цены на странице (необязательно: если пусто, цена ищется в стандартной разметке сайта):"))
        self.input_price_selector = QLineEdit()
        self.input_price_selector.setPlaceholderText("например: .product-price, span[itemprop='price']")
        layout.addWidget(self.input_price_selector)
        price_bar = QHBoxLayout()
        self.btn_check_price = QPushButton("Проверить цену по ссылке")
        self.btn_check_price.clicked.connect(self.check_price_now)
        self.btn_price_history = QPushButton("История цен")
        self.btn_price_history.clicked.connect(self.show_price_history)
        self.lbl_price_state = QLabel("")
        self.lbl_price_state.setWordWrap(True)
        price_bar.addWidget(self.btn_check_price)
        price_bar.addWidget(self.btn_price_history)
        price_bar.addWidget(self.lbl_price_state, 1)
        layout.addLayout(price_bar)

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

    def check_price_now(self):
        """Читает цену по ссылке и предлагает подставить её в цену продажи (в базу ничего не пишется, пока не нажато «Сохранить»)."""
        from . import price_sync
        url = self.input_url.text().strip()
        if not url:
            QMessageBox.information(self, "Цена", "Сначала укажите ссылку на позицию.")
            return
        self.btn_check_price.setEnabled(False)
        self.lbl_price_state.setText("Проверяю…")
        QApplication.processEvents()
        try:
            price, how = price_sync.extract_price(price_sync.fetch(url), self.input_price_selector.text())
        except Exception as e:
            price, how = None, str(e)
        self.btn_check_price.setEnabled(True)
        if price is None:
            self.lbl_price_state.setText("Не удалось получить цену: " + str(how))
            return
        self.lbl_price_state.setText(f"На сайте: {price:.2f} ({how}). Текущая цена в справочнике: {self.input_price.text() or '0'}.")
        if QMessageBox.question(self, "Цена по ссылке", f"На сайте найдена цена {price:.2f}. Подставить её в цену продажи?") == QMessageBox.StandardButton.Yes:
            self.input_price.setText(f"{price:.2f}")
            if self.combo_markup.currentData() == "manual":          # цена с сайта вводится как продажа — надбавка снова вычисляется по ней
                self.combo_markup.setCurrentIndex(self.combo_markup.findData("auto"))
            self.recalc_price("price")

    def show_price_history(self):
        from .price_sync_view import PriceHistoryDialog
        PriceHistoryDialog(self.material_id, self).exec()

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
        pricing = db.fetchone("SELECT coalesce(vat_on,0), coalesce(vat_pct,20), coalesce(markup_mode,'auto'), coalesce(markup,0) FROM materials WHERE id=?", (self.material_id,)) or (0, 20, 'auto', 0)
        row = db.fetchone("""SELECT category_id, name, unit, price, url, note, item_type, purchase_price,
                              labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs, coalesce(price_selector,''), coalesce(price_status,'')
                              FROM materials WHERE id=?""", (self.material_id,))
        if row:
            cat_id, name, unit, price, url, note, item_type, purch, labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs, price_selector, price_status = row
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
            self.input_price_selector.setText(price_selector)
            if price_status:
                self.lbl_price_state.setText("Последняя проверка: " + price_status)
            self.input_note.setPlainText(note or "")
            self.spin_labor_hours.setValue(float(labor_hours or 0.0))
            self.spin_hourly_rate.setValue(float(hourly_rate or 0.0))
            self.spin_overhead_pct.setValue(float(overhead_pct or 0.0))
            self.spin_profit_pct.setValue(float(profit_pct or 0.0))
            self.spin_other_costs.setValue(float(other_costs or 0.0))
        self._pricing = True
        self.chk_vat.setChecked(bool(pricing[0]))
        self.spin_vat.setValue(float(pricing[1]))
        mode = pricing[2] if pricing[2] in mp.MODES else 'auto'
        if mode == 'manual':                                   # цену продажи могли изменить в обход карточки (обновление с сайта) — тогда надбавку снова вычисляем по ней
            expected = mp.calc(float(row[7] or 0) if row else 0, bool(pricing[0]), pricing[1], 'manual', None, pricing[3])['price']
            if row and abs(float(row[3] or 0) - float(expected)) > 0.005:
                mode = 'auto'
        self.combo_markup.setCurrentIndex(max(0, self.combo_markup.findData(mode)))
        if mode == 'manual':
            self.input_markup.setText(f"{float(pricing[3]):.2f}")
        self._pricing = False
        self.refresh_formula_visibility()
        self.update_formula_preview()
        self.refresh_price_group()

    def refresh_formula_visibility(self):
        self.grp_formula.setVisible(self.combo_type.currentText() == "Работа")

    # --- цена материала: закупка + НДС + надбавка = продажа
    @staticmethod
    def _num(line):
        text = line.text().replace(' ', '').replace(',', '.').strip()
        try:
            return float(text) if text else 0.0
        except ValueError:
            return None

    def refresh_price_group(self):
        is_material = self.combo_type.currentText() == "Материал"
        self.grp_price.setVisible(is_material)
        if is_material:
            self.recalc_price("mode")

    def recalc_price(self, source):
        """Пересчёт полей цены. В режиме «авто» вводят закупку и продажу — надбавка считается; в режиме «вручную» вводят закупку и надбавку (руб или %) — продажа считается."""
        if self._pricing:
            return
        self._pricing = True
        try:
            mode = self.combo_markup.currentData()
            manual = mode == "manual"
            self.input_price.setReadOnly(manual)
            self.input_markup.setReadOnly(not manual)
            self.input_markup_pct.setReadOnly(not manual)
            self.spin_vat.setEnabled(self.chk_vat.isChecked())
            purchase = self._num(self.input_purchase)
            if purchase is None:
                self.lbl_formula.setText("Введите цену закупки числом.")
                return
            if manual and source == "markup_pct":
                pct = self._num(self.input_markup_pct)
                if pct is None:
                    return
                self.input_markup.setText(f"{mp.markup_from_percent(purchase, pct):.2f}")
            markup = self._num(self.input_markup) if manual else None
            price = self._num(self.input_price) if not manual else None
            if (manual and markup is None) or (not manual and price is None):
                self.lbl_formula.setText("Введите число.")
                return
            r = mp.calc(purchase, self.chk_vat.isChecked(), self.spin_vat.value(), mode, price, markup)
            if manual:
                self.input_price.setText(f"{r['price']:.2f}")
                if source != "markup_pct":
                    self.input_markup_pct.setText(f"{r['markup_pct']:.2f}")
            else:
                self.input_markup.setText(f"{r['markup']:.2f}")
                self.input_markup_pct.setText(f"{r['markup_pct']:.2f}")
            self.lbl_vat.setText(f"НДС: {r['vat']:.2f} руб.")
            warn = " — ниже закупки с НДС (убыток)" if r['markup'] < 0 else ""
            self.lbl_formula.setText(f"Закупка {float(purchase):.2f} + НДС {r['vat']:.2f} + надбавка {r['markup']:.2f} = продажа {r['price']:.2f} руб.{warn}")
            self.lbl_formula.setStyleSheet("color: #A4262C;" if r['markup'] < 0 else "")
        finally:
            self._pricing = False

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
        self.recalc_price("price")

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

        item_type = self.combo_type.currentText()
        mode = self.combo_markup.currentData()
        markup_value = 0.0
        if item_type == "Материал":
            if mode == "manual":                            # продажа = закупка + НДС + надбавка (рассчитывается, как на экране)
                markup_value = self._num(self.input_markup)
                if markup_value is None:
                    QMessageBox.warning(self, "Надбавка", "Введите надбавку числом.")
                    return
                price = float(mp.calc(purch, self.chk_vat.isChecked(), self.spin_vat.value(), "manual", None, markup_value)['price'])
            try:
                mp.validate(item_type, purch, price)
            except ValueError as e:
                QMessageBox.warning(self, "Цена материала", str(e))
                return
            r = mp.calc(purch, self.chk_vat.isChecked(), self.spin_vat.value(), mode, price, markup_value)
            markup_value = float(r['markup'])
            if markup_value < 0 and QMessageBox.question(self, "Цена ниже закупки", f"Цена продажи {price:.2f} меньше закупки с НДС ({purch:.2f} + {float(r['vat']):.2f}). Сохранить с убытком?") != QMessageBox.StandardButton.Yes:
                return

        cat_id = self.combo_category.currentData()
        unit = self.input_unit.text().strip() or "шт"
        url = self.input_url.text().strip()
        note = self.input_note.toPlainText().strip()

        db.execute("""UPDATE materials
                      SET category_id=?, name=?, unit=?, price=?, url=?, note=?, item_type=?, purchase_price=?, certificate_id=?,
                          labor_hours=?, hourly_rate=?, overhead_pct=?, profit_pct=?, other_costs=?,
                          vat_on=?, vat_pct=?, markup_mode=?, markup=?
                      WHERE id=?""", (cat_id, name, unit, price, url, note, item_type, purch, self.certificate_id,
                                       self.spin_labor_hours.value(), self.spin_hourly_rate.value(),
                                       self.spin_overhead_pct.value(), self.spin_profit_pct.value(), self.spin_other_costs.value(),
                                       int(self.chk_vat.isChecked()) if item_type == "Материал" else 0, self.spin_vat.value(), mode if item_type == "Материал" else 'auto', markup_value,
                                       self.material_id))
        from . import price_sync
        price_sync.remember_selector(db, self.material_id, url, self.input_price_selector.text()) if self.input_price_selector.text().strip() else db.execute("UPDATE materials SET price_selector='' WHERE id=?", (self.material_id,))
        self.accept()
