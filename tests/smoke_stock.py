import os,sys,tempfile
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=folder.name;os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMessageBox
app=QApplication([]);warnings=[]
QMessageBox.warning=lambda *a,**k:warnings.append(str(a[2]));QMessageBox.question=lambda *a,**k:QMessageBox.StandardButton.Yes
from smetagaz.database import db
db.init_db()
from smetagaz import stock_domain as s
from smetagaz.stock_view import WriteoffView,NormDialog,ActDialog,ReceiptDialog,DefectDialog,MaterialDialog,item
from smetagaz.welding_view import JobDialog,ScheduleView
# All free-form fields work without a contract or welder card.
j=JobDialog();j.object_text.setText('Котельная на ул. Лесной');j.title.setText('Переварка ввода');j.welder.setEditText('Петров, приглашённый сварщик');j.work_date.set_value('2026-09-17');j.save();assert j.job_id and not warnings
journal=ScheduleView();assert journal.table.rowCount()==1 and journal.table.columnCount()==5
journal.search.setText('лесной');assert journal.table.rowCount()==1
journal.date_from.set_value('2026-09-18');assert journal.table.rowCount()==0
journal.clear_dates();journal.search.clear()
# Define test norms through the real editor; these are not shipped as normative values.
n=NormDialog(1)
for r,rate in enumerate(['0.1','0.2','0.03','0','0.05']):item(n.table,r,2,rate)
n.save();assert not warnings
for mid in range(1,6):
 r=ReceiptDialog(mid);r.qty.setText('10');r.day.set_value('2026-09-01');r.note.setText('Начальный остаток');r.save()
a=ActDialog();a.header.object_name.setText('Дом на Лесной, 15');a.header.inputs['organization'].setText('Тестовая организация');a.header.inputs['commission'].setText('Иванов И.И., Петров П.П.');a.header.day.set_value('2026-09-17');a.volumes.add_row(1,'10');a.calculate();assert a.lines.rowCount()==4;a.save();assert a.aid and not warnings
a.post();assert a.status=='posted' and s.balance(db,1)==s.units(9)
a.reverse();assert a.status=='reversed' and s.balance(db,1)==s.units(10)
a.copy();assert a.status=='draft';a.post();assert s.balance(db,1)==s.units(9)
# Overdraw blocks all materials, reports shortage and keeps the draft.
b=ActDialog();b.header.object_name.setText('Нехватка');b.header.day.set_value('2026-09-17');b.add_line(1,None,s.units(100));b.post();assert b.status=='draft';assert any('Недостаточно' in w for w in warnings);warnings.clear()
# Defect -> quantities -> linked writeoff; duplicate click resolves same document.
d=DefectDialog();d.header.object_name.setText('Ремонт узла');d.header.day.set_value('2026-09-17');d.add_row(dict(defect='Течь стыка',work='Сварить стык Ду15',unit='стык',quantity='2',profile_id=1));assert d.save()
aid=s.from_defect(db,d.did);derived=ActDialog(aid);assert derived.defect_id==d.did and derived.lines.rowCount()==4;derived.post();assert derived.status=='posted'
module=WriteoffView();module.resize(1380,820);module.show();app.processEvents();assert module.tabs.count()==7
acts=module.tabs.widget(0);acts.status.setCurrentIndex(acts.status.findData('posted'));assert acts.table.rowCount()==2
acts.search.setText('лесной');assert acts.table.rowCount()==1
acts.date_to.set_value('2026-09-16');assert acts.table.rowCount()==0;acts.reset()
# SQL filters select a match beyond page 1.
for i in range(230):s.save_material(db,f'Тест {i}','Тест','шт')
materials=module.tabs.widget(3);materials.load_data();materials.pager.filters.rules=[('name','Равно','Тест 229')];materials.load_data();assert materials.table.rowCount()==1
from smetagaz.workspace_view import WorkspaceView
workspace=WorkspaceView('stock_acts');workspace.filters.rules=[('status','Равно','posted')];workspace.load_data();assert workspace.table.rowCount()==2
from smetagaz.stock_exports import export_document
out=Path(os.environ.get('SMETAGAZ_SCREENSHOTS',folder.name));out.mkdir(parents=True,exist_ok=True)
for source,rid,name in [('stock_acts',a.aid,'writeoff'),('defect_acts',d.did,'defect')]:
 for ext in ('pdf','docx','xlsx'):export_document(db,source,rid,out/f'{name}.{ext}',dict(mode='c29'))
if os.environ.get('SMETAGAZ_SCREENSHOTS'):
 module.tabs.setCurrentIndex(0);app.processEvents();module.grab().save(str(out/'writeoff-registry.png'))
 module.tabs.setCurrentIndex(4);app.processEvents();module.grab().save(str(out/'balances.png'))
 journal.resize(1380,760);journal.show();app.processEvents();journal.grab().save(str(out/'welding-journal.png'))
 derived.show();derived.tabs.setCurrentIndex(2);app.processEvents();derived.grab().save(str(out/'writeoff-card.png'))
assert not warnings,warnings
print('STOCK GUI OK: free journal; norms; receipt; post/reversal; shortage; defect writeoff; all-page filters; exports')
for w in app.topLevelWidgets():w.hide()
db.close()
