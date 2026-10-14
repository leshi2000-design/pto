import os, sys, tempfile
from pathlib import Path
folder = tempfile.TemporaryDirectory()
os.environ['SMETAGAZ_DATA_DIR'] = str(Path(folder.name) / 'data')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import QDate
app = QApplication([])
def warning(*args): raise AssertionError(str(args[1:]))
QMessageBox.warning = warning
from smetagaz.database import db
db.init_db()
from smetagaz.gsn_view import GsnContractDialog, GsnProjectsView
from smetagaz import gsn_domain as gn, gsn_docs as dd

card = GsnContractDialog()
card.number.setText('ГСН-25/26'); card.title.setText('Газоснабжение жилого дома'); card.address.setText('Минская область, ул. Центральная, 25')
card.client_form.name.setText('Иванов Иван Иванович'); card.client_form.phone.setText('+375 29 123-45-67'); card.client_form.address.setText('Минск'); card.client_form.passport.setText('AB1234567')
card.date_contract.setDate(QDate(2026, 3, 1))
assert card.date_end.date() == QDate(2026, 3, 1).addDays(60) and card.date_start.date() == QDate(2026, 3, 1)
card.pipeline_tab.pe.setValue(12.5); card.pipeline_tab.steel.setValue(3)
assert card.save_data() and card.contract_id
assert db.fetchone('SELECT count(*) FROM crm.clients')[0] == 1
cid = card.contract_id
again = GsnContractDialog(cid)
assert again.locked and again.client_form.name.text() == 'Иванов Иван Иванович' and again.number.text() == 'ГСН-25/26'
assert again.pipeline_tab.pe.value() == 12.5
for tab in range(again.tabs.count()):
    again.tabs.setCurrentIndex(tab); app.processEvents()
assert len(dd.tag_map(db, cid)) > 50
view = GsnProjectsView(); assert view.table.rowCount() == 1
view.search.setText('ГСН-25'); assert view.table.rowCount() == 1
view.search.setText('не найдено'); assert view.table.rowCount() == 0
print('ok')
