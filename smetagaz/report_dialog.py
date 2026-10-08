"""One template workflow for estimates, contracts, clients and reports."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QFileDialog,QInputDialog,QMessageBox,QTableWidget,QTableWidgetItem,QLineEdit,QAbstractItemView,QApplication
from PyQt6.QtCore import QTimer,Qt
from .database import db
from . import report_templates as reports
SCHEMAS={'items':('index','name','item_type','unit','quantity','price','amount'),'payments':('index','date','amount'),'materials':('index','name','unit','quantity','certificate_name','certificate_number'),'contracts':('index','number','date','object_name','amount'),'months':('index','month','total','paid'),'estimates':('index','title','date','client_name','total','paid'),'works':('index','name','unit','quantity','price','amount','has_breakdown','wage_unit','overhead_unit','profit_unit','social_unit','other_unit','tax_unit','wage_sum','overhead_sum','profit_sum','social_sum','other_sum','tax_sum')}
class ReportTemplateDialog(QDialog):
    def __init__(self,kind,rid=None,parent=None,filters=None):
        super().__init__(parent);self.kind=kind;self.rid=rid;self.filters=filters or {};self.key=f'{kind}:{rid or "report"}';self.future=None;self.pool=ThreadPoolExecutor(max_workers=1)
        self.setWindowTitle('Документ по шаблону · '+reports.KINDS[kind]);self.resize(980,720);layout=QVBoxLayout(self)
        title=QLabel(reports.KINDS[kind]);title.setObjectName('pageTitle');layout.addWidget(title)
        if kind=='estimates':
            self.author=QLineEdit();row=db.fetchone('SELECT prepared_by FROM estimates WHERE id=?',(rid,));self.author.setText((row[0] if row else '') or db.get_setting('estimate_prepared_by',''));self.author.setPlaceholderText('Кто составил смету — ФИО / должность');self.author.editingFinished.connect(self.save_author);layout.addWidget(self.author)
        self.info=QLabel('Подключите свой Word или Excel. Скопируйте теги в нужные места документа.\nСтрока таблицы с {{items.name}} повторяется для каждой позиции. Итоги уже рассчитаны программой.');self.info.setWordWrap(True);layout.addWidget(self.info)
        bar=QHBoxLayout();self.combo=QComboBox();bar.addWidget(self.combo,1)
        for label,fn in [('Подключить шаблон',self.add),('Заменить файл',self.edit),('Убрать из списка',self.remove)]:b=QPushButton(label);b.clicked.connect(fn);bar.addWidget(b)
        layout.addLayout(bar);self.search=QLineEdit();self.search.setPlaceholderText('Найти тег по названию или значению');self.search.textChanged.connect(self.filter_tags);layout.addWidget(self.search)
        self.tags=QTableWidget(0,2);self.tags.setHorizontalHeaderLabels(['Тег — двойной щелчок, чтобы скопировать','Значение / таблица']);self.tags.setColumnWidth(0,390);self.tags.horizontalHeader().setStretchLastSection(True);self.tags.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.tags.cellDoubleClicked.connect(self.copy_tag);layout.addWidget(self.tags,1)
        bar=QHBoxLayout();b=QPushButton('Обновить значения');b.clicked.connect(self.load_tags);bar.addWidget(b);b=QPushButton('Проверить шаблон');b.clicked.connect(self.validate);bar.addWidget(b)
        if kind not in ('balances','statistics','payment_report','estimate_breakdown'):
            b=QPushButton('Стандартный экспорт / PDF');b.clicked.connect(self.legacy);bar.addWidget(b)
        self.run_button=QPushButton('Сформировать документ');self.run_button.setProperty('type','primary');self.run_button.clicked.connect(self.run);bar.addWidget(self.run_button);layout.addLayout(bar);self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.timer=QTimer(self);self.timer.setInterval(100);self.timer.timeout.connect(self.poll);self.reload();self.load_tags()
    def save_author(self):
        if self.kind=='estimates':db.execute('UPDATE estimates SET prepared_by=? WHERE id=?',(self.author.text().strip(),self.rid))
    def reload(self,selected=None):
        if selected is None:
            row=db.fetchone('SELECT template_id FROM report_preferences WHERE record_key=?',(self.key,));selected=row[0] if row else None
        self.combo.clear()
        for rid,name,file in db.fetchall('SELECT id,name,file_path FROM report_templates WHERE kind=? ORDER BY name,id',(self.kind,)):self.combo.addItem(name,rid);self.combo.setItemData(self.combo.count()-1,file,Qt.ItemDataRole.ToolTipRole)
        if selected:self.combo.setCurrentIndex(max(0,self.combo.findData(selected)))
        self.run_button.setEnabled(self.combo.count()>0)
    def add(self):
        path,_=QFileDialog.getOpenFileName(self,'Подключить шаблон','','Word / Excel (*.docx *.xlsx)')
        if not path:return
        name,ok=QInputDialog.getText(self,'Название шаблона','Название',text=Path(path).stem)
        if ok and name.strip():rid=db.execute('INSERT INTO report_templates(kind,name,file_path) VALUES(?,?,?)',(self.kind,name.strip(),path)).lastrowid;self.reload(rid)
    def edit(self):
        rid=self.combo.currentData()
        if not rid:return
        path,_=QFileDialog.getOpenFileName(self,'Заменить файл шаблона','','Word / Excel (*.docx *.xlsx)')
        if path:db.execute('UPDATE report_templates SET file_path=? WHERE id=?',(path,rid));self.reload(rid)
    def remove(self):
        rid=self.combo.currentData()
        if rid and QMessageBox.question(self,'Шаблон','Убрать настройку шаблона для всех документов этого вида? Исходный файл останется на диске.')==QMessageBox.StandardButton.Yes:db.execute('DELETE FROM report_templates WHERE id=?',(rid,));self.reload()
    def load_tags(self):
        try:
            ctx,tables=reports.context(db,self.kind,self.rid,self.filters);from . import estimates_domain as ed;est=self.kind in ('estimates','estimate_breakdown');pairs=[('{{'+k+'}}',str(v)[:500]) for k,v in sorted(ctx.items()) if not (est and k in ed.HIDDEN_KEYS)]
            for key,values in tables.items():
                columns=ed.TABLE_TAGS[key][1] if est and key in ed.TABLE_TAGS else (list(values[0]) if values else list(SCHEMAS.get(key,('index','c1','c2','c3','c4','c5','c6'))))
                if self.kind=='balances' and key=='items':columns=['index','name','category','unit','balance','notes']
                for column in columns:pairs.append(('{{'+key+'.'+column+'}}',f'Повторяющаяся строка · {len(values)} записей'))
            self.tags.setRowCount(len(pairs))
            for r,pair in enumerate(pairs):
                for c,value in enumerate(pair):self.tags.setItem(r,c,QTableWidgetItem(value))
            self.filter_tags()
        except Exception as e:self.status.setText(str(e))
    def filter_tags(self):
        q=self.search.text().casefold()
        for row in range(self.tags.rowCount()):self.tags.setRowHidden(row,not any(q in self.tags.item(row,c).text().casefold() for c in range(2)))
    def copy_tag(self,r,c):QApplication.clipboard().setText(self.tags.item(r,0).text());self.status.setText('Тег скопирован: '+self.tags.item(r,0).text())
    def validate(self):
        self.save_author()
        rid=self.combo.currentData()
        if not rid:return
        try:
            import tempfile
            from .template_domain import path
            source=path(db,db.fetchone('SELECT file_path FROM report_templates WHERE id=?',(rid,))[0])
            with tempfile.TemporaryDirectory() as temp:reports.export(db,self.kind,self.rid,rid,Path(temp)/('check'+source.suffix),self.filters)
            self.status.setText('Проверка пройдена. Все используемые теги распознаны.')
        except Exception as e:self.status.setText('Ошибка: '+str(e))
    def run(self):
        self.save_author()
        tid=self.combo.currentData()
        if not tid or self.future:return
        row=db.fetchone('SELECT file_path FROM report_templates WHERE id=?',(tid,));ext=Path(row[0]).suffix.lower();path,_=QFileDialog.getSaveFileName(self,'Готовый документ',reports.KINDS[self.kind]+ext,f'{ext.upper()} (*{ext})')
        if not path:return
        if not path.lower().endswith(ext):path+=ext
        db.execute('INSERT INTO report_preferences(record_key,template_id) VALUES(?,?) ON CONFLICT(record_key) DO UPDATE SET template_id=excluded.template_id',(self.key,tid));self.run_button.setEnabled(False);self.status.setText('Создание документа…');self.future=self.pool.submit(reports.export,db,self.kind,self.rid,tid,path,self.filters);self.timer.start()
    def poll(self):
        if not self.future or not self.future.done():return
        future=self.future;self.future=None;self.timer.stop();self.run_button.setEnabled(True)
        try:self.status.setText('Сохранено: '+future.result())
        except Exception as e:self.status.setText('Ошибка: '+str(e))
    def legacy(self):
        if self.kind in ('stock_acts','defect_acts'):
            from .stock_exports import LegacyStockExportDialog
            LegacyStockExportDialog(self.kind,self.rid,self).exec()
        else:
            from .workspace_view import LegacyExportDialog
            LegacyExportDialog(self.kind,self.rid,self).exec()
    def reject(self):
        if self.future and not self.future.done():return
        self.pool.shutdown(wait=False);super().reject()
    def closeEvent(self,event):
        if self.future and not self.future.done():event.ignore()
        else:self.pool.shutdown(wait=False);event.accept()
