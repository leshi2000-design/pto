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


def test_payments_in_cards_dossier_and_journal(db, ed):
    cid, lid, gsv, gsn = seed(db)
    contract = make_contract(db)
    db.execute('UPDATE contracts SET contract_amount=1000, client_id=? WHERE id=?', (cid, contract))
    smr = cc.save_contract(db, 'smr', dict(contract_date='2026-05-01', party_type='legal', legal_id=lid, object_name='Котельная', amount=1200, status='Действует'))

    def pay(**fields):
        path = fields.pop('page')
        return ed.request('POST', '/pay', dict(csrf=ed.csrf(path), **fields))

    page = ed.request('GET', f'/m/contracts/{contract}')[1]
    assert 'Оплаты' in page and 'Остаток' in page and 'Заполнить остаток' in page and '1 000.00' in page          # итоги и кнопка «Заполнить остаток» как в программе
    status, _p, h = pay(page=f'/m/contracts/{contract}', action='add', owner='contracts', rid=str(contract), date='2026-10-10', amount='400,50', note='аванс', back=f'/m/contracts/{contract}#pay')
    assert status == 303 and 'ok=' in h['Location'] and h['Location'].endswith('#pay')
    from smetagaz import payments_domain as pd
    assert float(pd.summary(db, 'contracts', contract)['paid']) == 400.5
    page = ed.request('GET', f'/m/contracts/{contract}')[1]
    assert '400.50' in page and '599.50' in page and 'аванс' in page
    for bad in ('0', '-5', 'abc', '10.123'):
        h = pay(page=f'/m/contracts/{contract}', action='add', owner='contracts', rid=str(contract), date='2026-10-10', amount=bad, back='/m/contracts')[2]
        assert 'err=' in h['Location']
    assert float(pd.summary(db, 'contracts', contract)['paid']) == 400.5
    loc = pay(page=f'/m/contracts/{contract}', action='add', owner='users', rid='1', date='2026-10-10', amount='5', back='//evil.example')[2]['Location']
    assert loc.startswith('/m/contracts?err=') and 'evil' not in loc                     # чужой раздел отклонён, внешний адрес возврата не принимается
    # платёж по договору СМР (юрлицо), досье юрлица и клиента
    pay(page=f'/m/smr/{smr}', action='add', owner='smr_contracts', rid=str(smr), date='2026-10-11', amount='200', note='', back=f'/m/smr/{smr}#pay')
    _s, dos, _h = ed.request('GET', f'/dossier/person/{cid}')
    assert 'Досье клиента: Сидоров Пётр' in dos and 'Монтаж ГСВ' in dos and f'/m/contracts/{contract}#pay' in dos and '599.50' in dos
    assert '400.50' in ed.request('GET', f'/dossier/person/{cid}?tab=payments')[1]
    _s, dos, _h = ed.request('GET', f'/dossier/legal/{lid}')
    assert 'СМР (юрлица)' in dos and '200.00' in dos
    assert 'Договоров нет' not in dos and ed.request('GET', '/dossier/legal/99999')[0] == 404
    # чек: продажа и оплата
    status, _p, h = pay(page=f'/dossier/person/{cid}?tab=sales', action='sale_add', kind='person', cid=str(cid), title='Котёл Bosch', amount='1500', date='2026-10-12', receipt='77', note='', paid_now='1', back=f'/dossier/person/{cid}?tab=sales')
    assert status == 303 and 'ok=' in h['Location']
    sales_page = ed.request('GET', f'/dossier/person/{cid}?tab=sales')[1]
    assert 'Котёл Bosch' in sales_page and '1 500.00' in sales_page
    sid = db.fetchone('SELECT id FROM client_sales')[0]
    assert 'err=' in pay(page=f'/dossier/person/{cid}?tab=sales', action='sale_delete', sid=str(sid), back=f'/dossier/person/{cid}?tab=sales')[2]['Location']       # есть оплаты — как в программе
    # удаление платежа и журнал за период
    pid = db.fetchone("SELECT id FROM payments WHERE note='аванс'")[0]
    assert 'ok=' in pay(page=f'/dossier/person/{cid}?tab=payments', action='delete', pid=str(pid), back='/m/contracts')[2]['Location'] and float(pd.summary(db, 'contracts', contract)['paid']) == 0
    _s, journal, _h = ed.request('GET', '/payments?start=2026-10-01&end=2026-10-31')
    assert 'Журнал оплат' in journal and '200.00' in journal and 'СМР (юрлица)' in journal
    assert 'Журнал оплат' in ed.request('GET', '/m/clients')[1]                       # пункт меню «Оплаты» есть везде
    assert 'Начало периода позже окончания' in ed.request('GET', '/payments?start=2026-11-01&end=2026-10-01')[1]
    # ссылка на досье в карточке клиента и договора
    assert f'/dossier/person/{cid}' in ed.request('GET', f'/m/clients/{cid}')[1] and f'/dossier/person/{cid}' in ed.request('GET', f'/m/contracts/{contract}')[1]
    assert f'/dossier/legal/{lid}' in ed.request('GET', f'/m/legal_entities/{lid}')[1]


def test_viewer_sees_payments_but_cannot_change(db, gateway):
    cid, lid, gsv, gsn = seed(db)
    contract = make_contract(db)
    wg.add_user(db, 'vw', 'viewerpass1', 'viewer')
    v = Client(gateway)
    v.login('vw', 'viewerpass1')
    page = v.request('GET', f'/m/contracts/{contract}')[1]
    assert 'Оплат пока нет' in page and 'Внести оплату' not in page
    assert v.request('POST', '/pay', dict(csrf=v.csrf(f'/m/contracts/{contract}'), action='add', owner='contracts', rid=str(contract), date='2026-10-10', amount='5'))[0] == 403
    assert v.request('POST', '/pay', dict(action='add'))[0] == 403


def test_montage_gsv_full_card(db, ed):
    from smetagaz import gsvm_domain as md, gsvm_statuses
    contract = make_contract(db)
    pipe = db.execute("INSERT INTO gsv_pipelines(name) VALUES('Труба ПЭ 32x3')").lastrowid
    work_ids = [i for i, _n, _c in gsvm_statuses.catalog(db, 'work')]
    client_ids = [i for i, _n, _c in gsvm_statuses.catalog(db, 'client')]
    assert work_ids and client_ids
    path = f'/m/contracts/{contract}'
    page = ed.request('GET', path)[1]
    for label in ('7. Статусы договора', '5. Сроки и стоимость', '4. Проект', '8. Передача исполнительной документации', 'Трубопроводы', 'Стыки', 'Шифр проекта'):
        assert label in page, label
    form = {'csrf': ed.csrf(path), 'f_number': '09-02/26', 'f_contract_date': '2026-10-05', 'f_client_name': 'Иванов Иван', 'f_phones': '375291112233', 'f_object': 'Дом',
            'f_designer_code': 'ПР-5', 'f_designer': 'Проект-Бюро', 'f_project_month': '2026-09', 'f_work_end_date': '2026-12-01', 'f_act_date': '2026-12-05', 'f_contract_amount': '1 234,5',
            'f_act_signed': '1', 'f_id_transferred': '1', 'f_id_recipient': 'Заказчик', 'f_id_transfer_date': '2026-12-06', 'c_equipment_count': '0',
            'c_pipelines_count': '1', 'c_pipelines_id_0': '', 'c_pipelines_pipeline_id_0': str(pipe), 'c_pipelines_quantity_0': '12,5', 'c_pipelines_note_0': 'подземный',
            'c_joints_count': '1', 'c_joints_id_0': '', 'c_joints_name_0': 'Прочие стыки', 'c_joints_count_0': '3', 'c_joints_note_0': ''}
    body = urllib_encode(form, [('f_status_work', str(work_ids[0])), ('f_status_client', str(client_ids[0]))])
    status, page, _h = ed.raw_post(path, body)
    assert status == 200 and 'Сохранено.' in page
    row = db.fetchone('SELECT contract_number,designer_code,project_month,work_end_date,acceptance_act_date,contract_amount,act_signed,id_transferred,id_recipient,work_start_date FROM contracts WHERE id=?', (contract,))
    assert row == ('09-02/26', 'ПР-5', '2026-09', '2026-12-01', '2026-12-05', 1234.5, 1, 1, 'Заказчик', '2026-10-05')
    assert gsvm_statuses.contract_status_ids(db, contract) == {work_ids[0], client_ids[0]}
    assert [(r['name'], r['quantity']) for r in md.pipelines(db, contract)] == [('Труба ПЭ 32x3', 12.5)]
    assert sorted(r['name'] for r in md.joints(db, contract)) == ['Прочие стыки', 'Труба ПЭ 32x3']          # стыки трубопровода добавились сами, как в программе
    assert db.fetchone('SELECT statuses_text FROM contracts WHERE id=?', (contract,))[0]
    # занятый номер и неверный месяц
    other = make_contract(db, 'Другой Клиент')
    for bad, text in ((dict(form, f_number='09-02/26'), 'уже есть'), (dict(form, f_project_month='2026-13'), 'ГГГГ-ММ')):
        status, page, _h = ed.raw_post(f'/m/contracts/{other}', urllib_encode(dict(bad, csrf=ed.csrf(f'/m/contracts/{other}')), []))
        assert text in page
    # снятие всех статусов
    status, page, _h = ed.raw_post(path, urllib_encode(dict(form, csrf=ed.csrf(path), f_number='09-02/26'), []))
    assert 'Сохранено.' in page and gsvm_statuses.contract_status_ids(db, contract) == set()


def urllib_encode(form, extra):
    import urllib.parse
    return urllib.parse.urlencode(list(form.items()) + extra)
