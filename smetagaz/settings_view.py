"""
Вкладка "Настройки": цвет интерфейса, вкладки, название приложения, надбавки по умолчанию.
"""
import os
import json
import logging
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                              QFrame, QMessageBox, QFileDialog, QColorDialog, QLineEdit,
                              QDoubleSpinBox, QGridLayout, QGroupBox, QFontComboBox, QSpinBox,
                              QScrollArea, QTableWidgetItem, QCheckBox, QHeaderView)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt

from .backup import create_backup, restore_backup
from .contracts_excel_export import export_registries, EXPORT_FILENAME
from .security import password_hash, verify, encrypt_backup, decrypt_backup
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from PyQt6.QtWidgets import QInputDialog
from PyQt6.QtCore import QTimer
from .database import db
from .widgets import ReorderTableWidget


class SettingsView(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

        main_layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(15)
        self.backup_status=QLabel(db.get_setting('backup_status','Резервных копий пока нет'))
        self.backup_status.setWordWrap(True);layout.addWidget(self.backup_status)
        btn_password=QPushButton('Установить / изменить пароль входа')
        btn_password.clicked.connect(self.change_password);layout.addWidget(btn_password)
        self.pool=ThreadPoolExecutor(max_workers=1);self.job=None;self.job_callback=None
        self.job_timer=QTimer(self);self.job_timer.timeout.connect(self.poll_job)
        layout.addWidget(QLabel('Пароль входа защищает интерфейс. Базы на диске не зашифрованы.\nДля защиты диска используйте шифрование средствами ОС.'))

        # 1. Интерфейс: Название и вкладки
        box_app = QGroupBox("Внешний вид: Название программы и Вкладки (Требуется перезапуск)")
        l_app = QGridLayout(box_app)
        l_app.addWidget(QLabel("Название программы:"), 0, 0)
        self.inp_app_name = QLineEdit(db.get_setting("app_name", "СМЕТА-ГАЗ 1.0"))
        l_app.addWidget(self.inp_app_name, 0, 1, 1, 2)

        self.btn_color = QPushButton("Выбрать акцентный цвет интерфейса")
        self.btn_color.clicked.connect(self.choose_accent)
        l_app.addWidget(self.btn_color, 1, 0, 1, 3)

        l_app.addWidget(QLabel("Порядок и названия вкладок (перетаскивайте строки мышкой):"), 2, 0, 1, 3)

        self.table_tabs = ReorderTableWidget()
        self.table_tabs.setColumnCount(3)
        self.table_tabs.setHorizontalHeaderLabels(["ID", "Вкл", "Название вкладки"])
        self.table_tabs.setColumnHidden(0, True)
        self.table_tabs.setMinimumHeight(200)
        self.load_tabs_config()
        l_app.addWidget(self.table_tabs, 3, 0, 1, 3)

        btn_app_save = QPushButton("Сохранить настройки интерфейса")
        btn_app_save.setProperty("type", "primary")
        btn_app_save.clicked.connect(self.save_app_settings)
        l_app.addWidget(btn_app_save, 4, 0, 1, 3)

        layout.addWidget(box_app)

        # 2. Надбавки
        box_sur = QGroupBox("Настройки надбавок по умолчанию (%)")
        sur_layout = QGridLayout(box_sur)
        sur_layout.addWidget(QLabel("ОХР и ОПР:"), 0, 0)
        self.inp_ov = QDoubleSpinBox()
        self.inp_ov.setRange(0, 100)
        self.inp_ov.setValue(float(db.get_setting('def_overhead_pct', '15.0')))
        sur_layout.addWidget(self.inp_ov, 0, 1)

        sur_layout.addWidget(QLabel("Пл. Прибыль:"), 1, 0)
        self.inp_pr = QDoubleSpinBox()
        self.inp_pr.setRange(0, 100)
        self.inp_pr.setValue(float(db.get_setting('def_profit_pct', '10.0')))
        sur_layout.addWidget(self.inp_pr, 1, 1)

        sur_layout.addWidget(QLabel("НДС:"), 0, 2)
        self.inp_vat = QDoubleSpinBox()
        self.inp_vat.setRange(0, 100)
        self.inp_vat.setValue(float(db.get_setting('def_vat_pct', '20.0')))
        sur_layout.addWidget(self.inp_vat, 0, 3)

        sur_layout.addWidget(QLabel("СоцСтрах:"), 1, 2)
        self.inp_soc = QDoubleSpinBox()
        self.inp_soc.setRange(0, 100)
        self.inp_soc.setValue(float(db.get_setting('def_social_pct', '34.6')))
        sur_layout.addWidget(self.inp_soc, 1, 3)

        btn_sur_save = QPushButton("Сохранить надбавки")
        btn_sur_save.clicked.connect(self.save_surcharges)
        sur_layout.addWidget(btn_sur_save, 2, 0, 1, 4)
        layout.addWidget(box_sur)

        # 3. Настройки экспорта
        box_export = QGroupBox("Настройки экспорта документов (PDF, Excel, Word)")
        exp_layout = QGridLayout(box_export)
        exp_layout.addWidget(QLabel("Организация:"), 0, 0)
        self.inp_company = QLineEdit(db.get_setting("export_company_name", 'ООО "ГазМонтаж"'))
        exp_layout.addWidget(self.inp_company, 0, 1, 1, 2)

        exp_layout.addWidget(QLabel("Шрифт PDF:"), 1, 0)
        self.font_combo = QFontComboBox()
        self.font_combo.setCurrentFont(QFont(db.get_setting("export_font", "Segoe UI")))
        exp_layout.addWidget(self.font_combo, 1, 1)

        exp_layout.addWidget(QLabel("Размер шрифта PDF:"), 1, 2)
        self.font_size = QSpinBox()
        self.font_size.setRange(8, 24)
        self.font_size.setValue(int(db.get_setting("export_font_size", "13")))
        exp_layout.addWidget(self.font_size, 1, 3)

        self.inp_prepared_by=QLineEdit(db.get_setting('estimate_prepared_by',''));exp_layout.addWidget(QLabel('Смету составил (по умолчанию):'),3,0);exp_layout.addWidget(self.inp_prepared_by,3,1,1,3)
        btn_exp_save = QPushButton("Сохранить настройки экспорта")
        btn_exp_save.clicked.connect(self.save_export_settings)
        exp_layout.addWidget(btn_exp_save, 4, 0, 1, 4)
        layout.addWidget(box_export)

        # 4. БД
        box_db = QFrame()
        box_db_layout = QVBoxLayout(box_db)
        box_db_layout.addWidget(QLabel("Управление базой данных:"))
        btn_backup = QPushButton("Создать резервную копию БД вручную")
        btn_restore = QPushButton("Восстановить из копии")
        btn_restore.setProperty("type", "danger")
        btn_backup.clicked.connect(self.do_backup)
        btn_restore.clicked.connect(self.do_restore)
        box_db_layout.addWidget(btn_backup)
        box_db_layout.addWidget(btn_restore)
        layout.addWidget(box_db)

        # 5. Excel-снимок реестров договоров, отдельно от обычных бэкапов.
        box_excel = QFrame()
        box_excel_layout = QVBoxLayout(box_excel)
        box_excel_layout.addWidget(QLabel("Реестры договоров (ГСВ и ГСН) в Excel — обновляется автоматически каждый час, файл перезаписывается:"))
        self.contracts_excel_status = QLabel(db.get_setting('contracts_excel_status', 'Ещё не обновлялся'))
        self.contracts_excel_status.setWordWrap(True)
        box_excel_layout.addWidget(self.contracts_excel_status)
        box_excel_layout.addWidget(QLabel("Карточки договоров «Проекты ГСВ» (все поля, статусы, оплаты) — тоже каждый час, файл перезаписывается."))
        self.projects_excel_status = QLabel(db.get_setting('projects_excel_status', 'Ещё не обновлялся'))
        self.projects_excel_status.setWordWrap(True)
        box_excel_layout.addWidget(self.projects_excel_status)
        excel_bar = QHBoxLayout()
        btn_excel_now = QPushButton("Обновить сейчас")
        btn_excel_now.clicked.connect(self.export_contracts_excel_now)
        excel_bar.addWidget(btn_excel_now)
        btn_excel_folder = QPushButton("Открыть папку")
        btn_excel_folder.clicked.connect(self.open_contracts_excel_folder)
        excel_bar.addWidget(btn_excel_folder)
        excel_bar.addStretch()
        box_excel_layout.addLayout(excel_bar)
        layout.addWidget(box_excel)

        layout.addStretch()
        scroll.setWidget(container)
        main_layout.addWidget(scroll)

    def load_tabs_config(self):
        tabs_json = db.get_setting("tabs_config", "[]")
        try:
            tabs_data = json.loads(tabs_json)
        except (ValueError, TypeError) as e:
            logging.warning(f"Некорректный tabs_config, сброшен: {e}")
            tabs_data = []

        self.table_tabs.setRowCount(len(tabs_data))
        for r, tab in enumerate(tabs_data):
            self.table_tabs.setItem(r, 0, QTableWidgetItem(tab["id"]))

            chk = QCheckBox()
            chk.setChecked(bool(tab.get("visible", 1)))
            w = QWidget()
            l = QHBoxLayout(w)
            l.addWidget(chk)
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setContentsMargins(0,0,0,0)
            self.table_tabs.setCellWidget(r, 1, w)

            self.table_tabs.setItem(r, 2, QTableWidgetItem(tab["name"]))

        self.table_tabs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_tabs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    def save_app_settings(self):
        db.set_setting("app_name", self.inp_app_name.text().strip())

        tabs_data = []
        for r in range(self.table_tabs.rowCount()):
            t_id = self.table_tabs.item(r, 0).text()
            w = self.table_tabs.cellWidget(r, 1)
            chk = w.findChild(QCheckBox) if w else None
            visible = 1 if (chk and chk.isChecked()) else 0
            t_name = self.table_tabs.item(r, 2).text().strip()

            tabs_data.append({
                "id": t_id,
                "name": t_name,
                "visible": visible
            })

        db.set_setting("tabs_config", json.dumps(tabs_data))
        QMessageBox.information(self, "Успех", "Настройки сохранены. Пожалуйста, закройте и запустите программу заново, чтобы изменения вступили в силу.")

    def save_surcharges(self):
        db.set_setting('def_overhead_pct', self.inp_ov.value())
        db.set_setting('def_profit_pct', self.inp_pr.value())
        db.set_setting('def_vat_pct', self.inp_vat.value())
        db.set_setting('def_social_pct', self.inp_soc.value())
        QMessageBox.information(self, "Успех", "Значения надбавок сохранены.")

    def save_export_settings(self):
        db.set_setting('estimate_prepared_by',self.inp_prepared_by.text().strip())
        db.set_setting('export_company_name', self.inp_company.text())
        db.set_setting('export_font', self.font_combo.currentFont().family())
        db.set_setting('export_font_size', self.font_size.value())
        QMessageBox.information(self, "Успех", "Настройки экспорта сохранены.")

    def choose_accent(self):
        color = QColorDialog.getColor(QColor(db.get_setting("accent_color", "#0284C7")), self)
        if color.isValid():
            db.set_setting("accent_color", color.name())
            self.main_window.refresh_ui()

    def change_password(self):
        current=db.get_setting('password_hash','')
        if current:
            old,ok=QInputDialog.getText(self,'Пароль','Текущий пароль:',QLineEdit.EchoMode.Password)
            if not ok or not verify(old,current):return
        new,ok=QInputDialog.getText(self,'Пароль','Новый пароль (минимум 10 символов):',QLineEdit.EchoMode.Password)
        if not ok:return
        repeat,ok=QInputDialog.getText(self,'Пароль','Повторите пароль:',QLineEdit.EchoMode.Password)
        if not ok or repeat!=new:QMessageBox.warning(self,'Пароль','Пароли не совпали');return
        try:db.set_setting('password_hash',password_hash(new));QMessageBox.information(self,'Пароль','Пароль установлен')
        except ValueError as e:QMessageBox.warning(self,'Пароль',str(e))

    def start_job(self,fn,callback):
        if self.job and not self.job.done():
            QMessageBox.information(self,'Операция','Дождитесь завершения текущей операции');return
        self.job_callback=callback;self.job=self.pool.submit(fn);self.job_timer.start(100)
        self.backup_status.setText('Выполняется операция с копией…')

    def poll_job(self):
        if not self.job or not self.job.done():return
        self.job_timer.stop()
        try:self.job_callback(self.job.result())
        except Exception as e:QMessageBox.critical(self,'Копия',str(e));self.backup_status.setText('Ошибка: '+str(e))

    def do_backup(self):
        path,chosen=QFileDialog.getSaveFileName(self,'Полная резервная копия','smetagaz_backup.sgb','Зашифрованная копия (*.sgb);;Обычная копия (*.zip)')
        if not path:return
        encrypted='sgb' in chosen
        if not path.lower().endswith('.sgb' if encrypted else '.zip'):path+='.sgb' if encrypted else '.zip'
        password=''
        if encrypted:
            password,ok=QInputDialog.getText(self,'Копия','Пароль копии (минимум 10 символов):',QLineEdit.EchoMode.Password)
            if not ok:return
            if len(password)<10:QMessageBox.warning(self,'Пароль','Минимум 10 символов');return
            repeat,ok=QInputDialog.getText(self,'Копия','Повторите пароль копии:',QLineEdit.EchoMode.Password)
            if not ok or repeat!=password:QMessageBox.warning(self,'Пароль','Пароли не совпали');return
        def work():
            if not encrypted:return create_backup(db,path)
            with tempfile.TemporaryDirectory(dir=Path(path).parent) as tmp:
                archive=Path(tmp)/'data.zip';result=create_backup(db,archive)
                output=Path(tmp)/'encrypted.sgb';encrypt_backup(archive,output,password);os.replace(output,path)
                return result
        def done(result):
            message=f'Копия сохранена. Отсутствующих исходных файлов: {len(result["missing"])}.'
            self.backup_status.setText(message);QMessageBox.information(self,'Копия',message)
        self.start_job(work,done)

    def contracts_excel_path(self):
        return Path(db.db_name).parent / 'excel_reports' / EXPORT_FILENAME

    def export_contracts_excel_now(self):
        path = self.contracts_excel_path()
        now = datetime.now()
        try:
            gsv_count, gsn_count = export_registries(db, path)
            message = f'{now:%d.%m.%Y %H:%M}: ГСВ {gsv_count}, ГСН {gsn_count} строк — {path}'
            db.set_setting('last_contracts_excel', now.isoformat())
        except Exception as e:
            message = f'{now:%d.%m.%Y %H:%M}: ошибка экспорта — {e}'
        db.set_setting('contracts_excel_status', message)
        self.contracts_excel_status.setText(message)
        try:
            from .gsv_project_domain import export_cards, EXPORT_FILENAME as PROJECTS_FILE
            ppath = path.parent / PROJECTS_FILE
            count = export_cards(db, ppath)
            pmessage = f'{now:%d.%m.%Y %H:%M}: проекты ГСВ, карточек {count} — {ppath}'
            db.set_setting('last_projects_excel', now.isoformat())
        except Exception as e:
            pmessage = f'{now:%d.%m.%Y %H:%M}: ошибка экспорта — {e}'
        db.set_setting('projects_excel_status', pmessage)
        self.projects_excel_status.setText(pmessage)

    def open_contracts_excel_folder(self):
        from .platform_utils import open_local
        folder = self.contracts_excel_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        open_local(str(folder))

    def do_restore(self):
        path,_=QFileDialog.getOpenFileName(self,'Резервная копия','','Копии (*.zip *.sgb)')
        if not path:return
        parent=QFileDialog.getExistingDirectory(self,'Папка для восстановления')
        if not parent:return
        destination=Path(parent)/('smetagaz_restored_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        password=''
        if path.lower().endswith('.sgb'):
            password,ok=QInputDialog.getText(self,'Копия','Пароль копии:',QLineEdit.EchoMode.Password)
            if not ok:return
        def work():
            if not path.lower().endswith('.sgb'):return restore_backup(path,destination)
            with tempfile.TemporaryDirectory(dir=parent) as tmp:
                archive=Path(tmp)/'data.zip';decrypt_backup(path,archive,password);return restore_backup(archive,destination)
        def done(result):
            message=f'Данные проверены и восстановлены в {destination}.\nДля запуска выберите эту папку: python run.py --data-dir "{destination}".\nТекущие данные не изменены.'
            self.backup_status.setText(message);QMessageBox.information(self,'Восстановлено',message)
        self.start_job(work,done)
