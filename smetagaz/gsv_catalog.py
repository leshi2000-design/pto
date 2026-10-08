from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QLabel,QTableWidget,QTableWidgetItem,QAbstractItemView,QFileDialog,QDialogButtonBox,QCheckBox,QMessageBox,QComboBox)
from PyQt6.QtCore import Qt
from .database import db
from .pagination import RegistryPager

class CertificatePicker(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Сертификаты');self.resize(750,500);self.cert_id=None
        self.pager=RegistryPager(self);layout=QVBoxLayout(self);self.search=QLineEdit();self.search.setPlaceholderText('Название / номер');layout.addWidget(self.search);self.folder=QComboBox();self.folder.addItem('Все папки',None)
        for fid,name in db.fetchall('SELECT id,name FROM certificate_folders ORDER BY name'):self.folder.addItem(name,fid)
        layout.addWidget(self.folder);self.folder.currentIndexChanged.connect(self.load_data)
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Название','Номер','Путь']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        button=QPushButton('Выбрать сертификат');button.clicked.connect(self.choose);layout.addWidget(button);self.table.cellDoubleClicked.connect(lambda *_:self.choose());self.search.textChanged.connect(self.load_data);self.load_data()
    def load_data(self,*_):
        q='%'+self.search.text().casefold()+'%';rows=self.pager.fetch('SELECT id,name,cert_number,file_path FROM certificates WHERE (LOWER(name) LIKE ? OR LOWER(cert_number) LIKE ?) AND (? IS NULL OR folder_id=?) ORDER BY id DESC',(q,q,self.folder.currentData(),self.folder.currentData()));self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row[1:]):item=QTableWidgetItem(str(value or ''));item.setData(Qt.ItemDataRole.UserRole,row[0]);self.table.setItem(r,c,item)
    def choose(self):
        r=self.table.currentRow()
        if r>=0:self.cert_id=self.table.item(r,0).data(Qt.ItemDataRole.UserRole);self.accept()

class PipelineDialog(QDialog):
    def __init__(self,pipeline_id=None,parent=None):
        super().__init__(parent);self.pipeline_id=pipeline_id;self.certificate_id=None;self.new_path=None;self.setWindowTitle('Трубопровод');self.resize(650,350)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form);self.name=QLineEdit();self.unit=QLineEdit('м');self.notes=QLineEdit();self.active=QCheckBox('Доступен для выбора');self.active.setChecked(True)
        for label,field in [('Наименование (например, Труба 25)',self.name),('Единица',self.unit),('Примечание',self.notes)]:form.addRow(label,field)
        layout.addWidget(self.active);self.cert_label=QLabel('Сертификат не выбран');self.cert_label.setWordWrap(True);layout.addWidget(self.cert_label)
        bar=QHBoxLayout();existing=QPushButton('Выбрать сертификат…');existing.clicked.connect(self.pick);attach=QPushButton('Прикрепить файл…');attach.clicked.connect(self.attach);clear=QPushButton('Убрать связь');clear.clicked.connect(self.clear)
        for b in [existing,attach,clear]:bar.addWidget(b)
        layout.addLayout(bar);self.number=QLineEdit();self.number.setPlaceholderText('Номер нового сертификата');layout.addWidget(self.number)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        if pipeline_id:
            row=db.fetchone('SELECT name,unit,notes,active,certificate_id FROM gsv_pipelines WHERE id=?',(pipeline_id,));self.name.setText(row[0]);self.unit.setText(row[1]);self.notes.setText(row[2] or '');self.active.setChecked(bool(row[3]));self.certificate_id=row[4];self.refresh()
    def refresh(self):
        if self.new_path:self.cert_label.setText('Новый файл: '+self.new_path)
        else:
            row=db.fetchone('SELECT name,cert_number,file_path FROM certificates WHERE id=?',(self.certificate_id,))
            self.cert_label.setText(' · '.join(str(x or '') for x in row) if row else 'Сертификат не выбран')
    def pick(self):
        d=CertificatePicker(self)
        if d.exec():self.certificate_id=d.cert_id;self.new_path=None;self.refresh()
    def attach(self):
        path,_=QFileDialog.getOpenFileName(self,'Сертификат трубопровода','','Документы (*.pdf *.docx *.xlsx *.jpg *.jpeg *.png);;Все файлы (*)')
        if path:self.new_path=path;self.refresh()
    def clear(self):self.new_path=None;self.certificate_id=None;self.refresh()
    def save(self):
        name=self.name.text().strip()
        if not name:QMessageBox.warning(self,'Трубопровод','Введите наименование');return
        try:
            with db.transaction():
                cid=self.certificate_id
                if self.new_path:cid=db.execute('INSERT INTO certificates(name,cert_number,file_path) VALUES(?,?,?)',('Сертификат · '+name,self.number.text().strip(),self.new_path)).lastrowid
                values=(name,self.unit.text().strip() or 'м',cid,self.notes.text(),int(self.active.isChecked()))
                if self.pipeline_id:db.execute('UPDATE gsv_pipelines SET name=?,unit=?,certificate_id=?,notes=?,active=? WHERE id=?',(*values,self.pipeline_id))
                else:self.pipeline_id=db.execute('INSERT INTO gsv_pipelines(name,unit,certificate_id,notes,active) VALUES(?,?,?,?,?)',values).lastrowid
            self.accept()
        except Exception as e:QMessageBox.warning(self,'Не сохранено',str(e))

class GsvCatalogView(QWidget):
    def __init__(self):
        super().__init__();self.pager=RegistryPager(self);layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Трубопроводы ГСВ и их сертификаты. Изменение связи с сертификатом отражается в документации всех объектов, использующих этот вид.'))
        bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Поиск трубопровода…');bar.addWidget(self.search,1)
        for label,callback in [('Добавить',self.create),('Изменить',self.edit),('Открыть сертификат',self.open_file),('Зависимые сертификаты и по умолчанию…',self.open_rules)]:b=QPushButton(label);b.clicked.connect(callback);bar.addWidget(b)
        layout.addLayout(bar);self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Трубопровод','Ед.','Сертификат','Доступен','Путь']);self.table.setColumnWidth(0,250);self.table.horizontalHeader().setStretchLastSection(True);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);layout.addWidget(self.table,1)
        self.table.cellDoubleClicked.connect(lambda *_:self.edit());self.search.textChanged.connect(self.load_data);self.load_data()
    def selected(self):
        r=self.table.currentRow();return self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else None
    def load_data(self,*_):
        rows=self.pager.fetch('SELECT p.id,p.name,p.unit,c.cert_number,p.active,c.file_path FROM gsv_pipelines p LEFT JOIN certificates c ON c.id=p.certificate_id WHERE LOWER(p.name) LIKE ? ORDER BY p.id DESC',('%'+self.search.text().casefold()+'%',));self.table.setRowCount(len(rows))
        for r,(rid,name,unit,number,active,path) in enumerate(rows):
            for c,value in enumerate([name,unit,number,'Да' if active else 'Архив',path]):item=QTableWidgetItem(str(value or ''));item.setData(Qt.ItemDataRole.UserRole,rid);self.table.setItem(r,c,item)
    def open_rules(self):
        from .gsvm_tabs import RulesDialog
        RulesDialog(self).exec()
    def create(self):PipelineDialog(parent=self).exec();self.load_data()
    def edit(self):
        if self.selected():PipelineDialog(self.selected(),self).exec();self.load_data()
    def open_file(self):
        if self.selected():
            from .platform_utils import open_local
            from pathlib import Path
            row=db.fetchone('SELECT c.file_path FROM gsv_pipelines p JOIN certificates c ON c.id=p.certificate_id WHERE p.id=?',(self.selected(),))
            if row and row[0] and Path(row[0]).is_file():open_local(row[0])
            else:QMessageBox.warning(self,'Сертификат','Файл не указан или недоступен. Измените путь в справочнике сертификатов.')
