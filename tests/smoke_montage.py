import os,sys,tempfile
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=folder.name;os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMessageBox,QFileDialog
from PyQt6.QtCore import Qt
app=QApplication([])
from smetagaz.theme import apply
apply(app)
def warning(*a,**k):raise AssertionError(str(a[1:]))
QMessageBox.warning=warning;QMessageBox.information=lambda *a,**k:None
from smetagaz.database import db
db.init_db()
import smetagaz.preflight_ui as pfu;PREFLIGHT_SEEN=[];pfu.confirm=lambda parent,title,issues:PREFLIGHT_SEEN.append((title,issues)) or True      # сверку подтверждаем автоматически
from smetagaz import gsvm_domain as md,gsvm_docs as dd
import smetagaz.folder_ui as fu,smetagaz.gsvm_tabs as tabs,smetagaz.contract_card as cc
opened=[];tabs.open_local=lambda p,verb=None:opened.append((p,verb));cc.open_file=lambda parent,p,verb=None:opened.append((p,verb)) or True
fu.choose_folder=lambda parent,section,name,current='':(os.path.join(folder.name,'договоры',name),True)
from smetagaz.contract_card import ContractCardDialog
# --- новый договор: поля открыты, номер автоматический, после сохранения предлагается папка и карточка закрывается ---
c=ContractCardDialog();assert c.inp_number.text().startswith('XX-02/') and c.client_form.isEnabled()
c.client_form.name.setText('Иванов Иван Иванович');c.client_form.phone.setText('375291112233 (основной)');c.client_form.address.setText('Минск');c.client_form.passport.setPlainText('МР 1234567');c.client_form.passport_issuer.setText('РУВД')
c.inp_object.setText('Жилой дом');c.inp_object_address.setText('д. Ключи, 12');c.inp_code.setText('ГСВ-77');c.inp_designer.setText('ООО Проект');c.chk_project_month.setChecked(True)
from PyQt6.QtCore import QDate
c.date_contract.setDate(QDate(2026,11,12));assert c.date_end.date()==QDate(2027,1,11) and c.date_start.date()==QDate(2026,11,12)    # окончание = +60 дней
c.date_end.setDate(QDate(2027,1,20));c.date_contract.setDate(QDate(2026,11,13));assert c.date_end.date()==QDate(2027,1,20)           # вручную изменённый срок не двигается
c.date_contract.setDate(QDate(2026,11,12));c.chk_contract_signed.setChecked(True)
c.save_clicked();cid=c.contract_id;assert cid and c.inp_number.text()=='01-02/26' and not c.client_form.isEnabled() and not c.edit_button.isHidden()
folder_path=md.contract_folder(db,cid);assert os.path.basename(folder_path)=='01-02.26, д. Ключи, 12 (Иванов И.И.)',folder_path
# --- смета: нет данных → создать/привязать → получить → изменена ---
assert 'Нет данных' in c.lbl_estimate.text() and c.btn_pull.isHidden()
eid=db.execute("INSERT INTO estimates(title,total) VALUES('Смета на дом',0)").lastrowid;
md.link_estimate(db,cid,eid);c.estimate_id=eid;c.refresh_estimate_ui();assert 'Получить данные из сметы' in c.lbl_estimate.text()
p25=db.execute("INSERT INTO gsv_pipelines(name,unit) VALUES('Труба 25','м')").lastrowid
cert=db.execute("INSERT INTO certificates(name,cert_number,file_path) VALUES('Сертификат трубы 25','A-25',?)",(str(Path(folder.name)/'a25.pdf'),)).lastrowid;db.execute('UPDATE gsv_pipelines SET certificate_id=? WHERE id=?',(cert,p25))
(Path(folder.name)/'a25.pdf').write_bytes(b'pdf')
db.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum) VALUES(?,?,?,?,?,?,?)",(eid,'Материал','Труба 25','м',20,2,40));db.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum) VALUES(?,?,?,?,?,?,?)",(eid,'Работа','Монтаж','шт',1,60,60));db.execute('UPDATE estimates SET total=100 WHERE id=?',(eid,))
c.set_locked(False);c.pull_amount_from_estimate();assert c.inp_amount.value()==100 and 'материалов по клиенту' in c.lbl_estimate.text() and '40,00' in c.lbl_estimate.text() and '60,00' in c.lbl_estimate.text(),c.lbl_estimate.text()
db.execute("UPDATE estimate_items SET quantity=25,sum=50 WHERE item_type='Материал'");c.refresh_estimate_ui();assert 'была изменена — обновите данные' in c.lbl_estimate.text()
# --- оборудование: тип из списка и свой, файл копируется в папку договора ---
eq=c.equipment_tab;eq.add_row(dict(kind='Котел',model='Bosch 24',serial='SN-9'));eq.add_row(dict(kind='Печь',model='Своя',serial=''))
src=Path(folder.name)/'passport.pdf';src.write_bytes(b'x');QFileDialog.getOpenFileName=staticmethod(lambda *a,**k:(str(src),''))
eq.table.setCurrentCell(0,1);eq.attach();assert os.path.dirname(eq.table.item(0,4).data(Qt.ItemDataRole.UserRole)).endswith('Оборудование') and folder_path in eq.table.item(0,4).data(Qt.ItemDataRole.UserRole)
# --- трубы и стыки ---
pt=c.pipes_tab;pt.from_estimate();assert pt.top.rowCount()==1 and pt.top.cellWidget(0,1).value()==25 and pt.bottom.rowCount()==1
pt.bottom.cellWidget(0,1).setValue(5);
pt.add_joint_row('Сталь 57x3',3,'',None,None,1);pt.update_total();assert '8' in pt.total.text()
assert c.save_data();assert md.joints_total(db,cid)==8 and [j['custom'] for j in md.joints(db,cid)]==[0,1]
db.execute("UPDATE estimate_items SET quantity=40,sum=80 WHERE item_type='Материал'");c2=ContractCardDialog(contract_id=cid);assert c2.pipes_tab.top.cellWidget(0,1).value()==40       # строки из сметы следуют за сметой
# --- исполнительная документация ---
idt=c2.id_tab;idt.load();groups=[x['group'] for x in idt.certs.rows];assert 'equipment' in groups and 'pipeline' in groups,groups
idt.certs.table.selectRow(0);idt.certs.print_selected();idt.certs.print_all();assert opened and opened[-1][1]=='print'
welder_doc=db.execute("INSERT INTO welding_documents(title,category,document_type,file_path) VALUES('Аттестат производителя работ','attestation','Аттестация',?)",(str(src),)).lastrowid
md.set_attestations(db,cid,[welder_doc]);idt.attestations.load();assert idt.attestations.table.rowCount()==1
docs=idt.docs;docs.load();assert docs.table.rowCount()==7;docs.table.selectRow(1);docs.make();assert dd.doc_state(db,cid,'warranty')=='fresh';docs.make_all();assert all(dd.doc_state(db,cid,k)=='fresh' for k in dd.ID_KINDS)
# --- основные документы и смена данных ---
c2.set_locked(False);c2.make_document('contract');assert dd.doc_state(db,cid,'contract')=='fresh' and 'актуален' in c2.doc_state['contract'].text()
c2.inp_amount.setValue(555);assert c2.save_data();assert 'данные изменились' in c2.doc_state['contract'].text() and c2.doc_make['contract'].text().startswith('⟳')
# --- шаблоны и редактор тегов ---
tt=c2.templates_tab;tt.load_tags();assert tt.tags.rowCount()>40 and tt.tpl.rowCount()==10
names=[tt.tags.item(r,0).text() for r in range(tt.tags.rowCount())];assert 'НОМЕР_ДОГОВОРА' in names and 'КОТЕЛ_МОДЕЛЬ' in names and 'ТРУБА_25' in names and 'СТЫКИ_25' in names
row=names.index('КЛИЕНТ');tt.tags.item(row,0).setText('ЗАКАЗЧИК_ФИО');tt.new_tag();tt.tags.item(tt.tags.rowCount()-1,0).setText('ГОРОД');tt.save_tags();assert dd.tag_map(db,cid)['ЗАКАЗЧИК_ФИО']=='Иванов Иван Иванович'
# --- график работ и расход ---
welder=db.execute("INSERT INTO welders(name) VALUES('Сидоров')").lastrowid
from smetagaz import stock_domain
mats=[r[0] for r in db.fetchall('SELECT id FROM stock_materials ORDER BY id')];prof=db.fetchone("SELECT id FROM norm_profiles WHERE diameter='25'")[0]
stock_domain.save_profile(db,dict(name='Ду 25',diameter='25',thickness='3',basis='стык'),[(mats[0],'0.5')]+[(x,'0') for x in mats[1:]],prof)
d=tabs.WorkEntryDialog(cid,'Жилой дом',[(j['name'],j['count']) for j in md.joints(db,cid)]);d.welder.setCurrentIndex(d.welder.findData(welder));d.date.set_value('2026-11-20');assert d.table.rowCount()==2 and d.table.cellWidget(0,2).currentData()==prof
d.calculate();assert d.result.rowCount()==1;d.save();assert db.fetchone('SELECT count(*) FROM gsvm_consumption WHERE contract_id=?',(cid,))[0]==1 and md.consumption_summary(db,cid)[0][2]=='2.5'
tabs.ConsumptionDialog(cid)
print('MONTAGE GUI OK: auto number, folder prompt, locked card, estimate states, equipment files, pipes/joints, certificates, documents, tag editor, work schedule and consumption')
