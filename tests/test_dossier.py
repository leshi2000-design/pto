import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from decimal import Decimal
import pytest
from smetagaz import dossier_client as dc, contracts_core as cc, estimates_domain as ed, payments_domain, notes_domain as nd, board_domain as board
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_person_dossier_collects_all_sections(db):
    pid = db.execute("INSERT INTO crm.clients(name,phone,address) VALUES('Петров Пётр','+375291112233','ул. Мира 1')").lastrowid
    other = db.execute("INSERT INTO crm.clients(name) VALUES('Чужой')").lastrowid
    # договоры разных разделов
    mid = db.execute("INSERT INTO contracts(contract_number,contract_date,object_name,contract_amount,client_id,contract_signed) VALUES('01-02/26','2026-01-10','Дом',1000,?,1)", (pid,)).lastrowid
    gid = db.execute("INSERT INTO gsv_projects(pd_number,contract_number,contract_date,object_name,cost,client_id,contract_signed) VALUES('01-26 ГСВ','01-03/26','2026-02-01','Проект',300,?,0)", (pid,)).lastrowid
    nid = db.execute("INSERT INTO gsn_projects(title,contract_number,contract_date,contract_amount,client_id) VALUES('Газопровод','05-03/26','2026-03-01',2000,?)", (pid,)).lastrowid
    sid = cc.save_contract(db, 'smr', dict(party_type='person', person_id=pid, contract_date='2026-04-01', amount=500, signed=1, object_name='Баня'))
    db.execute("INSERT INTO gsv_projects(pd_number,contract_number,client_id,cost) VALUES('02-26 ГСВ','x',?,999)", (other,))
    # сметы: одна внутри договора, одна свободная
    e1 = ed.create_estimate(db, 'Смета к договору', client=('person', pid))
    ed.link_contract(db, e1, 'contracts', mid)
    e2 = ed.create_estimate(db, 'Свободная смета', client=('person', pid))
    db.execute("UPDATE estimates SET total=400 WHERE id=?", (e2,))
    payments_domain.add(db, 'contracts', mid, 300, '2026-01-20', 'аванс')
    payments_domain.add(db, 'smr_contracts', sid, 100, '2026-04-02')
    payments_domain.add(db, 'estimates', e2, 50, '2026-05-01')
    nd.save_note(db, 'Звонить после 18', '', '2026-01-11', ('crm.clients', pid))
    nd.save_note(db, 'Скидка на монтаж', '', '2026-01-12', ('contracts', mid))
    nd.save_note(db, 'Чужая заметка', '', '2026-01-12', ('crm.clients', other))
    board.add_task(db, 'Сдать акт', link=('contracts', mid))
    board.add_task(db, 'Посторонняя задача')
    d = dc.client_dossier(db, 'person', pid)
    assert {c['section'] for c in d['contracts']} == {'Монтаж ГСВ', 'Проекты ГСВ', 'Монтаж ГСН', 'СМР'} and len(d['contracts']) == 4
    assert d['totals']['contracts'] == 4 and d['totals']['unsigned'] == 1           # неподписан только проект ГСВ
    assert d['totals']['amount'] == Decimal(1000 + 300 + 2000 + 500 + 400)        # договоры + смета без договора, смета договора не дублируется
    assert d['totals']['paid'] == Decimal(300 + 100 + 50) and d['totals']['debt'] == d['totals']['amount'] - d['totals']['paid']
    assert [e['without_contract'] for e in d['estimates']] == [True, False]
    assert d['estimates'][1]['contract'].startswith('Монтаж ГСВ')
    assert {p['section'] for p in d['payments']} == {'Монтаж ГСВ', 'СМР', 'Смета'} and len(d['payments']) == 3
    assert {n['title'] for n in d['notes']} == {'Звонить после 18', 'Скидка на монтаж'}
    assert [t['title'] for t in d['tasks']] == ['Сдать акт']
    assert d['info']['name'] == 'Петров Пётр'


def test_legal_dossier_and_widget(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import smetagaz.dossier_client_view as view
    import smetagaz.client_files, smetagaz.workspace_view  # noqa: F401  (до подмены db)
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789', head_name='Иванов И.И.'))
    c1 = cc.save_contract(db, 'le', dict(client_id=lid, direction='Монтажные работы', contract_date='2026-03-01', amount=1200, signed=1, object_name='Котельная'))
    c2 = cc.save_contract(db, 'smr', dict(party_type='legal', legal_id=lid, contract_date='2026-03-02', amount=800))
    gid = db.execute("INSERT INTO gsv_projects(pd_number,le_client_id,party_name,cost,contract_signed,contract_date) VALUES('03-26 ГСВ',?,'ООО Ромашка',250,1,'2026-02-02')", (lid,)).lastrowid
    payments_domain.add(db, 'le_contracts', c1, 200, '2026-03-05')
    nd.save_note(db, 'Согласовать скидку', '', '2026-03-03', ('le_contracts', c1))
    ed.create_estimate(db, 'Смета Ромашки', client=('legal', lid))
    d = dc.client_dossier(db, 'legal', lid)
    assert {c['section'] for c in d['contracts']} == {'Юрлица', 'СМР', 'Проекты ГСВ'}
    assert d['totals']['amount'] == Decimal(1200 + 800 + 250) and d['totals']['paid'] == 200 and d['totals']['estimates'] == 1
    assert d['info']['lines'][0] == 'Общество' or 'УНП 123456789' in d['info']['lines']
    assert [n['title'] for n in d['notes']] == ['Согласовать скидку']
    import sys
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    w = view.DossierWidget('legal', lid)
    assert w.t_contracts.rowCount() == 3 and 'Договоров: <b>3</b>' in w.summary.text() and w.tabs.tabText(0) == 'Договоры (3)'
    with pytest.raises(ValueError):
        dc.client_dossier(db, 'legal', 99999)
