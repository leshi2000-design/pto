"""
Парсинг цены и наименования товара со страницы поставщика по CSS-селекторам:
- ScraperWorker: фоновый QThread, выполняющий HTTP-запрос и разбор HTML.
- WebScraperDialog: диалог настройки URL/селекторов и предпросмотра результата.
"""
import re

import requests
from bs4 import BeautifulSoup

from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QFrame, QMessageBox, QDialog, QLineEdit)
from PyQt6.QtCore import QThread, pyqtSignal

from .database import db


class ScraperWorker(QThread):
    finished_data = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, url, name_sel, price_sel, unit, note, cat_id):
        super().__init__()
        self.url = url
        self.name_sel = name_sel
        self.price_sel = price_sel
        self.unit = unit
        self.note = note
        self.cat_id = cat_id

    def run(self):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            res = requests.get(self.url, headers=headers, timeout=6)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')
            name_elem = soup.select_one(self.name_sel)
            parsed_name = name_elem.get_text(strip=True) if name_elem else ""
            parsed_price = 0.0
            price_elem = soup.select_one(self.price_sel)
            if price_elem:
                raw_text = price_elem.get_text(strip=True).replace(',', '.').replace('\xa0', '').replace(' ', '')
                match = re.search(r'\d+(?:\.\d+)?', raw_text)
                if match: parsed_price = float(match.group(0))

            if parsed_name and parsed_price > 0:
                self.finished_data.emit({"category_id": self.cat_id, "name": parsed_name, "unit": self.unit or "шт", "price": parsed_price, "url": self.url, "note": self.note})
            else:
                self.error_occurred.emit("Не удалось извлечь название или цену по селекторам.")
        except Exception as e:
            self.error_occurred.emit(str(e))

class WebScraperDialog(QDialog):
    def __init__(self, current_cat_id=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Парсинг материала из интернета")
        self.resize(620, 480)
        self.parsed_data = None
        self.current_cat_id = current_cat_id

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("URL страницы товара поставщика:"))
        self.input_url = QLineEdit()
        layout.addWidget(self.input_url)

        layout.addWidget(QLabel("CSS-селектор наименования (h1 или класс):"))
        self.input_name_sel = QLineEdit(db.get_setting("last_name_selector", "h1"))
        layout.addWidget(self.input_name_sel)

        layout.addWidget(QLabel("CSS-селектор цены:"))
        self.input_price_sel = QLineEdit(db.get_setting("last_price_selector", ".price, [itemprop='price']"))
        layout.addWidget(self.input_price_sel)

        h_opts = QHBoxLayout()
        v_unit = QVBoxLayout()
        v_unit.addWidget(QLabel("Ед. изм.:"))
        self.input_unit = QLineEdit("шт")
        v_unit.addWidget(self.input_unit)

        v_note = QVBoxLayout()
        v_note.addWidget(QLabel("Примечание:"))
        self.input_note = QLineEdit("Спарсено с сайта")
        v_note.addWidget(self.input_note)
        h_opts.addLayout(v_unit)
        h_opts.addLayout(v_note)
        layout.addLayout(h_opts)

        self.btn_test = QPushButton("Проверить и спарсить данные")
        self.btn_test.clicked.connect(self.start_scraping)
        layout.addWidget(self.btn_test)

        preview_box = QFrame()
        p_layout = QVBoxLayout(preview_box)
        self.lbl_res_name = QLabel("Наименование: —")
        self.lbl_res_price = QLabel("Цена: — бел. руб")
        p_layout.addWidget(self.lbl_res_name)
        p_layout.addWidget(self.lbl_res_price)
        layout.addWidget(preview_box)

        btn_bar = QHBoxLayout()
        self.btn_save = QPushButton("Добавить в справочник")
        self.btn_save.setProperty("type", "primary")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)

        btn_bar.addStretch()
        btn_bar.addWidget(btn_cancel)
        btn_bar.addWidget(self.btn_save)
        layout.addLayout(btn_bar)

    def start_scraping(self):
        url = self.input_url.text().strip()
        name_sel = self.input_name_sel.text().strip()
        price_sel = self.input_price_sel.text().strip()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите URL адрес страницы.")
            return

        self.btn_test.setEnabled(False)
        self.btn_test.setText("Загрузка данных...")
        self.worker = ScraperWorker(url, name_sel, price_sel, self.input_unit.text(), self.input_note.text(), self.current_cat_id)
        self.worker.finished_data.connect(self.on_scraped)
        self.worker.error_occurred.connect(self.on_scrape_error)
        self.worker.start()

    def on_scraped(self, data):
        self.parsed_data = data
        self.lbl_res_name.setText(f"Наименование: {data['name']}")
        self.lbl_res_price.setText(f"Цена: {data['price']:.2f} бел. руб")
        self.btn_save.setEnabled(True)
        self.btn_test.setEnabled(True)
        self.btn_test.setText("Проверить и спарсить данные")
        db.set_setting("last_name_selector", self.input_name_sel.text().strip())
        db.set_setting("last_price_selector", self.input_price_sel.text().strip())

    def on_scrape_error(self, err_msg):
        self.btn_test.setEnabled(True)
        self.btn_test.setText("Проверить и спарсить данные")
        QMessageBox.warning(self, "Ошибка парсинга", f"Не удалось извлечь данные:\n{err_msg}")


    def reject(self):
        if hasattr(self,'worker') and self.worker.isRunning():
            QMessageBox.information(self,'Загрузка','Дождитесь завершения запроса (таймаут ограничен).')
            return
        super().reject()
