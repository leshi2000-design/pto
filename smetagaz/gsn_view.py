"""GSN contracts and executive document workspace."""
from PyQt6.QtWidgets import QDialog,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QPushButton,QLabel,QTabWidget,QScrollArea,QMessageBox,QTableWidget,QTableWidgetItem,QAbstractItemView,QDoubleSpinBox,QCheckBox
from PyQt6.QtCore import Qt,QDate
from .database import db
from .domain_widgets import ClientForm,OptionalDate
from .gsv_domain import get_client,save_client
from .executive_workspace import ExecutiveWorkspace
from .pagination import RegistryPager
from .registry_tools import RegistryTools,search_clause

from .gsn_card import GsnContractDialog  # noqa: E402,F401  (карточка договора вынесена в gsn_card)

class GsnProjectsView(QWidget):
    def __init__(self):
        super().__init__();layout=QVBoxLayout(self);self.pager=RegistryPager(self);bar=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText('Договор, объект, клиент, телефон, адрес');bar.addWidget(self.search,1)
        for label,fn in [('Создать договор',self.create),('Открыть карточку',self.edit),('Оплаты',self.open_payments),('Теги для шаблонов',self.show_tag_reference)]:b=QPushButton(label);b.clicked.connect(fn);bar.addWidget(b)
        layout.addLayout(bar);self.table=QTableWidget(0,7);self.table.setHorizontalHeaderLabels(['Договор','Дата','Объект строительства','Клиент','Телефон','Адрес объекта','Дата акта']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setColumnWidth(2,280);self.table.setColumnWidth(3,240);self.table.horizontalHeader().setStretchLastSection(True);layout.addWidget(self.table,1);self.table.cellDoubleClicked.connect(self.edit);self.search.textChanged.connect(self.load_data);self.tools=RegistryTools(db,'gsn',self.table,self.search,bar);self.load_data()
    def load_data(self,*_):
        clause,found=search_clause(self.search.text(),['contract_number','title','client_name','phone','address','notes'],['phone']);rows=self.pager.fetch("SELECT id,contract_number,contract_date,title,client_name,phone,address,act_date FROM gsn_projects WHERE "+clause+" ORDER BY coalesce(contract_date,'') DESC,contract_number DESC,id DESC",tuple(found));self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate(row[1:]):item=QTableWidgetItem(str(value or ''));item.setData(Qt.ItemDataRole.UserRole,row[0]);self.table.setItem(r,c,item)
    def open_payments(self):
        r=self.table.currentRow()
        if r>=0:
            from .payments_view import PaymentsDialog
            PaymentsDialog('gsn_projects',self.table.item(r,0).data(Qt.ItemDataRole.UserRole),self).exec();self.load_data()
    def show_tag_reference(self):
        from PyQt6.QtWidgets import QDialog as _D,QVBoxLayout as _V
        from .gsn_tabs import TemplatesTab
        d=_D(self);d.setWindowTitle('Шаблоны и теги · Монтаж ГСН');d.resize(1100,700);_V(d).addWidget(TemplatesTab());d.exec()
    def create(self):GsnContractDialog(parent=self).exec();self.load_data()
    def edit(self,*_):
        r=self.table.currentRow()
        if r>=0:GsnContractDialog(self.table.item(r,0).data(Qt.ItemDataRole.UserRole),self).exec();self.load_data()
