"""Bound SQL filters operate before pagination, never just on visible rows."""
from PyQt6.QtWidgets import QWidget,QHBoxLayout,QPushButton,QDialog,QVBoxLayout,QTableWidget,QComboBox,QLineEdit,QDialogButtonBox,QLabel,QMessageBox
from PyQt6.QtCore import pyqtSignal
from datetime import date

EXTRA_LABELS={'object_text':'Объект / адрес','welder_text':'Сварщик','work_date':'Дата работы','act_date':'Дата акта','number':'Номер','category':'Категория','basis':'База расчёта','diameter':'Диаметр','thickness':'Толщина','material_name':'Материал','balance':'Остаток','quantity':'Количество','move_date':'Дата движения','status':'Статус','approved_by':'Утверждает','commission':'Комиссия','reason':'Основание','conditions':'Условия','norm_qty':'По норме','actual_qty':'Фактически','organization':'Организация','profile_name':'Норма','qty':'Количество','kind':'Вид','unit':'Ед. изм.'}
OPS=('Содержит','Равно','Не равно','Дата с','Дата по','Число ≥','Число ≤','Пусто','Не пусто')
def quote(name):return '"'+name.replace('"','""')+'"'
def compile_rules(rules,columns):
    clauses=[];params=[]
    for field,op,value in rules:
        if field not in columns:continue
        col=quote(field)
        if op=='Содержит':clauses.append(f"LOWER(coalesce({col},'')) LIKE ? ESCAPE '\\'");params.append('%'+value.casefold().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        elif op in ('Равно','Не равно'):clauses.append(f'LOWER(coalesce({col},\'\')) '+('=' if op=='Равно' else '<>')+' ?');params.append(value.casefold())
        elif op in ('Дата с','Дата по'):
            value=value.strip()
            if '.' in value:value='-'.join(reversed(value.split('.')))
            date.fromisoformat(value);clauses.append(f'substr({col},1,10) '+('>=' if op=='Дата с' else '<=')+' ?');params.append(value)
        elif op.startswith('Число'):
            from .stock_domain import decimal
            clauses.append(f'CAST({col} AS REAL) '+('>=' if op=='Число ≥' else '<=')+' ?');params.append(float(decimal(value)))
        elif op=='Пусто':clauses.append(f"coalesce({col},'')=''")
        elif op=='Не пусто':clauses.append(f"coalesce({col},'')<>''")
    return (' AND '.join(clauses) or '1=1'),params

class SqlFilters(QWidget):
    changed=pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent);self.columns=[];self.rules=[];bar=QHBoxLayout(self);bar.setContentsMargins(0,0,0,0)
        self.button=QPushButton('Фильтры…');self.button.clicked.connect(self.edit);bar.addWidget(self.button);clear=QPushButton('Сбросить');clear.clicked.connect(self.reset);bar.addWidget(clear)
        self.setMaximumHeight(36)
    def reset(self):self.rules=[];self.button.setText('Фильтры…');self.changed.emit()
    def set_columns(self,columns):
        if self.columns!=columns:
            self.columns=columns;self.rules=[r for r in self.rules if r[0] in columns];self.button.setText('Фильтры ('+str(len(self.rules))+')' if self.rules else 'Фильтры…')
    def apply(self,query,params):
        clause,extra=compile_rules(self.rules,self.columns)
        return (f'SELECT * FROM ({query}) AS filtered WHERE {clause}',[*params,*extra]) if self.rules else (query,list(params))
    def edit(self):
        from .exports import LABELS
        labels={**LABELS,**EXTRA_LABELS};d=QDialog(self);d.setWindowTitle('Фильтры — все условия одновременно');d.resize(730,400);l=QVBoxLayout(d);l.addWidget(QLabel('Фильтруются все записи реестра. Даты: ДД.ММ.ГГГГ или ГГГГ-ММ-ДД.'))
        t=QTableWidget(0,3);t.setHorizontalHeaderLabels(['Поле','Условие','Значение']);t.horizontalHeader().setStretchLastSection(True);t.setColumnWidth(0,210);t.setColumnWidth(1,150);l.addWidget(t)
        def add(rule=None):
            r=t.rowCount();t.insertRow(r);col=QComboBox()
            for c in self.columns:col.addItem(labels.get(c,c),c)
            op=QComboBox();op.addItems(OPS);val=QLineEdit()
            if rule:col.setCurrentIndex(max(0,col.findData(rule[0])));op.setCurrentText(rule[1]);val.setText(rule[2])
            t.setCellWidget(r,0,col);t.setCellWidget(r,1,op);t.setCellWidget(r,2,val)
        for rule in self.rules:add(rule)
        if not self.rules:add()
        bar=QHBoxLayout();a=QPushButton('Добавить условие');a.clicked.connect(lambda:add());bar.addWidget(a);b=QPushButton('Удалить условие');b.clicked.connect(lambda:t.removeRow(t.currentRow()) if t.currentRow()>=0 else None);bar.addWidget(b);l.addLayout(bar)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel);l.addWidget(buttons);buttons.rejected.connect(d.reject)
        def apply():
            rules=[(t.cellWidget(r,0).currentData(),t.cellWidget(r,1).currentText(),t.cellWidget(r,2).text()) for r in range(t.rowCount())]
            try:compile_rules(rules,self.columns)
            except (ValueError,TypeError) as e:QMessageBox.warning(d,'Фильтр',str(e));return
            self.rules=rules;self.button.setText(f'Фильтры ({len(rules)})');d.accept();self.changed.emit()
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(apply);d.exec()
