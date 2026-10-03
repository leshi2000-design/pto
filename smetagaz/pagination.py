from PyQt6.QtWidgets import QWidget,QHBoxLayout,QPushButton,QLabel,QSizePolicy
from PyQt6.QtCore import QTimer
from .database import db

class RegistryPager:
    def __init__(self,owner,callback=None):
        self.callback=callback or owner.load_data
        self.owner=owner;self.offset=0;self.size=200;self.key=None
        self.bar=QWidget(owner)
        self.bar.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.bar.setFixedHeight(44)
        layout=QHBoxLayout(self.bar);layout.setContentsMargins(0,4,0,4)
        from .filters import SqlFilters
        self.filters=SqlFilters(owner);self.filters.changed.connect(self.callback);layout.addWidget(self.filters)
        layout.addStretch()
        self.prev=QPushButton('← Назад');self.next=QPushButton('Далее →');self.label=QLabel()
        layout.addWidget(self.prev);layout.addWidget(self.label);layout.addWidget(self.next);layout.addStretch()
        self.prev.setFixedWidth(115);self.next.setFixedWidth(115)
        self.prev.clicked.connect(lambda:self.page(-1));self.next.clicked.connect(lambda:self.page(1))
        QTimer.singleShot(0,self.attach)
    def attach(self):
        if self.owner.layout():self.owner.layout().addWidget(self.bar)
    def page(self,direction):self.offset=max(0,self.offset+direction*self.size);self.callback()
    def fetch(self,query,params=()):
        columns=[c[0] for c in db.execute('SELECT * FROM ('+query+') LIMIT 0',params).description]
        self.filters.set_columns(columns)
        query,params=self.filters.apply(query,params)
        key=(query,tuple(params))
        if key!=self.key:self.offset=0;self.key=key
        rows=db.fetchall(query+' LIMIT ? OFFSET ?',(*params,self.size+1,self.offset))
        self.next.setEnabled(len(rows)>self.size);self.prev.setEnabled(self.offset>0)
        self.label.setText(f'Страница {self.offset//self.size+1} · до {self.size} записей')
        return rows[:self.size]
