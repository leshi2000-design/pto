import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from smetagaz import audit_domain as ad
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_changes_are_logged_and_noise_ignored(db):
    cid = db.execute("INSERT INTO contracts(contract_number,client_name,contract_amount) VALUES('01-02/26','Иванов',100)").lastrowid
    db.execute('UPDATE contracts SET contract_amount=200 WHERE id=?', (cid,))
    db.execute("UPDATE contracts SET est_synced_at='служебное' WHERE id=?", (cid,))
    kinds = [e['action'] for e in ad.entries(db, 'contracts')]
    assert sorted(kinds) == ['I', 'U']                       # служебное поле в журнал не попадает
    update = next(e for e in ad.entries(db, 'contracts') if e['action'] == 'U')
    assert ad.diff(update) == [('contract_amount', 100.0, 200.0)] and update['label'].startswith('01-02/26')


def test_restore_deleted_contract_with_children(db):
    cid = db.execute("INSERT INTO contracts(contract_number,contract_amount) VALUES('02-02/26',50)").lastrowid
    db.execute("INSERT INTO gsvm_equipment(contract_id,kind,model) VALUES(?,?,?)", (cid, 'ПГ', 'ПГ-4'))
    db.execute('DELETE FROM contracts WHERE id=?', (cid,))
    assert db.fetchone('SELECT count(*) FROM gsvm_equipment')[0] == 0
    deleted = next(e for e in ad.entries(db, action='D') if e['table'] == 'contracts')
    assert ad.restore(db, deleted['id']) == 2
    assert db.fetchone('SELECT contract_number,contract_amount FROM contracts WHERE id=?', (cid,)) == ('02-02/26', 50.0)
    assert db.fetchall('SELECT kind,model FROM gsvm_equipment') == [('ПГ', 'ПГ-4')]
    with pytest.raises(ValueError):
        ad.restore(db, deleted['id'])                         # повторно нельзя


def test_clients_database_is_audited_and_restorable(db):
    cl = db.execute("INSERT INTO crm.clients(name,phone) VALUES('Петров','1')").lastrowid
    db.execute('DELETE FROM crm.clients WHERE id=?', (cl,))
    deleted = next(e for e in ad.entries(db, action='D') if e['table'] == 'clients')
    assert deleted['schema'] == 'crm' and deleted['label'] == 'Петров'
    ad.restore(db, deleted['id'], 'crm')
    assert db.fetchone('SELECT name FROM crm.clients WHERE id=?', (cl,))[0] == 'Петров'


def test_view_lists_and_restores(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    import sys
    app = QApplication.instance() or QApplication([])
    import smetagaz.audit_view as av
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    cid = db.execute("INSERT INTO contracts(contract_number) VALUES('03-02/26')").lastrowid
    db.execute('DELETE FROM contracts WHERE id=?', (cid,))
    view = av.AuditView()
    view.action_filter.setCurrentIndex(1)
    view.load_data()
    assert view.table.rowCount() == 1 and view.table.item(0, 4).text() == 'в корзине'
    view.table.selectRow(0)
    view.restore()
    assert db.fetchone('SELECT contract_number FROM contracts WHERE id=?', (cid,))[0] == '03-02/26'
