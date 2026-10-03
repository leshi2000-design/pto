from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import QWidget,QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QComboBox,QTableWidget,QTableWidgetItem,QFileDialog,QMessageBox,QInputDialog,QTreeView,QTabWidget
from PyQt6.QtCore import Qt,QTimer
from .database import db
from .pagination import RegistryPager
from . import dossier_domain as domain,template_domain
from .gsv_catalog import CertificatePicker

def button(bar,text,fn):b=QPushButton(text);b.clicked.connect(fn);bar.addWidget(b);return b
class DossierDialog(QDialog):
    def __init__(self,did,parent=None):
        super().__init__(parent);self.did=did;self.future=None;self.pool=ThreadPoolExecutor(max_workers=1);self.setWindowTitle('Исполнительная документация · '+domain.row(db,did)['title']);self.resize(1150,850);l=QVBoxLayout(self);bar=QHBoxLayout();button(bar,'Карточка договора',self.open_contract);button(bar,'Папка объекта',self.choose_folder);button(bar,'Добавить сертификат',self.add_certificate);button(bar,'Убрать дополнительный сертификат',self.remove_certificate);l.addLayout(bar)
        self.tabs=QTabWidget();l.addWidget(self.tabs,1);self.docs=QTableWidget(0,3);self.docs.setHorizontalHeaderLabels(['Создать','Документ','Шаблон']);self.docs.setColumnWidth(0,65);self.docs.setColumnWidth(1,400);self.docs.horizontalHeader().setStretchLastSection(True);self.tabs.addTab(self.docs,'Документы');self.certs=QTableWidget(0,4);self.certs.setHorizontalHeaderLabels(['Материал / сертификат','Номер','Источник','Файл']);self.certs.horizontalHeader().setStretchLastSection(True);self.tabs.addTab(self.certs,'Сертификаты');from .executive_workspace import FolderModel
        self.model=FolderModel(self);self.model.setReadOnly(True);self.tree=QTreeView();self.tree.setModel(self.model);self.tree.setColumnWidth(0,500);self.tree.setColumnWidth(1,100);self.tree.setColumnWidth(2,190);self.tree.doubleClicked.connect(self.open_file);self.tabs.addTab(self.tree,'Файлы комплекта');self.history=QTableWidget(0,3);self.history.setHorizontalHeaderLabels(['Документ','Обновлён','Путь']);self.history.horizontalHeader().setStretchLastSection(True);self.history.cellDoubleClicked.connect(self.open_history);self.tabs.addTab(self.history,'История файлов');bar=QHBoxLayout();self.generate_button=button(bar,'Сформировать / переформировать ИД',self.generate);self.generate_button.setProperty('type','primary');button(bar,'Печатать сертификаты',self.print_certificates);button(bar,'Теги и значения',self.show_tags);button(bar,'Обновить',self.load_data);l.addLayout(bar);self.status=QLabel();self.status.setWordWrap(True);l.addWidget(self.status);self.timer=QTimer(self);self.timer.setInterval(150);self.timer.timeout.connect(self.poll);self.load_data()
    def open_history(self,r,c):
        from .platform_utils import open_local
        path=template_domain.path(db,self.history.item(r,2).text())
        if path.is_file():open_local(str(path))
        else:QMessageBox.warning(self,'Файл','Файл недоступен: '+str(path))
    def load_data(self):
        history=db.fetchall('SELECT title,updated_at,file_path FROM dossier_files WHERE dossier_id=? ORDER BY id DESC',(self.did,));self.history.setRowCount(len(history))
        for r,row in enumerate(history):
            for c,v in enumerate(row):item=QTableWidgetItem(str(v));item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.history.setItem(r,c,item)
        selected={r[0] for r in db.fetchall('SELECT slot FROM dossier_selection WHERE dossier_id=?',(self.did,))};self.templates=domain.templates(db,self.did);self.docs.setRowCount(len(self.templates))
        for r,t in enumerate(self.templates):
            item=QTableWidgetItem();item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if t['slot'] in selected else Qt.CheckState.Unchecked);self.docs.setItem(r,0,item)
            for c,v in enumerate((t['label'],t['file_path'] or 'Подключите в настройках шаблонов'),1):item=QTableWidgetItem(v);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.docs.setItem(r,c,item)
        self.cert_rows=domain.certificates(db,self.did);self.certs.setRowCount(len(self.cert_rows))
        for r,c in enumerate(self.cert_rows):
            for col,k in enumerate(('name','number','source','path')):item=QTableWidgetItem(c[k]);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.certs.setItem(r,col,item)
        try:
            folder=domain.folder(db,self.did);self.tree.setVisible(folder.exists());self.tree.setRootIndex(self.model.setRootPath(str(folder)));self.status.setText(str(folder)+(' · Комплект ещё не сформирован' if not folder.exists() else ''))
        except ValueError as e:self.tree.hide();self.status.setText(str(e))
    def open_file(self,index):
        from .platform_utils import open_local
        file=self.model.filePath(index)
        if Path(file).is_file():open_local(file)
    def open_contract(self):
        data=domain.row(db,self.did)
        if data['owner_type']:
            from .workspace_view import open_record
            open_record(data['owner_type'],data['owner_id'],self);self.load_data()
        else:QMessageBox.information(self,'Объект','Комплект создан для произвольного объекта без договора.')
    def choose_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'Папка договора / объекта')
        if not folder:return
        data=domain.row(db,self.did)
        if data['owner_type']:
            owner,rid=data['owner_type'],data['owner_id'];_,fields=template_domain.load_details(db,owner,rid);template_domain.save_details(db,owner,rid,folder,fields,template_domain.material_rows(db,owner,rid))
        else:db.execute('UPDATE dossiers SET folder_path=? WHERE id=?',(folder,self.did))
        self.load_data()
    def add_certificate(self):
        d=CertificatePicker(self)
        if d.exec():db.execute('INSERT OR IGNORE INTO dossier_certificates VALUES(?,?)',(self.did,d.cert_id));self.load_data()
    def remove_certificate(self):
        r=self.certs.currentRow()
        if r<0:return
        c=self.cert_rows[r]
        if not c['manual']:QMessageBox.information(self,'Сертификат договора','Автоматическая связь изменяется в карточке договора.');return
        db.execute('DELETE FROM dossier_certificates WHERE dossier_id=? AND certificate_id=?',(self.did,c['id']));self.load_data()
    def generate(self):
        if self.future:return
        with db.transaction():
            db.execute('DELETE FROM dossier_selection WHERE dossier_id=?',(self.did,))
            for r,t in enumerate(self.templates):
                if self.docs.item(r,0).checkState()==Qt.CheckState.Checked:db.execute('INSERT INTO dossier_selection VALUES(?,?)',(self.did,t['slot']))
        self.generate_button.setEnabled(False);self.status.setText('Проверка изменений и формирование…');self.future=self.pool.submit(domain.generate,db,self.did);self.timer.start()
    def poll(self):
        if not self.future or not self.future.done():return
        future=self.future;self.future=None;self.timer.stop();self.generate_button.setEnabled(True)
        try:r=future.result();self.load_data();self.status.setText(f"Обновлено: {r['changed']}; оставлено без изменений: {r['unchanged']}. {r['folder']}");self.tabs.setCurrentIndex(2)
        except Exception as e:self.status.setText(str(e));QMessageBox.warning(self,'Комплект не сформирован',str(e))
    def show_tags(self):
        from PyQt6.QtWidgets import QApplication
        ctx,tables,certs=domain.context(db,self.did);d=QDialog(self);d.setWindowTitle('Теги исполнительной документации');d.resize(850,650);l=QVBoxLayout(d);t=QTableWidget(0,2);t.setHorizontalHeaderLabels(['Тег · двойной щелчок копирует','Значение']);t.setColumnWidth(0,330);t.horizontalHeader().setStretchLastSection(True);l.addWidget(t)
        pairs=[('{{'+k+'}}',str(v)) for k,v in sorted(ctx.items())]
        for key,rows in tables.items():
            if rows:pairs.extend(('{{'+key+'.'+col+'}}','Повторяющаяся строка') for col in rows[0])
        t.setRowCount(len(pairs))
        for r,pair in enumerate(pairs):
            for c,v in enumerate(pair):t.setItem(r,c,QTableWidgetItem(v))
        t.cellDoubleClicked.connect(lambda r,c:QApplication.clipboard().setText(t.item(r,0).text()));d.exec()
    def print_certificates(self):
        import os
        if os.name!='nt':QMessageBox.information(self,'Печать','Пакетная печать доступна в Windows при установленной программе для соответствующего типа файлов. Здесь откройте сертификаты и отправьте их на печать из просмотрщика.');return
        certs=domain.certificates(db,self.did)
        if not certs:return
        if QMessageBox.question(self,'Печать',f'Отправить {len(certs)} сертификатов на принтер по умолчанию?')!=QMessageBox.StandardButton.Yes:return
        from .platform_utils import open_local
        errors=[]
        for c in certs:
            try:
                p=template_domain.path(db,c['path'])
                if not p.is_file():raise ValueError('Файл недоступен')
                open_local(str(p),'print')
            except Exception as e:errors.append(c['name']+': '+str(e))
        self.status.setText('\n'.join(errors) if errors else 'Файлы переданы системным приложениям для печати; проверьте очередь принтера.')
    def reject(self):
        if self.future and not self.future.done():return
        self.pool.shutdown(wait=False);super().reject()
    def closeEvent(self,event):
        if self.future and not self.future.done():event.ignore()
        else:self.pool.shutdown(wait=False);event.accept()
class DossierCreateDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.did=None;self.setWindowTitle('Создать исполнительную документацию');self.resize(700,550);l=QVBoxLayout(self);self.module=QComboBox();self.module.addItems(['ГСН','ГСВ']);l.addWidget(self.module);self.mode=QComboBox();self.mode.addItems(['Существующий договор','Новый договор','Произвольный объект']);l.addWidget(self.mode);self.source=QComboBox();self.source.addItem('ГСВ · монтаж','contracts');self.source.addItem('ГСВ · проектирование','gsv_projects');l.addWidget(self.source);self.search=QLineEdit();self.search.setPlaceholderText('Номер / название объекта или произвольное название');l.addWidget(self.search);self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Договор','Объект']);self.table.horizontalHeader().setStretchLastSection(True);l.addWidget(self.table,1);b=QPushButton('Продолжить');b.clicked.connect(self.create);l.addWidget(b)
        for w in (self.module,self.source,self.mode):w.currentIndexChanged.connect(self.load)
        self.search.textChanged.connect(self.load);self.load()
    def load(self,*_):
        self.source.setVisible(self.module.currentText()=='ГСВ');self.table.setVisible(self.mode.currentIndex()==0);owner='gsn_projects' if self.module.currentText()=='ГСН' else self.source.currentData();name='title' if owner=='gsn_projects' else 'object_name';rows=db.fetchall(f"SELECT id,contract_number,{name} FROM {owner} WHERE LOWER(coalesce(contract_number,'')||' '||coalesce({name},'')) LIKE ? ORDER BY id DESC LIMIT 200",('%'+self.search.text().casefold()+'%',));self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,v in enumerate(row[1:]):item=QTableWidgetItem(str(v or ''));item.setData(Qt.ItemDataRole.UserRole,row[0]);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(r,c,item)
    def create(self):
        owner='gsn_projects' if self.module.currentText()=='ГСН' else self.source.currentData();rid=None
        try:
            if self.mode.currentIndex()==0:
                r=self.table.currentRow()
                if r<0:raise ValueError('Выберите договор')
                rid=self.table.item(r,0).data(Qt.ItemDataRole.UserRole)
            elif self.mode.currentIndex()==1:
                if owner=='gsn_projects':
                    from .gsn_view import GsnContractDialog
                    card=GsnContractDialog(parent=self);card.exec();rid=card.rid
                elif owner=='contracts':
                    from .contract_card import ContractCardDialog
                    card=ContractCardDialog(parent=self);card.exec();rid=card.contract_id
                else:
                    from .gsv_view import ProjectEditDialog
                    card=ProjectEditDialog(parent=self);card.exec();rid=card.project_id
                if not rid:return
            else:owner=None
            self.did=domain.create(db,self.module.currentText(),owner,rid,self.search.text());self.accept()
        except Exception as e:QMessageBox.warning(self,'Создание ИД',str(e))
class DossierRegistry(QWidget):
    def __init__(self):
        super().__init__();l=QVBoxLayout(self);self.pager=RegistryPager(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Поиск по объекту');bar.addWidget(self.search,1);self.module=QComboBox();self.module.addItems(['Все разделы','ГСН','ГСВ']);bar.addWidget(self.module);button(bar,'Создать документацию',self.create);button(bar,'Открыть',self.open);l.addLayout(bar);self.table=QTableWidget(0,4);self.table.setHorizontalHeaderLabels(['Объект','Раздел','Создан','Файлов в истории']);self.table.setColumnWidth(0,430);self.table.horizontalHeader().setStretchLastSection(True);l.addWidget(self.table,1);self.search.textChanged.connect(self.load_data);self.module.currentIndexChanged.connect(self.load_data);self.table.cellDoubleClicked.connect(self.open);self.load_data()
    def load_data(self,*_):
        rows=self.pager.fetch("SELECT d.id,d.title,d.module,d.created_at,(SELECT count(*) FROM dossier_files f WHERE f.dossier_id=d.id) files FROM dossiers d WHERE LOWER(d.title) LIKE ? AND (?='' OR d.module=?) ORDER BY d.id DESC",('%'+self.search.text().casefold()+'%',self.module.currentText() if self.module.currentIndex() else '',self.module.currentText()));self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,v in enumerate(row[1:]):item=QTableWidgetItem(str(v));item.setData(Qt.ItemDataRole.UserRole,row[0]);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(r,c,item)
    def create(self):
        d=DossierCreateDialog(self)
        if d.exec():DossierDialog(d.did,self).exec();self.load_data()
    def open(self,*_):
        r=self.table.currentRow()
        if r>=0:DossierDialog(self.table.item(r,0).data(Qt.ItemDataRole.UserRole),self).exec();self.load_data()
    def load_projects(self):self.load_data()
class DossierTemplates(QWidget):
    def __init__(self):
        super().__init__();l=QVBoxLayout(self);bar=QHBoxLayout();self.module=QComboBox();self.module.addItems(['ГСН','ГСВ']);bar.addWidget(self.module);button(bar,'Подключить / заменить шаблон',self.edit);button(bar,'Добавить вид документа',self.add);l.addLayout(bar);self.info=QLabel('ГСН и ГСВ настраиваются отдельно. Для ГСВ список изначально пуст: добавляйте только свои виды документов.');self.info.setWordWrap(True);l.addWidget(self.info);self.table=QTableWidget(0,2);self.table.setHorizontalHeaderLabels(['Документ','Шаблон']);self.table.setColumnWidth(0,430);self.table.horizontalHeader().setStretchLastSection(True);l.addWidget(self.table,1);self.module.currentIndexChanged.connect(self.load_data);self.table.cellDoubleClicked.connect(self.edit);self.load_data()
    def load_data(self,*_):
        self.rows=db.fetchall('SELECT id,label,file_path FROM executive_templates WHERE module=? ORDER BY id',(self.module.currentText(),));self.table.setRowCount(len(self.rows))
        for r,row in enumerate(self.rows):
            for c,v in enumerate(row[1:]):item=QTableWidgetItem(v or 'Не подключён');item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(r,c,item)
    def edit(self,*_):
        r=self.table.currentRow()
        if r<0:return
        file,_=QFileDialog.getOpenFileName(self,'Шаблон документа','','Word / Excel (*.docx *.xlsx)')
        if file:db.execute('UPDATE executive_templates SET file_path=? WHERE id=?',(file,self.rows[r][0]));self.load_data()
    def add(self):
        name,ok=QInputDialog.getText(self,'Вид документа','Название')
        if ok and name.strip():
            import uuid
            db.execute('INSERT INTO executive_templates(module,slot,label,output_name) VALUES(?,?,?,?)',(self.module.currentText(),uuid.uuid4().hex,name.strip(),name.strip()));self.load_data()
class ContractDossiers(QWidget):
    def __init__(self,owner,workspace,save_callback):
        super().__init__();self.owner=owner;self.workspace=workspace;self.save_callback=save_callback;l=QVBoxLayout(self);l.addWidget(QLabel('Исполнительная документация формируется и хранится в отдельном разделе программы.'));bar=QHBoxLayout();bar.addWidget(workspace.folder,1);button(bar,'Папка договора',workspace.choose_folder);l.addLayout(bar);self.list=QTableWidget(0,2);self.list.setHorizontalHeaderLabels(['Комплект','Создан']);self.list.horizontalHeader().setStretchLastSection(True);l.addWidget(self.list,1);bar=QHBoxLayout();button(bar,'Перейти к исполнительной документации',self.open);button(bar,'Обновить перечень',self.load_data);l.addLayout(bar)
    def load_data(self):
        rows=db.fetchall('SELECT id,title,created_at FROM dossiers WHERE owner_type=? AND owner_id=? ORDER BY id DESC',(self.owner,self.workspace.rid));self.list.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,v in enumerate(row[1:]):item=QTableWidgetItem(str(v));item.setData(Qt.ItemDataRole.UserRole,row[0]);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.list.setItem(r,c,item)
    def open(self):
        if not self.save_callback():return
        r=self.list.currentRow();did=self.list.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else None
        if not did:
            found=db.fetchone('SELECT id FROM dossiers WHERE owner_type=? AND owner_id=? ORDER BY id DESC LIMIT 1',(self.owner,self.workspace.rid));did=found[0] if found else domain.create(db,'ГСН' if self.owner=='gsn_projects' else 'ГСВ',self.owner,self.workspace.rid)
        host=self.parent();dialogs=[]
        while host is not None and not hasattr(host,'tabs_buttons'):
            if isinstance(host,QDialog):dialogs.append(host)
            host=host.parent()
        if host is not None and len(dialogs)==1:
            for i,view in enumerate(host.views):
                if getattr(view,'_tab_id',None)=='exec':
                    dialogs[0].accept();host.switch_tab(i,host.tabs_buttons[i]);registry=host.views[i].tabs.widget(0)
                    QTimer.singleShot(0,lambda:DossierDialog(did,registry).exec());return
        DossierDialog(did,self).exec();self.load_data()
