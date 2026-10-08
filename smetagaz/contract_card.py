"""Раздел «Монтаж ГСВ»: карточка договора (договор и клиент, оборудование, трубопроводы и стыки, исполнительная документация, шаблоны и теги).

Раздел самостоятелен: общим с другими разделами у него только клиент из модуля «Клиенты». С модулем «Исполнительная документация» связей нет.
"""
import re

from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QGroupBox, QLineEdit, QDoubleSpinBox, QDateEdit, QLabel,
                              QPushButton, QTabWidget, QScrollArea, QMessageBox, QCheckBox, QTextEdit, QTableWidget, QTableWidgetItem, QAbstractItemView)
from PyQt6.QtCore import QDate, QLocale, Qt

from .database import db
from .domain_widgets import ClientForm, OptionalDate
from .gsv_domain import get_client, save_client
from . import gsvm_domain as md
from . import gsvm_docs as dd
from .gsvm_tabs import EquipmentTab, PipesTab, IdTab, TemplatesTab, WorkEntryDialog, ConsumptionDialog, STATE_TEXT, open_file, print_files


class ContractCardDialog(QDialog):
    def __init__(self, estimate_id=None, title='', parent=None, contract_id=None):
        super().__init__(parent)
        self.estimate_id = estimate_id
        self.contract_id = contract_id
        self.title = title
        self.locked = False
        self.setWindowTitle('Договор · монтаж ГСВ')
        self.resize(1150, 860)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # --- вкладка «Договор и клиент» ---
        page = QWidget()
        body = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, 'Договор и клиент')

        obj = QGroupBox('1. Адрес / Объект')
        form = QFormLayout(obj)
        self.inp_number = QLineEdit()
        self.inp_number.setReadOnly(True)
        self.inp_number.setToolTip('Номер формируется автоматически: порядковый номер, раздел 02 (монтаж ГСВ), год заключения')
        self.date_contract = self.make_date()
        self.chk_contract_signed = QCheckBox('Договор подписан')
        row = QHBoxLayout()
        row.addWidget(self.date_contract)
        row.addWidget(self.chk_contract_signed)
        row.addStretch()
        self.inp_object = QLineEdit(title)
        self.inp_object.setPlaceholderText('Согласно названию проекта и технических условий')
        self.inp_object_address = QLineEdit()
        form.addRow('Номер договора', self.inp_number)
        form.addRow('Дата заключения договора', row)
        form.addRow('Наименование объекта', self.inp_object)
        form.addRow('Адрес объекта', self.inp_object_address)
        body.addWidget(obj)

        from .counterparty_ui import CustomerSwitch
        self.customer = CustomerSwitch('contracts', lambda: self.contract_id, self.ensure_saved)
        self.customer.changed.connect(self.apply_customer_mode)
        body.addWidget(self.customer)
        self.client_form = ClientForm()
        body.addWidget(self.client_form)
        # имена, которыми пользуются другие модули
        self.inp_client = self.client_form.name
        self.inp_phone = self.client_form.phone
        self.inp_address = self.client_form.address
        self.inp_passport_num = self.client_form.passport
        self.inp_passport_issuer = self.client_form.passport_issuer
        self.date_passport = self.client_form.passport_date

        notes_box = QGroupBox('3. Примечания по объекту')
        nl = QVBoxLayout(notes_box)
        self.inp_notes = QTextEdit()
        self.inp_notes.setMaximumHeight(70)
        nl.addWidget(self.inp_notes)
        body.addWidget(notes_box)

        project = QGroupBox('4. Проект')
        pf = QFormLayout(project)
        self.inp_code = QLineEdit()
        self.inp_designer = QLineEdit()
        self.chk_project_month = QCheckBox('указана')
        self.dt_project = QDateEdit(QDate.currentDate())
        self.dt_project.setLocale(QLocale(QLocale.Language.Russian))
        self.dt_project.setDisplayFormat('MMMM yyyy')
        self.dt_project.setCalendarPopup(True)
        self.dt_project.setEnabled(False)
        self.chk_project_month.toggled.connect(self.dt_project.setEnabled)
        row = QHBoxLayout()
        row.addWidget(self.dt_project)
        row.addWidget(self.chk_project_month)
        row.addStretch()
        pf.addRow('Шифр проекта', self.inp_code)
        pf.addRow('Проектировщик', self.inp_designer)
        pf.addRow('Дата проекта (месяц и год)', row)
        body.addWidget(project)

        terms = QGroupBox('5. Сроки и стоимость')
        grid = QGridLayout(terms)
        self.date_start = self.make_date()
        self.date_start.setEnabled(False)
        self.date_start.setToolTip('Начало работ совпадает с датой заключения договора')
        self.date_end = self.make_date()
        self.date_act = OptionalDate()
        self.chk_act_signed = QCheckBox('Акт подписан')
        self.chk_act_signed.setToolTip('Пока акт не подписан, работа считается не сданной')
        self.inp_amount = QDoubleSpinBox()
        self.inp_amount.setRange(0, 1e9)
        self.inp_amount.setDecimals(2)
        self.inp_amount.setSuffix(' BYN')
        self.lbl_end_hint = QLabel(f'по умолчанию {md.DEFAULT_END_DAYS} дней с даты заключения, можно изменить вручную')
        self.lbl_end_hint.setStyleSheet('color: #65758b;')
        grid.addWidget(QLabel('Начало работ'), 0, 0)
        grid.addWidget(self.date_start, 0, 1)
        grid.addWidget(QLabel('Окончание работ'), 1, 0)
        grid.addWidget(self.date_end, 1, 1)
        grid.addWidget(self.lbl_end_hint, 1, 2, 1, 2)
        grid.addWidget(QLabel('Дата акта'), 2, 0)
        grid.addWidget(self.date_act, 2, 1)
        grid.addWidget(self.chk_act_signed, 2, 2)
        grid.addWidget(QLabel('Стоимость работ'), 3, 0)
        grid.addWidget(self.inp_amount, 3, 1)
        body.addWidget(terms)
        self.prev_contract = self.date_contract.date()
        self.date_contract.dateChanged.connect(self.on_contract_date)
        self.date_end.setDate(self.date_contract.date().addDays(md.DEFAULT_END_DAYS))
        self.date_start.setDate(self.date_contract.date())

        # смета
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
        r = len(dd.MAIN_KINDS)
        dl.addWidget(QLabel('Смета по объекту'), r, 0)
        dl.addWidget(QLabel('шаблон и теги сметы — в модуле «Реестр смет»'), r, 1)
        self.btn_estimate_doc = QPushButton('Сформировать смету…')
        self.btn_estimate_doc.clicked.connect(self.export_estimate)
        dl.addWidget(self.btn_estimate_doc, r, 2)
        dl.setColumnStretch(1, 1)
        self.lbl_folder = QLabel()
        self.lbl_folder.setWordWrap(True)
        self.lbl_folder.setStyleSheet('color: #65758b;')
        dl.addWidget(self.lbl_folder, r + 1, 0, 1, 5)
        body.addWidget(docs)
        body.addStretch()
        self.lock_widgets = [obj, self.customer, self.client_form, notes_box, project, terms]

        # --- остальные вкладки ---
        self.equipment_tab = EquipmentTab(self)
        self.equipment = self.equipment_tab
        self.table_equip = self.equipment_tab.table
        self.tabs.addTab(self.equipment_tab, 'Оборудование')
        self.pipes_tab = PipesTab(self)
        self.tabs.addTab(self.pipes_tab, 'Трубопроводы и стыки')
        self.id_tab = IdTab(self)
        self.tabs.addTab(self.id_tab, 'Исполнительная документация')
        self.templates_tab = TemplatesTab(self)
        self.tabs.addTab(self.templates_tab, 'Шаблоны и теги')
        self.tabs.currentChanged.connect(self.on_tab)

        # --- нижняя панель ---
        bottom = QHBoxLayout()
        self.status = QLabel('')
        bottom.addWidget(self.status, 1)
        for text, fn in (('Оплаты', self.open_payments), ('Создать задачу', self.create_task), ('Папка договора', self.open_folder), ('Расход материалов', self.open_consumption), ('График работ…', self.open_schedule)):
            b = QPushButton(text)
            b.clicked.connect(fn)
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

    # --- мелочи интерфейса ---
    @staticmethod
    def make_date():
        d = QDateEdit(QDate.currentDate())
        d.setCalendarPopup(True)
        d.setDisplayFormat('dd.MM.yyyy')
        return d

    def on_contract_date(self, qdate):
        """Начало работ = дата заключения; окончание следует за ней (+60 дней), пока его не изменили вручную."""
        if self.date_end.date() == self.prev_contract.addDays(md.DEFAULT_END_DAYS):
            self.date_end.setDate(qdate.addDays(md.DEFAULT_END_DAYS))
        self.prev_contract = qdate
        self.date_start.setDate(qdate)

    def on_tab(self, index):
        widget = self.tabs.widget(index)
        if widget in (self.id_tab, self.templates_tab) and self.contract_id:
            self.save_panels(silent=True)
        if widget is self.id_tab:
            self.id_tab.load()
        elif widget is self.templates_tab:
            self.templates_tab.load_tags()

    def set_locked(self, locked):
        """Сохранённый договор открывается только для просмотра; поля разблокирует кнопка «Изменить»."""
        self.locked = locked
        for w in self.lock_widgets:
            w.setEnabled(not locked)
        self.edit_button.setVisible(bool(self.contract_id))
        self.edit_button.setText('Изменить' if locked else 'Заблокировать')

    def toggle_edit(self):
        if not self.locked and not self.save_data():
            return
        self.set_locked(not self.locked)

    # --- загрузка ---
    def load_data(self):
        if not self.contract_id and self.estimate_id:
            found = db.fetchone('SELECT id FROM contracts WHERE estimate_id=?', (self.estimate_id,))
            if found:
                self.contract_id = found[0]
        if self.contract_id:
            cur = db.execute('SELECT * FROM contracts WHERE id=?', (self.contract_id,))
            c = dict(zip([x[0] for x in cur.description], cur.fetchone()))
            self.estimate_id = c['estimate_id']
            self.inp_number.setText(c['contract_number'] or '')
            self.inp_object.setText(c['object_name'] or '')
            self.inp_object_address.setText(c.get('object_address') or '')
            self.inp_notes.setPlainText(c.get('notes') or '')
            self.inp_code.setText(c.get('designer_code') or '')
            self.inp_designer.setText(c.get('designer') or '')
            month = QDate.fromString((c.get('project_month') or '') + '-01', 'yyyy-MM-dd')
            self.chk_project_month.setChecked(month.isValid())
            if month.isValid():
                self.dt_project.setDate(month)
            self.inp_amount.setValue(c['contract_amount'] or 0)
            self.chk_contract_signed.setChecked(bool(c.get('contract_signed')))
            self.chk_act_signed.setChecked(bool(c.get('act_signed')))
            self.date_contract.blockSignals(True)
            day = QDate.fromString(c['contract_date'] or '', 'yyyy-MM-dd')
            if day.isValid():
                self.date_contract.setDate(day)
            self.date_contract.blockSignals(False)
            self.prev_contract = self.date_contract.date()
            self.date_start.setDate(self.date_contract.date())
            end = QDate.fromString(c['work_end_date'] or '', 'yyyy-MM-dd')
            if end.isValid():
                self.date_end.setDate(end)
            self.date_act.set_value(c['acceptance_act_date'] or '')
            client = get_client(db, c['client_id']) or dict(name=c['client_name'], phone=c['client_phone'], address=c['client_address'], passport=c['passport_series_number'],
                                                           passport_issuer=c['passport_issued_by'], passport_date=c['passport_issue_date'])
            self.client_form.fill(client, c['client_id'])
            self.customer.set_legal(c.get('le_client_id'))
            try:
                changed = md.refresh_estimate_pipelines(db, self.contract_id)
                if changed:
                    self.status.setText(f'Трубопроводы обновлены по смете: {changed}')
            except Exception:
                pass
        elif self.estimate_id:
            row = db.fetchone('SELECT client_id,client_name,client_phone FROM estimates WHERE id=?', (self.estimate_id,))
            if row:
                self.client_form.fill(get_client(db, row[0]) or dict(name=row[1], phone=row[2]), row[0])
            self.pull_amount_from_estimate(silent=True)
        if not self.contract_id:
            self.inp_number.setText(f'XX-02/{QDate.currentDate().year() % 100:02d} (авто)')
        self.equipment_tab.load(self.contract_id)
        self.pipes_tab.load(self.contract_id)
        self.refresh_estimate_ui()
        self.refresh_docs()

    # --- сохранение ---
    def create_task(self):
        if not self.ensure_saved():
            return
        from .tasks_view import new_task_for
        new_task_for(self, 'contracts', self.contract_id)

    def apply_customer_mode(self):
        """Заказчик-юрлицо: техническая часть остаётся здесь, а договор, акт, справка и оплаты оформляются в разделе «Юрлица»."""
        legal = self.customer.is_legal()
        self.client_form.setVisible(not legal)
        if hasattr(self, 'doc_make'):
            for kind in dd.MAIN_KINDS:
                self.doc_make[kind].setEnabled(not legal)
                self.doc_open[kind].setEnabled(not legal)
            if not legal:
                self.refresh_docs()
        if legal and hasattr(self, 'status'):
            self.status.setText('Заказчик — юрлицо: договор, акт, справка и оплаты оформляются в разделе «Юрлица».')

    def save_data(self):
        try:
            legal = self.customer.is_legal()
            if legal and not self.customer.legal_id():
                raise ValueError('Выберите юрлицо-заказчика')
            values = dict(name='', phone='', address='', passport='', passport_issuer='', passport_date='') if legal else self.client_form.values()
            contract_date = self.date_contract.date().toString('yyyy-MM-dd')
            with db.transaction():
                cid = None if legal else save_client(db, values, self.client_form.client_id)
                party_name = db.fetchone('SELECT name FROM le_clients WHERE id=?', (self.customer.legal_id(),))[0] if legal else ''
                number = self.inp_number.text().strip()
                seq = year = None
                if not self.contract_id and (not number or number.upper().startswith('XX')):
                    seq, year, number = md.next_number(db, contract_date)
                else:
                    m = re.match(r'^(\d+)-02/(\d{2})$', number)
                    if m:
                        seq, year = int(m.group(1)), int(m.group(2))
                fields = dict(
                    estimate_id=self.estimate_id, contract_number=number, contract_date=contract_date, object_name=self.inp_object.text().strip(),
                    object_address=self.inp_object_address.text().strip(), client_address=values['address'], passport_series_number=values['passport'],
                    passport_issued_by=values['passport_issuer'], passport_issue_date=values['passport_date'], work_start_date=contract_date,
                    work_end_date=self.date_end.date().toString('yyyy-MM-dd'), acceptance_act_date=self.date_act.value(), contract_amount=self.inp_amount.value(),
                    client_id=cid, client_name=values['name'], client_phone=values['phone'], contract_signed=int(self.chk_contract_signed.isChecked()),
                    act_signed=int(self.chk_act_signed.isChecked()), le_client_id=self.customer.legal_id(), party_name=party_name, designer_code=self.inp_code.text().strip(), designer=self.inp_designer.text().strip(),
                    project_month=self.dt_project.date().toString('yyyy-MM') if self.chk_project_month.isChecked() else '', notes=self.inp_notes.toPlainText().strip())
                rid = self.contract_id
                if rid:
                    db.execute('UPDATE contracts SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), rid))
                else:
                    fields.update(seq_num=seq, year_num=year)
                    rid = db.execute('INSERT INTO contracts(' + ','.join(fields) + ') VALUES(' + ','.join('?' for _ in fields) + ')', tuple(fields.values())).lastrowid
                self.contract_id = rid
                self.equipment_tab.save(rid)
                self.pipes_tab.save(rid)
                if self.estimate_id and not legal:
                    from .data_services import link_client
                    link_client(db, 'estimates', self.estimate_id, cid)
            if not legal:
                self.client_form.client_id = cid
                self.client_form.info.setText(f'Клиент №{cid}. Данные сохранены.')
            self.inp_number.setText(db.fetchone('SELECT contract_number FROM contracts WHERE id=?', (rid,))[0])
            self.status.setText(f'Сохранено · договор {self.inp_number.text()} · ' + (f'заказчик: {party_name}' if legal else f'клиент №{cid}'))
            self.edit_button.setVisible(True)
            self.refresh_estimate_ui()
            self.refresh_docs()
            return True
        except Exception as e:
            QMessageBox.warning(self, 'Договор не сохранён', str(e))
            return False

    def save_panels(self, silent=False):
        """Сохраняет оборудование и трубопроводы (и договор целиком) без переключения блокировки."""
        if not self.contract_id:
            return False
        try:
            with db.transaction():
                self.equipment_tab.save(self.contract_id)
                self.pipes_tab.save(self.contract_id)
            return True
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, 'Не сохранено', str(e))
            return False

    def save_clicked(self):
        is_new = not self.contract_id
        if is_new and not self.customer.is_legal() and not self.client_form.confirm_duplicate():
            return
        if self.save_data():
            if is_new:
                self.ask_folder()
            self.set_locked(True)

    def ensure_saved(self):
        if self.contract_id:
            return self.save_panels() if not self.locked else True
        if not self.customer.is_legal() and not self.client_form.confirm_duplicate():
            return False
        return self.save_data()

    # --- папка ---
    def ask_folder(self):
        """Предлагает создать новую папку договора или привязать существующую. Возвращает путь или ''."""
        if not self.contract_id and not self.save_data():
            return ''
        current = md.contract_folder(db, self.contract_id)
        if current:
            return current
        from .folder_ui import choose_folder
        path, create = choose_folder(self, 'contracts', md.suggested_folder_name(db, self.contract_id))
        if not path:
            return ''
        try:
            md.link_folder(db, self.contract_id, path, create=create)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, 'Папка договора', str(e))
            return ''
        self.refresh_docs()
        return path

    def ensure_folder(self):
        return md.contract_folder(db, self.contract_id) or self.ask_folder()

    def open_folder(self):
        if not self.contract_id and not self.save_data():
            return
        folder = self.ask_folder()
        if folder:
            from .platform_utils import open_local
            open_local(folder)

    # --- смета ---
    def refresh_estimate_ui(self):
        state = md.estimate_state(db, self.contract_id) if self.contract_id else ('none' if not self.estimate_id else 'unsynced')
        s = md.estimate_summary(db, self.estimate_id) if self.estimate_id else None
        if not self.estimate_id or not s:
            text, color = '<b>Смета</b><br>Нет данных. Создайте новую смету или привяжите существующую.', '#65758b'
        elif state == 'unsynced':
            text, color = f'<b>Смета «{s["title"]}»</b><br>Получить данные из сметы (кнопка «Получить стоимость из сметы»).', '#2563EB'
        elif state == 'stale':
            text, color = (f'<b>Смета «{s["title"]}»</b><br><b>Смета была изменена — обновите данные.</b> '
                           f'Сейчас в смете: материалы {md_money(s["materials"])}, работы {md_money(s["works"])}, итого {md_money(s["total"])}.'), '#D97706'
        else:
            row = db.fetchone('SELECT est_materials,est_works,contract_amount FROM contracts WHERE id=?', (self.contract_id,)) or (0, 0, 0)
            text, color = (f'<b>Смета «{s["title"]}»</b><br>Стоимость материалов по клиенту: <b>{md_money(row[0])}</b> · стоимость работ по клиенту: <b>{md_money(row[1])}</b> · '
                           f'итого по смете: <b>{md_money(row[2])}</b>'), '#16A34A'
        self.lbl_estimate.setText(text)
        self.lbl_estimate.setStyleSheet(f'color: {color};')
        has = bool(self.estimate_id and s)
        self.btn_create_est.setVisible(not has)
        self.btn_link_est.setVisible(not has)
        self.btn_pull.setVisible(has)
        self.btn_history.setVisible(has)
        self.btn_open_est.setVisible(has)
        self.btn_estimate_doc.setEnabled(has)

    def create_linked_estimate(self):
        if not self.ensure_saved():
            return
        if self.estimate_id:
            return self.open_estimate_editor()
        with db.transaction():
            cid = self.client_form.client_id
            client = self.client_form.values()
            self.estimate_id = db.execute('INSERT INTO estimates(title,date,total,paid,client_id,client_name,client_phone) VALUES(?,?,0,0,?,?,?)',
                                          (self.inp_object.text() or 'Смета к договору ' + self.inp_number.text(), QDate.currentDate().toString('yyyy-MM-dd'), cid,
                                           client['name'], client['phone'])).lastrowid
            md.link_estimate(db, self.contract_id, self.estimate_id)
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
        from PyQt6.QtWidgets import QLineEdit as _Edit
        search = _Edit()
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
            rows = db.fetchall("""SELECT id,title,client_name,total FROM estimates WHERE id NOT IN (SELECT estimate_id FROM contracts WHERE estimate_id IS NOT NULL AND id<>?)
                AND LOWER(coalesce(title,'')||' '||coalesce(client_name,'')) LIKE ? ORDER BY id DESC LIMIT 300""", (self.contract_id, q))
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, v in enumerate((row[1], row[2], md_money(row[3]))):
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
                md.link_estimate(db, self.contract_id, table.item(r, 0).data(Qt.ItemDataRole.UserRole))
            except Exception as e:
                QMessageBox.warning(d, 'Смета', str(e))
                return
            d.accept()
        pick.clicked.connect(choose)
        table.cellDoubleClicked.connect(lambda *_: choose())
        if d.exec():
            self.estimate_id = db.fetchone('SELECT estimate_id FROM contracts WHERE id=?', (self.contract_id,))[0]
            self.refresh_estimate_ui()

    def pull_amount_from_estimate(self, silent=False):
        """«Получить стоимость из сметы»: материалы и работы фиксируются, итог становится стоимостью работ договора."""
        if not self.estimate_id:
            return
        if not self.contract_id:
            s = md.estimate_summary(db, self.estimate_id)
            if s:
                self.inp_amount.setValue(s['total'])
            return
        if not self.ensure_saved():
            return
        try:
            s = md.sync_estimate(db, self.contract_id)
        except ValueError as e:
            QMessageBox.warning(self, 'Смета', str(e))
            return
        self.inp_amount.setValue(s['total'])
        self.refresh_estimate_ui()
        self.refresh_docs()
        if not silent:
            self.status.setText(f'Получено из сметы: материалы {md_money(s["materials"])}, работы {md_money(s["works"])}')

    def show_estimate_history(self):
        if not self.estimate_id:
            return
        d = QDialog(self)
        d.setWindowTitle('История изменений сметы')
        d.resize(880, 520)
        layout = QVBoxLayout(d)
        rows = md.estimate_history(db, self.estimate_id)
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
            if self.contract_id and md.refresh_estimate_pipelines(db, self.contract_id):
                self.pipes_tab.load(self.contract_id)

    def export_estimate(self):
        if self.estimate_id:
            from .workspace_view import ExportDialog
            ExportDialog('estimates', self.estimate_id, self).exec()

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
        folder = md.contract_folder(db, self.contract_id) if self.contract_id else ''
        self.lbl_folder.setText(f'Папка договора: {folder}' if folder else 'Папка договора не привязана — программа предложит создать или выбрать её при формировании документов и кнопкой «Папка договора».')

    def make_document(self, kind):
        if not self.ensure_saved():
            return
        from . import preflight, preflight_ui
        if not preflight_ui.confirm(self, f'«{dd.DOC_KINDS[kind][0]}»', preflight.check_montage(db, self.contract_id, kind)):
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

    # --- оплаты, график, расход ---
    def open_payments(self):
        if not self.ensure_saved():
            return
        from .payments_view import PaymentsDialog
        PaymentsDialog('contracts', self.contract_id, self).exec()
        self.refresh_docs()

    def load_data_after_payments(self):
        self.refresh_docs()

    def open_schedule(self):
        if not self.ensure_saved():
            return
        from .welding_view import ScheduleView
        d = QDialog(self)
        d.setWindowTitle('График работ по договору')
        d.resize(1250, 650)
        QVBoxLayout(d).addWidget(ScheduleView(('contracts', self.contract_id)))
        d.exec()

    def open_work_entry(self):
        """«Внести в график работ»: объект, трубопроводы и стыки подставляются из карточки."""
        if not self.ensure_saved():
            return
        lines = [(j['name'], j['count']) for j in md.joints(db, self.contract_id)]
        if not lines:
            QMessageBox.information(self, 'График работ', 'Добавьте трубопроводы и стыки на вкладке «Трубопроводы и стыки».')
            return
        d = WorkEntryDialog(self.contract_id, self.inp_object.text().strip() or self.inp_number.text(), lines, self)
        if d.exec():
            self.status.setText('Запись добавлена в график работ' + (', расход материалов сохранён' if d.consumption else ''))

    def open_consumption(self):
        if self.ensure_saved():
            ConsumptionDialog(self.contract_id, self).exec()

    # --- совместимость со старым кодом ---
    def export_pdf(self):
        if self.ensure_saved():
            from .workspace_view import ExportDialog
            ExportDialog('contracts', self.contract_id, self).exec()

    def add_equipment_row(self, name='', cert='', note='', linked_cert_id=None):
        self.equipment_tab.add_row(dict(kind=name, model='', serial='', note=note, file_path=''))


def md_money(value):
    return f'{float(value or 0):,.2f}'.replace(',', ' ').replace('.', ',') + ' BYN'
