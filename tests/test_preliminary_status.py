"""Договоры с юрлицами (СМР юрлиц, ТО юрлиц, Прочие): статус «Предварительно»."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys

import pytest

from smetagaz import contracts_core as cc
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


def legal_contract(db, mod, **extra):
    lid = db.fetchone('SELECT id FROM le_clients')[0] if db.fetchone('SELECT id FROM le_clients') else cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789'))
    values = dict(contract_date='2026-09-01', object_name='Объект', amount=100, status='Предварительно')
    values.update(dict(client_id=lid, direction='Монтажные работы') if mod == 'le' else dict(party_type='legal', legal_id=lid))
    values.update(extra)
    return cc.save_contract(db, mod, values)


def test_status_available_only_for_legal_sections(db):
    for mod in ('smr', 'to', 'le'):
        assert cc.statuses(mod) == ('Предварительно', 'Действует', 'Завершён', 'Расторгнут'), mod
        assert 'preliminary' in cc.visual_keys(mod) and ('preliminary', 'Предварительно') in cc.status_filters(mod)
    for mod in ('ip', 'fl'):
        assert cc.statuses(mod) == cc.STATUSES and 'preliminary' not in cc.visual_keys(mod) and all(k != 'preliminary' for k, _t in cc.status_filters(mod))
    person = db.execute("INSERT INTO crm.clients(name) VALUES('Иванов')").lastrowid
    with pytest.raises(ValueError, match='недоступен'):
        cc.save_contract(db, 'fl', dict(party_type='person', person_id=person, contract_date='2026-09-01', status='Предварительно'))
    with pytest.raises(ValueError, match='недоступен'):
        cc.save_contract(db, 'smr', dict(party_type='legal', legal_id=1, contract_date='2026-09-01', status='Что-то'))


def test_visual_status_and_registry_filters(db):
    ids = {mod: legal_contract(db, mod) for mod in ('smr', 'to', 'le')}
    for mod, cid in ids.items():
        row = cc.contract(db, mod, cid)
        assert row['status'] == 'Предварительно' and cc.display_status(row) == 'preliminary'
        assert cc.display_status(dict(row, end_date='2020-01-01')) == 'preliminary'                      # срок прошёл — всё равно «Предварительно», а не «Просрочен»
        assert cc.display_status(dict(row, status_manual='done')) == 'done'                              # вручную проставленный статус сильнее
    active = legal_contract(db, 'smr', status='Действует', end_date='2020-01-01')
    table = cc.cfg('smr')['contracts']
    found = {key: [r[0] for r in db.fetchall(f'SELECT c.id FROM {table} c WHERE ' + cc.status_condition(key, 'c')[0], cc.status_condition(key, 'c')[1])] for key in ('preliminary', 'overdue', 'work')}
    assert found['preliminary'] == [ids['smr']] and found['overdue'] == [active] and found['work'] == []         # «Предварительно» не попадает ни в «В работе», ни в «Просрочен»
    cc.set_visual_status(db, 'smr', ids['smr'], 'preliminary')
    assert cc.display_status(cc.contract(db, 'smr', ids['smr'])) == 'preliminary'
    with pytest.raises(ValueError):
        cc.set_visual_status(db, 'fl', 1, 'preliminary')
    assert ('preliminary', 'Предварительно') in cc.status_titles('smr') and all(k != 'preliminary' for k, _t in cc.status_titles('fl'))


def test_status_icon_and_dialogs(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    from smetagaz import status_icons, counterparty_ui as cu
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    QApplication.instance() or QApplication([])
    assert status_icons.title('preliminary') == 'Предварительно' and not status_icons.icon('preliminary').isNull() and status_icons.color('preliminary') == '#B45309'
    for mod in ('smr', 'to', 'le'):
        d = cu.ContractDialog(mod)
        items = [d.cmb_status.itemText(i) for i in range(d.cmb_status.count())]
        assert items[0] == 'Предварительно' and d.cmb_status.currentText() == 'Действует'                      # новый договор по умолчанию «Действует»
        assert any(d.manual_status.itemData(i) == 'preliminary' for i in range(d.manual_status.count()))
        d.cmb_status.setCurrentText('Предварительно')
        assert d.values()['status'] == 'Предварительно'
        view = cu.ContractsRegistry(mod)
        assert any(view.cmb_status.itemData(i) == 'preliminary' for i in range(view.cmb_status.count()))
    fl = cu.ContractDialog('fl')
    assert 'Предварительно' not in [fl.cmb_status.itemText(i) for i in range(fl.cmb_status.count())]
    # сохранение и повторное открытие через окно договора
    cid = legal_contract(db, 'smr', status='Действует')
    dialog = cu.ContractDialog('smr', cid)
    dialog.cmb_status.setCurrentText('Предварительно')
    assert dialog.save() and cc.contract(db, 'smr', cid)['status'] == 'Предварительно'
    assert 'Предварительно' in cu.ContractDialog('smr', cid).status_badge.text()
    registry = cu.ContractsRegistry('smr')
    registry.cmb_status.setCurrentIndex(registry.cmb_status.findData('preliminary'))
    registry.search_changed()
    assert registry.table.rowCount() == 1


def test_web_status_select_and_validation(db, tmp_path):
    from test_web_gateway import Client
    from smetagaz import web_gateway as wg
    wg.add_user(db, 'ed', 'editorpass1', 'editor')
    g = wg.WebGateway(db, '127.0.0.1', 0)
    g.start()
    try:
        c = Client(g)
        c.login('ed', 'editorpass1')
        lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789'))
        status, _p, h = c.request('POST', '/m/smr/new', dict(csrf=c.csrf('/m/smr/new'), f_contract_date='2026-06-01', f_party_type='legal', f_legal_id=str(lid), f_object_name='О', f_amount='10',
                                                             f_status='Предварительно'))
        assert status == 303
        cid = int(h['Location'].rsplit('/', 1)[1])
        assert cc.contract(db, 'smr', cid)['status'] == 'Предварительно'
        page = c.request('GET', f'/m/smr/{cid}')[1]
        assert '<option value="Предварительно" selected>' in page and 'Предварительно' in c.request('GET', '/m/smr')[1]
        person = db.execute("INSERT INTO crm.clients(name) VALUES('Иванов')").lastrowid
        page = c.request('GET', '/m/fl/new')[1]
        assert 'value="Предварительно"' not in page
        status, bad, _h = c.request('POST', '/m/fl/new', dict(csrf=c.csrf('/m/fl/new'), f_contract_date='2026-06-01', f_person_id=str(person), f_status='Предварительно'))
        assert status == 200 and 'Неизвестный статус' in bad
    finally:
        g.stop()
