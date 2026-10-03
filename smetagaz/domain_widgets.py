"""Shared editors for clients, object references and GSV specifications."""
from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QLineEdit,QTextEdit,QDateEdit,QLabel,QPushButton,QGroupBox,QComboBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QDoubleSpinBox,QFileDialog)
from PyQt6.QtCore import QDate,Qt,pyqtSignal
from .database import db
from .gsv_domain import EQUIPMENT_KINDS,get_client,owner_label,save_equipment,save_pipelines

class OptionalDate(QDateEdit):
    def __init__(self):
        super().__init__();self.setCalendarPopup(True);self.setDisplayFormat('dd.MM.yyyy');self.setMinimumDate(QDate(1900,1,1));self.setSpecialValueText('Не указана');self.setDate(self.minimumDate())
    def value(self):return '' if self.date()==self.minimumDate() else self.date().toString('yyyy-MM-dd')
    def set_value(self,value):
        d=QDate.fromString(value or '','yyyy-MM-dd');self.setDate(d if d.isValid() else self.minimumDate())

class ClientForm(QGroupBox):
    def __init__(self,parent=None):
        super().__init__('Клиент — введите данные при оформлении договора',parent)
        self.client_id=None;layout=QGridLayout(self)
        self.name=QLineEdit();self.name.setPlaceholderText('ФИО / наименование заказчика *')
        self.phone=QLineEdit();self.address=QLineEdit();self.passport=QTextEdit();self.passport.setMaximumHeight(55)
        self.passport_issuer=QLineEdit();self.passport_date=OptionalDate()
        self.fields={'name':self.name,'phone':self.phone,'address':self.address,'passport':self.passport,'passport_issuer':self.passport_issuer,'passport_date':self.passport_date}
        layout.addWidget(QLabel('ФИО / организация *'),0,0);layout.addWidget(self.name,0,1,1,3)
        layout.addWidget(QLabel('Телефон'),1,0);layout.addWidget(self.phone,1,1)
        layout.addWidget(QLabel('Адрес клиента'),1,2);layout.addWidget(self.address,1,3)
        layout.addWidget(QLabel('Паспорт: серия, номер'),2,0);layout.addWidget(self.passport,2,1,1,3)
        layout.addWidget(QLabel('Кем выдан'),3,0);layout.addWidget(self.passport_issuer,3,1)
        layout.addWidget(QLabel('Дата выдачи'),3,2);layout.addWidget(self.passport_date,3,3)
        bar=QHBoxLayout();self.info=QLabel('Запись в «Клиенты» появится после сохранения договора.');self.info.setWordWrap(True);bar.addWidget(self.info,1)
        self.select_button=QPushButton('Заполнить из «Клиенты»…');self.select_button.clicked.connect(self.choose);bar.addWidget(self.select_button)
        clear=QPushButton('Новый клиент');clear.clicked.connect(lambda:self.fill({},None));bar.addWidget(clear);layout.addLayout(bar,4,0,1,4)
    def values(self):
        return dict(name=self.name.text(),phone=self.phone.text(),address=self.address.text(),passport=self.passport.toPlainText(),passport_issuer=self.passport_issuer.text(),passport_date=self.passport_date.value())
    def fill(self,values,cid=None):
        self.client_id=cid
        for key,field in self.fields.items():
            value=values.get(key) or ''
            if isinstance(field,OptionalDate):field.set_value(value)
            elif isinstance(field,QTextEdit):field.setPlainText(value)
            else:field.setText(value)
        self.info.setText(f'Клиент №{cid}. Изменения будут сохранены вместе с договором.' if cid else 'Новый клиент будет создан вместе с договором.')
    def choose(self):
        from .workspace_view import ClientPicker
        d=ClientPicker(self)
        if d.exec():self.fill(get_client(db,d.client_id) or {},d.client_id)

class ObjectPicker(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Выберите договор ГСВ / проект');self.resize(850,500);self.reference=None;self.offset=0
        layout=QVBoxLayout(self);self.search=QLineEdit();self.search.setPlaceholderText('Номер, объект, клиент…');layout.addWidget(self.search)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Раздел','Номер','Объект / клиент']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        bar=QHBoxLayout();bar.addStretch();prev=QPushButton('Назад');self.next=QPushButton('Далее');bar.addWidget(prev);bar.addWidget(self.next);choose=QPushButton('Выбрать');bar.addWidget(choose);layout.addLayout(bar)
        prev.clicked.connect(lambda:self.page(-1));self.next.clicked.connect(lambda:self.page(1));choose.clicked.connect(self.choose);self.table.cellDoubleClicked.connect(lambda *_:self.choose());self.search.textChanged.connect(self.reset);self.load_data()
    def reset(self,*_):self.offset=0;self.load_data()
    def page(self,delta):self.offset=max(0,self.offset+delta*100);self.load_data()
    def load_data(self):
        q='%'+self.search.text().strip().casefold()+'%'
        rows=db.fetchall('''SELECT kind,id,num,label FROM (
          SELECT 'contracts' kind,id,contract_number num,coalesce(object_name,'')||' · '||coalesce(client_name,'') label FROM contracts
          UNION ALL SELECT 'gsv_projects',id,pd_number,coalesce(object_name,'')||' · '||coalesce(client_name,'') FROM gsv_projects
        ) WHERE LOWER(num) LIKE ? OR LOWER(label) LIKE ? ORDER BY id DESC,kind LIMIT 101 OFFSET ?''',(q,q,self.offset))
        self.next.setEnabled(len(rows)>100);self.table.setRowCount(min(len(rows),100))
        for r,(kind,rid,num,label) in enumerate(rows[:100]):
            for c,text in enumerate(['Договор ГСВ' if kind=='contracts' else 'Проектирование',num,label]):
                item=QTableWidgetItem(str(text or ''));item.setData(Qt.ItemDataRole.UserRole,(kind,rid));self.table.setItem(r,c,item)
    def choose(self):
        r=self.table.currentRow()
        if r>=0:self.reference=self.table.item(r,0).data(Qt.ItemDataRole.UserRole);self.accept()

class ObjectField(QWidget):
    changed=pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent);self.reference=(None,None);bar=QHBoxLayout(self);bar.setContentsMargins(0,0,0,0)
        self.label=QLabel('Пользовательская работа');self.label.setWordWrap(True);bar.addWidget(self.label,1)
        btn=QPushButton('Выбрать объект…');btn.clicked.connect(self.choose);bar.addWidget(btn)
        clear=QPushButton('Без договора');clear.clicked.connect(lambda:self.set_reference(None,None));bar.addWidget(clear)
    def set_reference(self,owner,rid):self.reference=(owner,rid);self.label.setText(owner_label(db,owner,rid));self.changed.emit()
    def choose(self):
        d=ObjectPicker(self)
        if d.exec():self.set_reference(*d.reference)

class EquipmentPanel(QWidget):
    def __init__(self,owner,parent=None):
        super().__init__(parent);self.owner=owner;layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.addWidget(QLabel('Выберите вид оборудования, затем укажите тип / модель и номер сертификата или паспорта.'))
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Оборудование','Тип / модель','№ сертификата / паспорта','Примечание'])
        self.table.horizontalHeader().setStretchLastSection(True);self.table.setColumnWidth(0,160);self.table.setColumnWidth(1,230);self.table.setColumnWidth(2,210);layout.addWidget(self.table,1)
        bar=QHBoxLayout();add=QPushButton('Добавить оборудование');add.clicked.connect(lambda:self.add_row());delete=QPushButton('Убрать строку');delete.clicked.connect(lambda:self.table.removeRow(self.table.currentRow()) if self.table.currentRow()>=0 else None);bar.addWidget(add);bar.addWidget(delete);bar.addStretch();layout.addLayout(bar)
        bar=QHBoxLayout();attach=QPushButton('Привязать файл сертификата / паспорта');attach.clicked.connect(self.attach_certificate_file);bar.addWidget(attach);pick=QPushButton('Из справочника сертификатов');pick.clicked.connect(self.pick_certificate);bar.addWidget(pick);layout.addLayout(bar)
    def attach_certificate_file(self):
        r=self.table.currentRow()
        if r<0:return
        file,_=QFileDialog.getOpenFileName(self,'Сертификат / паспорт оборудования')
        if not file:return
        from pathlib import Path
        cid=db.execute('INSERT INTO certificates(name,cert_number,file_path) VALUES(?,?,?)',(Path(file).stem,self.table.item(r,2).text(),file)).lastrowid
        self.table.item(r,1).setData(Qt.ItemDataRole.UserRole,cid);self.table.item(r,1).setToolTip(file)
    def pick_certificate(self):
        r=self.table.currentRow()
        if r<0:return
        from .gsv_catalog import CertificatePicker
        d=CertificatePicker(self)
        if d.exec():
            self.table.item(r,1).setData(Qt.ItemDataRole.UserRole,d.cert_id)
            row=db.fetchone('SELECT cert_number,file_path FROM certificates WHERE id=?',(d.cert_id,));self.table.item(r,2).setText(row[0] or '');self.table.item(r,1).setToolTip(row[1] or '')
    def add_row(self,row=None):
        row=row or {};r=self.table.rowCount();self.table.insertRow(r);combo=QComboBox();combo.addItem('Выберите…','')
        for kind in EQUIPMENT_KINDS:combo.addItem(kind,kind)
        combo.setCurrentIndex(max(0,combo.findData(row.get('equipment_kind',''))));combo.setProperty('legacy',bool(row.get('equipment_name') and not row.get('equipment_kind')));self.table.setCellWidget(r,0,combo)
        # Unclassified legacy equipment remains as a manually entered model, never discarded.
        model=row.get('equipment_model') or (row.get('equipment_name','') if not row.get('equipment_kind') else '')
        for c,text in [(1,model),(2,row.get('certificate_number','')),(3,row.get('note',''))]:self.table.setItem(r,c,QTableWidgetItem(text or ''))
        self.table.item(r,1).setData(Qt.ItemDataRole.UserRole,row.get('linked_cert_id'))
    def load(self,rid):
        self.table.setRowCount(0)
        if not rid:return
        table,key={'contracts':('contract_equipment','contract_id'),'gsv_projects':('gsv_equipment','project_id'),'gsn_projects':('gsn_equipment','project_id')}[self.owner]
        fields=('equipment_name','equipment_kind','equipment_model','certificate_number','note','linked_cert_id')
        for row in db.fetchall(f'SELECT {",".join(fields)} FROM {table} WHERE {key}=? ORDER BY id',(rid,)):self.add_row(dict(zip(fields,row)))
    def rows(self):
        rows=[]
        for r in range(self.table.rowCount()):
            values=[self.table.item(r,c).text().strip() if self.table.item(r,c) else '' for c in (1,2,3)]
            kind=self.table.cellWidget(r,0).currentData()
            if not kind and not any(values):continue
            if not kind and not self.table.cellWidget(r,0).property('legacy'):raise ValueError('Выберите вид оборудования в строке '+str(r+1))
            rows.append(dict(equipment_kind=kind,equipment_model=values[0],certificate_number=values[1],note=values[2],linked_cert_id=self.table.item(r,1).data(Qt.ItemDataRole.UserRole)))
        return rows
    def save(self,rid):save_equipment(db,self.owner,rid,self.rows())

class PipelinesPanel(QWidget):
    def __init__(self,owner,parent=None):
        super().__init__(parent);self.owner=owner;layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.addWidget(QLabel('Сертификаты выбранных труб автоматически входят в исполнительную документацию объекта.'))
        self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Трубопровод из справочника','Количество','Сертификат','Примечание']);self.table.setColumnWidth(0,280);self.table.setColumnWidth(2,220);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        bar=QHBoxLayout();add=QPushButton('Добавить трубопровод');add.clicked.connect(lambda:self.add_row());delete=QPushButton('Убрать строку');delete.clicked.connect(lambda:self.table.removeRow(self.table.currentRow()) if self.table.currentRow()>=0 else None);catalog=QPushButton('Открыть справочник ГСВ…');catalog.clicked.connect(self.open_catalog)
        for b in [add,delete,catalog]:bar.addWidget(b)
        bar.addStretch();layout.addLayout(bar)
    def add_row(self,pipeline_id=None,quantity=0,note=''):
        r=self.table.rowCount();self.table.insertRow(r);combo=QComboBox();combo.addItem('Выберите трубопровод…',None)
        for pid,name,unit,active in db.fetchall('SELECT id,name,unit,active FROM gsv_pipelines WHERE active=1 OR id=? ORDER BY name',(pipeline_id,)):combo.addItem(f'{name} ({unit})'+(' · архив' if not active else ''),pid)
        combo.setCurrentIndex(max(0,combo.findData(pipeline_id)));self.table.setCellWidget(r,0,combo)
        qty=QDoubleSpinBox();qty.setRange(0,1e9);qty.setDecimals(3);qty.setValue(quantity or 0);self.table.setCellWidget(r,1,qty)
        cert=QTableWidgetItem();cert.setFlags(cert.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(r,2,cert);self.table.setItem(r,3,QTableWidgetItem(note or ''))
        combo.currentIndexChanged.connect(lambda *_:self.refresh_certificate(combo,cert));self.refresh_certificate(combo,cert)
    def refresh_certificate(self,combo,item):
        row=db.fetchone('SELECT c.cert_number,c.name FROM gsv_pipelines p LEFT JOIN certificates c ON c.id=p.certificate_id WHERE p.id=?',(combo.currentData(),))
        item.setText(('№ '+(row[0] or '')+' · '+(row[1] or 'Без файла')) if row else 'Не выбран')
    def rows(self):
        result=[]
        for r in range(self.table.rowCount()):
            pid=self.table.cellWidget(r,0).currentData()
            if pid:result.append((pid,self.table.cellWidget(r,1).value(),self.table.item(r,3).text()))
        return result
    def load(self,rid):
        self.table.setRowCount(0)
        if rid:
            for row in db.fetchall('SELECT pipeline_id,quantity,note FROM object_pipelines WHERE owner_type=? AND owner_id=? ORDER BY id',(self.owner,rid)):self.add_row(*row)
    def save(self,rid):save_pipelines(db,self.owner,rid,self.rows())
    def open_catalog(self):
        from .gsv_catalog import GsvCatalogView
        d=QDialog(self);d.setWindowTitle('Справочники ГСВ');d.resize(950,600);QVBoxLayout(d).addWidget(GsvCatalogView());d.exec()
        rows=self.rows();self.table.setRowCount(0)
        for row in rows:self.add_row(*row)
