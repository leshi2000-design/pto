import os,sys,tempfile,time
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=str(Path(folder.name)/'data');os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMessageBox
from PyQt6.QtCore import Qt
app=QApplication([])
def warning(*args):raise AssertionError(str(args[1:]))
QMessageBox.warning=warning
from smetagaz.database import db
db.init_db()
from smetagaz.gsn_view import GsnContractDialog,GsnProjectsView
from smetagaz import template_domain as domain
from docx import Document
from smetagaz.material_card import MaterialCardDialog
card=GsnContractDialog();card.number.setText('ГСН-25/26');card.title.setText('Газоснабжение жилого дома');card.address.setText('Минская область, ул. Центральная, 25');card.client_form.name.setText('Иванов Иван Иванович');card.client_form.phone.setText('+375 29 123-45-67');card.client_form.address.setText('Минск');card.client_form.passport.setText('AB1234567')
output=Path(folder.name)/'object';output.mkdir();card.executive.folder.setText(str(output));card.executive.fields['project_number'].setText('25-26 ГСН');card.executive.fields['project_date'].set_value('2026-09-01')
certfile=Path(folder.name)/'cert.pdf';certfile.write_bytes(b'example');cert=db.execute('INSERT INTO certificates(name,cert_number,file_path) VALUES(?,?,?)',('Сертификат трубы','BY-025',str(certfile))).lastrowid
mid=db.execute('INSERT INTO materials(name,unit,item_type,certificate_id) VALUES(?,?,?,?)',('Труба ПЭ 25','м','Материал',cert)).lastrowid
material=MaterialCardDialog(mid);assert material.certificate_id==cert
card.executive.add_material(dict(material_id=mid,kind='pe_pipe',name='Труба ПЭ 25',unit='м',quantity='25.5',certificate_id=cert,certificate_number='BY-025'));assert card.save_data();assert card.rid;assert db.fetchone('SELECT count(*) FROM crm.clients')[0]==1
rid=card.rid;reopened=GsnContractDialog(rid);assert reopened.executive.materials.rowCount()==1;assert reopened.client_form.name.text()=='Иванов Иван Иванович'
# The manual "pe_pipe_quantity" field was removed from the form (redundant with the materials
# table); the quantity must still reach templates through domain.context().
assert domain.context(db,'gsn_projects',rid)[0]['pe_pipe_quantity']=='25.5'
template=Path(folder.name)/'title.docx';doc=Document();doc.add_paragraph('{{номер_договора}} {{фио}} {{pe_pipe_certificate_number}}');doc.save(template);domain.save_template(db,'gsn_projects','title',str(template),'Титульник {{номер_договора}}');reopened.executive.refresh_templates();reopened.executive.templates_table.item(0,0).setCheckState(Qt.CheckState.Checked);reopened.executive.generate()
end=time.monotonic()+15
while reopened.executive.future and time.monotonic()<end:app.processEvents();time.sleep(.02)
assert not reopened.executive.future;assert len(list(output.iterdir()))==2;assert db.fetchone('SELECT count(*) FROM executive_generated')[0]==1
view=GsnProjectsView();assert view.table.rowCount()==1;view.search.setText('ГСН-25');assert view.table.rowCount()==1;view.search.setText('не найдено');assert view.table.rowCount()==0
from smetagaz.contract_card import ContractCardDialog
contract=ContractCardDialog();contract.client_form.name.setText('Петров Пётр Петрович');contract.executive.fields['tu_number'].setText('ТУ-42');assert contract.save_data();assert domain.context(db,contract.executive.owner,contract.executive.rid)[0]['tu_number']=='ТУ-42'
# ProjectEditDialog (Проекты ГСВ) no longer embeds ExecutiveWorkspace/Equipment/Pipelines — those
# belong to the installation contract card (ContractCardDialog) — but its own client+contract save
# and the domain-level context for gsv_projects (used by report/export templates) must still work.
from smetagaz.gsv_view import ProjectEditDialog
project=ProjectEditDialog();project.client_form.name.setText('Сидоров Сидор Сидорович');project.txt_object.setText('Проект ГСВ №2');assert project.save_data()
assert domain.context(db,'gsv_projects',project.project_id)[0]['full_name']=='Сидоров Сидор Сидорович'
assert not hasattr(project,'executive') and not hasattr(project,'equipment') and not hasattr(project,'pipelines') and not hasattr(project,'dossier')
reopened.show();reopened.findChild(__import__('PyQt6.QtWidgets',fromlist=['QTabWidget']).QTabWidget).setCurrentIndex(1);reopened.executive.setCurrentIndex(2);app.processEvents()
if os.environ.get('SMETAGAZ_SCREENSHOT'):reopened.grab().save(os.environ['SMETAGAZ_SCREENSHOT'])
print('GSN GUI OK: create/reopen, client, materials, certificates, background generation, filters, GSV integration')
reopened.close();card.close();db.close()
