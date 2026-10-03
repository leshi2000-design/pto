"""Four welding tabs: dated work grid, personnel, attestations and contracts/acts."""
from datetime import date
from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QAbstractItemView,QDialogButtonBox,QMessageBox,QTabWidget)
from PyQt6.QtCore import Qt,QDate
from PyQt6.QtGui import QColor
from .database import db
from .pagination import RegistryPager
from .domain_widgets import OptionalDate,ObjectField
from .gsv_domain import save_job,set_work_day,owner_label
from .welding_documents import DocumentsView

class WelderDialog(QDialog):
    FIELDS=('name','birth_date','phone','certificate','welding_type','stamp','grade','valid_until','notes')
    def __init__(self,welder_id=None,parent=None):
        super().__init__(parent);self.welder_id=welder_id;self.setWindowTitle('Карточка сварщика');self.resize(1050,700);layout=QVBoxLayout(self);self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        page=QWidget();form=QFormLayout(page);self.inputs={}
        labels=['ФИО *','Дата рождения','Телефон','Аттестация','Вид сварки','Клеймо','Разряд','Аттестация действительна до','Примечания']
        for key,label in zip(self.FIELDS,labels):
            field=OptionalDate() if key in ('birth_date','valid_until') else QLineEdit();self.inputs[key]=field;form.addRow(label,field)
        self.tabs.addTab(page,'Данные сварщика');self.docs=None
        if welder_id:
            row=db.fetchone('SELECT '+','.join(self.FIELDS)+' FROM welders WHERE id=?',(welder_id,))
            for k,v in zip(self.FIELDS,row):
                if isinstance(self.inputs[k],OptionalDate):self.inputs[k].set_value(v)
                else:self.inputs[k].setText(v or '')
            self.show_docs()
        else:self.tabs.addTab(QLabel('Сначала сохраните данные сварщика, затем укажите пути к его документам.'),'Документы')
        bar=QHBoxLayout();self.status=QLabel();bar.addWidget(self.status,1);save=QPushButton('Сохранить');save.clicked.connect(self.save);bar.addWidget(save);close=QPushButton('Закрыть');close.clicked.connect(self.accept);bar.addWidget(close);layout.addLayout(bar)
    def show_docs(self):
        if self.tabs.count()>1:
            old=self.tabs.widget(1);self.tabs.removeTab(1);old.deleteLater()
        self.docs=DocumentsView(welder_id=self.welder_id,category=None)
        # Default new records from this editor belong to the welder section.
        self.tabs.addTab(self.docs,'Документы сварщика')
    def save(self):
        values=[field.value() if isinstance(field,OptionalDate) else field.text().strip() for field in self.inputs.values()]
        if not values[0]:QMessageBox.warning(self,'Сварщик','Введите ФИО');return False
        if values[1] and date.fromisoformat(values[1])>date.today():QMessageBox.warning(self,'Дата','Дата рождения не может быть в будущем');return False
        try:
            if self.welder_id:db.execute('UPDATE welders SET '+','.join(f'{k}=?' for k in self.FIELDS)+' WHERE id=?',(*values,self.welder_id))
            else:self.welder_id=db.execute('INSERT INTO welders('+','.join(self.FIELDS)+') VALUES('+','.join('?' for _ in values)+')',values).lastrowid;self.show_docs()
            self.status.setText('Данные сохранены');return True
        except Exception as e:QMessageBox.warning(self,'Сварщик',str(e));return False

class WeldersRegistry(QWidget):
    def __init__(self):
        super().__init__();self.pager=RegistryPager(self);layout=QVBoxLayout(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('ФИО, телефон, клеймо…');bar.addWidget(self.search,1)
        for label,fn in [('Добавить сварщика',self.create),('Карточка / документы',self.edit),('Удалить запись',self.delete)]:b=QPushButton(label);b.clicked.connect(fn);bar.addWidget(b)
        layout.addLayout(bar);self.table=QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['ФИО','Рождение','Телефон','Аттестация','Вид сварки','Клеймо','Разряд','Действует до']);self.table.setColumnWidth(0,230);self.table.horizontalHeader().setStretchLastSection(True);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);layout.addWidget(self.table,1)
        self.search.textChanged.connect(self.load_data);self.table.cellDoubleClicked.connect(lambda *_:self.edit());self.load_data()
    def selected(self):
        r=self.table.currentRow();return self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else None
    def load_data(self,*_):
        q='%'+self.search.text().casefold()+'%';rows=self.pager.fetch('SELECT id,name,birth_date,phone,certificate,welding_type,stamp,grade,valid_until FROM welders WHERE LOWER(name) LIKE ? OR LOWER(phone) LIKE ? OR LOWER(stamp) LIKE ? ORDER BY id DESC',(q,q,q));self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row[1:]):
                item=QTableWidgetItem(str(value or ''));item.setData(Qt.ItemDataRole.UserRole,row[0])
                if c==7 and value and value<date.today().isoformat():item.setForeground(QColor('#b91c1c'));item.setToolTip('Срок аттестации истёк')
                self.table.setItem(r,c,item)
    def create(self):WelderDialog(parent=self).exec();self.load_data()
    def edit(self):
        if self.selected():WelderDialog(self.selected(),self).exec();self.load_data()
    def delete(self):
        rid=self.selected()
        if rid and QMessageBox.question(self,'Удаление','Удалить карточку сварщика? Работы и документы останутся, но без привязки к этому сварщику.')==QMessageBox.StandardButton.Yes:db.execute('DELETE FROM welders WHERE id=?',(rid,));self.load_data()

class JobDialog(QDialog):
    def __init__(self,job_id=None,reference=None,parent=None):
        super().__init__(parent);self.job_id=job_id;self.setWindowTitle('Запись сварочных работ');self.resize(760,540)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.work_date=OptionalDate();self.work_date.set_value(date.today().isoformat());form.addRow('Дата выполнения *',self.work_date)
        self.object_text=QLineEdit();self.object_text.setPlaceholderText('Введите объект, адрес или место работ');form.addRow('Где выполнялись работы *',self.object_text)
        self.title=QLineEdit();self.title.setPlaceholderText('Любое наименование сварочных работ');form.addRow('Выполненные работы *',self.title)
        self.welder=QComboBox();self.welder.setEditable(True);self.welder.addItem('',None)
        for rid,name in db.fetchall('SELECT id,name FROM welders ORDER BY name'):self.welder.addItem(name,rid)
        form.addRow('Сварщик (свободный ввод)',self.welder);self.notes=QLineEdit();form.addRow('Объём / примечания',self.notes)
        from PyQt6.QtWidgets import QGroupBox
        box=QGroupBox('Необязательно: заполнить из базы и сметы');secondary=QFormLayout(box);layout.addWidget(box)
        self.object=ObjectField();secondary.addRow('Связь с договором',self.object)
        self.source=QComboBox();secondary.addRow('Работа из сметы',self.source)
        reuse=QPushButton('Заполнить по прежней записи журнала…');reuse.clicked.connect(self.reuse);secondary.addRow(reuse)
        self.object.changed.connect(self.object_changed);self.source.currentIndexChanged.connect(self.source_changed);self.load_works()
        layout.addWidget(QLabel('Одна строка — один день работ на объекте. Запись появится в общем календаре.'))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        if reference:self.object.set_reference(*reference)
        if job_id:
            row=db.fetchone('SELECT title,owner_type,owner_id,estimate_item_id,welder_id,notes,object_text,welder_text FROM welding_jobs WHERE id=?',(job_id,))
            self.object.set_reference(row[1],row[2]);self.source.setCurrentIndex(max(0,self.source.findData(row[3])));self.title.setText(row[0]);self.welder.setCurrentIndex(max(0,self.welder.findData(row[4])))
            if row[7]:self.welder.setEditText(row[7])
            self.notes.setText(row[5] or '');self.object_text.setText(row[6] or (owner_label(db,row[1],row[2]) if row[1] else ''))
            day=db.fetchone('SELECT work_date FROM welding_days WHERE job_id=? ORDER BY work_date LIMIT 1',(job_id,));self.work_date.set_value(day[0] if day else '')
    def reuse(self):
        d=JobPicker(self)
        if d.exec():
            row=db.fetchone('SELECT title,owner_type,owner_id,estimate_item_id,welder_id,notes,object_text,welder_text FROM welding_jobs WHERE id=?',(d.job_id,))
            self.object.set_reference(row[1],row[2]);self.source.setCurrentIndex(max(0,self.source.findData(row[3])));self.title.setText(row[0]);self.welder.setCurrentIndex(max(0,self.welder.findData(row[4])))
            if row[7]:self.welder.setEditText(row[7])
            self.object_text.setText(row[6] or (owner_label(db,row[1],row[2]) if row[1] else ''));self.notes.setText(row[5] or '')
    def object_changed(self):
        self.load_works()
        if self.object.reference[0]:self.object_text.setText(owner_label(db,*self.object.reference))
    def load_works(self):
        self.source.blockSignals(True);self.source.clear();self.source.addItem('Ввести работу самостоятельно',None)
        owner,rid=self.object.reference
        if owner=='contracts':
            for item_id,name in db.fetchall("SELECT i.id,i.name FROM estimate_items i JOIN contracts c ON c.estimate_id=i.estimate_id WHERE c.id=? AND i.item_type='Работа' ORDER BY i.sort_order,i.id",(rid,)):self.source.addItem(name,item_id)
        self.source.blockSignals(False)
    def source_changed(self):
        if self.source.currentData():self.title.setText(self.source.currentText())
    def save(self):
        try:
            if not self.object_text.text().strip():raise ValueError('Укажите, где выполнялись работы')
            day=self.work_date.value();date.fromisoformat(day)
            wid=self.welder.currentData() if self.welder.currentIndex()>=0 and self.welder.currentText()==self.welder.itemText(self.welder.currentIndex()) else None
            with db.transaction():
                jid=save_job(db,self.title.text(),*self.object.reference,wid,self.notes.text(),self.source.currentData(),self.job_id)
                db.execute('UPDATE welding_jobs SET object_text=?,welder_text=? WHERE id=?',(self.object_text.text().strip(),self.welder.currentText().strip(),jid))
                db.execute('DELETE FROM welding_days WHERE job_id=?',(jid,));set_work_day(db,jid,day,True)
            self.job_id=jid;self.accept()
        except Exception as e:QMessageBox.warning(self,'Запись работ',str(e))

class JobPicker(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.job_id=None;self.setWindowTitle('Заполнить по прежним работам');self.resize(920,520);self.pager=RegistryPager(self);l=QVBoxLayout(self);self.search=QLineEdit();self.search.setPlaceholderText('Работа или объект…');l.addWidget(self.search);self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Дата','Работа','Объект']);self.table.setColumnWidth(1,340);self.table.horizontalHeader().setStretchLastSection(True);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);l.addWidget(self.table,1);b=QPushButton('Заполнить поля');b.clicked.connect(self.choose);l.addWidget(b);self.table.cellDoubleClicked.connect(lambda *_:self.choose());self.search.textChanged.connect(self.load_data);self.load_data()
    def load_data(self,*_):
        q='%'+self.search.text().casefold()+'%';rows=self.pager.fetch("SELECT j.id,d.work_date,j.title,j.object_text FROM welding_jobs j LEFT JOIN welding_days d ON d.job_id=j.id WHERE LOWER(j.title) LIKE ? OR LOWER(j.object_text) LIKE ? ORDER BY d.work_date DESC,j.id DESC",(q,q));self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,v in enumerate(row[1:]):i=QTableWidgetItem(str(v or ''));i.setData(Qt.ItemDataRole.UserRole,row[0]);self.table.setItem(r,c,i)
    def choose(self):
        if self.table.currentRow()>=0:self.job_id=self.table.item(self.table.currentRow(),0).data(Qt.ItemDataRole.UserRole);self.accept()

class ScheduleView(QWidget):
    def __init__(self,reference=None):
        super().__init__();self.reference=reference;self.pager=RegistryPager(self);layout=QVBoxLayout(self)
        bar=QHBoxLayout();self.date_from=OptionalDate();self.date_to=OptionalDate();bar.addWidget(QLabel('Дата с'));bar.addWidget(self.date_from);bar.addWidget(QLabel('по'));bar.addWidget(self.date_to)
        self.search=QLineEdit();self.search.setPlaceholderText('Поиск: объект, работа, сварщик…');bar.addWidget(self.search,1)
        reset=QPushButton('Все даты');reset.clicked.connect(self.clear_dates);bar.addWidget(reset);layout.addLayout(bar)
        actions=QHBoxLayout()
        for label,fn in [('Добавить запись',self.create),('Изменить',self.edit),('Открыть объект',self.open_object),('Удалить запись',self.delete)]:b=QPushButton(label);b.clicked.connect(fn);actions.addWidget(b)
        actions.addStretch();layout.addLayout(actions)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Дата','Объект / место работ','Выполненные работы','Сварщик','Объём / примечания']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setAlternatingRowColors(True);self.table.verticalHeader().setDefaultSectionSize(34);self.table.horizontalHeader().setStretchLastSection(True)
        for c,w in enumerate([110,280,330,190]):self.table.setColumnWidth(c,w)
        layout.addWidget(self.table,1);self.table.cellDoubleClicked.connect(lambda *_:self.edit())
        self.search.textChanged.connect(self.load_data);self.date_from.dateChanged.connect(self.load_data);self.date_to.dateChanged.connect(self.load_data);self.load_data()
    def clear_dates(self):self.date_from.set_value('');self.date_to.set_value('');self.load_data()
    def selected(self):
        r=self.table.currentRow();return self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else None
    def load_data(self,*_):
        q='%'+self.search.text().casefold()+'%'
        query="""SELECT j.id,d.work_date,coalesce(nullif(j.object_text,''),c.object_name,p.object_name,'') object_text,j.title,
          coalesce(nullif(j.welder_text,''),w.name,'') welder_text,j.notes FROM welding_jobs j
          LEFT JOIN welding_days d ON d.job_id=j.id LEFT JOIN welders w ON w.id=j.welder_id
          LEFT JOIN contracts c ON j.owner_type='contracts' AND c.id=j.owner_id
          LEFT JOIN gsv_projects p ON j.owner_type='gsv_projects' AND p.id=j.owner_id WHERE 1=1"""
        params=[]
        if self.reference:query+=' AND j.owner_type=? AND j.owner_id=?';params.extend(self.reference)
        if self.date_from.value():query+=' AND d.work_date>=?';params.append(self.date_from.value())
        if self.date_to.value():query+=' AND d.work_date<=?';params.append(self.date_to.value())
        query="SELECT * FROM ("+query+") WHERE LOWER(object_text||' '||title||' '||welder_text||' '||coalesce(notes,'')) LIKE ? ORDER BY work_date DESC,id DESC";params.append(q)
        rows=self.pager.fetch(query,params);self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row[1:]):
                text=str(value or '')
                if c==0:text=QDate.fromString(text,'yyyy-MM-dd').toString('dd.MM.yyyy') if text else 'Дата не задана'
                item=QTableWidgetItem(text);item.setData(Qt.ItemDataRole.UserRole,row[0]);self.table.setItem(r,c,item)
    def create(self):JobDialog(reference=self.reference,parent=self).exec();self.load_data()
    def edit(self):
        if self.selected():JobDialog(self.selected(),parent=self).exec();self.load_data()
    def delete(self):
        rid=self.selected()
        if rid and QMessageBox.question(self,'Удаление','Удалить запись из журнала и календаря?')==QMessageBox.StandardButton.Yes:db.execute('DELETE FROM welding_jobs WHERE id=?',(rid,));self.load_data()
    def open_object(self):
        if self.selected():
            row=db.fetchone('SELECT owner_type,owner_id FROM welding_jobs WHERE id=?',(self.selected(),))
            if row[0]:
                from .workspace_view import open_record
                open_record(row[0],row[1],self);self.load_data()
            else:QMessageBox.information(self,'Объект','Эта запись введена вручную и не связана с договором.')

class WeldersView(QWidget):
    def __init__(self):
        super().__init__();layout=QVBoxLayout(self);self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        for view,label in [(ScheduleView(),'График производства работ'),(WeldersRegistry(),'Сварщики'),(DocumentsView('attestation'),'Аттестация'),(DocumentsView('contract_act'),'Договоры и акты')]:self.tabs.addTab(view,label)
        self.tabs.currentChanged.connect(lambda _:self.load_data())
    def load_data(self):self.tabs.currentWidget().load_data()
