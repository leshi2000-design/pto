"""Объёмы СМР делятся по актам выполненных работ: вкладка «Объёмы» показывает все объёмы договора, сгруппированные по актам."""
import sys

import pytest

from smetagaz import contracts_core as cc, volumes_domain as vd
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def make(db, mod='smr'):
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789'))
    cid = cc.save_contract(db, mod, dict(party_type='legal', legal_id=lid, contract_date='2026-09-01', amount=0))
    a1 = cc.save_act(db, mod, dict(contract_id=cid, act_number='1', act_date='2026-09-20', amount=100))
    a2 = cc.save_act(db, mod, dict(contract_id=cid, act_number='2', act_date='2026-10-20', amount=200))
    return cid, a1, a2


def test_volumes_split_by_acts_and_listed_together(db):
    cid, a1, a2 = make(db)
    owner = 'smr_contracts'
    assert [label for _i, label in vd.acts(db, owner, cid)] == ['Акт № 1 от 20.09.2026', 'Акт № 2 от 20.10.2026']
    vd.save_items(db, owner, cid, [dict(kind='Материал', name='Труба', unit='м', quantity='10', act_id=a2), dict(kind='Работа', name='Монтаж', unit='м', quantity='10', act_id=a1),
                                   dict(kind='Материал', name='Труба', unit='м', quantity='5', act_id=a1), dict(kind='Материал', name='Хомут', unit='шт', quantity='3')])
    rows = vd.items(db, owner, cid)
    assert [(r['name'], r['act_id']) for r in rows] == [('Монтаж', a1), ('Труба', a1), ('Труба', a2), ('Хомут', None)]       # по актам в порядке дат, «без акта» в конце
    groups = vd.grouped(db, owner, cid)
    assert [(label, [r['name'] for r in rs]) for _a, label, rs in groups] == [('Акт № 1 от 20.09.2026', ['Монтаж', 'Труба']), ('Акт № 2 от 20.10.2026', ['Труба']), ('Без акта', ['Хомут'])]
    assert {(r['name'], r['quantity']) for r in vd.totals(db, owner, cid)} == {('Монтаж', 10.0), ('Труба', 15.0), ('Хомут', 3.0)}      # общие объёмы — сумма по актам


def test_acts_without_volumes_still_listed_and_foreign_act_rejected(db):
    cid, a1, a2 = make(db)
    other, b1, _b2 = make(db)
    owner = 'smr_contracts'
    assert [(a, rs) for a, _l, rs in vd.grouped(db, owner, cid)] == [(a1, []), (a2, [])]
    with pytest.raises(ValueError, match='акт'):
        vd.save_items(db, owner, cid, [dict(name='Труба', quantity='1', act_id=b1)])                   # акт чужого договора
    with pytest.raises(ValueError, match='акт'):
        vd.save_items(db, 'gsn_projects', 1, [dict(name='Труба', quantity='1', act_id=a1)])             # раздел без актов
    assert vd.items(db, owner, cid) == []


def test_deleting_act_keeps_its_volumes_as_without_act(db):
    cid, a1, a2 = make(db)
    owner = 'smr_contracts'
    vd.save_items(db, owner, cid, [dict(name='Труба', quantity='10', act_id=a1), dict(name='Кран', quantity='2', act_id=a2)])
    cc.delete_act(db, 'smr', a1)
    rows = {r['name']: r['act_id'] for r in vd.items(db, owner, cid)}
    assert rows == {'Труба': None, 'Кран': a2}                                                         # объёмы удалённого акта не потеряны


def test_estimate_is_built_from_total_of_all_acts(db):
    from smetagaz import estimates_domain as ed
    db.execute("INSERT INTO materials(item_type,name,unit,price,purchase_price) VALUES('Материал','Труба','м',5,3)")
    cid, a1, a2 = make(db)
    owner = 'smr_contracts'
    vd.save_items(db, owner, cid, [dict(name='Труба', unit='м', quantity='10', act_id=a1), dict(name='труба', unit='м', quantity='5', act_id=a2)])
    eid, _unpriced = vd.build_estimate(db, owner, cid)
    items = db.fetchall("SELECT name,quantity,sum FROM estimate_items WHERE estimate_id=? AND item_type<>'Раздел'", (eid,))
    assert len(items) == 1 and items[0][1] == 15 and float(items[0][2]) == 75.0
    assert ed.contract_of(db, eid)['id'] == cid


def test_ip_and_fl_also_split_and_gsv_has_no_acts(db):
    for mod, owner in (('ip', 'ip_contracts'), ('fl', 'fl_contracts')):
        cid = cc.save_contract(db, mod, dict(party_type='person', person_id=db.execute("INSERT INTO crm.clients(name) VALUES('Иванов')").lastrowid, contract_date='2026-09-01', amount=0))
        a = cc.save_act(db, mod, dict(contract_id=cid, act_number='7', act_date='2026-09-30', amount=1))
        vd.save_items(db, owner, cid, [dict(name='Работа', quantity='1', act_id=a)])
        assert vd.items(db, owner, cid)[0]['act_id'] == a
    assert vd.acts(db, 'contracts', 1) == [] and not vd.has_acts('contracts') and not vd.has_acts('gsn_projects')
    assert [(g[0], g[1]) for g in vd.grouped(db, 'contracts', 1)] == [(None, 'Объёмы договора')]


def test_tab_groups_by_act_filters_and_adds_to_selected_act(db, monkeypatch):
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    from smetagaz import counterparty_ui as cu
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: 0)
    cid, a1, a2 = make(db)
    d = cu.ContractDialog('smr')
    d.contract_id = cid
    tab = d.volumes_tab
    vd.save_items(db, 'smr_contracts', cid, [dict(name='Труба', unit='м', quantity='10', act_id=a1), dict(name='Кран', unit='шт', quantity='2', act_id=a2), dict(name='Хомут', quantity='3')])
    tab.reload()
    assert not tab.table.isColumnHidden(0) and tab.filter.isVisibleTo(tab)
    heads = [tab.table.item(r, 0).text() for r in range(tab.table.rowCount()) if tab.is_header(r)]
    assert [h.split('  ·')[0] for h in heads] == ['Акт № 1 от 20.09.2026', 'Акт № 2 от 20.10.2026', 'Без акта']
    assert [r['name'] for r in tab.rows()] == ['Труба', 'Кран', 'Хомут'] and [r['act_id'] for r in tab.rows()] == [a1, a2, None]
    # фильтр: только второй акт
    tab.filter.setCurrentIndex(tab.filter.findData(a2))
    visible = [tab.table.item(r, 2).text() for r in range(tab.table.rowCount()) if not tab.table.isRowHidden(r) and not tab.is_header(r)]
    assert visible == ['Кран']
    # новая строка попадает в выбранный акт и без количества по умолчанию
    tab.new_row('Материал', 'Муфта', 'шт', None)
    added = [r for r in tab.rows() if r['name'] == 'Муфта'][0]
    assert added['act_id'] == a2 and added['quantity'] == 0
    for r in range(tab.table.rowCount()):                                                                  # вписываем количество и сохраняем
        if tab.table.item(r, 2) and tab.table.item(r, 2).text() == 'Муфта':
            tab.table.item(r, 4).setText('4')
    assert tab.save()
    saved = {r['name']: (r['act_id'], r['quantity']) for r in vd.items(db, 'smr_contracts', cid)}
    assert saved['Муфта'] == (a2, 4.0) and saved['Труба'] == (a1, 10.0) and saved['Хомут'] == (None, 3.0)
    # после сохранения таблица перегруппирована: «Муфта» рядом с «Кран» во втором акте
    names = [tab.table.item(r, 2).text() for r in range(tab.table.rowCount()) if not tab.is_header(r)]
    assert names == ['Труба', 'Кран', 'Муфта', 'Хомут']
    # новый акт в договоре — появляется в списке без пересоздания окна
    a3 = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='3', act_date='2026-11-20', amount=5))
    tab.reload()
    assert tab.filter.findData(a3) >= 0 and any('Акт № 3' in h for h in [tab.table.item(r, 0).text() for r in range(tab.table.rowCount()) if tab.is_header(r)])
    # без актов (ГСВ) колонка и фильтр скрыты
    from smetagaz.volumes_ui import VolumesTab

    class Dlg:
        contract_id = None
    plain = VolumesTab('contracts', Dlg())
    assert plain.table.isColumnHidden(0) and not plain.filter.isVisibleTo(plain)
