"""СМР (юрлица): у договора несколько объектов работ; акты составляются по объектам и делятся по объектам."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys

import pytest

from smetagaz import contracts_core as cc, volumes_domain as vd
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


def contract(db, mod='smr'):
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789'))
    return cc.save_contract(db, mod, dict(party_type='legal', legal_id=lid, contract_date='2026-09-01', object_name='Общий объект', object_address='Минск', amount=0)), lid


def test_objects_domain_and_acts_by_object(db):
    cid, _ = contract(db)
    assert cc.has_objects('smr') and not cc.has_objects('ip') and not cc.has_objects('to') and cc.objects(db, 'ip', 1) == []                      # только СМР юрлиц
    assert cc.acts_by_object(db, 'smr', cid) == [(None, '', [], 0.0)]                                                                          # объектов нет — как раньше, одна группа
    cc.save_objects(db, 'smr', cid, [dict(name='Котельная №1', address='Минск, Лесная 1'), dict(name='Котельная №2', address='Минск, Лесная 2', note='вторая очередь'),
                                     dict(name='Склад'), dict(name='', address='', note='')])
    objs = cc.objects(db, 'smr', cid)
    assert [o['name'] for o in objs] == ['Котельная №1', 'Котельная №2', 'Склад'] and objs[1]['note'] == 'вторая очередь'
    a1 = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='1', act_date='2026-09-10', amount=100, object_id=objs[0]['id']))
    a2 = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='2', act_date='2026-09-20', amount=200, object_id=objs[1]['id']))
    a3 = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='3', act_date='2026-10-01', amount=50, object_id=objs[0]['id']))
    a4 = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='4', act_date='2026-10-05', amount=7))                                       # без объекта
    groups = cc.acts_by_object(db, 'smr', cid)
    assert [(g[1], [a['id'] for a in g[2]], g[3]) for g in groups] == [('Котельная №1, Минск, Лесная 1', [a1, a3], 150.0), ('Котельная №2, Минск, Лесная 2', [a2], 200.0), ('Склад', [], 0.0), ('Без объекта', [a4], 7.0)]
    # акт чужого объекта и правка объекта акта
    other, _l = contract(db)
    cc.save_objects(db, 'smr', other, [dict(name='Чужой')])
    foreign = cc.objects(db, 'smr', other)[0]['id']
    with pytest.raises(ValueError, match='не относится'):
        cc.save_act(db, 'smr', dict(contract_id=cid, act_number='9', act_date='2026-10-06', amount=1, object_id=foreign))
    cc.save_act(db, 'smr', dict(contract_id=cid, act_number='4', act_date='2026-10-05', amount=7, object_id=objs[2]['id']), a4)
    assert cc.act(db, 'smr', a4)['object_id'] == objs[2]['id']
    cc.save_act(db, 'smr', dict(contract_id=cid, act_number='4', act_date='2026-10-05', amount=8), a4)                                          # без object_id в данных объект акта не сбрасывается
    assert cc.act(db, 'smr', a4)['object_id'] == objs[2]['id']
    # проверка названий
    with pytest.raises(ValueError, match='название'):
        cc.save_objects(db, 'smr', cid, [dict(name='', address='адрес')])
    with pytest.raises(ValueError, match='повторяться'):
        cc.save_objects(db, 'smr', cid, [dict(name='А'), dict(name='а')])
    with pytest.raises(ValueError, match='не относится'):
        cc.save_objects(db, 'smr', cid, [dict(id=foreign, name='Чужой')])
    with pytest.raises(ValueError, match='не предусмотрены'):
        cc.save_objects(db, 'ip', cid, [dict(name='А')])
    # удалили объект — его акты «без объекта», сами акты целы; порядок и переименование
    cc.save_objects(db, 'smr', cid, [dict(id=objs[1]['id'], name='Котельная №2 (новая)'), dict(id=objs[0]['id'], name='Котельная №1')])
    assert [o['name'] for o in cc.objects(db, 'smr', cid)] == ['Котельная №2 (новая)', 'Котельная №1']
    assert cc.act(db, 'smr', a4)['object_id'] is None and cc.act(db, 'smr', a2)['object_id'] == objs[1]['id'] and len(cc.acts(db, 'smr', cid)) == 4
    # объекты удаляются вместе с договором
    db.execute('DELETE FROM smr_acts WHERE contract_id=?', (cid,))
    db.execute('DELETE FROM smr_contracts WHERE id=?', (cid,))
    assert db.fetchone('SELECT count(*) FROM smr_objects WHERE contract_id=?', (cid,))[0] == 0


def test_act_tags_use_act_object_with_fallback_to_contract_object(db):
    cid, _ = contract(db)
    cc.save_objects(db, 'smr', cid, [dict(name='Котельная №1', address='Минск, Лесная 1')])
    oid = cc.objects(db, 'smr', cid)[0]['id']
    with_object = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='1', act_date='2026-09-10', amount=10, object_id=oid))
    without = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='2', act_date='2026-09-11', amount=10))
    t1, t2 = cc.tag_map(db, 'smr', cid, with_object), cc.tag_map(db, 'smr', cid, without)
    assert t1['ОБЪЕКТ_АКТА'] == 'Котельная №1' and t1['АДРЕС_ОБЪЕКТА_АКТА'] == 'Минск, Лесная 1'
    assert t2['ОБЪЕКТ_АКТА'] == 'Общий объект' and t2['АДРЕС_ОБЪЕКТА_АКТА'] == 'Минск'                    # у акта без объекта — объект договора
    assert cc.tag_map(db, 'smr', cid)['ОБЪЕКТ_АКТА'] == ''


def test_volumes_act_labels_carry_the_object_and_follow_object_order(db):
    cid, _ = contract(db)
    cc.save_objects(db, 'smr', cid, [dict(name='Первый'), dict(name='Второй')])
    first, second = [o['id'] for o in cc.objects(db, 'smr', cid)]
    late = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='1', act_date='2026-12-01', amount=1, object_id=first))
    early = cc.save_act(db, 'smr', dict(contract_id=cid, act_number='2', act_date='2026-09-01', amount=1, object_id=second))
    labels = [l for _i, l in vd.acts(db, 'smr_contracts', cid)]
    assert labels == ['Акт № 1 от 01.12.2026 · Первый', 'Акт № 2 от 01.09.2026 · Второй']            # сначала объект «Первый», затем «Второй», как в договоре
    assert [i for i, _l in vd.acts(db, 'smr_contracts', cid)] == [late, early]


def dialog_env(db, monkeypatch):
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    from PyQt6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    seen = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: seen.append(a[2]))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    return seen


def test_dialog_objects_tab_acts_grouped_and_new_act_goes_to_selected_object(db, monkeypatch):
    seen = dialog_env(db, monkeypatch)
    from smetagaz import counterparty_ui as cu
    from PyQt6.QtCore import Qt
    cid, _ = contract(db)
    d = cu.ContractDialog('smr', cid)
    assert any(d.tabs.tabText(i) == 'Объекты работ' for i in range(d.tabs.count()))
    assert not any(cu.ContractDialog('ip').tabs.tabText(i) == 'Объекты работ' for i in range(cu.ContractDialog('ip').tabs.count()))               # СМР (ИП) не меняется
    for name, address in (('Котельная №1', 'Лесная 1'), ('Котельная №2', 'Лесная 2')):
        r = d.add_object_row(name, address)
    d.objects_table.item(1, 0).setText('Котельная №1')                                  # повтор названия
    assert d.save() is False and any('повторяться' in str(x) for x in seen)
    d.objects_table.item(1, 0).setText('Котельная №2')
    assert d.save() and [o['name'] for o in cc.objects(db, 'smr', cid)] == ['Котельная №1', 'Котельная №2']
    first, second = [o['id'] for o in cc.objects(db, 'smr', cid)]
    cc.save_act(db, 'smr', dict(contract_id=cid, act_number='1', act_date='2026-09-10', amount=100, object_id=first))
    cc.save_act(db, 'smr', dict(contract_id=cid, act_number='2', act_date='2026-09-20', amount=200, object_id=second))
    cc.save_act(db, 'smr', dict(contract_id=cid, act_number='3', act_date='2026-09-25', amount=5))
    d.refresh_all()
    t = d.acts_table
    kinds = ['H' if t.item(r, 0).data(Qt.ItemDataRole.UserRole + 1) else 'A' for r in range(t.rowCount())]
    assert kinds == ['H', 'A', 'H', 'A', 'H', 'A']                                      # три группы: объект 1, объект 2, «без объекта»
    assert 'Котельная №1, Лесная 1' in t.item(0, 0).text() and 'актов: 1 на сумму 100,00' in t.item(0, 0).text() and 'Без объекта' in t.item(4, 0).text()
    assert d.objects_table.item(0, 3).text() == '1' and '200,00' in d.objects_table.item(1, 4).text()                    # у каждого объекта — число и сумма актов
    t.setCurrentCell(3, 0)                                                              # строка акта второго объекта
    assert d.selected_object() == second
    t.setCurrentCell(0, 0)
    assert d.selected_object() == first
    act_dialog = cu.ActDialog('smr', cid, parent=d, object_id=second)
    assert act_dialog.object_box.currentData() == second and act_dialog.object_box.count() == 3                       # объект выбран заранее: «без объекта» + два объекта
    act_dialog.number.setText('10')
    act_dialog.amount.setValue(33)
    act_dialog.save()
    assert [a['object_id'] for a in cc.acts(db, 'smr', cid) if a['act_number'] == '10'] == [second]
    # удаление объекта в окне: акты остаются «без объекта»
    d.objects_table.setCurrentCell(0, 0)
    d.remove_object()
    assert d.save()
    assert [o['name'] for o in cc.objects(db, 'smr', cid)] == ['Котельная №2'] and len(cc.acts(db, 'smr', cid)) == 4
    # у договора без объектов окно актов выглядит как раньше (без заголовков)
    plain, _l = contract(db)
    pd = cu.ContractDialog('smr', plain)
    cc.save_act(db, 'smr', dict(contract_id=plain, act_number='1', act_date='2026-09-10', amount=1))
    pd.refresh_all()
    assert pd.acts_table.rowCount() == 1 and not pd.acts_table.item(0, 0).data(Qt.ItemDataRole.UserRole + 1)
    assert cu.ActDialog('smr', plain).object_box is None
