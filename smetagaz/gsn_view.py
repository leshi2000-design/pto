"""GSN contracts and executive document workspace."""
from PyQt6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QLabel,QTabWidget,QScrollArea,QMessageBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QDoubleSpinBox
from PyQt6.QtCore import Qt,QDate
from .database import db
from .domain_widgets import ClientForm,OptionalDate
from .gsv_domain import get_client,save_client
from .executive_workspace import ExecutiveWorkspace
from .pagination import RegistryPager

class GsnContractDialog(QDialog):
    def __init__(self,rid=None,parent=None):
        super().__init__(parent);self.rid=rid;self.setWindowTitle('Договор · монтаж ГСН');self.resize(1200,850);layout=QVBoxLayout(self);tabs=QTabWidget();layout.addWidget(tabs,1)
        page=QWidget();body=QVBoxLayout(page);form=QFormLayout();body.addLayout(form);self.number=QLineEdit();self.date=OptionalDate();self.date.setDate(QDate.currentDate());self.title=QLineEdit();self.address=QLineEdit();self.notes=QLineEdit();self.amount=QDoubleSpinBox();self.amount.setRange(0,1e9);self.amount.setDecimals(2);form.addRow("Сумма договора",self.amount)
        for label,field in [('Номер договора',self.number),('Дата договора',self.date),('Название объекта строительства',self.title),('Адрес объекта',self.address),('Примечание',self.notes)]:form.addRow(label,field)
        self.client_form=ClientForm();body.addWidget(self.client_form);body.addStretch();scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);tabs.addTab(scroll,'Договор и клиент');self.page=page
        self.executive=ExecutiveWorkspace('gsn_projects',self.save_data,self);tabs.addTab(self.executive,'Исполнительная документация');bar=QHBoxLayout();self.status=QLabel();bar.addWidget(self.status,1);self.edit_button=QPushButton('Изменить');self.edit_button.clicked.connect(self.toggle_edit);bar.addWidget(self.edit_button);folder=QPushButton('Папка договора');folder.clicked.connect(self.open_folder);bar.addWidget(folder);self.save_button=QPushButton('Сохранить');self.save_button.clicked.connect(self.save_clicked);bar.addWidget(self.save_button);payments=QPushButton('Оплаты');payments.clicked.connect(self.open_payments);bar.addWidget(payments);report=QPushButton('Договор по шаблону');report.clicked.connect(self.export_template);bar.addWidget(report);close=QPushButton('Закрыть');close.clicked.connect(self.close);bar.addWidget(close);layout.addLayout(bar)
        if rid:
            row=db.fetchone('SELECT contract_number,contract_date,title,address,notes,client_id,client_name,phone,passport FROM gsn_projects WHERE id=?',(rid,))
            if not row:raise ValueError('Договор ГСН не найден')
            self.number.setText(row[0] or '');self.date.set_value(row[1]);self.title.setText(row[2]);self.address.setText(row[3] or '');self.notes.setText(row[4] or '');self.client_form.fill(get_client(db,row[5]) or dict(name=row[6],phone=row[7],passport=row[8]),row[5])
        if rid:self.amount.setValue(db.fetchone("SELECT contract_amount FROM gsn_projects WHERE id=?",(rid,))[0] or 0)
        self.executive.load(rid)
        self.set_locked(bool(rid))
    def set_locked(self,locked):
        """Сохранённый договор открывается только для просмотра; поля разблокирует кнопка «Изменить»."""
        self.locked=locked;self.page.setEnabled(not locked);self.edit_button.setVisible(bool(self.rid));self.edit_button.setText('Изменить' if locked else 'Заблокировать')
    def toggle_edit(self):
        if not self.locked and not self.save_data():return
        self.set_locked(not self.locked)
    def save_clicked(self):
        if not self.rid and not self.client_form.confirm_duplicate():return
        if self.save_data() and self.rid:self.set_locked(True)
    def open_folder(self):
        """Папка договора создаётся только по кнопке: привязать существующую или создать новую «номер - адрес (ФИО)»."""
        if not self.rid and not self.save_data():return
        from .platform_utils import open_local
        from .folder_ui import choose_folder
        from .gsv_project_domain import folder_name
        import os
        current=self.executive.folder.text().strip()
        if not current or not os.path.isdir(current):
            path,create=choose_folder(self,'gsn_projects',folder_name(self.number.text().strip() or f'договор_{self.rid}',self.address.text() or self.title.text(),self.client_form.name.text()),current)
            if not path:return
            if create:os.makedirs(path,exist_ok=True)
            self.executive.folder.setText(path);self.save_data();current=path
        open_local(current)
    def export_template(self):
        if self.save_data():
            from .report_dialog import ReportTemplateDialog
            ReportTemplateDialog('gsn_projects',self.rid,self).exec()
    def open_payments(self):
        if self.save_data():
            from .payments_view import PaymentsDialog
            PaymentsDialog('gsn_projects',self.rid,self).exec()
    def save_data(self):
        try:
            if not self.title.text().strip():raise ValueError('Укажите название объекта строительства')
            client=self.client_form.values()
            with db.transaction():
                cid=save_client(db,client,self.client_form.client_id);values=(self.number.text().strip(),self.date.value(),self.title.text().strip(),self.address.text().strip(),self.notes.text(),cid,client['name'],client['phone'],client['passport']);rid=self.rid
                if rid:db.execute('UPDATE gsn_projects SET contract_number=?,contract_date=?,title=?,address=?,notes=?,client_id=?,client_name=?,phone=?,passport=? WHERE id=?',(*values,rid))
                else:rid=db.execute('INSERT INTO gsn_projects(contract_number,contract_date,title,address,notes,client_id,client_name,phone,passport) VALUES(?,?,?,?,?,?,?,?,?)',values).lastrowid
                self.executive.save(rid)
                db.execute("UPDATE gsn_projects SET contract_amount=? WHERE id=?",(self.amount.value(),rid))
            self.rid=rid;self.client_form.client_id=cid;self.executive.bind(rid);self.status.setText(f'Сохранено · договор {rid} · клиент {cid}');return True
        except Exception as e:QMessageBox.warning(self,'Договор не сохранён',str(e));return False

class GsnProjectsView(QWidget):
    def __init__(self):
        super().__init__();layout=QVBoxLayout(self);self.pager=RegistryPager(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Договор, объект, клиент, телефон, адрес');bar.addWidget(self.search,1)
        for label,fn in [('Создать договор',self.create),('Открыть карточку',self.edit),('Оплаты',self.open_payments),('Теги для шаблонов',self.show_tag_reference)]:b=QPushButton(label);b.clicked.connect(fn);bar.addWidget(b)
        layout.addLayout(bar);self.table=QTableWidget(0,6);self.table.setHorizontalHeaderLabels(['Договор','Дата','Объект строительства','Клиент','Телефон','Адрес объекта']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setColumnWidth(2,280);self.table.setColumnWidth(3,240);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1);self.table.cellDoubleClicked.connect(self.edit);self.search.textChanged.connect(self.load_data);self.load_data()
    def load_data(self,*_):
        q='%'+self.search.text().casefold()+'%';rows=self.pager.fetch("SELECT id,contract_number,contract_date,title,client_name,phone,address FROM gsn_projects WHERE LOWER(coalesce(contract_number,'')||' '||title||' '||coalesce(client_name,'')||' '||coalesce(phone,'')||' '||coalesce(address,'')) LIKE ? ORDER BY id DESC",(q,));self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row[1:]):item=QTableWidgetItem(str(value or ''));item.setData(Qt.ItemDataRole.UserRole,row[0]);self.table.setItem(r,c,item)
    def open_payments(self):
        r=self.table.currentRow()
        if r>=0:
            from .payments_view import PaymentsDialog
            PaymentsDialog('gsn_projects',self.table.item(r,0).data(Qt.ItemDataRole.UserRole),self).exec();self.load_data()
    def show_tag_reference(self):
        from .executive_workspace import TagReferenceDialog
        TagReferenceDialog('gsn_projects',self).exec()
    def create(self):GsnContractDialog(parent=self).exec();self.load_data()
    def edit(self,*_):
        r=self.table.currentRow()
        if r>=0:GsnContractDialog(self.table.item(r,0).data(Qt.ItemDataRole.UserRole),self).exec();self.load_data()
