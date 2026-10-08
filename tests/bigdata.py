"""Генератор большой тестовой базы для нагрузочных замеров (не персональные данные: имена и номера синтетические)."""
import random
from datetime import date, timedelta

FIRST = ['Иван', 'Пётр', 'Сергей', 'Андрей', 'Алексей', 'Николай', 'Дмитрий', 'Олег', 'Виктор', 'Максим']
LAST = ['Иванов', 'Петров', 'Сидоров', 'Кузнецов', 'Смирнов', 'Попов', 'Лебедев', 'Козлов', 'Новиков', 'Морозов', 'Волков', 'Соколов']
STREETS = ['Мира', 'Ленина', 'Советская', 'Садовая', 'Центральная', 'Лесная', 'Школьная', 'Заводская']


def day(rng, back=700):
    return (date(2026, 10, 1) - timedelta(days=rng.randint(0, back))).isoformat()


def generate(db, scale=1.0, seed=7):
    """scale=1 — около 10 000 записей в крупнейших реестрах. Возвращает словарь количеств."""
    from smetagaz import contracts_core as cc
    rng = random.Random(seed)
    n = lambda base: max(1, int(base * scale))
    counts = {}
    with db.transaction():
        clients = []
        for i in range(n(3000)):
            name = f'{rng.choice(LAST)} {rng.choice(FIRST)} {rng.choice(FIRST)}ович {i}'
            clients.append(db.execute('INSERT INTO crm.clients(name,phone,address,passport) VALUES(?,?,?,?)', (name, f'+37529{rng.randint(1000000, 9999999)}', f'ул. {rng.choice(STREETS)} {i % 90}', f'AB{i:07}')).lastrowid)
        legals = [cc.save_legal(db, dict(name=f'ООО Компания {i}', unp=f'{100000000 + i}', head_name=f'{rng.choice(LAST)} И.И.')) for i in range(n(300))]
        counts['clients'], counts['legals'] = len(clients), len(legals)
        # сметы с позициями и оплатами
        est = []
        for i in range(n(10000)):
            cid = rng.choice(clients)
            nm = db.fetchone('SELECT name,phone FROM crm.clients WHERE id=?', (cid,)) if i % 50 == 0 else None
            eid = db.execute("INSERT INTO estimates(title,date,total,paid,client_id,client_name,client_phone,statuses) VALUES(?,?,?,?,?,?,?,?)",
                             (f'Смета {i} · {rng.choice(STREETS)}', day(rng), 0, 0, cid, f'Клиент {cid}', '', 'Предварительная смета')).lastrowid
            est.append(eid)
            for k in range(6):
                kind = 'Работа' if k % 3 == 0 else 'Материал'
                q, p = rng.randint(1, 30), rng.randint(5, 90)
                db.execute('INSERT INTO estimate_items(estimate_id,name,item_type,unit,quantity,price,sum,sort_order,purchase_price) VALUES(?,?,?,?,?,?,?,?,?)',
                           (eid, f'Позиция {k}', kind, 'шт', q, p, q * p, k, p * 0.6))
            db.execute('UPDATE estimates SET total=(SELECT sum(sum) FROM estimate_items WHERE estimate_id=?) WHERE id=?', (eid, eid))
        counts['estimates'] = len(est)
        # договоры монтажа ГСВ и проекты ГСВ, привязанные к сметам и клиентам
        for i in range(n(2500)):
            cid = rng.choice(clients)
            db.execute("INSERT INTO contracts(estimate_id,contract_number,contract_date,object_name,object_address,contract_amount,client_id,client_name,contract_signed,act_signed,acceptance_act_date,seq_num,year_num) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (est[i], f'{i % 99 + 1:02}-02/{i % 5 + 21}', day(rng), 'Дом', f'ул. {rng.choice(STREETS)} {i % 90}', rng.randint(500, 5000), cid, f'Клиент {cid}',
                                                              i % 3 != 0, i % 2, day(rng, 300) if i % 2 else '', i + 1, 26))
        for i in range(n(2500)):
            cid = rng.choice(clients)
            db.execute("INSERT INTO gsv_projects(pd_number,seq_num,year_num,object_name,address,client_id,client_name,contract_number,contract_date,due_date,act_date,cost,contract_signed,act_signed,estimate_id) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (f'{i + 1:05}-26 ГСВ', i + 1, 26, 'Объект', f'ул. {rng.choice(STREETS)} {i % 90}', cid, f'Клиент {cid}', f'{i + 1:05}-03/26', day(rng), day(rng, 100),
                                                                 day(rng, 200) if i % 2 else '', rng.randint(200, 900), i % 4 != 0, i % 2, est[n(2500) + i] if n(2500) + i < len(est) else None))
        for i in range(n(1000)):
            cid = rng.choice(clients)
            db.execute("INSERT INTO gsn_projects(title,address,client_id,client_name,contract_number,contract_date,contract_amount) VALUES(?,?,?,?,?,?,?)",
                       (f'Газопровод {i}', f'ул. {rng.choice(STREETS)} {i % 90}', cid, f'Клиент {cid}', f'{i + 1:03}-03/26', day(rng), rng.randint(1000, 9000)))
        # юрлица и СМР
        le, smr = [], []
        for i in range(n(2000)):
            le.append(cc.save_contract(db, 'le', dict(client_id=rng.choice(legals), direction='Монтажные работы', contract_date=day(rng), amount=rng.randint(1000, 9000), object_name='Котельная',
                                                       object_address=f'ул. {rng.choice(STREETS)} {i % 90}', signed=i % 3 != 0, vat_included=1, vat_rate=20)))
        for cid in le:
            for k in range(2):
                cc.save_act(db, 'le', dict(contract_id=cid, act_date=day(rng, 200), amount=rng.randint(100, 900), signed=k % 2, description='Работы'))
        for i in range(n(2000)):
            legal = i % 3 == 0
            smr.append(cc.save_contract(db, 'smr', dict(party_type='legal' if legal else 'person', person_id=None if legal else rng.choice(clients), legal_id=rng.choice(legals) if legal else None,
                                                         contract_date=day(rng), amount=rng.randint(500, 5000), object_name='Дом', object_address=f'ул. {rng.choice(STREETS)} {i % 90}', signed=i % 4 != 0)))
        for cid in smr:
            cc.save_act(db, 'smr', dict(contract_id=cid, act_date=day(rng, 200), amount=rng.randint(100, 900), signed=cid % 2, description='Работы'))
        counts.update(contracts=n(2500), gsv_projects=n(2500), gsn=n(1000), le_contracts=len(le), smr_contracts=len(smr))
        # оплаты
        for eid in est[:n(6000)]:
            db.execute('INSERT INTO payments(estimate_id,amount,date,owner_type,owner_id) VALUES(?,?,?,?,?)', (eid, rng.randint(50, 400), day(rng, 400), 'estimates', eid))
        for cid in le[:n(1500)]:
            db.execute("INSERT INTO payments(amount,date,owner_type,owner_id) VALUES(?,?,'le_contracts',?)", (rng.randint(50, 500), day(rng, 400), cid))
        # заметки и задачи
        tables = ['le_contracts', 'smr_contracts', 'crm.clients', '']
        for i in range(n(5000)):
            t = tables[i % 4]
            link = (t, rng.choice(le if t == 'le_contracts' else smr if t == 'smr_contracts' else clients)) if t else ('', None)
            db.execute("INSERT INTO notes(title,body,note_date,link_table,link_id,created_at,updated_at) VALUES(?,?,?,?,?,'','')", (f'Заметка {i}', f'Текст заметки номер {i}', day(rng, 400), *link))
        for i in range(n(3000)):
            db.execute("INSERT INTO kanban_tasks(title,description,status,is_archived,created_at,urgency,due_date) VALUES(?,?,?,?,?,?,?)",
                       (f'Задача {i}', '', rng.choice(['todo', 'in_progress', 'done']), i % 10 == 0, '2026-01-01 00:00:00', 'Обычная', day(rng, 60)))
        counts.update(notes=n(5000), tasks=n(3000))
    return counts
