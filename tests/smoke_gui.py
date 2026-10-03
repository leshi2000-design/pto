"""Run separately: QT_QPA_PLATFORM=offscreen python tests/smoke_gui.py"""
import os,sys,tempfile
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=folder.name;os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMessageBox
app=QApplication([])
QMessageBox.information=lambda *a,**k:QMessageBox.StandardButton.Ok
QMessageBox.warning=lambda *a,**k:QMessageBox.StandardButton.Ok
from smetagaz.database import db
db.init_db()
rid=db.execute('INSERT INTO estimates(title,client_name,client_phone,mat_adj_pct,work_adj_pct,total_adj_pct) VALUES(?,?,?,?,?,?)',('Тестовая смета','Иван Петров','+43 555',12.5,14.5,5.0)).lastrowid
with db.transaction():
 db.executemany('INSERT INTO materials(name,item_type) VALUES(?,?)',((f'Материал {i}','Материал') for i in range(420)))
 db.executemany('INSERT INTO certificates(name) VALUES(?)',((f'Сертификат {i}',) for i in range(420)))
from smetagaz.main_window import MainWindow
w=MainWindow()
for i,b in enumerate(w.tabs_buttons):w.switch_tab(i,b);app.processEvents()
from smetagaz.materials_view import MaterialsView
from smetagaz.executive_view import CertificatesTab
from smetagaz.dialogs_common import MaterialSelectionDialog
for test_view in [MaterialsView(),CertificatesTab(),MaterialSelectionDialog()]:
 assert test_view.table.rowCount()==200
 test_view.pager.page(1);assert test_view.table.rowCount()==200
 test_view.pager.page(1);assert test_view.table.rowCount()==20
from smetagaz.estimate_editor import EstimateEditorDialog
editor=EstimateEditorDialog(rid,'Тестовая смета',w)
assert db.fetchone('SELECT mat_adj_pct,work_adj_pct,total_adj_pct FROM estimates WHERE id=?',(rid,))==(12.5,14.5,5.0)
from smetagaz.contract_card import ContractCardDialog
cid=db.execute('INSERT INTO contracts(estimate_id,contract_number) VALUES(?,?)',(rid,'25/2026')).lastrowid
cert=db.execute('INSERT INTO certificates(name) VALUES("Сертификат")').lastrowid
db.execute('INSERT INTO contract_equipment(contract_id,equipment_name,linked_cert_id) VALUES(?,?,?)',(cid,'Котёл',cert))
card=ContractCardDialog(contract_id=cid);card.save_data();assert db.fetchone('SELECT linked_cert_id FROM contract_equipment WHERE contract_id=?',(cid,))[0]==cert
from smetagaz.gsv_view import ProjectEditDialog
project=ProjectEditDialog()
from smetagaz.workspace_view import WorkspaceView,ExportDialog
workspace=WorkspaceView();export=ExportDialog('estimates',rid)
from smetagaz.main_window import GlobalSearchDialog
search=GlobalSearchDialog(w);search.inp.setText('петр');search.submit()
import time
for _ in range(40):app.processEvents();time.sleep(.01)
assert search.results.count()>0
search.reject();export.reject()
# Verify duplicate with all metadata retained.
from smetagaz.estimates_registry import EstimatesView
view=EstimatesView();view.table.selectRow(0);view.duplicate_estimate()
assert db.fetchone('SELECT count(*) FROM estimates')[0]==2
assert db.fetchone('SELECT mat_adj_pct FROM estimates ORDER BY id DESC LIMIT 1')[0]==12.5
for i,b in enumerate(w.tabs_buttons):
 if 'быстрый' in b.text():w.switch_tab(i,b);break
w.show();app.processEvents()
if os.environ.get('SMETAGAZ_SCREENSHOT'):w.grab().save(os.environ['SMETAGAZ_SCREENSHOT'])
w.backup_service.close();w.hide();db.close()
print(f'GUI OK: {len(w.tabs_buttons)} tabs; estimate metadata; contract certificate links; duplication; search; export dialog')
