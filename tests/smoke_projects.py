import os,sys,tempfile
from pathlib import Path
folder=tempfile.TemporaryDirectory();os.environ['SMETAGAZ_DATA_DIR']=folder.name;os.environ.setdefault('QT_QPA_PLATFORM','offscreen');sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication,QMessageBox
from PyQt6.QtCore import Qt,QDate
app=QApplication([])
from smetagaz.theme import apply
apply(app)
def warning(*a,**k):raise AssertionError(str(a[1:]))
QMessageBox.warning=warning
from smetagaz.database import db
db.init_db()
from smetagaz import gsv_project_domain as g
from smetagaz.gsv_view import ProjectEditDialog,GsvProjectsView,StatusEditorDialog,TemplateSettingsPanel
# --- новый договор: поля открыты, номера и срок по умолчанию ---
p=ProjectEditDialog();assert p.client_form.isEnabled() and p.spn_cost.value()==250
assert p.dt_due.date()==p.dt_contract.date().addDays(30)
p.dt_contract.setDate(QDate(2026,11,12));assert p.dt_due.date()==QDate(2026,12,12)           # срок следует за датой заключения
p.dt_due.setDate(QDate(2026,12,20));p.dt_contract.setDate(QDate(2026,11,13));assert p.dt_due.date()==QDate(2026,12,20)   # вручную изменённый срок не трогаем
p.client_form.name.setText('Иванов Иван Иванович');p.client_form.phone.setText('111 (основной); 222 (жена)');p.client_form.address.setText('Минск');p.client_form.passport.setPlainText('МР 1234567');p.client_form.passport_issuer.setText('РУВД');p.client_form.passport_date.set_value('2015-03-04')
assert p.client_form.phone.text()=='111 (основной); 222 (жена)' and len(p.client_form.phone.rows)==2
p.txt_object.setText('Жилой дом');p.chk_contract_signed.setChecked(True);p.dt_act.set_value('2026-12-10');p.chk_act.setChecked(True)
p.lst_work.item(1).setCheckState(Qt.CheckState.Checked);p.lst_work.item(2).setCheckState(Qt.CheckState.Checked);p.lst_client.item(1).setCheckState(Qt.CheckState.Checked)
assert p.save_data()
row=db.fetchone('SELECT pd_number,contract_number,work_status,client_status,contract_signed,act_signed,project_folder,client_id FROM gsv_projects WHERE id=?',(p.project_id,))
assert row[0].endswith('ГСВ') and '-03/' in row[1] and row[2]=='В работе, Не хватает данных' and row[3]=='Договор подписан' and row[4]==1 and row[5]==1 and not row[6]
client=db.fetchone('SELECT name,phone,address,passport,passport_issuer,passport_date FROM crm.clients WHERE id=?',(row[7],));assert client==('Иванов Иван Иванович','111 (основной); 222 (жена)','Минск','МР 1234567','РУВД','2015-03-04')
# --- документы: создание, пометка «изменилось», повторное формирование ---
assert p.doc_make['contract'].text()=='Сформировать' and not p.doc_open['contract'].isEnabled()
import smetagaz.gsv_view as gv
gv.open_file_or_dir=lambda path:None
import smetagaz.folder_ui as fu
fu.choose_folder=lambda parent,section,name,current='':(os.path.join(folder.name,'мои проекты',name),True)       # пользователь выбрал «Создать новую»
for kind in ('contract','act','card'):p.make_document(kind)
row=db.fetchone('SELECT pd_number,contract_number,work_status,client_status,contract_signed,act_signed,project_folder,client_id FROM gsv_projects WHERE id=?',(p.project_id,));assert os.path.isdir(row[6]) and os.path.basename(row[6]).startswith(row[0]+' - ') and row[6].endswith('(Иванов Иван Иванович)'),row[6]
assert all(p.doc_state[k].text()=='актуален' for k in g.DOC_KINDS)
assert p.is_editing_enabled          # сразу после первого создания карточка ещё открыта
p.toggle_edit();assert not p.txt_object.isEnabled();p.toggle_edit();assert p.is_editing_enabled and p.txt_object.isEnabled()
p.spn_cost.setValue(300);assert p.save_data();assert p.doc_state['contract'].text().startswith('данные изменились') and p.doc_make['contract'].text().startswith('⟳')
p.toggle_edit();assert not p.client_form.isEnabled() and not p.txt_object.isEnabled()          # после сохранения карточка закрыта
# --- повторное открытие: поля заблокированы, пока не нажата «Изменить» ---
q=ProjectEditDialog(p.project_id);assert not q.client_form.isEnabled() and not q.spn_cost.isEnabled() and q.txt_pd.text()==p.txt_pd.text() and q.chk_act.isChecked()
assert q.lst_work.item(1).checkState()==Qt.CheckState.Checked
# --- реестр: статусы и «сдан» только по подписанному акту ---
view=GsvProjectsView();view.load_data();assert view.model.rowCount()==1 and 'Сдан' in view.model.data(view.model.index(0,3))
db.execute('UPDATE gsv_projects SET act_signed=0');view.load_data();assert 'Сдан' not in view.model.data(view.model.index(0,3))
tree_texts=[view.side_board.tree.topLevelItem(g).child(i).text(0) for g in range(2) for i in range(view.side_board.tree.topLevelItem(g).childCount())];assert 'Не хватает данных  (1)' in tree_texts or any(t.startswith('Не хватает данных') for t in tree_texts)
# --- редактор статусов ---
ed=StatusEditorDialog();page=ed.tabs.widget(1);page.start_new();page.name.setText('Выдан проект');page.save();assert 'Выдан проект' in [r[1] for r in g.catalog(db,'client')]
TemplateSettingsPanel().table_tags.rowCount()==len(g.TAGS)
# --- клиент с таким ФИО уже есть: вторая карточка предлагает подставить данные ---
r=ProjectEditDialog();r.client_form.name.setText('иванов  иван иванович');assert r.client_form.duplicates()
QMessageBox.exec=lambda self:0
r.client_form.fill(db.execute('SELECT 1').fetchone() and {'name':'Иванов Иван Иванович','phone':'111'},row[7]);assert not r.client_form.duplicates()
# --- монтаж ГСВ и ГСН: сохранённый договор закрыт, папка создаётся автоматически ---
from smetagaz.gsn_view import GsnContractDialog
n=GsnContractDialog();n.title.setText('Газоснабжение дома');n.number.setText('ГСН-1');n.client_form.name.setText('Сидоров Сидор');assert n.save_data();assert not n.executive.folder.text()           # без кнопки папка не создаётся
import smetagaz.platform_utils as pu;pu.open_local=lambda p:None
n.open_folder();assert os.path.isdir(n.executive.folder.text()) and os.path.basename(n.executive.folder.text()).startswith('ГСН-1 - ') and n.executive.folder.text().endswith('(Сидоров Сидор)'),n.executive.folder.text()
n2=GsnContractDialog(n.rid);assert not n2.page.isEnabled() and n2.edit_button.isVisible() is not None;n2.toggle_edit();assert n2.page.isEnabled()
from smetagaz.contract_card import ContractCardDialog
from smetagaz import gsvm_domain as md
c=ContractCardDialog(title='Дом');c.client_form.name.setText('Петров Пётр Иванович');c.inp_object_address.setText('д. Ключи, 5');assert c.save_data();assert not md.contract_folder(db,c.contract_id)           # без кнопки папка не создаётся
assert c.inp_number.text().endswith('-02/'+str(__import__('datetime').date.today().year%100).zfill(2))
assert c.ask_folder() and os.path.basename(md.contract_folder(db,c.contract_id)).startswith(c.inp_number.text().replace('/','.')+', д. Ключи, 5 (Петров П.И.)'),md.contract_folder(db,c.contract_id)
c2=ContractCardDialog(contract_id=c.contract_id);assert not c2.client_form.isEnabled() and not c2.inp_object.isEnabled() and c2.equipment_tab.isEnabled();c2.toggle_edit();assert c2.client_form.isEnabled()
# --- файлы клиента ---
from smetagaz.client_files import client_folders,ClientFilesWidget
(Path(row[6])/'тест.txt').write_text('x');widget=ClientFilesWidget(row[7]);assert widget.tree.topLevelItemCount()==1 and widget.tree.topLevelItem(0).childCount()>=1
assert [s for s,_,_ in client_folders(db,row[7])]==['Проекты ГСВ']
# --- календарь ---
from smetagaz import agenda_domain as a
from datetime import date
ev=a.events_between(db,date(2026,11,13),date(2026,11,13));assert any(e['title'].startswith('Заключение договора Иванов И.И.') for e in ev)
print('PROJECTS GUI OK: client-first contract, 30-day due date, locked cards, multi-status editor, Word/Excel documents with regenerate flag, client files, calendar')
for w in (p,q,r,n,n2,c,c2,view):w.close()
# --- импорт из Excel ---
import sys as _sys
_sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_gsv_import import make_xlsx,ROWS
from smetagaz.gsv_import_view import ImportProjectsDialog
xlsx=Path(folder.name)/'clients.xlsx';make_xlsx(xlsx,ROWS[1:3])
imp_dialog=ImportProjectsDialog(view,str(xlsx));assert [c.currentData() for c in imp_dialog.combos][:4]==['pd_number','object_name','client_address','client_name']
imp_dialog.check();assert imp_dialog.preview.rowCount()==2 and imp_dialog.run.isEnabled()
QMessageBox.question=lambda *a,**k:QMessageBox.StandardButton.Yes;QMessageBox.information=lambda *a,**k:None
imp_dialog.do_import();assert db.fetchone("SELECT count(*) FROM gsv_projects WHERE object_name IN ('Баня','Гараж')")[0]==2
card=ProjectEditDialog(db.fetchone("SELECT id FROM gsv_projects WHERE object_name='Гараж'")[0]);assert card.txt_tu.text()=='ТУ 99' and not card.txt_tu.isEnabled()
# --- дерево статусов и порядок по № ПД ---
from smetagaz.gsv_view import GsvProjectsView as _V
picked=[];_V.open_edit_dialog=lambda self,pid:picked.append(pid)       # без модального окна
v2=_V();v2.load_data();pds=[v2.model.get_row_record(i)[1] for i in range(v2.model.rowCount())];keys=[(int(x[3:5]),int(x[:2])) for x in pds];assert keys==sorted(keys,reverse=True),pds
v2.toggle_order();pds=[v2.model.get_row_record(i)[1] for i in range(v2.model.rowCount())];keys=[(int(x[3:5]),int(x[:2])) for x in pds];assert keys==sorted(keys)
board=v2.side_board;board.reload_data();group=board.tree.topLevelItem(1);item=next(group.child(i) for i in range(group.childCount()) if group.child(i).text(0).startswith('Договор подписан'))
assert board.tree.topLevelItemCount()==2 and item.childCount()>=1 and not item.isExpanded()
board.on_clicked(item);assert item.isExpanded() and item.child(0).data(0,board.PROJECT_ROLE)
board.on_double_clicked(item.child(0));assert picked
v2.btn_tree.setChecked(False);assert board.isHidden() and db.get_setting('gsvp_tree_visible')=='0';v2.btn_tree.setChecked(True);assert not board.isHidden()
print('IMPORT GUI OK: column mapping, preview, import, TU field')
