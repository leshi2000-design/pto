import os,sys,tempfile,time
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=folder.name;os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMessageBox
from PyQt6.QtCore import Qt
app=QApplication([])
from smetagaz.theme import apply
apply(app)
def warning(*a,**k):raise AssertionError(str(a[1:]))
QMessageBox.warning=warning
from smetagaz.database import db
db.init_db()
from smetagaz.tasks_view import TaskEditDialog
from smetagaz.task_catalog import TasksTable
sid=db.execute("INSERT INTO task_statuses(code,name) VALUES('review','На согласовании')").lastrowid;tag=db.execute("INSERT INTO task_tags(name) VALUES('Срочный выезд')").lastrowid
task=TaskEditDialog();task.inp_title.setText('Проверить объект');task.task_fields.status.setCurrentIndex(task.task_fields.status.findData('review'));task.task_fields.tags.item(0).setCheckState(Qt.CheckState.Checked);task.save_task();view=TasksTable();view.search.setText('согласовании');assert view.table.rowCount()==1;view.search.setText('выезд');assert view.table.rowCount()==1;view.tag.setCurrentIndex(view.tag.findData(tag));assert view.table.rowCount()==1
from smetagaz.data_services import search
assert search(db,'согласовании');assert search(db,'выезд')
from smetagaz.gsn_view import GsnContractDialog
card=GsnContractDialog();card.title.setText('Газоснабжение дома');card.number.setText('ГСН-42');card.client_form.name.setText('Иванов Иван Иванович');card.amount.setValue(1000);out=Path(folder.name)/'object';out.mkdir();card.executive.folder.setText(str(out));assert card.save_data()
from smetagaz.payments_view import PaymentsDialog
pay=PaymentsDialog('gsn_projects',card.rid);pay.amount.setValue(250);pay.add();assert pay.table.rowCount()==1 and '250' in pay.info.text()
from smetagaz import payments_domain
est=db.execute("INSERT INTO estimates(title,total) VALUES('Связанная',1000)").lastrowid;payments_domain.link(db,'gsn_projects',card.rid,est);linked=PaymentsDialog('estimates',est);assert linked.table.rowCount()==1
from smetagaz import dossier_domain as dossier,template_domain
from docx import Document
src=Path(folder.name)/'title.docx';doc=Document();doc.add_paragraph('{{номер_договора}} {{фио}}');doc.save(src);template_domain.save_template(db,'gsn_projects','title',str(src),'Титул');did=dossier.create(db,'ГСН','gsn_projects',card.rid)
from smetagaz.dossier_view import DossierDialog,DossierRegistry,DossierTemplates
window=DossierDialog(did);assert window.docs.rowCount()==12;window.generate();deadline=time.monotonic()+15
while window.future and time.monotonic()<deadline:app.processEvents();time.sleep(.02)
assert not window.future;assert db.fetchone('SELECT count(*) FROM dossier_files WHERE dossier_id=?',(did,))[0]==1
registry=DossierRegistry();assert registry.table.rowCount()==1;templates=DossierTemplates();templates.module.setCurrentText('ГСВ');assert templates.table.rowCount()==8
card.executive.dossier_link.load_data();assert card.executive.dossier_link.list.rowCount()==1
window.show();app.processEvents()
if os.environ.get('SMETAGAZ_REVISION_SCREENSHOT'):assert window.grab().save(os.environ['SMETAGAZ_REVISION_SCREENSHOT'])
print('REVISION GUI OK: custom task statuses/tags and search; GSN payments shared with estimate; dossier generation and contract list; separate GSV templates')
window.close();card.close();pay.close();linked.close();app.processEvents()
