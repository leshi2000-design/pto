"""Shared contract fields, certificate selection and template workspace."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QLabel,QTabWidget,QScrollArea,QTableWidget,QTableWidgetItem,QComboBox,QFileDialog,QMessageBox,QCheckBox,QTreeView,QAbstractItemView,QDialogButtonBox,QInputDialog)
from PyQt6.QtCore import Qt,QTimer,QEvent
from PyQt6.QtGui import QFileSystemModel
from .database import db
from . import template_domain as domain
from .domain_widgets import OptionalDate
from .pagination import RegistryPager
from .gsv_catalog import CertificatePicker

class TagReferenceDialog(QDialog):
    """Read-only list of {{тег}} substitutions available for a module's Word/Excel templates."""
    def __init__(self,owner,parent=None):
        super().__init__(parent);self.setWindowTitle('Теги для шаблонов');self.resize(750,600)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Скопируйте тег целиком вместе с {{ }} в шаблон Word / Excel.'))
        rows=domain.tag_reference(owner)
        table=QTableWidget(len(rows),2);table.setHorizontalHeaderLabels(['Тег','Что подставится'])
        table.setColumnWidth(0,260);table.horizontalHeader().setStretchLastSection(True)
        for r,(tag,desc) in enumerate(rows):
            table.setItem(r,0,QTableWidgetItem('{{'+tag+'}}'));table.setItem(r,1,QTableWidgetItem(desc))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);layout.addWidget(table)

class FolderModel(QFileSystemModel):
    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if orientation==Qt.Orientation.Horizontal and role==Qt.ItemDataRole.DisplayRole and section<4:return ('Имя','Размер','Тип','Изменён')[section]
        return super().headerData(section,orientation,role)

class MaterialPicker(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.result_row=None;self.resize(850,500);self.setWindowTitle('Материалы строительства');layout=QVBoxLayout(self);self.pager=RegistryPager(self)
        self.search=QLineEdit();self.search.setPlaceholderText('Поиск в справочнике материалов');layout.addWidget(self.search);self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Материал','Ед.','Сертификат']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1)
        b=QPushButton('Выбрать');b.clicked.connect(self.choose);layout.addWidget(b);self.search.textChanged.connect(self.load_data);self.table.cellDoubleClicked.connect(self.choose);self.load_data()
    def load_data(self,*_):
        self.rows=self.pager.fetch("SELECT m.id,m.name,m.unit,m.certificate_id,c.cert_number FROM materials m LEFT JOIN certificates c ON c.id=m.certificate_id WHERE coalesce(m.item_type,'Материал')!='Работа' AND LOWER(m.name) LIKE ? ORDER BY m.name",('%'+self.search.text().casefold()+'%',));self.table.setRowCount(len(self.rows))
        for i,row in enumerate(self.rows):
            for j,value in enumerate((row[1],row[2],row[4])):self.table.setItem(i,j,QTableWidgetItem(str(value or '')))
    def choose(self,*_):
        r=self.table.currentRow()
        if r>=0:self.result_row=dict(zip(('material_id','name','unit','certificate_id','certificate_number'),self.rows[r]));self.accept()

class ExecutiveWorkspace(QTabWidget):
    def __init__(self,owner,save_callback,parent=None):
        super().__init__(parent);self.owner=owner;self.rid=None;self.save_callback=save_callback;self.future=None;self.pool=ThreadPoolExecutor(max_workers=1);self.fields={}
        page=QWidget();form=QFormLayout(page)
        for key,label in domain.FIELDS.items():
            if owner=='contracts' and key in ('start_date','end_date'):continue
            widget=OptionalDate() if key in domain.DATES else QLineEdit();self.fields[key]=widget;form.addRow(label,widget)
        form.addRow(QLabel('Количество из таблицы материалов имеет приоритет над ручным итогом.'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);self.addTab(scroll,'Данные для документов')
        page=QWidget();layout=QVBoxLayout(page);bar=QHBoxLayout()
        for title,fn in [('Из справочника',self.pick_material),('Ввести материал',self.add_material),('Сертификат…',self.pick_certificate),('Файл сертификата…',self.attach_certificate),('Удалить строку',self.remove_material)]:
            b=QPushButton(title);b.clicked.connect(fn);bar.addWidget(b)
        layout.addLayout(bar);self.materials=QTableWidget(0,6);self.materials.setHorizontalHeaderLabels(['Вид','Материал','Ед.','Количество','Сертификат','Примечание']);self.materials.setColumnWidth(0,190);self.materials.setColumnWidth(1,250);self.materials.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.materials,1);self.addTab(page,'Материалы и сертификаты')
        page=QWidget();layout=QVBoxLayout(page);bar=QHBoxLayout();self.folder=QLineEdit();self.folder.setPlaceholderText('Папка этого договора');bar.addWidget(self.folder,1);b=QPushButton('Привязать папку…');b.clicked.connect(self.choose_folder);bar.addWidget(b);layout.addLayout(bar)
        self.templates_table=QTableWidget(0,3);self.templates_table.setHorizontalHeaderLabels(['Создать','Документ','Шаблон (двойной щелчок — настройка)']);self.templates_table.setColumnWidth(0,65);self.templates_table.setColumnWidth(1,340);self.templates_table.horizontalHeader().setStretchLastSection(True);self.templates_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.templates_table.cellDoubleClicked.connect(self.configure);layout.addWidget(self.templates_table,2)
        bar=QHBoxLayout();b=QPushButton('Настроить шаблон');b.clicked.connect(self.configure);bar.addWidget(b);b=QPushButton('Теги и значения');b.clicked.connect(self.show_tags);bar.addWidget(b);self.copy_certs=QCheckBox('Добавить файлы сертификатов');self.copy_certs.setChecked(True);bar.addWidget(self.copy_certs);self.generate_button=QPushButton('Создать выбранные документы');self.generate_button.clicked.connect(self.generate);bar.addWidget(self.generate_button);layout.addLayout(bar)
        self.status=QLabel('Подключите свои шаблоны .docx / .xlsx. Теги: {{номер_договора}}, {{фио}} и другие.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.model=FolderModel(self);self.model.setReadOnly(True);self.tree=QTreeView();self.tree.setModel(self.model);self.tree.setRootIsDecorated(False);self.tree.setColumnWidth(0,400);self.tree.doubleClicked.connect(self.open_file);layout.addWidget(self.tree,2);self.tree.hide();self.folder.editingFinished.connect(self.refresh_folder)
        bar=QHBoxLayout();b=QPushButton('Добавить готовый файл / распечатку аппарата…');b.clicked.connect(self.import_file);bar.addWidget(b);b=QPushButton('Открыть папку');b.clicked.connect(self.open_folder);bar.addWidget(b);layout.addLayout(bar);self.addTab(page,'Шаблоны и папка')
        if owner not in ('gsn_projects','contracts'):
            self.status.setText('Перечень исполнительных документов для этого раздела будет настроен отдельно. Здесь доступны материалы и папка; договор создавайте через экспорт по шаблону.')
            self.generate_button.setEnabled(False)
        from .dossier_view import ContractDossiers
        self.removeTab(2);self.dossier_link=ContractDossiers(owner,self,save_callback);self.addTab(self.dossier_link,'Перечень ИД и папка')
        self.timer=QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self.poll);self.refresh_templates()
        if parent:parent.installEventFilter(self)
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Close and self.future and not self.future.done():event.ignore();QMessageBox.information(self,'Создание документов','Дождитесь завершения создания документов.');return True
        return super().eventFilter(obj,event)
    def load(self,rid):
        self.rid=rid;folder,fields=domain.load_details(db,self.owner,rid)
        if not folder and self.owner=='gsv_projects' and rid:
            row=db.fetchone('SELECT project_folder FROM gsv_projects WHERE id=?',(rid,));folder=row[0] or ''
        self.folder.setText(folder)
        auto_initials,auto_surname='',''
        if rid:
            from .gsv_domain import get_client
            data=domain.record(db,self.owner,rid);client=get_client(db,data.get('client_id')) or {}
            full=client.get('name') or data.get('client_name') or ''
            if full:auto_initials,auto_surname=domain.names(full)
        for key,widget in self.fields.items():
            if key in domain.DATES:widget.set_value(fields.get(key,''))
            elif key=='initials_first':widget.setText(str(fields.get(key) or auto_initials))
            elif key=='surname_first':widget.setText(str(fields.get(key) or auto_surname))
            else:widget.setText(str(fields.get(key,'') or ''))
        self.materials.setRowCount(0)
        for row in domain.material_rows(db,self.owner,rid):self.add_material(row)
        self.refresh_templates();self.refresh_folder();self.dossier_link.load_data()
    def bind(self,rid):self.rid=rid;self.refresh_templates();self.dossier_link.load_data()
    def save(self,rid):
        values={k:(w.value() if k in domain.DATES else w.text().strip()) for k,w in self.fields.items()};rows=[]
        for r in range(self.materials.rowCount()):
            row=dict(self.materials.item(r,1).data(Qt.ItemDataRole.UserRole) or {});row.update(kind=self.materials.cellWidget(r,0).currentData(),name=self.materials.item(r,1).text(),unit=self.materials.item(r,2).text(),quantity=self.materials.item(r,3).text(),note=self.materials.item(r,5).text());rows.append(row)
        domain.save_details(db,self.owner,rid,self.folder.text(),values,rows)
    def add_material(self,row=None):
        row=row if isinstance(row,dict) else {};r=self.materials.rowCount();self.materials.insertRow(r);kind=QComboBox()
        for key,(label,unit) in domain.KINDS.items():kind.addItem(label,key)
        kind.setCurrentIndex(max(0,kind.findData(row.get('kind','other'))));self.materials.setCellWidget(r,0,kind)
        for c,value in enumerate((row.get('name',''),row.get('unit','м'),row.get('quantity','1'),row.get('certificate_number',''),row.get('note','')),1):self.materials.setItem(r,c,QTableWidgetItem(str(value or '')))
        self.materials.item(r,1).setData(Qt.ItemDataRole.UserRole,row);self.materials.item(r,4).setFlags(self.materials.item(r,4).flags() & ~Qt.ItemFlag.ItemIsEditable);self.materials.selectRow(r)
        kind.currentIndexChanged.connect(lambda *_:self.set_unit(kind))
    def set_unit(self,combo):
        for r in range(self.materials.rowCount()):
            if self.materials.cellWidget(r,0) is combo:
                unit=domain.KINDS[combo.currentData()][1]
                if unit:self.materials.item(r,2).setText(unit)
    def pick_material(self):
        d=MaterialPicker(self)
        if d.exec():self.add_material(d.result_row)
    def remove_material(self):
        r=self.materials.currentRow()
        if r>=0:self.materials.removeRow(r)
    def set_certificate(self,cid):
        r=self.materials.currentRow()
        if r<0:return
        item=self.materials.item(r,1);row=dict(item.data(Qt.ItemDataRole.UserRole) or {});row['certificate_id']=cid;item.setData(Qt.ItemDataRole.UserRole,row);cert=db.fetchone('SELECT name,cert_number FROM certificates WHERE id=?',(cid,));self.materials.item(r,4).setText(' · '.join(str(v or '') for v in cert) if cert else '')
    def pick_certificate(self):
        if self.materials.currentRow()<0:return
        d=CertificatePicker(self)
        if d.exec():self.set_certificate(d.cert_id)
    def attach_certificate(self):
        if self.materials.currentRow()<0:return
        file,_=QFileDialog.getOpenFileName(self,'Файл сертификата')
        if not file:return
        number,ok=QInputDialog.getText(self,'Сертификат','Номер сертификата')
        if ok:self.set_certificate(db.execute('INSERT INTO certificates(name,cert_number,file_path) VALUES(?,?,?)',(Path(file).stem,number,file)).lastrowid)
    def refresh_templates(self):
        self.template_rows=domain.templates(db,self.owner,self.rid);self.templates_table.setRowCount(len(self.template_rows))
        for r,row in enumerate(self.template_rows):
            old=self.templates_table.item(r,0);checked=old.checkState() if old else Qt.CheckState.Unchecked
            item=QTableWidgetItem();item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(checked);self.templates_table.setItem(r,0,item)
            self.templates_table.setItem(r,1,QTableWidgetItem(row['label']));self.templates_table.setItem(r,2,QTableWidgetItem(('Этот договор · ' if row['override'] else '')+(row['file_path'] or 'Не подключён')))
    def configure(self,*_):
        r=self.templates_table.currentRow()
        if r<0:return
        row=self.template_rows[r];d=QDialog(self);d.setWindowTitle(row['label']);d.resize(750,230);layout=QFormLayout(d);file=QLineEdit(row['file_path']);name=QLineEdit(row['output_name']);local=QCheckBox('Только для этого договора');local.setChecked(row['override']);layout.addRow('Шаблон',file);b=QPushButton('Выбрать Word / Excel…');layout.addRow(b)
        def browse():
            value,_=QFileDialog.getOpenFileName(d,'Шаблон','','Шаблоны (*.docx *.xlsx)')
            if value:file.setText(value)
        b.clicked.connect(browse);layout.addRow('Имя результата (можно с тегами)',name);layout.addRow(local);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addRow(buttons);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject)
        if d.exec():
            try:
                if local.isChecked() and not self.save_callback():return
                domain.save_template(db,self.owner,row['slot'],file.text(),name.text(),self.rid if local.isChecked() else None)
                if not local.isChecked() and self.rid:db.execute('DELETE FROM executive_overrides WHERE owner_type=? AND owner_id=? AND slot=?',(self.owner,self.rid,row['slot']))
                self.refresh_templates()
            except Exception as e:QMessageBox.warning(self,'Шаблон',str(e))
    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Папка договора',self.folder.text())
        if folder:self.folder.setText(folder);self.refresh_folder()
    def refresh_folder(self):
        value=self.folder.text().strip()
        if value and domain.path(db,value).is_dir():root=str(domain.path(db,value));self.tree.setRootIndex(self.model.setRootPath(root));self.tree.show()
        else:self.tree.hide()
    def open_file(self,index):
        from .platform_utils import open_local
        file=self.model.filePath(index)
        if Path(file).is_file():open_local(file)
    def open_folder(self):
        from .platform_utils import open_local
        if self.folder.text() and domain.path(db,self.folder.text()).is_dir():open_local(str(domain.path(db,self.folder.text())))
    def import_file(self):
        if not self.save_callback():return
        folder=self.folder.text().strip()
        if not folder or not domain.path(db,folder).is_dir():QMessageBox.warning(self,'Папка','Привяжите доступную папку договора');return
        source,_=QFileDialog.getOpenFileName(self,'Добавить готовый документ')
        if not source:return
        try:
            import shutil
            import uuid
            p=Path(source);target=domain.path(db,folder)/(p.stem+'_'+uuid.uuid4().hex[:8]+p.suffix)
            with p.open('rb') as src,target.open('xb') as dst:shutil.copyfileobj(src,dst)
            self.refresh_folder()
        except Exception as e:QMessageBox.warning(self,'Файл',str(e))
    def show_tags(self):
        if not self.save_callback():return
        ctx,_=domain.context(db,self.owner,self.rid);d=QDialog(self);d.setWindowTitle('Теги: скопируйте целиком вместе с {{ }}');d.resize(950,650);layout=QVBoxLayout(d);table=QTableWidget(len(ctx),2);table.setHorizontalHeaderLabels(['Тег','Значение']);table.setColumnWidth(0,350);table.horizontalHeader().setStretchLastSection(True)
        for r,(key,value) in enumerate(sorted(ctx.items())):table.setItem(r,0,QTableWidgetItem('{{'+key+'}}'));table.setItem(r,1,QTableWidgetItem(str(value)))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);layout.addWidget(table);d.exec()
    def generate(self):
        if self.future or not self.save_callback():return
        slots=[row['slot'] for r,row in enumerate(self.template_rows) if self.templates_table.item(r,0).checkState()==Qt.CheckState.Checked]
        from .template_engine import generate
        self.generate_button.setEnabled(False);self.status.setText('Проверка тегов и создание документов…');self.future=self.pool.submit(generate,db,self.owner,self.rid,slots,self.copy_certs.isChecked());self.timer.start()
    def poll(self):
        if not self.future or not self.future.done():return
        self.timer.stop();future=self.future;self.future=None;self.generate_button.setEnabled(True)
        try:files=future.result();self.status.setText(f'Создано файлов: {len(files)}. Исходные шаблоны сохранены.');self.refresh_folder()
        except Exception as e:self.status.setText('Документы не созданы: '+str(e));QMessageBox.warning(self,'Создание документов',str(e))
