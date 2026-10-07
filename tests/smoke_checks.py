import os,sys,tempfile
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=folder.name;os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMessageBox,QFileDialog
app=QApplication([])
sys.path.insert(0,str(Path(__file__).resolve().parent))
from smetagaz.theme import apply
apply(app)
QMessageBox.warning=lambda *a,**k:None;QMessageBox.information=lambda *a,**k:None;QMessageBox.question=lambda *a,**k:QMessageBox.StandardButton.Yes
from smetagaz.database import db
db.init_db()
import smetagaz.acts_statement_view as av,smetagaz.integrity_view as iv,smetagaz.preflight_ui as pfu
av.open_local=lambda p:None
# --- ведомость актов ---
db.execute("INSERT INTO gsv_projects(pd_number,contract_number,client_name,cost,act_date,act_signed) VALUES('01-26 ГСВ','01-03/26','Иванов',250,'2026-09-05',1)")
db.execute("INSERT INTO contracts(contract_number,client_name,contract_amount,acceptance_act_date,act_signed) VALUES('01-02/26','Козлов',1000,'2026-09-15',1)")
for section,expected in (('gsv_projects','Иванов'),('contracts','Козлов')):
    d=av.ActsStatementDialog(section);d.year.setValue(2026);d.month.setCurrentIndex(8);d.load()
    assert d.signed.rowCount()==1 and d.signed.item(0,2).text()==expected and 'подписано актов — 1' in d.summary.text()
    out=Path(folder.name)/f'v_{section}.xlsx';QFileDialog.getSaveFileName=staticmethod(lambda *a,**k:(str(out),''));d.save_excel();assert out.exists()
    QFileDialog.getExistingDirectory=staticmethod(lambda *a,**k:str(Path(folder.name)/'acts'));d.collect();assert (Path(folder.name)/'acts').exists()
# --- проверка базы ---
db.execute("INSERT INTO contracts(contract_number,client_id,client_name) VALUES('9',999,'Призрак')")
dlg=iv.IntegrityDialog();dlg.check();assert dlg.table.rowCount()>=1 and dlg.fix.isEnabled() and 'Ошибок: 1' in dlg.summary.text()
dlg.fix_clients();assert not dlg.fix.isEnabled() and list((Path(folder.name)/'backups').glob('before_integrity_fix_*'))
# --- резервная копия перед импортом ---
import smetagaz.gsv_import_view as gi
from test_gsv_import import make_xlsx,ROWS
x=Path(folder.name)/'c.xlsx';make_xlsx(x,ROWS[:2]);im=gi.ImportProjectsDialog(None,str(x));im.check();im.do_import()
assert len(list((Path(folder.name)/'backups').glob('before_import_*')))==1
# --- удаление клиента делает копию ---
import smetagaz.workspace_view as wv
cid=db.fetchone('SELECT id FROM crm.clients LIMIT 1')[0];assert wv.confirm_delete_client(None,cid) and len(list((Path(folder.name)/'backups').glob('before_delete_client_*')))==1
print('CHECKS GUI OK: acts statement for both sections, integrity dialog and fix, backups before import and client deletion')
