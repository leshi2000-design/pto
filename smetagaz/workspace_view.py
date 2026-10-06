"""Paged SQL registry, shared client picker and per-document export UI."""
import json
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QPushButton,QLabel,QLineEdit,QComboBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QDialogButtonBox,QMessageBox,QFileDialog,QSpinBox,QCheckBox,QListWidget,QListWidgetItem)
from PyQt6.QtCore import Qt,QTimer
from .database import db
from .data_services import SOURCES,link_client
from .exports import get_profile,record_data,export_record,LABELS

class LegacyExportDialog(QDialog):
    def __init__(self,table,rid,parent=None):
        super().__init__(parent);self.table=table;self.rid=rid;self.key=f'{table}:{rid}'
        self.setWindowTitle('Настройки экспорта документа');self.resize(520,650)
        opts=get_profile(db,self.key);layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.title=QLineEdit(opts['title']);form.addRow('Заголовок',self.title)
        self.company=QLineEdit(opts['company']);form.addRow('Организация',self.company)
        self.font=QLineEdit(opts['font']);form.addRow('Шрифт Word / Excel',self.font)
        self.size=QSpinBox();self.size.setRange(6,24);self.size.setValue(opts['font_size']);form.addRow('Размер шрифта',self.size)
        self.margin=QSpinBox();self.margin.setRange(5,40);self.margin.setValue(opts['margin_mm']);form.addRow('Поля Word / PDF, мм',self.margin)
        self.landscape=QCheckBox('Альбомная ориентация');self.landscape.setChecked(opts['landscape']);layout.addWidget(self.landscape)
        self.private=QCheckBox('Включить телефон, адрес и паспорт');self.private.setChecked(opts['include_private']);layout.addWidget(self.private)
        layout.addWidget(QLabel('Поля документа (позиции сметы добавляются автоматически):'))
        self.columns=QListWidget();layout.addWidget(self.columns)
        data,_=record_data(db,table,rid)
        for k in data:
            item=QListWidgetItem(LABELS.get(k,k));item.setData(Qt.ItemDataRole.UserRole,k)
            item.setCheckState(Qt.CheckState.Checked if not opts['columns'] or k in opts['columns'] else Qt.CheckState.Unchecked);self.columns.addItem(item)
        self.format=QComboBox();self.format.addItems(['docx','xlsx','pdf']);form.addRow('Формат',self.format)
        self.status=QLabel('PDF использует встроенный шрифт с кириллицей.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.button=QPushButton('Сохранить настройки и экспортировать');self.button.clicked.connect(self.run);layout.addWidget(self.button)
        self.pool=ThreadPoolExecutor(max_workers=1);self.future=None
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll)
    def run(self):
        opts=dict(title=self.title.text(),company=self.company.text(),font=self.font.text() or 'Arial',font_size=self.size.value(),margin_mm=self.margin.value(),landscape=self.landscape.isChecked(),include_private=self.private.isChecked(),columns=[self.columns.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.columns.count()) if self.columns.item(i).checkState()==Qt.CheckState.Checked])
        if not opts['columns']:QMessageBox.warning(self,'Поля','Выберите хотя бы одно поле');return
        ext=self.format.currentText();path,_=QFileDialog.getSaveFileName(self,'Экспорт',f'document_{self.rid}.{ext}',f'{ext.upper()} (*.{ext})')
        if not path:return
        if not path.lower().endswith('.'+ext):path+='.'+ext
        db.execute('INSERT INTO export_profiles VALUES(?,?) ON CONFLICT(record_key) DO UPDATE SET options=excluded.options',(self.key,json.dumps(opts,ensure_ascii=False)))
        self.button.setEnabled(False);self.status.setText('Создание файла…')
        self.future=self.pool.submit(export_record,db,self.table,self.rid,path,opts);self.timer.start(100)
    def poll(self):
        if not self.future or not self.future.done():return
        self.timer.stop();self.button.setEnabled(True)
        try:self.status.setText('Сохранено: '+self.future.result())
        except Exception as e:self.status.setText('Ошибка: '+str(e))
    def reject(self):
        if self.future and not self.future.done():return
        self.pool.shutdown(wait=False);super().reject()

class ClientPicker(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('Выбрать клиента');self.resize(700,500);self.client_id=None
        layout=QVBoxLayout(self);self.view=WorkspaceView('crm.clients',picker=True);layout.addWidget(self.view)
        btn=QPushButton('Выбрать');btn.clicked.connect(self.choose);layout.addWidget(btn)
    def choose(self):
        self.client_id=self.view.selected_id()
        if self.client_id:self.accept()

class RecordDialog(QDialog):
    def __init__(self,table,rid=None,parent=None):
        super().__init__(parent);self.table=table;self.rid=rid;self.setWindowTitle('Карточка');self.resize(650,500)
        layout=QVBoxLayout(self);form=QFormLayout();self.inputs={}
        fields={'crm.clients':['name','phone','address','passport','passport_issuer','passport_date','notes'],'gsn_projects':['title','address','notes'],'welders':['name','certificate','notes'],'writeoffs':['title','notes']}[table]
        row=db.fetchone(f'SELECT {",".join(fields)} FROM {table} WHERE id=?',(rid,)) if rid else None
        for i,k in enumerate(fields):
            value=str(row[i] or '') if row else ''
            if table=='crm.clients' and k=='phone':
                from .domain_widgets import PhonesEditor
                inp=PhonesEditor();inp.setText(value)
            elif table=='crm.clients' and k=='passport_date':
                from .domain_widgets import OptionalDate
                inp=OptionalDate();inp.set_value(value)
            else:inp=QLineEdit(value)
            self.inputs[k]=inp;form.addRow(LABELS.get(k) or {'passport_issuer':'Кем выдан','passport_date':'Дата выдачи'}.get(k,k),inp)
        if table=='crm.clients' and rid:
            # карточка клиента: его данные и файлы папок всех его договоров
            from PyQt6.QtWidgets import QTabWidget
            from .client_files import ClientFilesWidget
            data=QWidget();data.setLayout(form);tabs=QTabWidget();self.tabs=tabs;tabs.addTab(data,'Данные клиента');tabs.addTab(ClientFilesWidget(rid),'Файлы договоров');layout.addWidget(tabs);self.resize(780,560)
        else:layout.addLayout(form)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject)
        if table=='crm.clients' and rid:
            remove=buttons.addButton('Удалить клиента',QDialogButtonBox.ButtonRole.DestructiveRole);remove.clicked.connect(self.remove_client)
        layout.addWidget(buttons)
    def field_text(self,key):
        from .domain_widgets import OptionalDate
        w=self.inputs[key]
        return w.value() if isinstance(w,OptionalDate) else w.text().strip()
    def remove_client(self):
        if confirm_delete_client(self,self.rid):self.done(2)
    def save(self):
        fields=list(self.inputs);values=[self.field_text(k) for k in fields]
        if not values[0]:QMessageBox.warning(self,'Ошибка','Укажите название / имя');return
        if self.table=='crm.clients':
            key=' '.join(values[0].split()).casefold()
            twin=[r for r in db.fetchall('SELECT id,name FROM crm.clients WHERE id IS NOT ?',(self.rid,)) if ' '.join((r[1] or '').split()).casefold()==key]
            if twin and QMessageBox.question(self,'Такой клиент уже есть','Клиент с таким ФИО уже есть в базе. Всё равно сохранить?')!=QMessageBox.StandardButton.Yes:return
        with db.transaction():
            if self.rid:db.execute(f'UPDATE {self.table} SET '+','.join(f'{k}=?' for k in fields)+' WHERE id=?',(*values,self.rid))
            else:self.rid=db.execute(f'INSERT INTO {self.table} ({",".join(fields)}) VALUES ({",".join("?" for _ in fields)})',values).lastrowid
        self.accept()

def confirm_delete_client(parent,cid):
    """Подтверждение и удаление клиента с обезличиванием его договоров. True — клиент удалён."""
    from .data_services import client_links,delete_client
    row=db.fetchone('SELECT name FROM crm.clients WHERE id=?',(cid,))
    if not row:return False
    links=client_links(db,cid)
    text=f'Удалить клиента «{row[0]}»?'
    if links:
        text+='\n\nКлиент используется:\n'+'\n'.join(f'• {label}: {n}' for label,n in links.items())
        text+='\n\nДоговоры, суммы, оплаты и файлы останутся, но ФИО, телефон, паспорт и адрес клиента в них будут стёрты. Это нельзя отменить.'
    else:text+='\n\nЭто нельзя отменить.'
    if QMessageBox.question(parent,'Удаление клиента',text)!=QMessageBox.StandardButton.Yes:return False
    try:delete_client(db,cid)
    except ValueError as e:QMessageBox.warning(parent,'Удаление клиента',str(e));return False
    return True

class WorkspaceView(QWidget):
    def __init__(self,initial='estimates',picker=False):
        super().__init__();self.offset=0;self.page_size=100;self.picker=picker
        layout=QVBoxLayout(self);bar=QHBoxLayout();layout.addLayout(bar)
        self.source=QComboBox()
        for key,(label,*_) in SOURCES.items():self.source.addItem(label,key)
        self.source.setCurrentIndex(self.source.findData(initial));bar.addWidget(self.source)
        from .filters import SqlFilters
        self.filters=SqlFilters(self);bar.addWidget(self.filters);self.filters.changed.connect(self.reset)
        self.query=QLineEdit();self.query.setPlaceholderText('Поиск в реестре…');bar.addWidget(self.query)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(300);self.timer.timeout.connect(self.reset)
        self.query.textChanged.connect(lambda:self.timer.start());self.source.currentIndexChanged.connect(self.reset)
        actions=QHBoxLayout();layout.addLayout(actions)
        for label,fn in [('Открыть / изменить',self.open),('Создать',self.create),('Связать с клиентом',self.assign),('Экспорт…',self.export)]:
            b=QPushButton(label);b.clicked.connect(fn);actions.addWidget(b)
        self.delete_button=QPushButton('Удалить клиента');self.delete_button.setProperty('type','danger');self.delete_button.clicked.connect(self.delete_client);actions.addWidget(self.delete_button)
        self.table=QTableWidget();self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.table.cellDoubleClicked.connect(lambda *_:self.open());layout.addWidget(self.table)
        nav=QHBoxLayout();layout.addLayout(nav);self.prev=QPushButton('← Назад');self.next=QPushButton('Далее →');self.label=QLabel();nav.addWidget(self.prev);nav.addWidget(self.label);nav.addWidget(self.next)
        self.prev.clicked.connect(lambda:self.page(-1));self.next.clicked.connect(lambda:self.page(1))
        self.source.setEnabled(not picker);self.load_data()
    def reset(self,*_):self.offset=0;self.load_data()
    def delete_client(self):
        rid=self.selected_id()
        if rid and self.source.currentData()=='crm.clients' and confirm_delete_client(self,rid):self.load_data()
    def page(self,direction):self.offset=max(0,self.offset+direction*self.page_size);self.load_data()
    def selected_id(self):
        row=self.table.currentRow();return self.table.item(row,0).data(Qt.ItemDataRole.UserRole) if row>=0 else None
    def load_data(self):
        source=self.source.currentData()
        if not source:return
        self.delete_button.setVisible(source=='crm.clients' and not self.picker)
        if source=='crm.clients':cols=['id','name','phone'];fields=['name','phone']
        else:
            _,title,fields=SOURCES[source];cols=list(dict.fromkeys(['id',title,*fields[:3]]))
        params=[];where=''
        if self.query.text().strip():
            pattern='%'+self.query.text().strip().casefold().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            where=' WHERE '+' OR '.join(f'LOWER({f}) LIKE ? ESCAPE \'\\\'' for f in fields);params=[pattern]*len(fields)
        all_cols=[r[1] for r in db.fetchall('PRAGMA '+('crm.table_info(clients)' if source=='crm.clients' else f'table_info({source})'))]
        self.filters.set_columns(all_cols)
        query,params=self.filters.apply(f'SELECT * FROM {source}{where} ORDER BY id DESC',params)
        rows=db.fetchall('SELECT '+','.join(cols)+' FROM ('+query+') LIMIT ? OFFSET ?',(*params,self.page_size+1,self.offset))
        self.next.setEnabled(len(rows)>self.page_size);rows=rows[:self.page_size];self.prev.setEnabled(self.offset>0)
        self.table.setUpdatesEnabled(False);self.table.setColumnCount(len(cols));self.table.setHorizontalHeaderLabels([LABELS.get(k,k) for k in cols]);self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row):
                item=QTableWidgetItem(str(value if value is not None else ''));item.setData(Qt.ItemDataRole.UserRole,row[0]);self.table.setItem(r,c,item)
        self.table.setColumnWidth(0,60)
        if len(cols)>1:self.table.setColumnWidth(1,340)
        if len(cols)>2:self.table.setColumnWidth(2,240)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.horizontalHeader().setStretchLastSection(True);self.table.setUpdatesEnabled(True)
        self.label.setText(f'Строки {self.offset+1 if rows else 0}–{self.offset+len(rows)}')
    def open(self):
        rid=self.selected_id()
        if rid:open_record(self.source.currentData(),rid,self);self.load_data()
    def create(self):
        source=self.source.currentData()
        if source=='welders':
            from .welding_view import WelderDialog
            WelderDialog(parent=self).exec();self.reset()
        elif source=='gsn_projects':
            from .gsn_view import GsnContractDialog
            GsnContractDialog(parent=self).exec();self.reset()
        elif source in ['crm.clients','writeoffs']:RecordDialog(source,parent=self).exec();self.reset()
        else:QMessageBox.information(self,'Создание','Создайте запись в соответствующем разделе основного меню.')
    def assign(self):
        rid=self.selected_id()
        if not rid:return
        d=ClientPicker(self)
        if d.exec():
            try:link_client(db,self.source.currentData(),rid,d.client_id);self.load_data()
            except ValueError as e:QMessageBox.warning(self,'Связь с клиентом',str(e))
    def export(self):
        rid=self.selected_id()
        if rid:
            if self.source.currentData() in ('stock_acts','defect_acts'):
                from .stock_exports import StockExportDialog
                StockExportDialog(self.source.currentData(),rid,self).exec()
            else:ExportDialog(self.source.currentData(),rid,self).exec()

def open_record(table,rid,parent=None):
    if table=='estimates':
        from .estimate_editor import EstimateEditorDialog
        row=db.fetchone('SELECT title FROM estimates WHERE id=?',(rid,))
        if row:EstimateEditorDialog(rid,row[0] or '',parent).exec()
    elif table=='contracts':
        from .contract_card import ContractCardDialog
        ContractCardDialog(contract_id=rid,parent=parent).exec()
    elif table=='gsv_projects':
        from .gsv_view import ProjectEditDialog
        ProjectEditDialog(rid,parent=parent).exec()
    elif table=='materials':
        from .material_card import MaterialCardDialog
        MaterialCardDialog(rid,parent).exec()
    elif table=='certificates':
        from .executive_view import CertificateEditDialog
        CertificateEditDialog(rid,parent).exec()
    elif table=='welders':
        from .welding_view import WelderDialog
        WelderDialog(rid,parent).exec()
    elif table in ('stock_acts','defect_acts','stock_materials','norm_profiles'):
        from .stock_view import ActDialog,DefectDialog,MaterialDialog,NormDialog
        {'stock_acts':ActDialog,'defect_acts':DefectDialog,'stock_materials':MaterialDialog,'norm_profiles':NormDialog}[table](rid,parent=parent).exec()
    elif table=='welding_jobs':
        from .welding_view import JobDialog
        JobDialog(rid,parent=parent).exec()
    elif table=='welding_documents':
        from .welding_documents import DocumentDialog
        DocumentDialog(rid,parent=parent).exec()
    elif table=='gsv_pipelines':
        from .gsv_catalog import PipelineDialog
        PipelineDialog(rid,parent).exec()
    elif table=='gsn_projects':
        from .gsn_view import GsnContractDialog
        GsnContractDialog(rid,parent).exec()
    elif table in ['crm.clients','writeoffs']:RecordDialog(table,rid,parent).exec()
    else:
        data,_=record_data(db,table,rid);d=QDialog(parent);d.setWindowTitle('Карточка записи');layout=QVBoxLayout(d)
        for k,v in data.items():
            label=QLabel(f'{LABELS.get(k,k)}: {v if v is not None else ""}');label.setWordWrap(True);label.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(label)
        d.resize(600,500);d.exec()

def choose_client(parent,table,rid):
    if not rid:
        QMessageBox.information(parent,'Клиент','Сначала сохраните новую запись, затем выберите клиента.');return
    dialog=ClientPicker(parent)
    if not dialog.exec():return
    link_client(db,table,rid,dialog.client_id)
    row=db.fetchone('SELECT name,phone,address,passport FROM crm.clients WHERE id=?',(dialog.client_id,))
    if table=='estimates':parent.load_meta()
    elif table=='gsv_projects':
        parent.txt_client.setText(row[0]);parent.txt_phone.setText(row[1]);parent.txt_passport.setPlainText(row[3] or '')
        db.execute('UPDATE gsv_projects SET passport=? WHERE id=?',(row[3],rid))
    elif table=='contracts':
        parent.inp_phone.setText(row[1]);parent.inp_address.setText(row[2] or '');parent.inp_passport_num.setText(row[3] or '')


def ExportDialog(table,rid,parent=None):
    from .report_templates import KINDS
    if table in KINDS:
        from .report_dialog import ReportTemplateDialog
        return ReportTemplateDialog(table,rid,parent)
    return LegacyExportDialog(table,rid,parent)
