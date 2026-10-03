"""GSV installation contract: client-first entry and linked technical dossier."""
from PyQt6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGridLayout,QGroupBox,QLineEdit,QDoubleSpinBox,QDateEdit,QLabel,QPushButton,QTabWidget,QScrollArea,QMessageBox)
from PyQt6.QtCore import QDate
from .database import db
from .domain_widgets import ClientForm,EquipmentPanel,PipelinesPanel,OptionalDate
from .gsv_domain import get_client,save_client
from .welding_documents import ObjectDossierWidget

class ContractCardDialog(QDialog):
    def __init__(self,estimate_id=None,title='',parent=None,contract_id=None):
        super().__init__(parent);self.estimate_id=estimate_id;self.contract_id=contract_id;self.title=title
        self.setWindowTitle('Договор · монтаж ГСВ');self.resize(1050,780)
        layout=QVBoxLayout(self);self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        page=QWidget();body=QVBoxLayout(page);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.tabs.addTab(scroll,'Договор и клиент')
        group=QGroupBox('Договор / объект');form=QFormLayout(group);self.inp_number=QLineEdit();self.inp_object=QLineEdit(title)
        self.date_contract=QDateEdit(QDate.currentDate());self.date_contract.setCalendarPopup(True);self.date_contract.setDisplayFormat("dd.MM.yyyy")
        for label,field in [('Номер договора',self.inp_number),('Дата договора',self.date_contract),('Объект / адрес работ',self.inp_object)]:form.addRow(label,field)
        body.addWidget(group);self.client_form=ClientForm();body.addWidget(self.client_form)
        # Compatibility aliases used by estimate workflows.
        self.inp_client=self.client_form.name;self.inp_phone=self.client_form.phone;self.inp_address=self.client_form.address;self.inp_passport_num=self.client_form.passport;self.inp_passport_issuer=self.client_form.passport_issuer;self.date_passport=self.client_form.passport_date
        terms=QGroupBox('Сроки и стоимость');grid=QGridLayout(terms)
        self.date_start=QDateEdit(QDate.currentDate());self.date_end=QDateEdit(QDate.currentDate());self.date_act=OptionalDate()
        for date_field in [self.date_start,self.date_end,self.date_act]:date_field.setCalendarPopup(True)
        self.inp_amount=QDoubleSpinBox();self.inp_amount.setRange(0,1e9);self.inp_amount.setDecimals(2)
        for r,(label,field) in enumerate([('Начало работ',self.date_start),('Окончание работ',self.date_end),('Дата акта',self.date_act),('Сумма',self.inp_amount)]):grid.addWidget(QLabel(label),r//2,(r%2)*2);grid.addWidget(field,r//2,(r%2)*2+1)
        body.addWidget(terms);self.lock_widgets=[group,self.client_form,terms]
        box=QGroupBox('Связанная смета');bar=QHBoxLayout(box);self.lbl_est_status=QLabel();bar.addWidget(self.lbl_est_status,1)
        self.btn_open_est=QPushButton('Открыть смету');self.btn_open_est.clicked.connect(self.open_estimate_editor);bar.addWidget(self.btn_open_est)
        self.btn_create_est=QPushButton('Создать смету');self.btn_create_est.clicked.connect(self.create_linked_estimate);bar.addWidget(self.btn_create_est)
        amount=QPushButton('Сумма из сметы');amount.clicked.connect(self.pull_amount_from_estimate);bar.addWidget(amount);body.addWidget(box);body.addStretch()
        self.equipment=EquipmentPanel('contracts');self.table_equip=self.equipment.table;self.tabs.addTab(self.equipment,'Оборудование')
        self.pipelines=PipelinesPanel('contracts');self.tabs.addTab(self.pipelines,'Трубопроводы')
        self.dossier=ObjectDossierWidget('contracts',contract_id);self.tabs.addTab(self.dossier,'Исполнительная документация')
        from .executive_workspace import ExecutiveWorkspace
        self.executive=ExecutiveWorkspace('contracts',self.save_data,self);self.tabs.addTab(self.executive,'Шаблоны ГСВ и материалы')
        self.tabs.currentChanged.connect(lambda *_:self.dossier.load_data())
        bottom=QHBoxLayout();self.status=QLabel('');bottom.addWidget(self.status,1)
        payments=QPushButton('Оплаты');payments.clicked.connect(self.open_payments);bottom.addWidget(payments)
        export=QPushButton('Word / Excel / PDF…');export.clicked.connect(self.export_pdf);bottom.addWidget(export)
        schedule=QPushButton('График работ…');schedule.clicked.connect(self.open_schedule);bottom.addWidget(schedule)
        self.edit_button=QPushButton('Изменить');self.edit_button.clicked.connect(self.toggle_edit);bottom.addWidget(self.edit_button)
        folder=QPushButton('Папка договора');folder.clicked.connect(self.open_folder);bottom.addWidget(folder)
        self.save_button=QPushButton('Сохранить');self.save_button.setDefault(True);self.save_button.clicked.connect(self.save_clicked);bottom.addWidget(self.save_button)
        close=QPushButton('Закрыть');close.clicked.connect(self.accept);bottom.addWidget(close);layout.addLayout(bottom)
        self.load_data();self.set_locked(bool(self.contract_id))
    def set_locked(self,locked):
        """Сохранённый договор открывается только для просмотра; поля разблокирует кнопка «Изменить»."""
        self.locked=locked
        for w in self.lock_widgets:w.setEnabled(not locked)
        self.edit_button.setVisible(bool(self.contract_id));self.edit_button.setText('Изменить' if locked else 'Заблокировать')
    def toggle_edit(self):
        if not self.locked and not self.save_data():return
        self.set_locked(not self.locked)
    def save_clicked(self):
        if not self.contract_id and not self.client_form.confirm_duplicate():return
        if self.save_data() and self.contract_id:self.set_locked(True)
    def open_folder(self):
        if not self.contract_id and not self.save_data():return
        from .platform_utils import open_local
        if self.executive.folder.text():open_local(self.executive.folder.text())
    def load_data(self):
        if not self.contract_id and self.estimate_id:
            found=db.fetchone('SELECT id FROM contracts WHERE estimate_id=?',(self.estimate_id,))
            if found:self.contract_id=found[0]
        if self.contract_id:
            fields=['estimate_id','contract_number','contract_date','object_name','client_address','passport_series_number','passport_issued_by','passport_issue_date','work_start_date','work_end_date','acceptance_act_date','contract_amount','client_id','client_name','client_phone']
            row=db.fetchone('SELECT '+','.join(fields)+' FROM contracts WHERE id=?',(self.contract_id,));data=dict(zip(fields,row))
            self.estimate_id=data['estimate_id'];self.inp_number.setText(data['contract_number'] or '');self.inp_object.setText(data['object_name'] or '')
            self.inp_amount.setValue(data['contract_amount'] or 0)
            for key,field in [('contract_date',self.date_contract),('work_start_date',self.date_start),('work_end_date',self.date_end),('acceptance_act_date',self.date_act)]:
                day=QDate.fromString(data[key] or '','yyyy-MM-dd')
                if day.isValid():field.setDate(day)
            client=get_client(db,data['client_id']) or dict(name=data['client_name'],phone=data['client_phone'],address=data['client_address'],passport=data['passport_series_number'],passport_issuer=data['passport_issued_by'],passport_date=data['passport_issue_date'])
            self.client_form.fill(client,data['client_id'])
        elif self.estimate_id:
            row=db.fetchone('SELECT client_id,client_name,client_phone FROM estimates WHERE id=?',(self.estimate_id,))
            if row:self.client_form.fill(get_client(db,row[0]) or dict(name=row[1],phone=row[2]),row[0])
            self.pull_amount_from_estimate()
        self.equipment.load(self.contract_id);self.pipelines.load(self.contract_id);self.dossier.bind(self.contract_id);self.executive.load(self.contract_id);self.refresh_estimate_ui()
    def open_payments(self):
        if self.save_data():
            from .payments_view import PaymentsDialog
            PaymentsDialog('contracts',self.contract_id,self).exec();self.load_data()
    def save_data(self):
        try:
            values=self.client_form.values()
            with db.transaction():
                cid=save_client(db,values,self.client_form.client_id)
                fields=['estimate_id','contract_number','contract_date','object_name','client_address','passport_series_number','passport_issued_by','passport_issue_date','work_start_date','work_end_date','acceptance_act_date','contract_amount','client_id','client_name','client_phone']
                data=[self.estimate_id,self.inp_number.text().strip(),self.date_contract.date().toString('yyyy-MM-dd'),self.inp_object.text().strip(),values['address'],values['passport'],values['passport_issuer'],values['passport_date'],self.date_start.date().toString('yyyy-MM-dd'),self.date_end.date().toString('yyyy-MM-dd'),self.date_act.value(),self.inp_amount.value(),cid,values['name'],values['phone']]
                rid=self.contract_id
                if rid:db.execute('UPDATE contracts SET '+','.join(f'{f}=?' for f in fields)+' WHERE id=?',(*data,rid))
                else:rid=db.execute('INSERT INTO contracts('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',data).lastrowid
                self.equipment.save(rid);self.pipelines.save(rid)
                if not self.executive.folder.text().strip():
                    from .gsv_project_domain import ensure_folder
                    self.executive.folder.setText(ensure_folder('contracts',self.inp_number.text().strip() or f'договор_{rid}',values['name']))
                self.executive.save(rid)
                if self.estimate_id:
                    from .data_services import link_client
                    link_client(db,'estimates',self.estimate_id,cid)
            self.contract_id=rid;self.executive.bind(rid);self.client_form.client_id=cid;self.client_form.info.setText(f'Клиент №{cid}. Данные сохранены.');self.dossier.bind(rid);self.status.setText(f'Сохранено · договор №{rid} · клиент №{cid}');self.refresh_estimate_ui()
            return True
        except Exception as e:QMessageBox.warning(self,'Договор не сохранён',str(e));return False
    def refresh_estimate_ui(self):
        row=db.fetchone('SELECT title FROM estimates WHERE id=?',(self.estimate_id,)) if self.estimate_id else None
        self.lbl_est_status.setText('Смета: '+str(row[0] or '') if row else 'Смета не привязана');self.btn_open_est.setVisible(bool(row));self.btn_create_est.setVisible(not row)
    def create_linked_estimate(self):
        if not self.save_data():return
        if self.estimate_id:return self.open_estimate_editor()
        with db.transaction():
            cid=self.client_form.client_id;client=self.client_form.values()
            self.estimate_id=db.execute('INSERT INTO estimates(title,date,total,paid,client_id,client_name,client_phone) VALUES(?,?,0,0,?,?,?)',(self.inp_object.text() or 'Смета к договору '+self.inp_number.text(),QDate.currentDate().toString('yyyy-MM-dd'),cid,client['name'],client['phone'])).lastrowid
            from .payments_domain import link
            link(db,'contracts',self.contract_id,self.estimate_id)
        self.refresh_estimate_ui();self.open_estimate_editor()
    def open_estimate_editor(self):
        if not self.estimate_id:return
        from .estimate_editor import EstimateEditorDialog
        row=db.fetchone('SELECT title FROM estimates WHERE id=?',(self.estimate_id,))
        if row:EstimateEditorDialog(self.estimate_id,row[0] or '',self).exec()
    def pull_amount_from_estimate(self):
        row=db.fetchone('SELECT total FROM estimates WHERE id=?',(self.estimate_id,)) if self.estimate_id else None
        if row:self.inp_amount.setValue(row[0] or 0)
    def export_pdf(self):
        if not self.save_data():return
        from .workspace_view import ExportDialog
        ExportDialog('contracts',self.contract_id,self).exec()
    def open_schedule(self):
        if not self.save_data():return
        from .welding_view import ScheduleView
        d=QDialog(self);d.setWindowTitle('График работ по договору');d.resize(1250,650);QVBoxLayout(d).addWidget(ScheduleView(('contracts',self.contract_id)));d.exec()
    def add_equipment_row(self,name='',cert='',note='',linked_cert_id=None):
        self.equipment.add_row(dict(equipment_name=name,certificate_number=cert,note=note,linked_cert_id=linked_cert_id))
