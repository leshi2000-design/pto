"""Shared external-file register and per-object executive documentation."""
from pathlib import Path
from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QAbstractItemView,QDialogButtonBox,QFileDialog,QMessageBox)
from PyQt6.QtCore import Qt
from .database import db
from .pagination import RegistryPager
from .domain_widgets import OptionalDate
from .gsv_domain import DOCUMENT_CATEGORIES,DOCUMENT_TYPES,add_document,dossier,link_documents
from .platform_utils import open_local


def file_state(path):return 'Доступен' if path and Path(path).is_file() else 'Файл недоступен' if path else 'Файл не указан'

def open_path(parent,path):
    if file_state(path)!='Доступен':QMessageBox.warning(parent,'Документ','Файл недоступен по сохранённому пути. Подключите носитель или измените путь в карточке документа.');return
    try:open_local(path)
    except OSError as e:QMessageBox.warning(parent,'Документ',str(e))

class DocumentDialog(QDialog):
    def __init__(self,doc_id=None,category='attestation',welder_id=None,parent=None):
        super().__init__(parent);self.doc_id=doc_id;self.setWindowTitle('Документ сварки — ссылка на файл');self.resize(700,480)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form);self.title=QLineEdit();self.category=QComboBox()
        for key,label in DOCUMENT_CATEGORIES.items():self.category.addItem(label,key)
        self.category.setCurrentIndex(self.category.findData(category));self.kind=QComboBox();self.kind.addItems(DOCUMENT_TYPES);self.number=QLineEdit();self.date=OptionalDate();self.note=QLineEdit();self.path=QLineEdit();self.path.setPlaceholderText('Путь к существующему файлу на компьютере / сетевом диске')
        self.welder=QComboBox();self.welder.addItem('Не связан со сварщиком',None)
        for rid,name in db.fetchall('SELECT id,name FROM welders ORDER BY name'):self.welder.addItem(name,rid)
        self.welder.setCurrentIndex(max(0,self.welder.findData(welder_id)))
        for label,field in [('Название *',self.title),('Раздел',self.category),('Тип',self.kind),('Сварщик',self.welder),('Номер',self.number),('Дата',self.date),('Примечание',self.note)]:form.addRow(label,field)
        row=QHBoxLayout();row.addWidget(self.path,1);browse=QPushButton('Выбрать файл…');browse.clicked.connect(self.browse);row.addWidget(browse);form.addRow('Путь *',row)
        hint=QLabel('Хранится только путь. Файл не копируется в программу и не включается в резервные копии приложения.');hint.setWordWrap(True);layout.addWidget(hint)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        if doc_id:
            r=db.fetchone('SELECT title,category,document_type,file_path,welder_id,number,document_date,note FROM welding_documents WHERE id=?',(doc_id,))
            self.title.setText(r[0]);self.category.setCurrentIndex(self.category.findData(r[1]));self.kind.setCurrentText(r[2]);self.path.setText(r[3]);self.welder.setCurrentIndex(max(0,self.welder.findData(r[4])));self.number.setText(r[5] or '');self.date.set_value(r[6]);self.note.setText(r[7] or '')
    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'Указать существующий документ','','Все файлы (*)')
        if path:
            self.path.setText(path)
            if not self.title.text():self.title.setText(Path(path).stem)
    def save(self):
        try:
            self.doc_id=add_document(db,dict(title=self.title.text(),category=self.category.currentData(),document_type=self.kind.currentText(),file_path=self.path.text(),welder_id=self.welder.currentData(),number=self.number.text(),document_date=self.date.value(),note=self.note.text()),self.doc_id);self.accept()
        except Exception as e:QMessageBox.warning(self,'Документ',str(e))

class DocumentsView(QWidget):
    def __init__(self,category=None,welder_id=None,picker=False):
        super().__init__();self.category=category;self.welder_id=welder_id;self.picker=picker;self.selected_ids=set();self._loading=False;self.pager=RegistryPager(self)
        layout=QVBoxLayout(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Название, номер, тип, ФИО…');bar.addWidget(self.search,1)
        for label,callback in [('Добавить',self.create),('Выбрать несколько файлов…',self.add_many),('Изменить',self.edit),('Открыть',self.open),('Связанные объекты',self.objects),('Удалить запись',self.delete)]:
            b=QPushButton(label);b.clicked.connect(callback);bar.addWidget(b)
        layout.addLayout(bar)
        label=QLabel('Документы остаются по исходным путям. Удаление записи не удаляет файл с диска.');label.setWordWrap(True);layout.addWidget(label)
        self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['Название','Тип','Номер','Сварщик','Дата','Доступность','Путь']);self.table.setColumnWidth(0,260);self.table.horizontalHeader().setStretchLastSection(True);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);layout.addWidget(self.table,1)
        self.search.textChanged.connect(self.load_data);self.table.cellDoubleClicked.connect(lambda *_:self.edit());self.table.itemChanged.connect(self.checked);self.load_data()
    def selected(self):
        r=self.table.currentRow();return self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else None
    def checked(self,item):
        if self._loading or not self.picker or item.column()!=0:return
        rid=item.data(Qt.ItemDataRole.UserRole)
        if item.checkState()==Qt.CheckState.Checked:self.selected_ids.add(rid)
        else:self.selected_ids.discard(rid)
    def load_data(self,*_):
        q='%'+self.search.text().casefold()+'%';where=['(LOWER(d.title) LIKE ? OR LOWER(d.number) LIKE ? OR LOWER(d.document_type) LIKE ? OR LOWER(w.name) LIKE ?)'];params=[q]*4
        if self.category:where.append('d.category=?');params.append(self.category)
        if self.welder_id:where.append('d.welder_id=?');params.append(self.welder_id)
        rows=self.pager.fetch('SELECT d.id,d.title,d.document_type,d.number,w.name,d.document_date,d.file_path FROM welding_documents d LEFT JOIN welders w ON w.id=d.welder_id WHERE '+' AND '.join(where)+' ORDER BY d.id DESC',params)
        self._loading=True;self.table.setRowCount(len(rows))
        for r,(rid,title,kind,number,welder,day,path) in enumerate(rows):
            for c,value in enumerate([title,kind,number,welder,day,file_state(path),path]):
                item=QTableWidgetItem(str(value or ''));item.setData(Qt.ItemDataRole.UserRole,rid)
                if c==0 and self.picker:item.setCheckState(Qt.CheckState.Checked if rid in self.selected_ids else Qt.CheckState.Unchecked)
                self.table.setItem(r,c,item)
        self._loading=False
    def create(self):DocumentDialog(category=self.category or ('welder' if self.welder_id else 'attestation'),welder_id=self.welder_id,parent=self).exec();self.load_data()
    def add_many(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Указать документы (без копирования)','','Все файлы (*)')
        if paths:
            try:
                with db.transaction():
                    for path in paths:add_document(db,dict(title=Path(path).stem,category=self.category or ('welder' if self.welder_id else 'attestation'),document_type='Другое',file_path=path,welder_id=self.welder_id,number='',document_date='',note=''))
                self.load_data()
            except Exception as e:QMessageBox.warning(self,'Документы',str(e))
    def edit(self):
        if self.selected():DocumentDialog(self.selected(),parent=self).exec();self.load_data()
    def open(self):
        if self.selected():open_path(self,db.fetchone('SELECT file_path FROM welding_documents WHERE id=?',(self.selected(),))[0])
    def objects(self):
        if not self.selected():return
        from .gsv_domain import owner_label
        from .workspace_view import open_record
        d=QDialog(self);d.setWindowTitle('Объекты, использующие документ');d.resize(800,450);layout=QVBoxLayout(d)
        table=QTableWidget(0,1);table.setHorizontalHeaderLabels(['Договор / объект']);table.horizontalHeader().setStretchLastSection(True);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);layout.addWidget(table)
        rows=db.fetchall('SELECT owner_type,owner_id FROM object_welding_documents WHERE document_id=?',(self.selected(),));table.setRowCount(len(rows))
        for r,(owner,rid) in enumerate(rows):
            item=QTableWidgetItem(owner_label(db,owner,rid));item.setData(Qt.ItemDataRole.UserRole,(owner,rid));table.setItem(r,0,item)
        table.cellDoubleClicked.connect(lambda r,c:open_record(*table.item(r,0).data(Qt.ItemDataRole.UserRole),d))
        layout.addWidget(QLabel('Двойной щелчок открывает карточку объекта.'))
        d.exec()

    def delete(self):
        rid=self.selected()
        if not rid:return
        count=db.fetchone('SELECT count(*) FROM object_welding_documents WHERE document_id=?',(rid,))[0]
        if QMessageBox.question(self,'Удалить ссылку',f'Удалить запись и её связи с объектами ({count})? Сам файл останется на диске.')==QMessageBox.StandardButton.Yes:
            db.execute('DELETE FROM welding_documents WHERE id=?',(rid,));self.selected_ids.discard(rid);self.load_data()

class DocumentsPicker(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Добавить документы из модуля сварщиков');self.resize(1150,600);layout=QVBoxLayout(self);self.view=DocumentsView(picker=True);layout.addWidget(self.view,1)
        label=QLabel('Отметьте документы галочками. Выбор сохраняется при переходе между страницами.');layout.addWidget(label)
        button=QPushButton('Добавить выбранные к объекту');button.clicked.connect(self.accept);layout.addWidget(button)

class ObjectDossierWidget(QWidget):
    def __init__(self,owner,rid=None,parent=None):
        super().__init__(parent);self.owner=owner;self.rid=rid;self.rows=[];layout=QVBoxLayout(self)
        self.info=QLabel();self.info.setWordWrap(True);layout.addWidget(self.info)
        bar=QHBoxLayout()
        for label,callback in [('Добавить из модуля сварщиков…',self.add),('Открыть документ',self.open),('Карточка документа',self.edit),('Убрать связь',self.unlink),('Обновить',self.load_data)]:b=QPushButton(label);b.clicked.connect(callback);bar.addWidget(b)
        bar.addStretch();layout.addLayout(bar);self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['Источник','Документ','Номер','Доступность','Путь']);self.table.setColumnWidth(0,210);self.table.setColumnWidth(1,260);self.table.horizontalHeader().setStretchLastSection(True);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);layout.addWidget(self.table,1);self.table.cellDoubleClicked.connect(lambda *_:self.open());self.load_data()
    def bind(self,rid):self.rid=rid;self.load_data()
    def load_data(self,*_):
        self.rows=dossier(db,self.owner,self.rid) if self.rid else [];self.table.setRowCount(len(self.rows));self.info.setText('Сертификаты оборудования и трубопроводов подтягиваются автоматически. Документы сварки добавляются ссылками.' if self.rid else 'Сохраните новую карточку, затем добавьте документы сварки. Трубы и оборудование можно заполнить до сохранения.')
        for r,row in enumerate(self.rows):
            for c,value in enumerate([row['source'],row['title'],row['number'],file_state(row['path']),row['path']]):self.table.setItem(r,c,QTableWidgetItem(str(value or '')))
    def selected(self):
        r=self.table.currentRow();return self.rows[r] if 0<=r<len(self.rows) else None
    def add(self):
        if not self.rid:QMessageBox.information(self,'Документы','Сначала сохраните карточку');return
        d=DocumentsPicker(self)
        if d.exec():link_documents(db,self.owner,self.rid,d.view.selected_ids);self.load_data()
    def open(self):
        row=self.selected()
        if row:open_path(self,row['path'])
    def edit(self):
        row=self.selected()
        if row and row['reference']:
            if row['removable']:DocumentDialog(row['reference'],parent=self).exec()
            else:
                from .executive_view import CertificateEditDialog
                CertificateEditDialog(row['reference'],self).exec()
            self.load_data()
    def unlink(self):
        row=self.selected()
        if not row:return
        if not row['removable']:QMessageBox.information(self,'Автоматический сертификат','Измените оборудование или трубопровод в соответствующей вкладке карточки.');return
        db.execute('DELETE FROM object_welding_documents WHERE owner_type=? AND owner_id=? AND document_id=?',(self.owner,self.rid,row['reference']));self.load_data()
