"""Integration test of user workflows; uses an isolated directory and offscreen Qt."""
import os,sys,tempfile
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=folder.name;os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMessageBox
from PyQt6.QtCore import Qt,QDate
app=QApplication([]);warnings=[]
QMessageBox.warning=lambda *a,**k:warnings.append(str(a[2]))
QMessageBox.information=lambda *a,**k:QMessageBox.StandardButton.Ok
from smetagaz.database import db
db.init_db()
from smetagaz.contract_card import ContractCardDialog
c=ContractCardDialog();c.inp_number.setText('ГСВ-21');c.inp_object.setText('Дом, ул. Садовая, 12');c.client_form.name.setText('Петров Иван');c.client_form.phone.setText('+375 29 1234567');c.client_form.address.setText('Минск');c.client_form.passport.setPlainText('AB 1234567')
c.equipment.add_row(dict(kind='Котел',model='BAXI 24',serial='SN-123'))
assert c.save_data();cid=c.client_form.client_id;rid=c.contract_id
assert db.fetchone('SELECT count(*) FROM crm.clients')[0]==1
assert c.save_data();assert db.fetchone('SELECT count(*) FROM crm.clients')[0]==1
# Existing client can be selected before the new contract has ever been saved.
from smetagaz.gsv_domain import get_client,dossier,add_document,link_documents
other=ContractCardDialog();other.client_form.fill(get_client(db,cid),cid);other.inp_number.setText('ГСВ-22');assert other.save_data();assert db.fetchone('SELECT count(*) FROM crm.clients')[0]==1
from smetagaz.gsv_view import ProjectEditDialog
project=ProjectEditDialog();project.client_form.name.setText('Заказчик проектирования');project.client_form.phone.setText('123');project.client_form.passport.setPlainText('ID 55');project.txt_object.setText('Проект ГСВ');assert project.save_data()
assert db.fetchone('SELECT passport FROM crm.clients WHERE id=?',(project.client_form.client_id,))[0]=='ID 55'
assert db.fetchone('SELECT count(*) FROM crm.clients')[0]==2
# Catalog certificate -> pipeline -> automatically visible in dossier.
from smetagaz.gsv_catalog import PipelineDialog
certfile=Path(folder.name)/'pipe_certificate.pdf';certfile.write_bytes(b'certificate test')
pipe=PipelineDialog();pipe.name.setText('Труба 25');pipe.new_path=str(certfile);pipe.number.setText('С-25');pipe.save()
c.pipes_tab.add_pipe(pipe.pipeline_id,12.5,'Стальная');assert c.save_data()
from smetagaz import gsvm_domain
assert any(r['number']=='С-25' for r in gsvm_domain.collect_certs(db,rid))
from smetagaz.welding_view import WelderDialog,JobDialog,ScheduleView,WeldersView
welder=WelderDialog();welder.inputs['name'].setText('Сидоров Павел');welder.inputs['birth_date'].set_value('1986-04-12');welder.inputs['certificate'].setText('НАКС-001');welder.inputs['stamp'].setText('ПС-12');welder.inputs['welding_type'].setText('РД');welder.inputs['grade'].setText('5');welder.inputs['valid_until'].set_value('2027-12-31');assert welder.save();assert welder.tabs.count()==2
source=Path(folder.name)/'external_docs';source.mkdir();path=source/'protocol.pdf';path.write_bytes(b'protocol')
doc=add_document(db,dict(title='Протокол сварщика',category='welder',document_type='Протокол',file_path=str(path),welder_id=welder.welder_id,number='П-1',document_date='2026-09-17',note=''))
gsvm_domain.set_attestations(db,rid,[doc]);link_documents(db,'contracts',rid,[doc]);c.id_tab.load();assert c.id_tab.attestations.table.rowCount()==1 and c.id_tab.certs.table.rowCount()>=1
assert path.read_bytes()==b'protocol'
# Existing estimate work can be chosen; free-form work remains an option.
est=db.execute('INSERT INTO estimates(title) VALUES("Работы ГСВ")').lastrowid
db.execute('UPDATE contracts SET estimate_id=? WHERE id=?',(est,rid))
item=db.execute('INSERT INTO estimate_items(estimate_id,item_type,name) VALUES(?,?,?)',(est,'Работа','Сварка трубопровода')).lastrowid
job=JobDialog(reference=('contracts',rid));job.source.setCurrentIndex(job.source.findData(item));job.welder.setCurrentIndex(job.welder.findData(welder.welder_id));job.work_date.set_value('2026-09-17');job.save();assert job.job_id
schedule=ScheduleView();schedule.load_data();assert schedule.table.columnCount()==5
assert db.fetchone('SELECT work_date FROM welding_days WHERE job_id=?',(job.job_id,))[0]=='2026-09-17'
from smetagaz.today_view import TodayView
calendar=TodayView();calendar.show_date_str('2026-09-17');assert any('Сварка трубопровода' in t for t in calendar.day.texts())
edit=JobDialog(job.job_id);edit.work_date.set_value('2026-09-18');edit.save()
calendar.show_date_str('2026-09-17');assert not any('Сварка трубопровода' in t for t in calendar.day.texts())
calendar.show_date_str('2026-09-18');assert any('Сварка трубопровода' in t for t in calendar.day.texts())
schedule.date_to.set_value('2026-09-17');assert schedule.table.rowCount()==0
schedule.date_to.set_value('2026-09-18');assert schedule.table.rowCount()==1
module=WeldersView();assert [module.tabs.tabText(i) for i in range(module.tabs.count())]==['График производства работ','Сварщики','Аттестация','Договоры и акты']
# No half-screen pagination panel.
from smetagaz.materials_view import MaterialsView
materials=MaterialsView();materials.resize(1100,750);materials.show();app.processEvents();assert materials.pager.bar.height()==44;assert materials.table.height()>400
from smetagaz.executive_view import ExecDocsBuilderTab
executive=ExecDocsBuilderTab();executive.cmb_projects.setCurrentIndex(executive.cmb_projects.findData(rid));assert executive.object_docs.table.rowCount()==1       # карточка монтажа ГСВ больше не пишет в общий модуль «Исполнительная документация»
# Export sections contain linked pipes and welding documents.
from smetagaz.exports import record_data
_,sections=record_data(db,'contracts',rid);assert any('Протокол сварщика' in str(section) for section in sections)
if os.environ.get('SMETAGAZ_SCREENSHOTS'):
 out=Path(os.environ['SMETAGAZ_SCREENSHOTS']);out.mkdir(parents=True,exist_ok=True)
 materials.grab().save(str(out/'pagination.png'))
 c.show();c.tabs.setCurrentIndex(0);app.processEvents();c.grab().save(str(out/'contract-client.png'))
 c.tabs.setCurrentIndex(2);app.processEvents();c.grab().save(str(out/'contract-pipelines.png'))
 c.tabs.setCurrentIndex(3);app.processEvents();c.grab().save(str(out/'contract-dossier.png'))
 module.resize(1400,760);module.show();app.processEvents();module.grab().save(str(out/'welding-schedule.png'))
assert not warnings,warnings
print('GSV/WELDING GUI OK: client-first creation/reuse; pipeline certificates; external documents; four tabs; schedule/calendar; compact pagination; dossier/export sections')
for window in app.topLevelWidgets():window.hide()
db.close()
