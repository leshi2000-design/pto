import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import date
import pytest
from smetagaz import notes_domain as nd, agenda_domain as agenda, contracts_core as cc
from smetagaz.data_services import delete_client, search
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_notes_free_and_linked_in_calendar(db):
    lid = cc.save_legal(db, dict(name='ООО Ромашка'))
    cid = cc.save_contract(db, 'le', dict(client_id=lid, direction='Монтажные работы', contract_date='2026-09-01', amount=10))
    pid = db.execute("INSERT INTO crm.clients(name) VALUES('Петров Пётр')").lastrowid
    free = nd.save_note(db, 'Купить материалы', 'Список у прораба', '2026-10-12')
    linked = nd.save_note(db, 'Договорились о скидке', 'Скидка 5%', '2026-10-13', ('le_contracts', cid))
    client_note = nd.save_note(db, '', 'Звонить после 18:00', '2026-10-14', ('crm.clients', pid))
    assert nd.get_note(db, client_note)['title'] == 'Звонить после 18:00'
    assert [n['id'] for n in nd.list_notes(db, 'free')] == [free]
    assert {n['id'] for n in nd.list_notes(db, 'linked')} == {linked, client_note}
    assert nd.list_notes(db, link=('le_contracts', cid))[0]['link'].startswith('Юрлица · 01-04/26')
    assert nd.count_for(db, 'le_contracts', cid) == 1
    events = [e for e in agenda.events_between(db, date(2026, 10, 12), date(2026, 10, 14)) if e['kind'] == 'note']
    assert {e['title'] for e in events} == {'Купить материалы', 'Договорились о скидке', 'Звонить после 18:00'}
    assert search(db, 'прораба')
    with pytest.raises(ValueError):
        nd.save_note(db, '', '')
    with pytest.raises(ValueError):
        nd.save_note(db, 'x', link=('bad', 1))
    delete_client(db, pid)
    assert nd.get_note(db, client_note) is None
    db.execute('DELETE FROM le_contracts WHERE id=?', (cid,))
    assert nd.get_note(db, linked) is None and nd.get_note(db, free)
