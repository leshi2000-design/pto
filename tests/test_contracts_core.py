import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from smetagaz import contracts_core as cc, payments_domain
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path, monkeypatch):
    from smetagaz import gsv_project_domain as gd
    monkeypatch.setattr(gd, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(gd, 'TEMPLATES_DIR', tmp_path / 'templates')
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def make_legal(db):
    return cc.save_legal(db, dict(name='ООО Ромашка', full_name='Общество «Ромашка»', unp='123456789', legal_address='г. Минск', bank='Банк', bic='AKBBBY2X',
                                  account='BY00', head_name='Иванов Иван Иванович', head_name_gen='Иванова Ивана Ивановича'), contact_rows=[dict(name='Пётр', phone='+375291234567')])


def test_numbers_and_documents(db, tmp_path):
    lid = make_legal(db)
    assert cc.contacts(db, lid)[0]['name'] == 'Пётр'
    c1 = cc.save_contract(db, 'le', dict(client_id=lid, direction='Монтажные работы', contract_date='2026-03-01', amount=1200, vat_included=1, vat_rate=20, subject='Монтаж', object_address='ул. Мира 1'))
    c2 = cc.save_contract(db, 'le', dict(client_id=lid, direction='Монтажные работы', contract_date='2026-04-01', amount=10))
    assert db.fetchone('SELECT contract_number FROM le_contracts WHERE id=?', (c1,))[0] == '01-04/26'
    assert db.fetchone('SELECT contract_number FROM le_contracts WHERE id=?', (c2,))[0] == '02-04/26'
    a = cc.save_act(db, 'le', dict(contract_id=c1, act_date='2026-03-20', amount=1200, description='Работы', signed=1))
    tags = cc.tag_map(db, 'le', c1, a)
    assert tags['СУММА_НДС'] == '200,00' and tags['УНП'] == '123456789' and tags['КОНТРАГЕНТ'] == 'Общество «Ромашка»'
    with pytest.raises(ValueError):
        cc.generate(db, 'le', 'contract', c1)
    cc.link_folder(db, 'le', c1, tmp_path / 'f', create=True)
    path = cc.generate(db, 'le', 'contract', c1)
    assert os.path.exists(path) and cc.doc_state(db, 'le', 'contract', c1) == 'fresh'
    db.execute('UPDATE le_contracts SET amount=5 WHERE id=?', (c1,))
    assert cc.doc_state(db, 'le', 'contract', c1) == 'stale'
    assert os.path.exists(cc.generate(db, 'le', 'statement', a))
    payments_domain.add(db, 'le_contracts', c1, 100, '2026-03-05')
    assert cc.tag_map(db, 'le', c1)['ОПЛАЧЕНО'] == '100,00'
    with pytest.raises(Exception):
        db.execute('DELETE FROM le_contracts WHERE id=?', (c1,))


def test_smr_person_and_legal_with_estimate(db):
    lid = make_legal(db)
    pid = db.execute("INSERT INTO crm.clients(name,phone) VALUES('Петров Пётр','+375')").lastrowid
    c1 = cc.save_contract(db, 'smr', dict(party_type='person', person_id=pid, contract_date='2026-05-01', amount=500))
    c2 = cc.save_contract(db, 'smr', dict(party_type='legal', legal_id=lid, contract_date='2026-05-02'))
    assert db.fetchone('SELECT contract_number FROM smr_contracts WHERE id=?', (c2,))[0] == '02-05/26'
    assert cc.party(db, 'smr', cc.contract(db, 'smr', c1))['name'] == 'Петров Пётр'
    eid = db.execute("INSERT INTO estimates(title,total) VALUES('Смета',700)").lastrowid
    cc.link_estimate(db, c1, eid)
    assert cc.estimate_state(db, c1) == 'unsynced'
    cc.sync_estimate(db, c1)
    assert cc.estimate_state(db, c1) == 'fresh' and cc.contract(db, 'smr', c1)['amount'] == 700
    with pytest.raises(ValueError):
        cc.link_estimate(db, c2, eid)
    with pytest.raises(ValueError):
        cc.save_contract(db, 'smr', dict(party_type='person'))
    tags = cc.tag_map(db, 'smr', c1)
    assert 'СТОИМОСТЬ_МАТЕРИАЛОВ' in tags and 'СТОИМОСТЬ_МАТЕРИАЛОВ' not in cc.tag_map(db, 'le', cc.save_contract(db, 'le', dict(client_id=lid, direction='Монтажные работы')))


def test_integration_with_other_subsystems(db, tmp_path):
    from smetagaz import acts_statement, agenda_domain, integrity, contracts_excel_export, payments_domain
    from smetagaz.data_services import search
    from datetime import date
    lid = make_legal(db)
    pid = db.execute("INSERT INTO crm.clients(name) VALUES('Петров Пётр')").lastrowid
    c1 = cc.save_contract(db, 'le', dict(client_id=lid, direction='Монтажные работы', contract_date='2026-03-01', end_date='2026-03-30', amount=1000, signed=1, subject='Монтаж ВДГО'))
    c2 = cc.save_contract(db, 'smr', dict(party_type='person', person_id=pid, contract_date='2026-03-02', amount=500, signed=1))
    a1 = cc.save_act(db, 'le', dict(contract_id=c1, act_date='2026-03-20', amount=1500, signed=1))
    cc.save_act(db, 'smr', dict(contract_id=c2, act_date='2026-03-25', amount=100, signed=0))
    payments_domain.add(db, 'le_contracts', c1, 300, '2026-03-10')
    payments_domain.add(db, 'smr_contracts', c2, 50, '2026-03-11')
    # ведомость актов
    st = acts_statement.statement(db, 'le_contracts', 2026, 3)
    assert [r['number'] for r in st['signed']] == ['1'] and st['signed'][0]['client'] == 'ООО Ромашка' and st['signed'][0]['paid'] == 300
    assert len(acts_statement.statement(db, 'smr_contracts', 2026, 3)['unsigned']) == 1
    out = tmp_path / 'v.xlsx'
    acts_statement.export_statement(db, 'le_contracts', 2026, 3, out)
    assert out.exists()
    # календарь
    events = agenda_domain.events_between(db, date(2026, 3, 1), date(2026, 3, 31)) if hasattr(agenda_domain, 'events_between') else []
    titles = ' | '.join(e['title'] for e in events)
    assert events and 'Ромашка' in titles and 'Петров' in titles
    # оплаты
    rows = payments_domain.report(db, '2026-03-01', '2026-03-31')
    assert {r['section'] for r in rows} == {'Юрлица', 'СМР'} and {r['client_name'] for r in rows} == {'ООО Ромашка', 'Петров Пётр'}
    # проверка базы: акты больше суммы договора
    assert any('больше суммы договора' in f['text'] for f in integrity.check(db))
    # экспорт и поиск
    xlsx = tmp_path / 'r.xlsx'
    contracts_excel_export.export_registries(db, xlsx)
    assert search(db, 'ВДГО')


def test_deleting_person_client_detaches_smr(db):
    from smetagaz.data_services import client_links, delete_client
    pid = db.execute("INSERT INTO crm.clients(name) VALUES('Сидоров')").lastrowid
    c = cc.save_contract(db, 'smr', dict(party_type='person', person_id=pid, amount=10))
    assert client_links(db, pid) == {'СМР': 1}
    delete_client(db, pid)
    assert cc.contract(db, 'smr', c)['person_id'] is None
