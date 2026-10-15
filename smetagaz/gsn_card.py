"""Раздел «Монтаж ГСН»: карточка договора. Четыре вкладки: «Договор и клиент», «Трубопроводы и оборудование», «Исполнительная документация», «Шаблоны и теги».

Раздел самостоятелен: общего у него с остальными только «Клиенты» и «Сметы». Заказчик — всегда клиент-физлицо (юрлица в монтаже ГСН недоступны)."""
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QGroupBox, QLineEdit, QDoubleSpinBox, QLabel, QPushButton, QTabWidget,
                              QScrollArea, QMessageBox, QCheckBox, QTextEdit, QTableWidget, QTableWidgetItem, QAbstractItemView)
from PyQt6.QtCore import QDate, QLocale, Qt

from .date_widgets import DateEdit
from .database import db
from .domain_widgets import ClientForm, OptionalDate
from .gsv_domain import get_client
from . import gsn_domain as gn
from . import gsn_docs as dd
from .gsn_tabs import GsnPipelineTab, GsnIdTab, TemplatesTab
from .gsvm_tabs import STATE_TEXT, open_file, print_files


def money_text(value):
    return f'{float(value or 0):,.2f}'.replace(',', ' ').replace('.', ',') + ' BYN'


class GsnContractDialog(QDialog):
    def __init__(self, rid=None, parent=None):
        super().__init__(parent)
        self.contract_id = rid
        self.estimate_id = None
        self.locked = False
        self.setWindowTitle('Договор · монтаж ГСН')
        self.resize(1150, 860)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        page = QWidget()
        body = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, 'Договор и клиент')

        # 1. Адрес / объект
        obj = QGroupBox('1. Адрес / Объект')
        form = QFormLayout(obj)
        self.number = QLineEdit()
        self.number.setPlaceholderText('Вводится вручную')
        self.date_contract = self.make_date()
        self.chk_contract_signed = QCheckBox('Договор подписан')
        row = QHBoxLayout()
        row.addWidget(self.date_contract)
        row.addWidget(self.chk_contract_signed)
        row.addStretch()
        self.title = QLineEdit()
        self.title.setPlaceholderText('Согласно названию проекта и технических условий')
        self.address = QLineEdit()
        form.addRow('Номер договора', self.number)
        form.addRow('Дата заключения договора', row)
        form.addRow('Наименование объекта', self.title)
        form.addRow('Адрес объекта', self.address)
        body.addWidget(obj)

        # 2. Клиент (общий раздел «Клиенты»; проверка по ФИО, кнопка выбора, несколько телефонов)
        self.client_form = ClientForm()
        body.addWidget(self.client_form)

        # 3. Примечания
        notes_box = QGroupBox('3. Примечания по объекту')
        nl = QVBoxLayout(notes_box)
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(70)
        nl.addWidget(self.notes)
        body.addWidget(notes_box)

        # 4. Проект
        project = QGroupBox('4. Проект')
        pf = QFormLayout(project)
        self.code = QLineEdit()
        self.designer = QLineEdit()
        self.chk_project_month = QCheckBox('указана')
        self.dt_project = DateEdit(QDate.currentDate())
        self.dt_project.setLocale(QLocale(QLocale.Language.Russian))
        self.dt_project.setDisplayFormat('MMMM yyyy')
        self.dt_project.setEnabled(False)
        self.chk_project_month.toggled.connect(self.dt_project.setEnabled)
        row = QHBoxLayout()
        row.addWidget(self.dt_project)
        row.addWidget(self.chk_project_month)
        row.addStretch()
        self.tu = QTextEdit()
        self.tu.setMaximumHeight(60)
        self.tu.setPlaceholderText('Номер, дата и содержание технических условий — вводится вручную')
        pf.addRow('Шифр проекта', self.code)
        pf.addRow('Проектировщик', self.designer)
        pf.addRow('Дата проекта (месяц и год)', row)
        pf.addRow('ТУ (технические условия)', self.tu)
        body.addWidget(project)

        # 5. Сроки и стоимость
        terms = QGroupBox('5. Сроки и стоимость')
        grid = QGridLayout(terms)
        self.date_start = self.make_date()
        self.date_start.setEnabled(False)
        self.date_start.setToolTip('Начало работ совпадает с датой заключения договора')
        self.date_end = self.make_date()
        self.date_act = OptionalDate()
        self.chk_act_signed = QCheckBox('Акт подписан')
        self.chk_act_signed.setToolTip('Пока акт не подписан, работа считается не сданной')
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e9)
        self.amount.setDecimals(2)
        self.amount.setSuffix(' BYN')
        hint = QLabel(f'по умолчанию {gn.DEFAULT_END_DAYS} дней с даты заключения, можно изменить вручную')
        hint.setStyleSheet('color: #605E5C;')
        grid.addWidget(QLabel('Начало работ'), 0, 0)
        grid.addWidget(self.date_start, 0, 1)
        grid.addWidget(QLabel('Окончание работ'), 1, 0)
        grid.addWidget(self.date_end, 1, 1)
        grid.addWidget(hint, 1, 2, 1, 2)
        grid.addWidget(QLabel('Дата акта'), 2, 0)
        grid.addWidget(self.date_act, 2, 1)
        grid.addWidget(self.chk_act_signed, 2, 2)
        grid.addWidget(QLabel('Стоимость работ'), 3, 0)
        grid.addWidget(self.amount, 3, 1)
        body.addWidget(terms)
        self.prev_contract = self.date_contract.date()
        self.date_contract.dateChanged.connect(self.on_contract_date)
        self.date_end.setDate(self.date_contract.date().addDays(gn.DEFAULT_END_DAYS))
        self.date_start.setDate(self.date_contract.date())

        # 6. Смета
        est = QGroupBox('6. Смета')
        el = QVBoxLayout(est)
        self.lbl_estimate = QLabel()
        self.lbl_estimate.setWordWrap(True)
        el.addWidget(self.lbl_estimate)
        bar = QHBoxLayout()
        self.btn_create_est = QPushButton('Создать смету')
        self.btn_create_est.clicked.connect(self.create_linked_estimate)
        self.btn_link_est = QPushButton('Привязать смету')
        self.btn_link_est.clicked.connect(self.link_estimate)
        self.btn_pull = QPushButton('Получить стоимость из сметы')
        self.btn_pull.clicked.connect(self.pull_amount_from_estimate)
        self.btn_history = QPushButton('История изменений сметы')
        self.btn_history.clicked.connect(self.show_estimate_history)
        self.btn_open_est = QPushButton('Открыть смету')
        self.btn_open_est.clicked.connect(self.open_estimate_editor)
        for b in (self.btn_create_est, self.btn_link_est, self.btn_pull, self.btn_history, self.btn_open_est):
            bar.addWidget(b)
        bar.addStretch()
        el.addLayout(bar)
        body.addWidget(est)

        # документы договора и справки (остальные — на вкладке «Исполнительная документация»)
        docs = QGroupBox('Документы по тегам')
        dl = QGridLayout(docs)
        self.doc_state, self.doc_make, self.doc_open = {}, {}, {}
        for r, kind in enumerate(dd.MAIN_KINDS):
            dl.addWidget(QLabel(dd.DOC_KINDS[kind][0]), r, 0)
            st = QLabel()
            self.doc_state[kind] = st
            dl.addWidget(st, r, 1)
            make = QPushButton()
            make.clicked.connect(lambda _=False, k=kind: self.make_document(k))
            self.doc_make[kind] = make
            dl.addWidget(make, r, 2)
            opn = QPushButton('Открыть')
            opn.clicked.connect(lambda _=False, k=kind: self.open_document(k))
            self.doc_open[kind] = opn
            dl.addWidget(opn, r, 3)
            prn = QPushButton('Печать')
            prn.clicked.connect(lambda _=False, k=kind: print_files(self, [dd.doc_path(db, self.contract_id, k)]))
            dl.addWidget(prn, r, 4)
        dl.setColumnStretch(1, 1)
        self.lbl_folder = QLabel()
        self.lbl_folder.setWordWrap(True)
        self.lbl_folder.setStyleSheet('color: #605E5C;')
        dl.addWidget(self.lbl_folder, len(dd.MAIN_KINDS), 0, 1, 5)
        body.addWidget(docs)
        body.addStretch()
        self.lock_widgets = [obj, self.client_form, notes_box, project, terms]

        # остальные вкладки
        self.pipeline_tab = GsnPipelineTab(self)
        self.tabs.addTab(self.pipeline_tab, 'Трубопроводы и оборудование')
        self.id_tab = GsnIdTab(self)
        self.tabs.addTab(self.id_tab, 'Исполнительная документация')
        self.templates_tab = TemplatesTab(self)
        self.tabs.addTab(self.templates_tab, 'Шаблоны и теги')
        self.tabs.currentChanged.connect(self.on_tab)

        # нижняя панель
        bottom = QHBoxLayout()
        self.status = QLabel('')
        bottom.addWidget(self.status, 1)
        for text, fn in (('Оплаты', self.open_payments), ('Создать задачу', self.create_task), ('Заметки', self.open_notes), ('Папка договора', self.open_folder)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bottom.addWidget(b)
        from .print_ui import make_buttons, gsn_card
        for b in make_buttons(self, lambda: gsn_card(db, self.contract_id), lambda: 'Договор ГСН ' + (self.number.text() or str(self.contract_id)), self.ensure_saved):
            bottom.addWidget(b)
        self.edit_button = QPushButton('Изменить')
        self.edit_button.clicked.connect(self.toggle_edit)
        bottom.addWidget(self.edit_button)
        self.save_button = QPushButton('Сохранить')
        self.save_button.setProperty('type', 'primary')
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save_clicked)
        bottom.addWidget(self.save_button)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        layout.addLayout(bottom)

        self.load_data()
        self.set_locked(bool(self.contract_id))

    @property
    def rid(self):
        return self.contract_id

    # --- мелочи интерфейса ---
    @staticmethod
    def make_date():
        d = DateEdit(QDate.currentDate())
        d.setCalendarPopup(True)
        d.setDisplayFormat('dd.MM.yyyy')
        return d

    def on_contract_date(self, qdate):
        """Начало работ = дата заключения; окончание следует за ней (+60 дней), пока его не изменили вручную."""
        if self.date_end.date() == self.prev_contract.addDays(gn.DEFAULT_END_DAYS):
            self.date_end.setDate(qdate.addDays(gn.DEFAULT_END_DAYS))
        self.prev_contract = qdate
        self.date_start.setDate(qdate)

    def on_tab(self, index):
        widget = self.tabs.widget(index)
        if widget in (self.id_tab, self.templates_tab) and self.contract_id and not self.locked:
            self.save_data(silent=True)
        if widget is self.id_tab:
            self.id_tab.load()
        elif widget is self.templates_tab:
            self.templates_tab.load_tags()
        elif widget is self.pipeline_tab:
            self.pipeline_tab.refresh()

    def set_locked(self, locked):
        """Сохранённый договор открывается только для просмотра; поля разблокирует кнопка «Изменить»."""
        self.locked = locked
        for w in self.lock_widgets:
            w.setEnabled(not locked)
        self.pipeline_tab.set_enabled_inputs(not locked)
        self.edit_button.setVisible(bool(self.contract_id))
        self.edit_button.setText('Изменить' if locked else 'Заблокировать')

    def toggle_edit(self):
        if not self.locked and not self.save_data():
            return
        self.set_locked(not self.locked)

    # --- загрузка ---
    def load_data(self):
        if self.contract_id:
            c = gn.get(db, self.contract_id)
            self.estimate_id = c.get('estimate_id')
            self.number.setText(c['contract_number'] or '')
            self.title.setText(c['title'] or '')
            self.address.setText(c.get('address') or '')
            self.notes.setPlainText(c.get('notes') or '')
            self.code.setText(c.get('designer_code') or '')
            self.designer.setText(c.get('designer') or '')
            self.tu.setPlainText(c.get('tu_text') or '')
            month = QDate.fromString((c.get('project_month') or '') + '-01', 'yyyy-MM-dd')
            self.chk_project_month.setChecked(month.isValid())
            if month.isValid():
                self.dt_project.setDate(month)
            self.amount.setValue(float(c.get('contract_amount') or 0))
            self.chk_contract_signed.setChecked(bool(c.get('contract_signed')))
            self.chk_act_signed.setChecked(bool(c.get('act_signed')))
            self.date_contract.blockSignals(True)
            day = QDate.fromString(c['contract_date'] or '', 'yyyy-MM-dd')
            if day.isValid():
                self.date_contract.setDate(day)
            self.date_contract.blockSignals(False)
            self.prev_contract = self.date_contract.date()
            self.date_start.setDate(self.date_contract.date())
            end = QDate.fromString(c.get('work_end_date') or '', 'yyyy-MM-dd')
            if end.isValid():
                self.date_end.setDate(end)
            self.date_act.set_value(c.get('act_date') or '')
            client = get_client(db, c['client_id']) if c.get('client_id') else None
            self.client_form.fill(client or dict(name=c['client_name'], phone=c['phone'], address=c.get('client_address'), passport=c['passport'],
                                                 passport_issuer=c.get('passport_issuer'), passport_date=c.get('passport_issue_date')), c['client_id'])
            self.pipeline_tab.fill(c, gn.chosen_items(db, self.contract_id))
        else:
            self.pipeline_tab.fill({}, {})
        self.refresh_estimate_ui()
        self.refresh_docs()

    # --- сохранение ---
    def values(self):
        return dict(contract_number=self.number.text().strip(), contract_date=self.date_contract.date().toString('yyyy-MM-dd'), title=self.title.text().strip(),
                    address=self.address.text().strip(), notes=self.notes.toPlainText().strip(), designer_code=self.code.text().strip(), designer=self.designer.text().strip(),
                    project_month=self.dt_project.date().toString('yyyy-MM') if self.chk_project_month.isChecked() else '', tu_text=self.tu.toPlainText().strip(),
                    contract_signed=int(self.chk_contract_signed.isChecked()), work_start_date=self.date_contract.date().toString('yyyy-MM-dd'),
                    work_end_date=self.date_end.date().toString('yyyy-MM-dd'), act_date=self.date_act.value(), act_signed=int(self.chk_act_signed.isChecked()),
                    contract_amount=self.amount.value(), **self.pipeline_tab.values())

    def save_data(self, silent=False):
        try:
            client = self.client_form.values()
            cid, client_id = gn.save_card(db, self.values(), client, self.client_form.client_id, self.contract_id, self.pipeline_tab.items())
            self.contract_id = cid
            self.client_form.client_id = client_id
            self.client_form.info.setText(f'Клиент №{client_id}. Данные сохранены.')
            self.status.setText(f'Сохранено · договор {self.number.text() or cid} · клиент №{client_id}')
            self.edit_button.setVisible(True)
            self.refresh_estimate_ui()
            self.refresh_docs()
            return True
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, 'Договор не сохранён', str(e))
            return False

    def save_clicked(self):
        is_new = not self.contract_id
        if is_new and not self.client_form.confirm_duplicate():
            return
        if self.save_data():
            if is_new:
                self.ask_folder()
            self.set_locked(True)

    def ensure_saved(self):
        if self.contract_id:
            return True if self.locked else self.save_data()
        if not self.client_form.confirm_duplicate():
            return False
        return self.save_data()

    # --- папка ---
    def ask_folder(self):
        """Предлагает создать новую папку договора или привязать существующую. Возвращает путь или ''."""
        if not self.contract_id and not self.save_data():
            return ''
        current = gn.contract_folder(db, self.contract_id)
        if current:
            return current
        from .folder_ui import choose_folder
        path, create = choose_folder(self, 'gsn_projects', gn.suggested_folder_name(db, self.contract_id))
        if not path:
            return ''
        try:
            gn.link_folder(db, self.contract_id, path, create=create)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, 'Папка договора', str(e))
            return ''
        self.refresh_docs()
        return path

    def ensure_folder(self):
        return gn.contract_folder(db, self.contract_id) or self.ask_folder()

    def open_folder(self):
        if not self.contract_id and not self.save_data():
            return
        folder = self.ask_folder()
        if folder:
            from .platform_utils import open_local
            open_local(folder)

    # --- смета ---
    def refresh_estimate_ui(self):
        state = gn.estimate_state(db, self.contract_id) if self.contract_id else ('none' if not self.estimate_id else 'unsynced')
        s = gn.estimate_summary(db, self.estimate_id) if self.estimate_id else None
        if not self.estimate_id or not s:
            text, color = '<b>Смета</b><br>Нет данных. Создайте новую смету или привяжите существующую.', '#605E5C'
        elif state == 'unsynced':
            text, color = f'<b>Смета «{s["title"]}»</b><br>Получить данные из сметы (кнопка «Получить стоимость из сметы»).', '#2563EB'
        elif state == 'stale':
            text, color = (f'<b>Смета «{s["title"]}»</b><br><b>Смета была изменена — обновите данные.</b> '
                           f'Сейчас в смете: материалы {money_text(s["materials"])}, работы {money_text(s["works"])}, итого {money_text(s["total"])}.'), '#B45309'
        else:
            row = db.fetchone('SELECT est_materials,est_works,contract_amount FROM gsn_projects WHERE id=?', (self.contract_id,)) or (0, 0, 0)
            text, color = (f'<b>Смета «{s["title"]}»</b><br>Стоимость материалов по клиенту: <b>{money_text(row[0])}</b> · стоимость работ по клиенту: <b>{money_text(row[1])}</b> · '
                           f'итого по смете: <b>{money_text(row[2])}</b>'), '#15803D'
        self.lbl_estimate.setText(text)
        self.lbl_estimate.setStyleSheet(f'color: {color};')
        has = bool(self.estimate_id and s)
        self.btn_create_est.setVisible(not has)
        self.btn_link_est.setVisible(not has)
        self.btn_pull.setVisible(has)
        self.btn_history.setVisible(has)
        self.btn_open_est.setVisible(has)

    def create_linked_estimate(self):
        if not self.ensure_saved():
            return
        if self.estimate_id:
            return self.open_estimate_editor()
        with db.transaction():
            client = self.client_form.values()
            self.estimate_id = db.execute('INSERT INTO estimates(title,date,total,paid,client_id,client_name,client_phone) VALUES(?,?,0,0,?,?,?)',
                                          (self.title.text() or 'Смета к договору ' + self.number.text(), QDate.currentDate().toString('yyyy-MM-dd'), self.client_form.client_id,
                                           client['name'], client['phone'])).lastrowid
            gn.link_estimate(db, self.contract_id, self.estimate_id)
        self.refresh_estimate_ui()
        self.open_estimate_editor()
        self.refresh_estimate_ui()

    def link_estimate(self):
        if not self.ensure_saved():
            return
        d = QDialog(self)
        d.setWindowTitle('Привязать смету')
        d.resize(700, 480)
        layout = QVBoxLayout(d)
        search = QLineEdit()
        search.setPlaceholderText('Название сметы или клиент…')
        layout.addWidget(search)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(['Смета', 'Клиент', 'Итого'])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 330)
        table.setColumnWidth(1, 200)
        layout.addWidget(table, 1)

        def load():
            q = '%' + search.text().casefold() + '%'
            taken = ' AND '.join(f'id NOT IN (SELECT estimate_id FROM {t} WHERE estimate_id IS NOT NULL)' for t in ('contracts', 'gsv_projects', 'smr_contracts', 'gsn_projects'))
            rows = db.fetchall(f"SELECT id,title,client_name,total FROM estimates WHERE {taken} AND LOWER(coalesce(title,'')||' '||coalesce(client_name,'')) LIKE ? ORDER BY id DESC LIMIT 300", (q,))
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, v in enumerate((row[1], row[2], money_text(row[3]))):
                    item = QTableWidgetItem(str(v or ''))
                    item.setData(Qt.ItemDataRole.UserRole, row[0])
                    table.setItem(r, c, item)
        search.textChanged.connect(load)
        load()
        pick = QPushButton('Привязать выбранную смету')
        pick.setProperty('type', 'primary')
        layout.addWidget(pick)

        def choose():
            r = table.currentRow()
            if r < 0:
                return
            try:
                gn.link_estimate(db, self.contract_id, table.item(r, 0).data(Qt.ItemDataRole.UserRole))
            except Exception as e:
                QMessageBox.warning(d, 'Смета', str(e))
                return
            d.accept()
        pick.clicked.connect(choose)
        table.cellDoubleClicked.connect(lambda *_: choose())
        if d.exec():
            self.estimate_id = db.fetchone('SELECT estimate_id FROM gsn_projects WHERE id=?', (self.contract_id,))[0]
            self.refresh_estimate_ui()

    def pull_amount_from_estimate(self, silent=False):
        """«Получить стоимость из сметы»: материалы и работы фиксируются, итог становится стоимостью работ договора."""
        if not self.estimate_id or not self.ensure_saved():
            return
        try:
            s = gn.sync_estimate(db, self.contract_id)
        except ValueError as e:
            QMessageBox.warning(self, 'Смета', str(e))
            return
        self.amount.setValue(s['total'])
        self.refresh_estimate_ui()
        self.refresh_docs()
        if not silent:
            self.status.setText(f'Получено из сметы: материалы {money_text(s["materials"])}, работы {money_text(s["works"])}')

    def show_estimate_history(self):
        if not self.estimate_id:
            return
        d = QDialog(self)
        d.setWindowTitle('История изменений сметы')
        d.resize(880, 520)
        layout = QVBoxLayout(d)
        rows = gn.estimate_history(db, self.estimate_id)
        table = QTableWidget(len(rows), 4)
        table.setHorizontalHeaderLabels(['Когда', 'Что', 'Позиция', 'Подробности'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 150)
        table.setColumnWidth(1, 90)
        table.setColumnWidth(2, 280)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                table.setItem(r, c, QTableWidgetItem(str(v or '')))
        layout.addWidget(table, 1)
        if not rows:
            layout.addWidget(QLabel('Изменений сметы пока не зафиксировано (журнал ведётся с момента обновления программы).'))
        close = QPushButton('Закрыть')
        close.clicked.connect(d.accept)
        layout.addWidget(close)
        d.exec()

    def open_estimate_editor(self):
        if not self.estimate_id:
            return
        from .estimate_editor import EstimateEditorDialog
        row = db.fetchone('SELECT title FROM estimates WHERE id=?', (self.estimate_id,))
        if row:
            EstimateEditorDialog(self.estimate_id, row[0] or '', self).exec()
            self.refresh_estimate_ui()

    # --- документы ---
    def refresh_docs(self):
        for kind in dd.MAIN_KINDS:
            state = dd.doc_state(db, self.contract_id, kind) if self.contract_id else 'none'
            text, color = STATE_TEXT[state]
            self.doc_state[kind].setText(text)
            self.doc_state[kind].setStyleSheet(f'color: {color}; font-weight: 600;')
            self.doc_make[kind].setText('⟳ Переформировать' if state in ('stale', 'fresh', 'linked') else 'Сформировать')
            self.doc_make[kind].setProperty('type', 'primary' if state in ('stale', 'none', 'missing') else '')
            self.doc_make[kind].style().unpolish(self.doc_make[kind])
            self.doc_make[kind].style().polish(self.doc_make[kind])
            self.doc_open[kind].setEnabled(state in ('fresh', 'stale', 'linked'))
        folder = gn.contract_folder(db, self.contract_id) if self.contract_id else ''
        self.lbl_folder.setText(f'Папка договора: {folder}' if folder else 'Папка договора не привязана — программа предложит создать или выбрать её при формировании документа.')

    def make_document(self, kind):
        if not self.ensure_saved():
            return
        from . import preflight_ui
        if not preflight_ui.confirm(self, f'«{dd.DOC_KINDS[kind][0]}»', dd.check(db, self.contract_id, kind)):
            return
        if not self.ensure_folder():
            return
        try:
            path = dd.generate(db, self.contract_id, kind)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, 'Документ не создан', str(e))
            return
        self.refresh_docs()
        self.status.setText(f'Создан файл: {path}')
        open_file(self, path)

    def open_document(self, kind):
        open_file(self, dd.doc_path(db, self.contract_id, kind))

    # --- оплаты, задачи, заметки ---
    def open_payments(self):
        if not self.ensure_saved():
            return
        from .payments_view import PaymentsDialog
        PaymentsDialog('gsn_projects', self.contract_id, self).exec()
        self.refresh_docs()

    def open_notes(self):
        if not self.ensure_saved():
            return
        from .notes_view import open_notes
        open_notes(self, 'gsn_projects', self.contract_id)

    def create_task(self):
        if not self.ensure_saved():
            return
        from .tasks_view import new_task_for
        new_task_for(self, 'gsn_projects', self.contract_id)

    def export_template(self):
        if self.ensure_saved():
            from .report_dialog import ReportTemplateDialog
            ReportTemplateDialog('gsn_projects', self.contract_id, self).exec()
