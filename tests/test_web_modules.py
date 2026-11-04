"""Веб-доступ: все модули разделов «Услуги», «Юрлица», «Клиенты» открываются, ищутся, правятся и создаются по HTTP; записи совпадают с тем, что видит окно программы."""
import re

import pytest

from smetagaz import contracts_core as cc, web_gateway as wg, web_modules
from test_web_gateway import Client, db, gateway, make_contract  # noqa: F401


@pytest.fixture
def ed(gateway, db):
    wg.add_user(db, 'ed', 'editorpass1', 'editor')
    wg.add_user(db, 'vw', 'viewerpass1', 'viewer')
    c = Client(gateway)
    assert c.login('ed', 'editorpass1')[0] == 303
    return c


def seed(db):
    cid = db.execute("INSERT INTO crm.clients(name,phone,address) VALUES('Сидоров Пётр','375291112233','Минск')").lastrowid
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789', legal_address='Минск, Мира 1', phone='111'), None, [dict(name='Анна', position='Бухгалтер', phone='222', email='a@x.by')])
    gsv = db.execute("INSERT INTO gsv_projects(pd_number,seq_num,year_num,object_name,address,client_name,client_id,phone,contract_number,contract_date,cost,contract_signed,act_signed) VALUES('01-26 ГСВ',1,26,'Дом','Минск',?,?,?,?,?,?,0,0)",
                     ('Сидоров Пётр', cid, '375291112233', '01-01/26', '2026-03-01', 250)).lastrowid
    gsn = db.execute("INSERT INTO gsn_projects(title,address,client_id,client_name,phone,contract_number,contract_date,contract_amount,pe_length,steel_under_length,steel_above_length) VALUES('Газопровод','Минск',?,?,?,'02-03/26','2026-04-01',1000,10,5,2)",
                     (cid, 'Сидоров Пётр', '375291112233')).lastrowid
    return cid, lid, gsv, gsn


def test_every_module_lists_and_opens(db, ed):
    cid, lid, gsv, gsn = seed(db)
    mods = web_modules.all_modules()
    assert list(mods) == ['gsv', 'contracts', 'gsn', 'ip', 'fl', 'legal_entities', 'smr', 'to', 'le_other', 'clients', 'contacts']
    make_contract(db)
    ids = {}
    ids['smr'] = cc.save_contract(db, 'smr', dict(contract_date='2026-05-01', party_type='legal', legal_id=lid, object_name='Котельная', amount=1200, status='Действует'))
    ids['to'] = cc.save_contract(db, 'to', dict(contract_date='2026-05-02', party_type='legal', legal_id=lid, object_name='ТО котлов', amount=300, status='Действует'))
    ids['le_other'] = cc.save_contract(db, 'le', dict(contract_date='2026-05-03', client_id=lid, direction='Монтажные работы', object_name='Прочее', amount=50, status='Действует'))
    ids['ip'] = cc.save_contract(db, 'ip', dict(contract_date='2026-05-04', party_type='person', person_id=cid, object_name='Баня', amount=70, status='Действует'))
    ids['fl'] = cc.save_contract(db, 'fl', dict(contract_date='2026-05-05', party_type='person', person_id=cid, object_name='Гараж', amount=80, status='Действует'))
    ids.update(gsv=gsv, gsn=gsn, legal_entities=lid, clients=cid, contracts=db.fetchone('SELECT id FROM contracts')[0])
    from smetagaz import contacts_domain
    ids['contacts'] = contacts_domain.save_contact(db, dict(name='Слесарь Иван', phone='375441234567', category='Рабочие'))
    for key, mod in mods.items():
        status, page, _h = ed.request('GET', f'/m/{key}')
        assert status == 200 and mod.title in page, key
        for item in mod.search(db, ''):
            assert item['cols'], key
        status, page, _h = ed.request('GET', f'/m/{key}/{ids[key]}')
        assert status == 200 and 'name="csrf"' in page and 'Сохранить' in page, key
    # боковое меню как в программе: три раздела и все модули
    _s, page, _h = ed.request('GET', '/m/gsv')
    for title in ('Услуги', 'Клиенты', 'Юрлица', 'Проекты ГСВ', 'Монтаж ГСВ', 'Монтаж ГСН', 'СМР (ИП)', 'СМР (физлица)', 'Справочник юрлиц', 'СМР (юрлица)', 'ТО (юрлица)', 'Прочие (юр.лица)', 'Контакты'):
        assert title in page, title
    assert '#1B6B62' in page or '#1b6b62' in page                              # акцентный цвет программы
    assert ed.request('GET', '/m/unknown')[0] == 404 and ed.request('GET', '/m/smr/999999')[0] == 404


def test_edit_and_create_through_forms(db, ed):
    cid, lid, gsv, gsn = seed(db)

    def post(path, **fields):
        token = ed.csrf(path)
        return ed.request('POST', path, dict(csrf=token, **fields))

    # клиенты и контакты — создание
    status, _p, h = post('/m/clients/new', f_client_name='Новый Клиент', f_phones='375291111111\n375292222222 (доп)', f_client_address='Гомель')
    assert status == 303
    new_client = int(h['Location'].rsplit('/', 1)[1])
    assert db.fetchone('SELECT name,phone,address FROM crm.clients WHERE id=?', (new_client,)) == ('Новый Клиент', '375291111111; 375292222222 (доп)', 'Гомель')
    assert 'Введите ФИО' in post('/m/clients/new', f_client_name='')[1]
    status, _p, h = post('/m/contacts/new', f_name='Диспетчер', f_phones='375173334455', f_category='Рабочие', f_favorite='1')
    assert status == 303 and db.fetchone('SELECT name,phone,favorite FROM contacts')[0] == 'Диспетчер'
    # юрлицо: правка и контактные лица
    status, page, _h = post(f'/m/legal_entities/{lid}', f_name='ООО Ромашка', f_unp='123456789', f_phone='999', c_contacts_count='2', c_contacts_id_0='1', c_contacts_name_0='Анна', c_contacts_position_0='Главбух',
                            c_contacts_phone_0='222', c_contacts_email_0='a@x.by', c_contacts_id_1='', c_contacts_name_1='Борис', c_contacts_position_1='Директор', c_contacts_phone_1='333', c_contacts_email_1='')
    assert status == 200 and 'Сохранено.' in page and db.fetchone('SELECT phone FROM le_clients WHERE id=?', (lid,))[0] == '999'
    assert [c['name'] for c in cc.contacts(db, lid)] == ['Анна', 'Борис']
    assert 'УНП' in post(f'/m/legal_entities/{lid}', f_name='ООО', f_unp='12')[1]
    # СМР (юрлица): создание с автоматическим номером, акты, статус вручную
    status, _p, h = post('/m/smr/new', f_contract_date='2026-06-01', f_party_type='legal', f_legal_id=str(lid), f_object_name='Котельная 2', f_amount='1 500,50', f_vat_rate='20', f_status='Действует',
                         c_acts_count='1', c_acts_id_0='', c_acts_act_number_0='1', c_acts_act_date_0='2026-06-10', c_acts_amount_0='500', c_acts_description_0='Этап 1')
    assert status == 303
    smr = int(h['Location'].rsplit('/', 1)[1])
    row = cc.contract(db, 'smr', smr)
    assert row['contract_number'] and row['amount'] == 1500.5 and row['legal_id'] == lid
    acts = cc.acts(db, 'smr', smr)
    assert len(acts) == 1 and acts[0]['amount'] == 500
    status, page, _h = post(f'/m/smr/{smr}', f_contract_date='2026-06-01', f_party_type='legal', f_legal_id=str(lid), f_object_name='Котельная 2', f_amount='1500', f_vat_rate='20', f_status='Действует',
                            f_status_manual='done', c_acts_count='2', c_acts_id_0=str(acts[0]['id']), c_acts_act_number_0='1', c_acts_act_date_0='2026-06-10', c_acts_amount_0='700', c_acts_del_0='1')
    assert 'Сохранено.' in page and cc.acts(db, 'smr', smr) == [] and cc.contract(db, 'smr', smr)['status_manual'] == 'done'
    assert 'Выберите юрлицо' in post('/m/smr/new', f_contract_date='2026-06-01', f_party_type='legal', f_legal_id='')[1]
    assert 'ГГГГ-ММ-ДД' in post(f'/m/smr/{smr}', f_contract_date='01.06.2026', f_party_type='legal', f_legal_id=str(lid), f_status='Действует')[1]
    # ИП и физлица: клиент выбирается из справочника
    status, _p, h = post('/m/fl/new', f_contract_date='2026-06-02', f_person_id=str(cid), f_object_name='Гараж', f_amount='80', f_status='Действует')
    assert status == 303 and cc.contract(db, 'fl', int(h['Location'].rsplit('/', 1)[1]))['person_id'] == cid
    assert post('/m/ip/new', f_contract_date='2026-06-02', f_person_id='', f_status='Действует')[0] == 200
    # ТО и прочие
    status, _p, h = post('/m/to/new', f_contract_date='2026-06-03', f_legal_id=str(lid), f_object_name='ТО', f_amount='10', f_status='Действует', f_annual='1')
    assert status == 303 and cc.contract(db, 'to', int(h['Location'].rsplit('/', 1)[1]))['annual']
    status, _p, h = post('/m/le_other/new', f_contract_date='2026-06-04', f_legal_id=str(lid), f_direction='Монтажные работы', f_object_name='Иное', f_amount='5', f_status='Действует')
    assert status == 303 and db.fetchone('SELECT count(*) FROM le_contracts')[0] == 1
    # Монтаж ГСВ: создание договора с номером как в программе
    status, _p, h = post('/m/contracts/new', f_contract_date='2026-07-01', f_client_name='Козлов Олег', f_phones='375291234567', f_object='Дом', f_object_address='Минск')
    assert status == 303
    new = int(h['Location'].rsplit('/', 1)[1])
    assert re.fullmatch(r'\d{2}-\d{2}/26', db.fetchone('SELECT contract_number FROM contracts WHERE id=?', (new,))[0])
    assert db.fetchone('SELECT client_id FROM contracts WHERE id=?', (new,))[0]
    # Проекты ГСВ и Монтаж ГСН: правка карточки; создание — только в программе
    status, page, _h = post(f'/m/gsv/{gsv}', f_client_name='Сидоров Пётр', f_phones='375291112233', f_object='Дом новый', f_address='Минск 5', f_cost='300,5', f_contract_date='2026-03-01', f_contract_signed='1')
    assert 'Сохранено.' in page
    assert db.fetchone('SELECT object_name,cost,contract_signed FROM gsv_projects WHERE id=?', (gsv,)) == ('Дом новый', 300.5, 1)
    assert ed.request('GET', '/m/gsv/new')[0] == 404 and ed.request('GET', '/m/gsn/new')[0] == 404
    status, page, _h = post(f'/m/gsn/{gsn}', f_title='Газопровод 2', f_address='Минск', f_contract_number='02-03/26', f_contract_date='2026-04-01', f_client_name='Сидоров Пётр', f_phones='375291112233',
                            f_contract_amount='1200', f_pe_length='20', f_steel_under_length='3', f_steel_above_length='4', f_pressure_type='low', f_tie_in='pe', f_couplings='2')
    assert 'Сохранено.' in page
    assert db.fetchone('SELECT title,contract_amount,steel_length,tie_in FROM gsn_projects WHERE id=?', (gsn,)) == ('Газопровод 2', 1200, 7, 'pe')
    assert 'Окончание работ раньше' in post(f'/m/gsn/{gsn}', f_title='X', f_work_start_date='2026-05-02', f_work_end_date='2026-05-01', f_client_name='А')[1]


def test_viewer_cannot_edit_or_create_and_locks(db, gateway):
    cid, lid, gsv, gsn = seed(db)
    wg.add_user(db, 'vw', 'viewerpass1', 'viewer')
    wg.add_user(db, 'ed', 'editorpass1', 'editor')
    v = Client(gateway)
    v.login('vw', 'viewerpass1')
    assert '+ Добавить' not in v.request('GET', '/m/clients')[1] and 'disabled' in v.request('GET', f'/m/clients/{cid}')[1]
    assert v.request('POST', f'/m/clients/{cid}', dict(csrf=v.csrf(f'/m/clients/{cid}'), f_client_name='Взлом'))[0] == 403
    e = Client(gateway)
    e.login('ed', 'editorpass1')
    smr = cc.save_contract(db, 'smr', dict(contract_date='2026-05-01', party_type='legal', legal_id=lid, object_name='О', amount=1, status='Действует'))
    db.execute("INSERT INTO edit_locks(key,sid,user,host,since,beat) VALUES(?,?,?,?,?,CAST(strftime('%s','now') AS INTEGER))", (f'cp:smr:{smr}', 'x', 'Мария', 'PC-2', ''))
    page = e.request('POST', f'/m/smr/{smr}', dict(csrf=e.csrf(f'/m/smr/{smr}'), f_contract_date='2026-05-01', f_party_type='legal', f_legal_id=str(lid), f_object_name='Под замком', f_status='Действует'))[1]
    assert 'Мария' in page and cc.contract(db, 'smr', smr)['object_name'] == 'О'
