import sys

import pytest

from smetagaz import contracts_core as cc, gsvm_domain as md, numbering as nm, section_codes as sc
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_defaults_and_validation(db):
    assert {k: sc.code(db, k) for k in sc.KINDS} == {'contracts': '02', 'gsv_projects': '03', 'le': '04', 'smr': '05', 'to': '06', 'ip': '07', 'fl': '08'}
    for bad in ('', 'a b', '1-2', '1/2', '12345'):
        with pytest.raises(ValueError):
            sc.set_code(db, 'smr', bad)
    with pytest.raises(ValueError):
        sc.set_code(db, 'smr', '02')                                 # занят видом «монтаж ГСВ»
    with pytest.raises(ValueError):
        sc.save_all(db, {'smr': '10', 'to': '10'})                   # два вида с одним номером


def test_new_numbers_use_new_code_and_old_numbers_still_recognised(db):
    day = '2026-03-01'
    seq, yy, number = md.next_number(db, day)
    assert number == '01-02/26'
    db.execute("INSERT INTO contracts(contract_number,seq_num,year_num) VALUES(?,?,?)", (number, seq, yy))
    sc.set_code(db, 'contracts', '12')
    seq, yy, number = md.next_number(db, day)
    assert number == '02-12/26'                                      # порядок продолжается, раздел новый
    db.execute("INSERT INTO contracts(contract_number,seq_num,year_num) VALUES(?,?,?)", (number, seq, yy))
    assert md.next_number(db, day)[2] == '03-12/26'
    # старый номер по-прежнему разбирается (например, при обмене номерами)
    assert nm.parse('contracts', '01-02/26', db) == (1, 26)
    assert nm.parse('contracts', '02-12/26', db) == (2, 26)
    assert nm.format_number('contracts', 5, 26, db)[0] == '05-12/26'
    # номер без «хвоста» из истории: старый номер раздела другого вида занять нельзя
    with pytest.raises(ValueError):
        sc.set_code(db, 'smr', '02')
    assert sc.used(db, 'contracts') == 2


def test_each_contract_kind_has_its_own_section(db):
    sc.save_all(db, {'contracts': '21', 'gsv_projects': '22', 'smr': '23', 'to': '24', 'ip': '25', 'le': '26', 'fl': '27'})
    day = '2026-05-05'
    assert cc.next_number(db, 'smr', day)[2] == '01-23/26'
    assert cc.next_number(db, 'to', day)[2] == '01-24/26'
    assert cc.next_number(db, 'ip', day)[2] == '01-25/26'
    assert cc.next_number(db, 'le', day)[2] == '01-26/26'
    assert md.next_number(db, day)[2] == '01-21/26'
    # сохранение договора без номера берёт новый раздел
    lid = cc.save_legal(db, dict(name='ООО Ромашка'))
    cid = cc.save_contract(db, 'smr', dict(contract_date=day, object_name='Объект', legal_id=lid))
    assert db.fetchone('SELECT contract_number FROM smr_contracts WHERE id=?', (cid,))[0] == '01-23/26'
    # резерв номера проекта ГСВ: договор получает раздел проектов, проектный номер не затрагивается
    rid, _pd = nm.reserve(db, 'gsv_projects', 1)[0]
    number, pd = db.fetchone('SELECT contract_number,pd_number FROM gsv_projects WHERE id=?', (rid,))
    assert '-22/' in number and pd.endswith('ГСВ')
    # смена номера карточки проекта по-новому
    assert nm.change_number(db, 'gsv_projects', rid, '9-26').endswith('ГСВ')
    assert db.fetchone('SELECT contract_number FROM gsv_projects WHERE id=?', (rid,))[0] == '09-22/26'


def test_swap_not_allowed_when_old_codes_would_collide(db):
    sc.set_code(db, 'contracts', '12')
    with pytest.raises(ValueError):
        sc.save_all(db, {'smr': '02'})                               # 02 — прежний номер раздела монтажа ГСВ


def test_settings_box(db, monkeypatch):
    import smetagaz.section_codes_ui as ui
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    box = ui.SectionCodesBox()
    assert box.table.rowCount() == 7 and box.table.item(0, 1).text() == '02'
    box.table.item(0, 1).setText('11')
    assert '-11/' in box.table.item(0, 2).text()
    monkeypatch.setattr(ui.QMessageBox, 'question', staticmethod(lambda *a, **k: ui.QMessageBox.StandardButton.Yes))
    box.save()
    assert sc.code(db, 'contracts') == '11' and box.status.text() == 'Сохранено'
    box.table.item(1, 1).setText('11')                                # совпадает с монтажом — ошибка
    shown = []
    monkeypatch.setattr(ui.QMessageBox, 'warning', staticmethod(lambda *a, **k: shown.append(a[2])))
    box.save()
    assert shown and 'дважды' in shown[0]
    assert sc.code(db, 'gsv_projects') == '03'
    box.deleteLater()
