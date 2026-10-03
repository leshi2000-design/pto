from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QTableWidget,QTableWidgetItem,QDateEdit,QDoubleSpinBox,QLineEdit,QMessageBox
from PyQt6.QtCore import QDate,Qt
from .database import db
from . import payments_domain as domain
class PaymentsDialog(QDialog):
    def __init__(self,owner,rid,parent=None):
        super().__init__(parent);self.owner=owner;self.rid=rid;self.setWindowTitle('Оплаты · '+domain.OWNERS[owner][1]);self.resize(800,600);l=QVBoxLayout(self);self.info=QLabel();self.info.setWordWrap(True);l.addWidget(self.info);self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['Дата','Сумма','Примечание']);self.table.horizontalHeader().setStretchLastSection(True);l.addWidget(self.table,1)
        bar=QHBoxLayout();self.day=QDateEdit(QDate.currentDate());self.day.setCalendarPopup(True);self.amount=QDoubleSpinBox();self.amount.setRange(0,1e9);self.amount.setDecimals(2);self.note=QLineEdit();self.note.setPlaceholderText('Примечание к платежу')
        for w in (self.day,self.amount,self.note):bar.addWidget(w)
        b=QPushButton('Внести оплату');b.clicked.connect(self.add);bar.addWidget(b);l.addLayout(bar);bar=QHBoxLayout();b=QPushButton('Заполнить остаток');b.clicked.connect(lambda:self.amount.setValue(max(0,float(domain.summary(db,self.owner,self.rid)['debt']))));bar.addWidget(b);b=QPushButton('Удалить ошибочный платёж');b.clicked.connect(self.remove);bar.addWidget(b)
        if owner!='estimates':b=QPushButton('Связать со сметой…');b.clicked.connect(self.link);bar.addWidget(b)
        l.addLayout(bar);self.load_data()
    def done(self,result):
        super().done(result)
        parent=self.parent()
        if parent and hasattr(parent,'load_data'):parent.load_data()
    def load_data(self):
        s=domain.summary(db,self.owner,self.rid);self.info.setText(f"Сумма: {s['total']:.2f} · Оплачено: {s['paid']:.2f} · Остаток: {s['debt']:.2f}\n"+(f"Общий учёт со сметой №{s['estimate_id']}. " if s['estimate_id'] else 'Самостоятельный договор. ')+(f"Включён ранее учтённый остаток оплаты: {s['opening']:.2f}; он не считается новым платежом периода." if s['opening'] else ''));rows=domain.history(db,self.owner,self.rid);self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row[1:]):item=QTableWidgetItem(str(value or ''));item.setData(Qt.ItemDataRole.UserRole,row[0]);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.table.setItem(r,c,item)
    def add(self):
        try:domain.add(db,self.owner,self.rid,self.amount.value(),self.day.date().toString('yyyy-MM-dd'),self.note.text());self.amount.setValue(0);self.load_data()
        except Exception as e:QMessageBox.warning(self,'Оплата',str(e))
    def remove(self):
        r=self.table.currentRow()
        if r>=0 and QMessageBox.question(self,'Исправление','Удалить ошибочно внесённый платёж?')==QMessageBox.StandardButton.Yes:db.execute('DELETE FROM payments WHERE id=?',(self.table.item(r,0).data(Qt.ItemDataRole.UserRole),));self.load_data()
    def link(self):
        d=QDialog(self);d.setWindowTitle('Выберите смету');d.resize(650,450);l=QVBoxLayout(d);search=QLineEdit();search.setPlaceholderText('Название / клиент');l.addWidget(search);table=QTableWidget(0,2);table.setHorizontalHeaderLabels(['Смета','Клиент']);l.addWidget(table);b=QPushButton('Связать выбранную');l.addWidget(b)
        def load():
            rows=db.fetchall("SELECT id,title,client_name FROM estimates WHERE LOWER(coalesce(title,'')||' '||coalesce(client_name,'')) LIKE ? ORDER BY id DESC LIMIT 200",('%'+search.text().casefold()+'%',));table.setRowCount(len(rows))
            for r,row in enumerate(rows):
                for c,v in enumerate(row[1:]):item=QTableWidgetItem(str(v or ''));item.setData(Qt.ItemDataRole.UserRole,row[0]);table.setItem(r,c,item)
        def choose():
            r=table.currentRow()
            if r<0:return
            try:domain.link(db,self.owner,self.rid,table.item(r,0).data(Qt.ItemDataRole.UserRole));d.accept();self.load_data()
            except Exception as e:QMessageBox.warning(d,'Связь',str(e))
        search.textChanged.connect(load);b.clicked.connect(choose);load();d.exec()
