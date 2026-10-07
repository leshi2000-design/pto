import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
from smetagaz import contracts_core as cc


@pytest.fixture
def env(tmp_path, monkeypatch):
    from smetagaz import gsv_project_domain as gd, counterparty_ui as ui, folder_ui, preflight_ui
    from smetagaz.database import DatabaseManager
    monkeypatch.setattr(gd, 'PROJECTS_DIR', tmp_path / 'p')
    monkeypatch.setattr(gd, 'TEMPLATES_DIR', tmp_path / 't')
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    monkeypatch.setattr(ui, 'db', d)
    import smetagaz.legal_entities_view as lev
    monkeypatch.setattr(lev, 'db', d)
    monkeypatch.setattr(preflight_ui, 'confirm', lambda *a, **k: True)
    monkeypatch.setattr(folder_ui, 'choose_folder', lambda parent, section, name, current='': (str(tmp_path / 'f' / name), True))
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: print('WARN', a[2:]))
    monkeypatch.setattr(ui, 'open_file', lambda *a, **k: True)
    app = QApplication.instance() or QApplication([])
    yield d, ui
    del app
    d.close()


def test_dialogs_and_registries(env):
    db, ui = env
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789'))
    d = ui.ContractDialog('le')
    d.set_party('legal', lid)
    d.amount.setValue(1200)
    d.vat_included.setChecked(True)
    d.subject.setText('Монтаж')
    assert d.save()
    assert d.number.text().endswith('-04/' + d.number.text()[-2:])
    act = cc.save_act(db, 'le', dict(contract_id=d.contract_id, act_date='2026-03-01', amount=1200, description='Работы', signed=1))
    d.refresh_all()
    d.acts_table.selectRow(0)
    d.make('contract')
    d.make('act')
    d.make('statement')
    assert cc.doc_state(db, 'le', 'statement', act) == 'fresh'
    pid = db.execute("INSERT INTO crm.clients(name) VALUES('Петров')").lastrowid
    s = ui.ContractDialog('smr')
    s.set_party('person', pid)
    s.amount.setValue(10)
    assert s.save() and s.number.text().startswith('01-05/')
    ui.ContractDialog.open_estimate = lambda self: None
    s.create_estimate()
    assert cc.estimate_state(db, s.contract_id) == "unsynced"
    for mod in ('le', 'smr'):
        for cls in (ui.ContractsRegistry, ui.ActsRegistry, ui.TemplatesTab):
            cls(mod)
    ui.LegalClientsRegistry()
    ui.LegalClientDialog(lid)
    ui.SmrView()
    from smetagaz.legal_entities_view import LegalEntitiesView
    LegalEntitiesView()


def test_legal_customer_in_gsv_cards(env, monkeypatch):
    db, ui = env
    import smetagaz.gsv_view as gv, smetagaz.contract_card as cardm
    import sys
    from smetagaz.database import db as singleton
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is singleton:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(ui.ContractDialog, 'exec', lambda self: 1)
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789', head_name='Иванов И.И.'))
    before = db.fetchone('SELECT count(*) FROM crm.clients')[0]
    dlg = gv.ProjectEditDialog()
    dlg.customer.set_legal(lid)
    dlg.txt_object.setText('Котельная')
    dlg.spn_cost.setValue(500)
    assert dlg.save_data()
    row = db.fetchone('SELECT le_client_id,party_name,client_name,client_id FROM gsv_projects WHERE id=?', (dlg.project_id,))
    assert row == (lid, 'ООО Ромашка', '', None)
    assert db.fetchone('SELECT count(*) FROM crm.clients')[0] == before
    dlg.customer.open_contract()
    c = db.fetchone("SELECT id,client_id,amount FROM le_contracts WHERE source_type='gsv_projects' AND source_id=?", (dlg.project_id,))
    assert c[1] == lid and c[2] == 500
    assert cc.contract_from_source(db, 'gsv_projects', dlg.project_id) == (c[0], False)
    reopened = gv.ProjectEditDialog(dlg.project_id)
    assert reopened.customer.is_legal() and reopened.customer.legal_id() == lid
    card = cardm.ContractCardDialog()
    card.customer.set_legal(lid)
    card.inp_object.setText('Дом')
    assert card.save_data()
    assert db.fetchone('SELECT le_client_id,party_name,client_id FROM contracts WHERE id=?', (card.contract_id,)) == (lid, 'ООО Ромашка', None)
    assert db.fetchone('SELECT count(*) FROM crm.clients')[0] == before
    assert cc.contract_from_source(db, 'contracts', card.contract_id)[1] is True
