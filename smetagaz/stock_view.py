"""Writeoff workspace: documents, defects, rate profiles, material ledger and balances."""
import json
from datetime import date
from PyQt6.QtWidgets import (QWidget,QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QLabel,QPushButton,QComboBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QDialogButtonBox,QMessageBox,QTabWidget,QScrollArea,QTextEdit,QCheckBox)
from PyQt6.QtCore import Qt,QTimer
from .database import db
from .domain_widgets import OptionalDate,ObjectField
from .pagination import RegistryPager
from . import stock_domain as domain
from .gsv_domain import owner_label

STATUS={'draft':'Черновик','posted':'Проведён','reversed':'Отменён'}

def error(parent,e):QMessageBox.warning(parent,'Не удалось выполнить',str(e))
def button(bar,text,fn):
    b=QPushButton(text);b.clicked.connect(fn);bar.addWidget(b);return b

def table(headers,editable=False):
    t=QTableWidget(0,len(headers));t.setHorizontalHeaderLabels(headers);t.setAlternatingRowColors(True);t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);t.horizontalHeader().setStretchLastSection(True);t.verticalHeader().setDefaultSectionSize(34)
    if not editable:t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    return t

def text(t,r,c):return t.item(r,c).text().strip() if t.item(r,c) else ''
def item(t,r,c,value,editable=True):
    i=QTableWidgetItem(str(value if value is not None else ''))
    if not editable:i.setFlags(i.flags() & ~Qt.ItemFlag.ItemIsEditable)
    t.setItem(r,c,i);return i

def record(source,rid):
    cur=db.execute(f'SELECT * FROM {source} WHERE id=?',(rid,));row=cur.fetchone();return dict(zip([c[0] for c in cur.description],row)) if row else {}

class Choice(QComboBox):
    """Searchable selector loads at most 100 matches, plus the retained selection."""
    def __init__(self,source,selected=None):
        super().__init__();self.source=source;self.setEditable(True);self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert);self.setCompleter(None);self.setMinimumWidth(160);self.setMaxVisibleItems(16)
        self.refresh('',selected);self.lineEdit().setPlaceholderText('Введите название для поиска…');self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(250);self.timer.timeout.connect(self.search);self.lineEdit().textEdited.connect(lambda _:self.timer.start())
    def refresh(self,query,selected=None):
        rows=db.fetchall(f'SELECT id,name FROM {self.source} WHERE LOWER(name) LIKE ?'+(' AND coalesce(active,1)=1' if self.source=='stock_materials' else '')+' ORDER BY name,id LIMIT 100',('%'+query.casefold()+'%',))
        if selected and not any(r[0]==selected for r in rows):
            row=db.fetchone(f'SELECT id,name FROM {self.source} WHERE id=?',(selected,))
            if row:rows.append(row)
        self.blockSignals(True);self.clear();self.addItem('',None)
        for rid,name in rows:self.addItem(name,rid)
        self.setCurrentIndex(max(0,self.findData(selected)));self.blockSignals(False)
    def search(self):
        typed=self.currentText();self.refresh(typed);self.setEditText(typed)
        if self.lineEdit().hasFocus():self.showPopup();self.lineEdit().setFocus()
    def currentData(self,role=Qt.ItemDataRole.UserRole):
        return super().currentData(role) if self.currentIndex()>=0 and self.currentText()==self.itemText(self.currentIndex()) else None

class MaterialDialog(QDialog):
    def __init__(self,mid=None,parent=None):
        super().__init__(parent);self.mid=mid;self.setWindowTitle('Материал для списания');self.resize(580,310);l=QVBoxLayout(self);f=QFormLayout();l.addLayout(f)
        self.name=QLineEdit();self.category=QComboBox();self.category.setEditable(True);self.category.addItems(domain.CATEGORIES);self.unit=QComboBox();self.unit.setEditable(True);self.unit.addItems(['кг','м³','л','шт','м','м²']);self.notes=QLineEdit()
        for label,w in [('Наименование *',self.name),('Категория',self.category),('Единица *',self.unit),('Примечание',self.notes)]:f.addRow(label,w)
        if mid:
            d=record('stock_materials',mid);self.name.setText(d['name']);self.category.setCurrentText(d['category']);self.unit.setCurrentText(d['unit']);self.notes.setText(d['notes'])
        l.addWidget(QLabel('Остаток задаётся поступлением. Единицы нормы и остатка должны совпадать.'))
        b=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);b.accepted.connect(self.save);b.rejected.connect(self.reject);l.addWidget(b)
    def save(self):
        try:self.mid=domain.save_material(db,self.name.text(),self.category.currentText(),self.unit.currentText(),self.notes.text(),self.mid);self.accept()
        except Exception as e:error(self,e)

class ReceiptDialog(QDialog):
    def __init__(self,mid=None,parent=None):
        super().__init__(parent);self.setWindowTitle('Поступление / корректировка остатка');l=QVBoxLayout(self);f=QFormLayout();l.addLayout(f);self.material=Choice('stock_materials',mid);self.day=OptionalDate();self.day.set_value(date.today().isoformat());self.qty=QLineEdit();self.kind=QComboBox();self.kind.addItems(['Поступление / начальный остаток','Корректировка (+ или −)']);self.note=QLineEdit()
        for label,w in [('Материал',self.material),('Дата',self.day),('Операция',self.kind),('Количество в единице материала',self.qty),('Основание / накладная',self.note)]:f.addRow(label,w)
        self.info=QLabel();l.addWidget(self.info);self.material.currentIndexChanged.connect(self.show_balance);self.show_balance()
        b=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);b.accepted.connect(self.save);b.rejected.connect(self.reject);l.addWidget(b)
    def show_balance(self):
        mid=self.material.currentData();self.info.setText('Текущий остаток: '+domain.fmt(domain.balance(db,mid))+' '+domain.material(db,mid)[2] if mid else '')
    def save(self):
        try:domain.receive(db,self.material.currentData(),self.qty.text(),self.day.value(),self.note.text(),self.kind.currentIndex()==1);self.accept()
        except Exception as e:error(self,e)

class NormDialog(QDialog):
    def __init__(self,pid=None,parent=None):
        super().__init__(parent);self.pid=pid;self.setWindowTitle('Норма расхода на единицу работ');self.resize(900,630);l=QVBoxLayout(self);f=QFormLayout();l.addLayout(f);self.inputs={}
        for key,label in [('name','Название *'),('diameter','Диаметр Ду, мм'),('thickness','Толщина стенки, мм'),('notes','Источник нормы / технология')]:self.inputs[key]=QLineEdit();f.addRow(label,self.inputs[key])
        self.basis=QComboBox();self.basis.addItems(domain.BASES);f.addRow('Норма на один',self.basis)
        l.addWidget(QLabel('Пусто = норма не задана, расчёт блокируется. 0 = материал не расходуется.\n«Как списывается»: на стык — ацетилен, кислород, проволока; на объект — норма на весь объект строительства (круги — штучно); на футляр — краска и асбестовый шнур.'))
        self.table=table(['Материал','Единица','Норма','Как списывается'],True);self.table.setColumnWidth(0,350);l.addWidget(self.table,1)
        bar=QHBoxLayout();button(bar,'Добавить материал',self.add_row);button(bar,'Удалить строку',lambda:self.table.removeRow(self.table.currentRow()));l.addLayout(bar)
        if pid:
            d=record('norm_profiles',pid)
            for k,w in self.inputs.items():w.setText(d[k] or '')
            self.basis.setCurrentText(d['basis'])
            for mid,rate,per in db.fetchall('SELECT material_id,rate,per FROM norm_items WHERE profile_id=? ORDER BY id',(pid,)):self.add_row(mid,rate,per)
        b=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);b.accepted.connect(self.save);b.rejected.connect(self.reject);l.addWidget(b)
    def add_row(self,mid=None,rate=None,per=None):
        if isinstance(mid,bool):mid=None
        r=self.table.rowCount();self.table.insertRow(r);combo=Choice('stock_materials',mid);self.table.setCellWidget(r,0,combo);item(self.table,r,1,domain.material(db,mid)[2] if mid else '',False);item(self.table,r,2,rate)
        per_box=QComboBox()
        for key,label in domain.PER_LABELS.items():per_box.addItem(label,key)
        if per is None:per=domain.default_per(domain.material(db,mid)[0]) if mid else ''
        per_box.setCurrentIndex(max(0,per_box.findData(per)));self.table.setCellWidget(r,3,per_box)
        def changed():
            for row in range(self.table.rowCount()):
                if self.table.cellWidget(row,0) is combo:
                    item(self.table,row,1,domain.material(db,combo.currentData())[2] if combo.currentData() else '',False)
                    if combo.currentData() and not rate:per_box.setCurrentIndex(max(0,per_box.findData(domain.default_per(domain.material(db,combo.currentData())[0]))))
        combo.currentIndexChanged.connect(changed)
    def save(self):
        try:
            data={k:w.text().strip() for k,w in self.inputs.items()};data['basis']=self.basis.currentText();items=[(self.table.cellWidget(r,0).currentData(),text(self.table,r,2),self.table.cellWidget(r,3).currentData()) for r in range(self.table.rowCount())]
            self.pid=domain.save_profile(db,data,items,self.pid);self.accept()
        except Exception as e:error(self,e)

class Header(QWidget):
    def __init__(self,defect=False):
        super().__init__();self.defect=defect;f=QFormLayout(self);self.inputs={}
        self.number=QLineEdit();self.day=OptionalDate();self.day.set_value(date.today().isoformat());f.addRow('Номер *',self.number);f.addRow('Дата *',self.day)
        self.object_name=QLineEdit();self.object_name.setPlaceholderText('Введите произвольный объект / адрес');f.addRow('Объект *',self.object_name)
        self.listed=QComboBox();self.listed.addItem('— не выбран —',None)
        for oid,name,*_ in domain.objects(db):self.listed.addItem(name,oid)
        self.listed.setToolTip('Объекты из раздела «Объекты списания»: подставляют название, связь с договором и реквизиты по умолчанию')
        f.addRow('Объект из списка «Объекты списания»',self.listed);self.listed.currentIndexChanged.connect(self.pick_listed)
        self.reference=ObjectField();f.addRow('Необязательно: выбрать из базы',self.reference);self.reference.changed.connect(self.fill_object)
        keys=[('organization','Организация'),('approved_by','Утверждает (должность, ФИО)'),('commission','Комиссия / ответственные (ФИО)'),('reason' if defect else 'basis','Основание'),('conditions','Условия выполнения работ')] if defect else [('organization','Организация'),('approved_by','Утверждает (должность, ФИО)'),('commission','Комиссия / ответственные (ФИО)'),('basis','Основание: акт работ / документ')]
        keys.append(('notes','Примечания'))
        for key,label in keys:self.inputs[key]=QLineEdit();f.addRow(label,self.inputs[key])
        self.apply_defaults()
    def apply_defaults(self,oid=None):
        """Подставляет значения по умолчанию в пустые поля (комиссия, кто утверждает и т. д.)."""
        for key,value in domain.object_defaults(db,oid).items():
            if key in self.inputs and value and not self.inputs[key].text().strip():self.inputs[key].setText(value)
    def pick_listed(self):
        oid=self.listed.currentData()
        if not oid:return
        row=db.fetchone('SELECT name,owner_type,owner_id FROM writeoff_objects WHERE id=?',(oid,))
        if row:
            self.object_name.setText(row[0]);self.reference.set_reference(row[1],row[2]) if row[1] else self.reference.set_reference(None,None)
            for key in ('organization','approved_by','commission'):
                if key in self.inputs:self.inputs[key].clear()
            self.apply_defaults(oid)
    def fill_object(self):
        if self.reference.reference[0]:self.object_name.setText(owner_label(db,*self.reference.reference))
    def values(self):
        return dict(number=self.number.text().strip(),act_date=self.day.value(),object_name=self.object_name.text().strip(),owner_type=self.reference.reference[0],owner_id=self.reference.reference[1],**{k:w.text().strip() for k,w in self.inputs.items()})
    def fill(self,d):
        self.reference.set_reference(d.get('owner_type'),d.get('owner_id'));self.number.setText(d.get('number',''));self.day.set_value(d.get('act_date'));self.object_name.setText(d.get('object_name',''))
        for k,w in self.inputs.items():w.setText(d.get(k) or '')

class Volumes(QWidget):
    def __init__(self):
        super().__init__();l=QVBoxLayout(self);l.setContentsMargins(0,0,0,0);l.addWidget(QLabel('Выберите нормы по диаметрам и укажите число стыков. Краску и круги можно рассчитать отдельными строками.'))
        self.table=table(['Норма / вид работ','База','Объём'],True);self.table.setColumnWidth(0,480);l.addWidget(self.table,1);b=QHBoxLayout();button(b,'Добавить объём',self.add_row);button(b,'Удалить строку',lambda:self.table.removeRow(self.table.currentRow()));l.addLayout(b)
    def add_row(self,pid=None,qty=''):
        if isinstance(pid,bool):pid=None
        r=self.table.rowCount();self.table.insertRow(r);combo=Choice('norm_profiles',pid);self.table.setCellWidget(r,0,combo);item(self.table,r,2,qty)
        def changed():
            for row in range(self.table.rowCount()):
                if self.table.cellWidget(row,0) is combo:
                    p=db.fetchone('SELECT basis FROM norm_profiles WHERE id=?',(combo.currentData(),));item(self.table,row,1,p[0] if p else '',False)
        combo.currentIndexChanged.connect(changed);changed()
    def values(self):return [(self.table.cellWidget(r,0).currentData(),text(self.table,r,2)) for r in range(self.table.rowCount())]

class ActDialog(QDialog):
    def __init__(self,aid=None,parent=None):
        super().__init__(parent);self.aid=aid;self.revision=None;self.defect_id=None;self.status='draft';self.snapshot=[];self.setWindowTitle('Акт списания материалов');self.resize(1120,800)
        l=QVBoxLayout(self);self.status_label=QLabel();l.addWidget(self.status_label);self.tabs=QTabWidget();l.addWidget(self.tabs,1)
        self.header=Header();scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.header);self.tabs.addTab(scroll,'Реквизиты / объект')
        self.volumes=Volumes();self.tabs.addTab(self.volumes,'Стыки и объёмы');self.calc_button=QPushButton('Рассчитать материалы по нормам');self.calc_button.clicked.connect(self.calculate);self.volumes.layout().addWidget(self.calc_button)
        page=QWidget();pl=QVBoxLayout(page);pl.addWidget(QLabel('«По норме» и «Фактически» независимы. Проведение списывает фактический расход. Пустая норма означает ручной расход.'))
        self.lines=table(['Материал','Ед.','По норме','Фактически','Доступно сейчас','Примечание'],True);self.lines.setColumnWidth(0,310);pl.addWidget(self.lines,1);bar=QHBoxLayout();self.add_button=button(bar,'Добавить вручную',self.add_line);self.remove_button=button(bar,'Удалить строку',lambda:self.lines.removeRow(self.lines.currentRow()));pl.addLayout(bar);self.tabs.addTab(page,'Материалы к списанию')
        bar=QHBoxLayout();self.save_button=button(bar,'Сохранить черновик',self.save);self.post_button=button(bar,'Провести списание',self.post);self.reverse_button=button(bar,'Отменить проведение',self.reverse);self.copy_button=button(bar,'Исправленный черновик',self.copy);button(bar,'Word / Excel / PDF',self.export);button(bar,'Закрыть',self.accept);l.addLayout(bar)
        if aid:self.load()
        else:self.header.number.setText('СП-'+date.today().strftime('%Y%m%d')+'-'+str(db.fetchone('SELECT coalesce(max(id),0)+1 FROM stock_acts')[0]));self.state()
    def state(self):
        draft=self.status=='draft';self.header.setEnabled(draft);self.volumes.setEnabled(draft);self.lines.setEnabled(True);self.lines.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked|QAbstractItemView.EditTrigger.EditKeyPressed if draft else QAbstractItemView.EditTrigger.NoEditTriggers);self.add_button.setEnabled(draft);self.remove_button.setEnabled(draft);self.save_button.setEnabled(draft);self.post_button.setEnabled(draft);self.reverse_button.setEnabled(self.status=='posted');self.copy_button.setEnabled(self.status=='reversed');self.status_label.setText(STATUS[self.status]+(' · по дефектному акту №'+str(self.defect_id) if self.defect_id else '')+' — остатки изменяются только при проведении.')
        for r in range(self.lines.rowCount()):
            combo=self.lines.cellWidget(r,0);combo.setEnabled(draft);combo.setStyleSheet('QComboBox:disabled {color:#334155; background:#f8fafc;}')
    def load(self):
        d=record('stock_acts',self.aid);self.header.fill(d);self.status=d['status'];self.revision=d['revision'];self.defect_id=d['defect_id'];self.snapshot=json.loads(d['calculation'] or '[]');self.volumes.table.setRowCount(0)
        for v in self.snapshot:self.volumes.add_row(v['profile_id'],v['volume'])
        self.lines.setRowCount(0)
        for mid,norm,actual,note,name in db.fetchall('SELECT material_id,norm_qty,actual_qty,note,material_name FROM stock_act_lines WHERE act_id=? ORDER BY id',(self.aid,)):
            self.add_line(mid,norm,actual,note)
            if self.status!='draft':
                combo=self.lines.cellWidget(self.lines.rowCount()-1,0);combo.setItemText(combo.currentIndex(),name)
        self.state()
    def add_line(self,mid=None,norm=None,actual=0,note=''):
        if isinstance(mid,bool):mid=None
        r=self.lines.rowCount();self.lines.insertRow(r);combo=Choice('stock_materials',mid);self.lines.setCellWidget(r,0,combo);item(self.lines,r,2,domain.fmt(norm) if norm is not None else '');item(self.lines,r,3,domain.fmt(actual));item(self.lines,r,5,note)
        def changed():
            for row in range(self.lines.rowCount()):
                if self.lines.cellWidget(row,0) is combo:
                    mid=combo.currentData();item(self.lines,row,1,domain.material(db,mid)[2] if mid else '',False);item(self.lines,row,4,domain.fmt(domain.balance(db,mid)) if mid else '',False)
        combo.currentIndexChanged.connect(changed);changed()
    def calculate(self):
        try:
            lines,snapshot=domain.calculate(db,self.volumes.values())
            if not snapshot:raise ValueError('Добавьте объёмы работ')
            if self.lines.rowCount() and QMessageBox.question(self,'Пересчёт','Заменить текущие строки материалов результатом расчёта? Ручные изменения будут заменены.')!=QMessageBox.StandardButton.Yes:return
            self.lines.setRowCount(0);self.snapshot=snapshot
            for line in lines:self.add_line(line['material_id'],line['norm_qty'],line['actual_qty'])
            self.tabs.setCurrentIndex(2)
        except Exception as e:error(self,e)
    def save(self):
        if self.status!='draft':return True
        try:
            data=self.header.values();data['defect_id']=self.defect_id
            # Changing calculation inputs without recalculation must not silently preserve stale quantities.
            if self.volumes.values() and [(int(v['profile_id']),domain.decimal(v['volume'])) for v in self.snapshot] != [(pid,domain.decimal(qty)) for pid,qty in self.volumes.values()]:raise ValueError('Объёмы изменены. Нажмите «Рассчитать материалы по нормам».')
            if not self.volumes.values() and self.snapshot:raise ValueError('Для удаления расчёта сначала пересчитайте или создайте новый ручной акт')
            data['calculation']=json.dumps(self.snapshot,ensure_ascii=False);lines=[]
            for r in range(self.lines.rowCount()):lines.append(dict(material_id=self.lines.cellWidget(r,0).currentData(),norm_qty=domain.units(text(self.lines,r,2)) if text(self.lines,r,2) else None,actual_qty=domain.units(text(self.lines,r,3)),note=text(self.lines,r,5)))
            self.aid=domain.save_act(db,data,lines,self.aid,self.revision);self.load();return True
        except Exception as e:error(self,e);return False
    def post(self):
        if self.save():
            try:domain.post_act(db,self.aid);self.load()
            except Exception as e:error(self,e)
    def reverse(self):
        if QMessageBox.question(self,'Отмена','Отменить проведение и вернуть материалы на остаток? Акт останется в истории.')==QMessageBox.StandardButton.Yes:
            try:domain.reverse_act(db,self.aid);self.load()
            except Exception as e:error(self,e)
    def copy(self):
        try:self.aid=domain.copy_act(db,self.aid);self.load()
        except Exception as e:error(self,e)
    def export(self):
        if self.save():
            from .stock_exports import StockExportDialog
            StockExportDialog('stock_acts',self.aid,self).exec()

class DefectDialog(QDialog):
    def __init__(self,did=None,parent=None):
        super().__init__(parent);self.did=did;self.revision=None;self.locked=False;self.setWindowTitle('Дефектный акт');self.resize(1120,810);l=QVBoxLayout(self);tabs=QTabWidget();l.addWidget(tabs,1)
        self.header=Header(True);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(self.header);tabs.addTab(scroll,'Реквизиты')
        page=QWidget();pl=QVBoxLayout(page);pl.addWidget(QLabel('Опишите дефект, необходимые работы и объём. Норма необязательна: материалы можно добавить вручную в акт списания.'))
        self.lines=table(['Дефект / место','Необходимые работы','Ед.','Объём','Норма (необязательно)','Примечание'],True);self.lines.setColumnWidth(0,200);self.lines.setColumnWidth(1,240);self.lines.setColumnWidth(4,260);pl.addWidget(self.lines,1);bar=QHBoxLayout();self.add_button=button(bar,'Добавить работу',self.add_row);self.remove_button=button(bar,'Удалить строку',lambda:self.lines.removeRow(self.lines.currentRow()));pl.addLayout(bar);tabs.addTab(page,'Дефекты и объёмы')
        self.info=QLabel();l.addWidget(self.info);bar=QHBoxLayout();self.save_button=button(bar,'Сохранить',self.save);button(bar,'Составить акт списания',self.writeoff);button(bar,'Word / Excel / PDF',self.export);button(bar,'Закрыть',self.accept);l.addLayout(bar)
        if did:self.load()
        else:self.header.number.setText('ДА-'+date.today().strftime('%Y%m%d')+'-'+str(db.fetchone('SELECT coalesce(max(id),0)+1 FROM defect_acts')[0]))
    def add_row(self,d=None):
        d=d if isinstance(d,dict) else {};r=self.lines.rowCount();self.lines.insertRow(r)
        for c,k in [(0,'defect'),(1,'work'),(2,'unit'),(3,'quantity'),(5,'notes')]:item(self.lines,r,c,d.get(k,''))
        combo=Choice('norm_profiles',d.get('profile_id'));self.lines.setCellWidget(r,4,combo)
        def changed():
            pid=combo.currentData()
            if pid:
                for row in range(self.lines.rowCount()):
                    if self.lines.cellWidget(row,4) is combo:item(self.lines,row,2,db.fetchone('SELECT basis FROM norm_profiles WHERE id=?',(pid,))[0])
        combo.currentIndexChanged.connect(changed)
    def load(self):
        d=record('defect_acts',self.did);self.header.fill(d);self.revision=d['revision'];self.lines.setRowCount(0)
        for row in db.fetchall('SELECT defect,work,unit,quantity,profile_id,notes FROM defect_lines WHERE act_id=? ORDER BY id',(self.did,)):self.add_row(dict(zip(('defect','work','unit','quantity','profile_id','notes'),row)))
        self.locked=bool(db.fetchone("SELECT 1 FROM stock_acts WHERE defect_id=? AND status<>'reversed'",(self.did,)))
        self.header.setEnabled(not self.locked);self.lines.setEnabled(not self.locked);self.save_button.setEnabled(not self.locked);self.add_button.setEnabled(not self.locked);self.remove_button.setEnabled(not self.locked);self.info.setText('Есть связанное списание. Редактирование основания заблокировано.' if self.locked else '')
    def save(self):
        if self.locked:return True
        try:
            rows=[dict(defect=text(self.lines,r,0),work=text(self.lines,r,1),unit=text(self.lines,r,2),quantity=text(self.lines,r,3),profile_id=self.lines.cellWidget(r,4).currentData(),notes=text(self.lines,r,5)) for r in range(self.lines.rowCount())]
            self.did=domain.save_defect(db,self.header.values(),rows,self.did,self.revision);self.load();return True
        except Exception as e:error(self,e);return False
    def writeoff(self):
        if self.save():
            try:aid=domain.from_defect(db,self.did);ActDialog(aid,self).exec();self.load()
            except Exception as e:error(self,e)
    def export(self):
        if self.save():
            from .stock_exports import StockExportDialog
            StockExportDialog('defect_acts',self.did,self).exec()

class Registry(QWidget):
    def __init__(self,mode):
        super().__init__();self.mode=mode;self.pager=RegistryPager(self);l=QVBoxLayout(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Поиск по объекту, номеру, материалу…');bar.addWidget(self.search,1);self.date_from=OptionalDate();self.date_to=OptionalDate()
        if mode in ('acts','defects','moves'):
            bar.addWidget(QLabel('с'));bar.addWidget(self.date_from);bar.addWidget(QLabel('по'));bar.addWidget(self.date_to)
        self.category=QComboBox();self.category.addItem('Все категории','')
        for (cat,) in db.fetchall('SELECT DISTINCT category FROM stock_materials ORDER BY category'):self.category.addItem(cat,cat)
        if mode in ('materials','balances','moves'):bar.addWidget(self.category)
        self.status=QComboBox();self.status.addItem('Все статусы','')
        for k,v in STATUS.items():self.status.addItem(v,k)
        if mode=='acts':bar.addWidget(self.status)
        button(bar,'Сбросить',self.reset);l.addLayout(bar);actions=QHBoxLayout();l.addLayout(actions)
        if mode in ('acts','defects','materials','norms'):button(actions,'Создать',self.create);button(actions,'Изменить / открыть' if mode!='materials' else 'Изменить материал',self.edit_item if mode=='materials' else self.edit)
        if mode in ('materials','balances'):button(actions,'Поступления и списания',self.history)
        if mode=='norms':button(actions,'Копировать норму',self.copy_norm)
        if mode in ('materials','balances'):button(actions,'Поступление / остаток',self.receive)
        if mode=='acts':button(actions,'Удалить акт',self.delete)
        if mode=='defects':button(actions,'Списание по акту',self.writeoff);button(actions,'Копия на основании',self.copy_defect);button(actions,'Удалить акт',self.delete_defect)
        if mode=='materials':button(actions,'Удалить материал',self.delete_material)
        if mode in ('acts','defects'):button(actions,'Экспорт документа',self.export)
        if mode=='balances':button(actions,'Отчёт по шаблону',self.report)
        button(actions,'Обновить',self.load_data);actions.addStretch();self.table=table([]);l.addWidget(self.table,1);self.summary=QLabel();l.addWidget(self.summary)
        self.table.cellDoubleClicked.connect(lambda *_:self.history() if self.mode in ('materials','balances') else self.edit());self.search.textChanged.connect(self.load_data);self.date_from.dateChanged.connect(self.load_data);self.date_to.dateChanged.connect(self.load_data);self.category.currentIndexChanged.connect(self.load_data);self.status.currentIndexChanged.connect(self.load_data);self.load_data()
    def selected(self):
        r=self.table.currentRow();return self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else None
    def reset(self):self.search.clear();self.date_from.set_value('');self.date_to.set_value('');self.category.setCurrentIndex(0);self.status.setCurrentIndex(0);self.pager.filters.reset()
    def load_data(self,*_):
        mode=self.mode
        selected_category=self.category.currentData();self.category.blockSignals(True);self.category.clear();self.category.addItem('Все категории','')
        for (cat,) in db.fetchall('SELECT DISTINCT category FROM stock_materials ORDER BY category'):self.category.addItem(cat,cat)
        self.category.setCurrentIndex(max(0,self.category.findData(selected_category)));self.category.blockSignals(False)
        if mode in ('acts','defects'):
            source='stock_acts' if mode=='acts' else 'defect_acts';cols='id,act_date,number,object_name,'+('status,basis' if mode=='acts' else 'reason,notes');query=f'SELECT {cols} FROM {source}';headers=['Дата','Номер','Объект','Статус' if mode=='acts' else 'Основание','Основание' if mode=='acts' else 'Примечание'];fields=['number','object_name','basis' if mode=='acts' else 'reason'];datecol='act_date'
        elif mode=='norms':query="SELECT id,name,diameter,thickness,basis,(SELECT count(*) FROM norm_items i WHERE i.profile_id=norm_profiles.id AND i.rate IS NOT NULL)||' из '||(SELECT count(*) FROM norm_items i WHERE i.profile_id=norm_profiles.id) filled,notes FROM norm_profiles";headers=['Название нормы','Диаметр','Стенка','На единицу','Нормы заданы','Источник / примечание'];fields=['name','diameter','notes'];datecol=None
        elif mode in ('materials','balances'):
            query='SELECT m.id,m.name,m.category,m.unit,coalesce(b.qty,0)/1000000.0 balance,m.notes FROM stock_materials m LEFT JOIN (SELECT material_id,sum(qty) qty FROM stock_moves GROUP BY material_id) b ON b.material_id=m.id WHERE coalesce(m.active,1)=1';headers=['Материал','Категория','Ед.','Остаток','Примечание'];fields=['name','category','notes'];datecol=None
        else:
            query="SELECT v.id,v.move_date,m.name,m.category,m.unit,v.qty/1000000.0 qty,CASE v.kind WHEN 'receipt' THEN 'Поступление' WHEN 'correction' THEN 'Корректировка' WHEN 'writeoff' THEN 'Списание' WHEN 'transfer_out' THEN 'Перевод: было' WHEN 'transfer_in' THEN 'Перевод: стало' WHEN 'transfer_reversal' THEN 'Отмена перевода' ELSE 'Отмена' END kind,coalesce(a.number,'') number,coalesce(a.object_name,'') object_name,v.note FROM stock_moves v JOIN stock_materials m ON m.id=v.material_id LEFT JOIN stock_acts a ON a.id=v.act_id";headers=['Дата','Материал','Категория','Ед.','Количество','Операция','Акт','Объект','Примечание'];fields=['name','object_name','number','note'];datecol='move_date'
        where=[];params=[]
        if self.search.text():where.append('('+' OR '.join('LOWER('+f+') LIKE ?' for f in fields)+')');params.extend(['%'+self.search.text().casefold()+'%']*len(fields))
        if datecol:
            if self.date_from.value():where.append(datecol+'>=?');params.append(self.date_from.value())
            if self.date_to.value():where.append(datecol+'<=?');params.append(self.date_to.value())
        if mode in ('materials','balances','moves') and self.category.currentData():where.append('category=?');params.append(self.category.currentData())
        if mode=='acts' and self.status.currentData():where.append('status=?');params.append(self.status.currentData())
        query='SELECT * FROM ('+query+') WHERE '+(' AND '.join(where) if where else '1=1')+' ORDER BY '+(datecol+' DESC,' if datecol else '')+'id DESC';self.report_query=query;self.report_params=tuple(params);rows=self.pager.fetch(query,params);self.table.setColumnCount(len(headers));self.table.setHorizontalHeaderLabels(headers);self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,v in enumerate(row[1:]):
                value=STATUS.get(v,v) if mode=='acts' and c==3 else v
                if isinstance(value,float):value=f'{value:.6f}'.rstrip('0').rstrip('.')
                i=item(self.table,r,c,value,False);i.setData(Qt.ItemDataRole.UserRole,row[0])
        for c in range(len(headers)):self.table.setColumnWidth(c,130 if c else 220)
        if mode in ('acts','defects'):self.table.setColumnWidth(2,360)
        if mode=='balances':
            q='SELECT category,unit,sum(qty)/1000000.0 FROM stock_moves v JOIN stock_materials m ON m.id=v.material_id'+(' WHERE category=?' if self.category.currentData() else '')+' GROUP BY category,unit'
            summary=db.fetchall(q,(self.category.currentData(),) if self.category.currentData() else ());self.summary.setText('Всего по категориям (весь склад): '+ ' · '.join(f'{cat}: {qty:g} {unit}' for cat,unit,qty in summary));self.summary.setWordWrap(True)
    def create(self):
        {'acts':ActDialog,'defects':DefectDialog,'materials':MaterialDialog,'norms':NormDialog}[self.mode](parent=self).exec();self.load_data()
    def edit(self):
        if self.selected() and self.mode in ('acts','defects','materials','balances','norms'):{'acts':ActDialog,'defects':DefectDialog,'materials':MaterialDialog,'balances':MaterialDialog,'norms':NormDialog}[self.mode](self.selected(),self).exec();self.load_data()
    def edit_item(self):
        if self.selected():MaterialDialog(self.selected(),self).exec();self.load_data()
    def history(self):
        if self.selected():MaterialHistoryDialog(self.selected(),self).exec();self.load_data()
    def copy_defect(self):
        if self.selected():
            try:new=domain.copy_defect(db,self.selected());self.load_data();DefectDialog(new,self).exec();self.load_data()
            except Exception as e:error(self,e)
    def delete_defect(self):
        rid=self.selected()
        if rid and QMessageBox.question(self,'Удаление','Удалить дефектный акт? Это действие нельзя отменить (запись останется в «Журнале и корзине»).')==QMessageBox.StandardButton.Yes:
            try:domain.delete_defect(db,rid);self.load_data()
            except Exception as e:error(self,e)
    def delete_material(self):
        rid=self.selected()
        if not rid:return
        try:
            usage=domain.material_usage(db,rid);name=domain.material(db,rid)[0]
            if usage['acts']:
                box=QMessageBox(self);box.setWindowTitle('Материал используется');box.setText(f'«{name}» есть в актах списания ({len(usage["acts"])}): '+', '.join(usage['acts'][:6])+('…' if len(usage['acts'])>6 else '')+'.\nУдалить его нельзя, чтобы не нарушить акты. Можно скрыть материал: он пропадёт из списков и остатков, но останется в актах.')
                hide=box.addButton('Скрыть материал',QMessageBox.ButtonRole.AcceptRole);box.addButton('Отмена',QMessageBox.ButtonRole.RejectRole);box.exec()
                if box.clickedButton() is hide:domain.delete_material(db,rid,True);self.load_data()
                return
            extra=(f' Будут удалены также поступления и движения ({usage["moves"]}).' if usage['moves'] else '')+(f' Он будет убран из норм: {len(usage["norms"])}.' if usage['norms'] else '')
            if QMessageBox.question(self,'Удаление',f'Удалить материал «{name}»?'+extra)==QMessageBox.StandardButton.Yes:domain.delete_material(db,rid);self.load_data()
        except Exception as e:error(self,e)
    def copy_norm(self):
        pid=self.selected()
        if not pid:return
        try:
            with db.transaction():
                old=db.fetchone('SELECT name,diameter,thickness,basis,notes FROM norm_profiles WHERE id=?',(pid,))
                new=db.execute('INSERT INTO norm_profiles(name,diameter,thickness,basis,notes) VALUES(?,?,?,?,?)',(old[0]+' (копия)',*old[1:])).lastrowid
                db.execute('INSERT INTO norm_items(profile_id,material_id,rate,per) SELECT ?,material_id,rate,per FROM norm_items WHERE profile_id=?',(new,pid))
            self.load_data()
            NormDialog(new,self).exec();self.load_data()
        except Exception as e:error(self,e)
    def report(self):
        from .report_dialog import ReportTemplateDialog
        query,params=self.pager.filters.apply(self.report_query,self.report_params)
        ReportTemplateDialog('balances',parent=self,filters={'query':query,'params':tuple(params),'category':self.category.currentData(),'search':self.search.text()}).exec()
    def receive(self):ReceiptDialog(self.selected(),self).exec();self.load_data()
    def delete(self):
        rid=self.selected()
        if not rid:return
        row=db.fetchone('SELECT number,status FROM stock_acts WHERE id=?',(rid,))
        if not row:return
        warn='Удалить акт списания №'+row[0]+'?'+(' Он проведён: материалы вернутся на остаток.' if row[1]=='posted' else '')
        if QMessageBox.question(self,'Удаление',warn)==QMessageBox.StandardButton.Yes:
            try:domain.delete_act(db,rid);self.load_data()
            except Exception as e:error(self,e)
    def writeoff(self):
        if self.selected():
            try:ActDialog(domain.from_defect(db,self.selected()),self).exec();self.load_data()
            except Exception as e:error(self,e)
    def export(self):
        if self.selected():
            from .stock_exports import StockExportDialog
            StockExportDialog('stock_acts' if self.mode=='acts' else 'defect_acts',self.selected(),self).exec()

class WriteoffView(QWidget):
    def __init__(self):
        super().__init__();l=QVBoxLayout(self);self.tabs=QTabWidget();l.addWidget(self.tabs,1)
        for mode,label in [('acts','Акты списания'),('defects','Дефектные акты'),('norms','Справочник норм'),('materials','Материалы'),('balances','Остатки'),('moves','Движение материалов')]:self.tabs.addTab(Registry(mode),label)
        self.tabs.addTab(ObjectsView(),'Объекты списания')
        self.tabs.addTab(RegisterView('orders'),'Приказы')
        self.tabs.addTab(RegisterView('transfers'),'Акты перевода материалов')
        self.tabs.currentChanged.connect(lambda _:self.load_data())
    def load_data(self):self.tabs.currentWidget().load_data()


class MaterialHistoryDialog(QDialog):
    """Все поступления и списания выбранного материала с нарастающим остатком."""
    def __init__(self,mid,parent=None):
        super().__init__(parent);name,category,unit=domain.material(db,mid);self.setWindowTitle(f'Движение материала · {name}');self.resize(1000,560);l=QVBoxLayout(self)
        self.summary=QLabel();self.summary.setWordWrap(True);l.addWidget(self.summary)
        self.table=table(['Дата','Операция','Количество','Остаток после','Акт №','Объект','Примечание']);l.addWidget(self.table,1)
        rows=domain.material_history(db,mid);self.table.setRowCount(len(rows));received=written=0
        for r,h in enumerate(reversed(rows)):
            qty=h['qty']
            if qty>0:received+=qty
            else:written+=-qty
            for c,v in enumerate([h['date'],h['kind'],('+' if qty>0 else '')+domain.fmt(qty)+' '+unit,domain.fmt(h['balance'])+' '+unit,h['act'],h['object'],h['note']]):
                i=item(self.table,r,c,v,False)
                if c==2:i.setForeground(__import__('PyQt6.QtGui',fromlist=['QColor']).QColor('#15803D' if qty>0 else '#B91C1C'))
        self.summary.setText(f'{category} · остаток сейчас: {domain.fmt(domain.balance(db,mid))} {unit}. Всего поступило: {domain.fmt(received)} {unit}, списано: {domain.fmt(written)} {unit}. Новые записи сверху.')
        from .registry_tools import autofit_columns;autofit_columns(self.table)
        bar=QHBoxLayout();button(bar,'Поступление / остаток',lambda:(ReceiptDialog(mid,self).exec(),self.accept()));bar.addStretch();button(bar,'Закрыть',self.accept);l.addLayout(bar)


class ObjectDialog(QDialog):
    def __init__(self,oid=None,parent=None,link=False):
        super().__init__(parent);self.oid=oid;self.setWindowTitle('Объект списания');self.resize(620,420);l=QVBoxLayout(self);f=QFormLayout();l.addLayout(f)
        self.name=QLineEdit();self.address=QLineEdit();self.organization=QLineEdit();self.approved_by=QLineEdit();self.commission=QLineEdit();self.notes=QLineEdit()
        self.reference=ObjectField();self.reference.changed.connect(self.from_reference)
        f.addRow('Название *',self.name);f.addRow('Адрес',self.address)
        f.addRow('Связать с объектом услуг (ГСВ / ГСН)',self.reference)
        for label,w in [('Организация (если отличается от общей)',self.organization),('Утверждает (если отличается)',self.approved_by),('Комиссия (если отличается)',self.commission),('Примечание',self.notes)]:f.addRow(label,w)
        l.addWidget(QLabel('Пустые поля реквизитов берутся из «Значений по умолчанию». Объект можно не связывать с договорами — например, собственное здание.'))
        if oid:
            row=db.fetchone('SELECT name,owner_type,owner_id,address,organization,approved_by,commission,notes FROM writeoff_objects WHERE id=?',(oid,))
            self.name.setText(row[0]);self.address.setText(row[3] or '');self.organization.setText(row[4] or '');self.approved_by.setText(row[5] or '');self.commission.setText(row[6] or '');self.notes.setText(row[7] or '')
            if row[1]:self.reference.set_reference(row[1],row[2])
        elif link:QTimer.singleShot(0,self.reference.choose if hasattr(self.reference,'choose') else (lambda:None))
        b=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);b.accepted.connect(self.save);b.rejected.connect(self.reject);l.addWidget(b)
    def from_reference(self):
        if self.reference.reference[0] and not self.name.text().strip():self.name.setText(owner_label(db,*self.reference.reference))
    def save(self):
        try:
            owner,rid=self.reference.reference
            self.oid=domain.save_object(db,self.name.text(),self.address.text().strip(),owner,rid,self.organization.text().strip(),self.approved_by.text().strip(),self.commission.text().strip(),self.notes.text().strip(),self.oid);self.accept()
        except Exception as e:error(self,e)


class ObjectsView(QWidget):
    """Объекты списания (свои и связанные с услугами) и значения по умолчанию для актов."""
    FIELDS=(('organization','Организация'),('approved_by','Утверждает (должность, ФИО)'),('commission','Комиссия / ответственные (ФИО)'),('basis','Основание акта списания'),('reason','Основание дефектного акта'),('conditions','Условия выполнения работ'))
    def __init__(self):
        super().__init__();l=QVBoxLayout(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Поиск объекта…');bar.addWidget(self.search,1)
        button(bar,'Добавить свой объект',self.create);button(bar,'Добавить объект услуг…',self.create_linked);button(bar,'Изменить',self.edit);b=button(bar,'Удалить',self.delete);b.setProperty('type','danger');l.addLayout(bar)
        self.table=table(['Объект','Связь','Адрес','Организация','Утверждает','Комиссия','Примечание']);l.addWidget(self.table,1)
        from PyQt6.QtWidgets import QGroupBox
        box=QGroupBox('Значения по умолчанию для новых актов (комиссия, кто утверждает и т. д.)');form=QFormLayout(box);self.defaults={}
        for key,label in self.FIELDS:self.defaults[key]=QLineEdit();form.addRow(label,self.defaults[key])
        row=QHBoxLayout();button(row,'Сохранить значения',self.save_defaults);self.status=QLabel();row.addWidget(self.status,1);form.addRow(row);l.addWidget(box)
        self.search.textChanged.connect(self.load_data);self.table.cellDoubleClicked.connect(lambda *_:self.edit());self.load_data()
    def selected(self):
        r=self.table.currentRow();return self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else None
    def load_data(self,*_):
        q=self.search.text().casefold();rows=[r for r in domain.objects(db) if not q or q in (r[1]+' '+(r[4] or '')).casefold()];self.table.setRowCount(len(rows))
        for r,(oid,name,owner,rid,address,org,appr,comm,notes) in enumerate(rows):
            link=('связан: '+owner_label(db,owner,rid)) if owner else 'свой объект'
            for c,v in enumerate([name,link,address,org,appr,comm,notes]):item(self.table,r,c,v,False).setData(Qt.ItemDataRole.UserRole,oid)
        for key,value in domain.get_defaults(db).items():self.defaults[key].setText(value)
        from .registry_tools import autofit_columns;autofit_columns(self.table)
    def save_defaults(self):
        domain.set_defaults(db,{k:w.text() for k,w in self.defaults.items()});self.status.setText('Значения сохранены: они подставляются в новые акты и дефектные акты.')
    def create(self):
        if ObjectDialog(parent=self).exec():self.load_data()
    def create_linked(self):
        if ObjectDialog(parent=self,link=True).exec():self.load_data()
    def edit(self):
        if self.selected() and ObjectDialog(self.selected(),self).exec():self.load_data()
    def delete(self):
        rid=self.selected()
        if rid and QMessageBox.question(self,'Удаление','Удалить объект из списка? Ранее созданные акты не изменятся.')==QMessageBox.StandardButton.Yes:domain.delete_object(db,rid);self.load_data()


def _pick_file(parent,line_edit,title):
    from PyQt6.QtWidgets import QFileDialog
    path,_=QFileDialog.getOpenFileName(parent,title,line_edit.text() or '','Все файлы (*)')
    if path:line_edit.setText(path)

def _open_file(parent,path):
    import os
    if not path or not os.path.isfile(path):QMessageBox.information(parent,'Файл','Файл не найден: '+(path or 'не прикреплён'));return
    from .platform_utils import open_local
    open_local(path)


class OrderDialog(QDialog):
    """Приказ по модулю «Списание»: номер, дата, содержание, кто издал, срок действия, скан/файл."""
    def __init__(self,oid=None,parent=None):
        super().__init__(parent);self.oid=oid;self.setWindowTitle('Приказ');self.resize(700,560);l=QVBoxLayout(self);f=QFormLayout();l.addLayout(f)
        from . import stock_registers as reg
        self.number=QLineEdit();self.day=OptionalDate();self.day.set_value(date.today().isoformat());self.title=QLineEdit();self.title.setPlaceholderText('О чём приказ: например, «О создании комиссии по списанию материалов»')
        self.content=QTextEdit();self.content.setPlaceholderText('Содержание, пункты приказа, основание');self.content.setMinimumHeight(140);self.issued_by=QLineEdit();self.valid_until=OptionalDate();self.notes=QLineEdit()
        self.file=QLineEdit();self.file.setReadOnly(True);fb=QHBoxLayout();fb.addWidget(self.file,1);button(fb,'Прикрепить…',lambda:_pick_file(self,self.file,'Файл приказа (скан, Word, PDF)'));button(fb,'Открыть',lambda:_open_file(self,self.file.text()));button(fb,'Убрать',self.file.clear)
        for label,w in [('Номер *',self.number),('Дата *',self.day),('О чём приказ *',self.title),('Содержание',self.content),('Кто издал / подписал',self.issued_by),('Действует до',self.valid_until),('Примечание',self.notes)]:f.addRow(label,w)
        f.addRow('Файл приказа',fb)
        if oid:
            d=record('stock_orders',oid);self.number.setText(d['number']);self.day.set_value(d['order_date']);self.title.setText(d['title']);self.content.setPlainText(d['content'] or '');self.issued_by.setText(d['issued_by'] or '');self.valid_until.set_value(d['valid_until']);self.notes.setText(d['notes'] or '');self.file.setText(d['file_path'] or '')
        else:self.number.setText(reg.next_order_number(db))
        b=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);b.accepted.connect(self.save);b.rejected.connect(self.reject);l.addWidget(b)
    def save(self):
        from . import stock_registers as reg
        try:
            self.oid=reg.save_order(db,dict(number=self.number.text(),order_date=self.day.value(),title=self.title.text(),content=self.content.toPlainText(),issued_by=self.issued_by.text(),valid_until=self.valid_until.value(),file_path=self.file.text(),notes=self.notes.text()),self.oid);self.accept()
        except Exception as e:error(self,e)


class TransferDialog(QDialog):
    """Акт перевода материалов: меняет единицу измерения и количество, стоимость партии сохраняется, цена за новую единицу пересчитывается
    (было 1 шт за 120 → стало 5,05 м³ → 23,7624 за м³). При проведении меняются остатки склада и цена в справочнике."""
    COLS=['Материал','Было, ед.','Было, кол-во','Стало, ед.','Стало, кол-во','Стоимость партии, BYN','Цена за ед. было','Цена за ед. стало','Примечание']
    def __init__(self,tid=None,parent=None):
        super().__init__(parent);self.tid=tid;self.setWindowTitle('Акт перевода материалов');self.resize(1180,720);l=QVBoxLayout(self);f=QFormLayout();l.addLayout(f)
        from . import stock_registers as reg
        self.number=QLineEdit();self.day=OptionalDate();self.day.set_value(date.today().isoformat())
        self.from_place=self.place_box('Склад, объект, ответственное лицо (необязательно)');self.to_place=self.place_box('Склад, объект, ответственное лицо (необязательно)')
        self.reason=QLineEdit();self.approved_by=QLineEdit();self.commission=QLineEdit();self.notes=QLineEdit()
        self.file=QLineEdit();self.file.setReadOnly(True);fb=QHBoxLayout();fb.addWidget(self.file,1);button(fb,'Прикрепить…',lambda:_pick_file(self,self.file,'Файл акта (скан, Word, PDF)'));button(fb,'Открыть',lambda:_open_file(self,self.file.text()));button(fb,'Убрать',self.file.clear)
        defaults=domain.get_defaults(db)
        for label,w in [('Номер *',self.number),('Дата *',self.day),('Откуда',self.from_place),('Куда',self.to_place),('Основание / причина',self.reason),('Утверждает',self.approved_by),('Комиссия / ответственные',self.commission),('Примечание',self.notes)]:f.addRow(label,w)
        f.addRow('Файл акта',fb)
        self._busy=False
        self.lines=table(self.COLS,True);self.lines.setColumnWidth(0,300);l.addWidget(self.lines,1)
        bar=QHBoxLayout();button(bar,'Добавить материал',self.add_line);button(bar,'Удалить строку',lambda:self.lines.removeRow(self.lines.currentRow()));bar.addStretch()
        self.update_catalog=QCheckBox('При проведении обновить цену в справочнике');self.update_catalog.setChecked(True);bar.addWidget(self.update_catalog);l.addLayout(bar)
        self.hint=QLabel('Перевод единиц: укажите «Стало, ед.» и «Стало, кол-во» — цена за новую единицу = стоимость партии / новое количество. Стоимость подставляется из справочника цен (цена × количество), её можно исправить. '
                         'Остатки склада и справочник меняются только при проведении акта.');self.hint.setWordWrap(True);l.addWidget(self.hint)
        self.status=QLabel('');l.addWidget(self.status)
        if tid:
            d=record('stock_transfers',tid);self.number.setText(d['number']);self.day.set_value(d['transfer_date']);self.from_place.setEditText(d['from_place']);self.to_place.setEditText(d['to_place']);self.reason.setText(d['reason'] or '');self.approved_by.setText(d['approved_by'] or '');self.commission.setText(d['commission'] or '');self.notes.setText(d['notes'] or '');self.file.setText(d['file_path'] or '')
            for ln in reg.transfer_conversions(db,tid):self.add_line(ln['material_id'],ln['material_name'],ln['unit'],ln['quantity'],ln['note'],ln['new_unit'] or '',ln['new_quantity'] or '',ln['cost'])
        else:
            self.number.setText(reg.next_transfer_number(db));self.approved_by.setText(defaults.get('approved_by',''));self.commission.setText(defaults.get('commission',''));self.add_line()
        self.lines.cellChanged.connect(self.recalc)
        bb=QHBoxLayout();self.save_btn=button(bb,'Сохранить',self.save);self.post_btn=button(bb,'Провести перевод',self.post);self.reverse_btn=button(bb,'Отменить проведение',self.reverse);button(bb,'Закрыть',self.reject);l.addLayout(bb)
        self.refresh_state()
    def place_box(self,hint):
        box=QComboBox();box.setEditable(True);box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert);box.lineEdit().setPlaceholderText(hint);box.addItem('')
        for _id,name,*_ in domain.objects(db):box.addItem(name)
        box.setCurrentIndex(0);return box
    def add_line(self,mid=None,name='',unit='',qty='',note='',new_unit='',new_qty='',cost=None):
        if isinstance(mid,bool):mid=None
        self._busy=True
        r=self.lines.rowCount();self.lines.insertRow(r);combo=QComboBox();combo.setEditable(True);combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert);combo.addItem('',None)
        for rid,mname,munit in db.fetchall('SELECT id,name,unit FROM stock_materials WHERE coalesce(active,1)=1 ORDER BY name'):combo.addItem(f'{mname}, {munit}',(rid,munit,mname))
        combo.setCurrentIndex(0)
        found=-1
        for k in range(combo.count()):
            d=combo.itemData(k)
            if d and d[0]==mid:found=k
        if found>=0:combo.setCurrentIndex(found)
        else:combo.setEditText(name)
        self.lines.setCellWidget(r,0,combo);item(self.lines,r,1,unit,False);item(self.lines,r,2,qty);item(self.lines,r,3,new_unit);item(self.lines,r,4,new_qty);item(self.lines,r,5,'' if cost is None else ('%g'%cost));item(self.lines,r,6,'',False);item(self.lines,r,7,'',False);item(self.lines,r,8,note)
        self._busy=False
        def changed():
            data=combo.currentData()
            for row in range(self.lines.rowCount()):
                if self.lines.cellWidget(row,0) is combo:
                    self._busy=True;item(self.lines,row,1,data[1] if data else '',False);self._busy=False;self.recalc(row,2)
        combo.currentIndexChanged.connect(changed);self.recalc(r,2)
    def _material(self,row):
        combo=self.lines.cellWidget(row,0);data=combo.currentData() if combo.currentIndex()>=0 and combo.currentText()==combo.itemText(combo.currentIndex()) else None
        return data
    def recalc(self,row,col):
        if self._busy:return
        from . import stock_registers as reg
        self._busy=True
        try:
            data=self._material(row);qty=text(self.lines,row,2);new_qty=text(self.lines,row,4);cost_text=text(self.lines,row,5)
            def num(v):
                try:return float(v.replace(',','.').replace(' ',''))
                except ValueError:return None
            q,nq,cost=num(qty),num(new_qty),num(cost_text)
            if col in (2,) and data and q and not cost_text:                      # стоимость партии из справочника цен
                c=reg.default_cost(db,data[2],data[1],q)
                if c is not None:item(self.lines,row,5,'%g'%c);cost=c
            if col==0 and data and q and not cost_text:
                c=reg.default_cost(db,data[2],data[1],q)
                if c is not None:item(self.lines,row,5,'%g'%c);cost=c
            old_p,new_p=reg.unit_prices(cost,q,nq) if cost is not None and q and nq else (reg.unit_prices(cost,q,None) if cost is not None and q else (None,None))
            item(self.lines,row,6,'' if old_p is None else ('%.4f'%old_p).rstrip('0').rstrip('.'),False);item(self.lines,row,7,'' if new_p is None else ('%.4f'%new_p).rstrip('0').rstrip('.'),False)
        finally:self._busy=False
    def rows(self):
        rows=[]
        for r in range(self.lines.rowCount()):
            combo=self.lines.cellWidget(r,0);data=self._material(r)
            rows.append(dict(material_id=data[0] if data else None,material_name=data[2] if data else combo.currentText(),unit=text(self.lines,r,1),quantity=text(self.lines,r,2),new_unit=text(self.lines,r,3),new_quantity=text(self.lines,r,4),cost=text(self.lines,r,5),note=text(self.lines,r,8)))
        return rows
    def header(self):
        return dict(number=self.number.text(),transfer_date=self.day.value(),from_place=self.from_place.currentText(),to_place=self.to_place.currentText(),reason=self.reason.text(),approved_by=self.approved_by.text(),commission=self.commission.text(),file_path=self.file.text(),notes=self.notes.text())
    def save(self):
        from . import stock_registers as reg
        try:
            self.tid=reg.save_transfer(db,self.header(),self.rows(),self.tid);self.status.setText('Акт сохранён.');self.refresh_state();return True
        except Exception as e:error(self,e);return False
    def post(self):
        from . import stock_registers as reg
        if not self.save():return
        try:
            n=reg.post_transfer(db,self.tid,self.update_catalog.isChecked())
        except Exception as e:error(self,e);return
        self.status.setText(f'Акт проведён: переведено позиций — {n}. Остатки склада'+(' и цены справочника' if self.update_catalog.isChecked() else '')+' обновлены.');self.refresh_state()
    def reverse(self):
        from . import stock_registers as reg
        if self.tid and QMessageBox.question(self,'Отмена проведения','Отменить проведение акта? Остатки склада и цены справочника вернутся к прежним значениям.')==QMessageBox.StandardButton.Yes:
            try:reg.reverse_transfer(db,self.tid)
            except Exception as e:error(self,e);return
            self.status.setText('Проведение отменено.');self.refresh_state()
    def refresh_state(self):
        from . import stock_registers as reg
        posted=bool(self.tid) and reg.is_posted(db,self.tid)
        self.post_btn.setEnabled(not posted);self.reverse_btn.setEnabled(posted);self.save_btn.setEnabled(not posted)
        self.lines.setEnabled(not posted)
        self.setWindowTitle('Акт перевода материалов'+(' — ПРОВЕДЁН' if posted else ''))


class RegisterView(QWidget):
    """Журнал приказов (mode='orders') или актов перевода материалов (mode='transfers')."""
    def __init__(self,mode):
        super().__init__();self.mode=mode;self.pager=RegistryPager(self);l=QVBoxLayout(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Поиск по номеру, содержанию, объекту, материалу…');bar.addWidget(self.search,1)
        self.date_from=OptionalDate();self.date_to=OptionalDate();bar.addWidget(QLabel('с'));bar.addWidget(self.date_from);bar.addWidget(QLabel('по'));bar.addWidget(self.date_to);button(bar,'Сбросить',self.reset);l.addLayout(bar)
        actions=QHBoxLayout();l.addLayout(actions)
        button(actions,'Создать приказ' if mode=='orders' else 'Создать акт перевода',self.create);button(actions,'Изменить / открыть',self.edit)
        if mode=='transfers':button(actions,'Копия на основании',self.copy)
        button(actions,'Открыть файл',self.open_file);b=button(actions,'Удалить',self.delete);b.setProperty('type','danger');actions.addStretch()
        self.table=table([]);l.addWidget(self.table,1);self.summary=QLabel();l.addWidget(self.summary)
        self.table.cellDoubleClicked.connect(lambda *_:self.edit());self.search.textChanged.connect(self.load_data);self.date_from.dateChanged.connect(self.load_data);self.date_to.dateChanged.connect(self.load_data);self.load_data()
    def reset(self):self.search.clear();self.date_from.set_value('');self.date_to.set_value('')
    def selected(self):
        r=self.table.currentRow();return self.table.item(r,0).data(Qt.ItemDataRole.UserRole) if r>=0 else None
    def load_data(self,*_):
        orders=self.mode=='orders';words=[w for w in self.search.text().casefold().split() if w];params=[];where=[]
        if orders:
            headers=['Дата','№','О чём приказ','Кто издал','Действует до','Файл','Примечание'];base="SELECT id,order_date,number,title,issued_by,valid_until,CASE WHEN coalesce(file_path,'')<>'' THEN 'есть' ELSE '' END,notes,order_date dt,number||' '||title||' '||coalesce(content,'')||' '||coalesce(issued_by,'')||' '||coalesce(notes,'') hay FROM stock_orders"
        else:
            headers=['Дата','№','Откуда','Куда','Материалы','Основание','Статус','Файл'];base="SELECT t.id,t.transfer_date,t.number,t.from_place,t.to_place,coalesce((SELECT group_concat(material_name||': '||quantity||' '||unit||CASE WHEN coalesce(new_quantity,'')<>'' THEN ' → '||new_quantity||' '||new_unit||CASE WHEN new_price IS NOT NULL THEN ' ('||round(new_price,2)||' за '||new_unit||')' ELSE '' END ELSE '' END,'; ') FROM stock_transfer_lines l WHERE l.transfer_id=t.id),'') materials,t.reason,CASE WHEN t.posted=1 THEN 'Проведён' ELSE 'Черновик' END,CASE WHEN coalesce(t.file_path,'')<>'' THEN 'есть' ELSE '' END,t.transfer_date dt,t.number||' '||t.from_place||' '||t.to_place||' '||coalesce(t.reason,'')||' '||coalesce(t.notes,'')||' '||coalesce((SELECT group_concat(material_name,' ') FROM stock_transfer_lines l WHERE l.transfer_id=t.id),'') hay FROM stock_transfers t"
        for w in words:where.append('LOWER(hay) LIKE ?');params.append('%'+w+'%')
        if self.date_from.value():where.append('dt>=?');params.append(self.date_from.value())
        if self.date_to.value():where.append('dt<=?');params.append(self.date_to.value())
        query='SELECT * FROM ('+base+') WHERE '+(' AND '.join(where) if where else '1=1')+' ORDER BY dt DESC,id DESC';rows=self.pager.fetch(query,params)
        self.table.setColumnCount(len(headers));self.table.setHorizontalHeaderLabels(headers);self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,v in enumerate(row[1:len(headers)+1]):item(self.table,r,c,v,False).setData(Qt.ItemDataRole.UserRole,row[0])
        from .registry_tools import autofit_columns;autofit_columns(self.table,max_width=520)
        total=db.fetchone('SELECT count(*) FROM '+('stock_orders' if orders else 'stock_transfers'))[0];self.summary.setText(f'Записей в журнале: {total}')
    def create(self):
        if (OrderDialog if self.mode=='orders' else TransferDialog)(parent=self).exec():self.load_data()
    def edit(self):
        if self.selected() and (OrderDialog if self.mode=='orders' else TransferDialog)(self.selected(),self).exec():self.load_data()
    def copy(self):
        from . import stock_registers as reg
        if self.selected():
            try:new=reg.copy_transfer(db,self.selected());self.load_data();TransferDialog(new,self).exec();self.load_data()
            except Exception as e:error(self,e)
    def open_file(self):
        rid=self.selected()
        if rid:_open_file(self,db.fetchone('SELECT file_path FROM '+('stock_orders' if self.mode=='orders' else 'stock_transfers')+' WHERE id=?',(rid,))[0])
    def delete(self):
        rid=self.selected()
        if rid and QMessageBox.question(self,'Удаление','Удалить запись из журнала? Её можно вернуть через «Журнал и корзину».')==QMessageBox.StandardButton.Yes:
            from . import stock_registers as reg
            (reg.delete_order if self.mode=='orders' else reg.delete_transfer)(db,rid);self.load_data()
