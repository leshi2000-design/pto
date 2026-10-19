"""Досье клиента: все договоры во всех разделах, сметы, оплаты, заметки, задачи и файлы — на одном экране (физлицо и юрлицо)."""
from decimal import Decimal

from . import board_domain as board
from . import payments_domain

SECTION_NAMES = {'contracts': 'Монтаж ГСВ', 'gsv_projects': 'Проекты ГСВ', 'gsn_projects': 'Монтаж ГСН', 'smr_contracts': 'СМР (юрлица)', 'to_contracts': 'ТО (юрлица)', 'ip_contracts': 'СМР (ИП)', 'fl_contracts': 'СМР (физлица)', 'le_contracts': 'Прочие (юр.лица)'}
AMOUNT_COLUMN = {'contracts': 'contract_amount', 'gsv_projects': 'cost', 'gsn_projects': 'contract_amount', 'smr_contracts': 'amount', 'to_contracts': 'amount', 'ip_contracts': 'amount', 'fl_contracts': 'amount', 'le_contracts': 'amount'}
NUMBER_COLUMN = {'contracts': 'contract_number', 'gsv_projects': 'pd_number', 'gsn_projects': 'contract_number', 'smr_contracts': 'contract_number', 'to_contracts': 'contract_number', 'ip_contracts': 'contract_number', 'fl_contracts': 'contract_number', 'le_contracts': 'contract_number'}
OBJECT_COLUMN = {'contracts': "coalesce(nullif(object_address,''),object_name)", 'gsv_projects': "coalesce(nullif(address,''),object_name)", 'gsn_projects': "coalesce(nullif(address,''),title)",
                 'smr_contracts': "coalesce(nullif(object_address,''),object_name)", 'to_contracts': "coalesce(nullif(object_address,''),object_name)", 'ip_contracts': "coalesce(nullif(object_address,''),object_name)", 'fl_contracts': "coalesce(nullif(object_address,''),object_name)", 'le_contracts': "coalesce(nullif(object_address,''),object_name)"}
DATE_COLUMN = {'contracts': 'contract_date', 'gsv_projects': 'contract_date', 'gsn_projects': 'contract_date', 'smr_contracts': 'contract_date', 'to_contracts': 'contract_date', 'ip_contracts': 'contract_date', 'fl_contracts': 'contract_date', 'le_contracts': 'contract_date'}
SIGNED_COLUMN = {'contracts': 'contract_signed', 'gsv_projects': 'contract_signed', 'gsn_projects': '1', 'smr_contracts': 'signed', 'to_contracts': 'signed', 'ip_contracts': 'signed', 'fl_contracts': 'signed', 'le_contracts': 'signed'}
OWNER_FILTER = {
    'person': {'contracts': 'client_id', 'gsv_projects': 'client_id', 'gsn_projects': 'client_id', 'smr_contracts': 'person_id', 'ip_contracts': 'person_id', 'fl_contracts': 'person_id'},
    'legal': {'contracts': 'le_client_id', 'gsv_projects': 'le_client_id', 'smr_contracts': 'legal_id', 'to_contracts': 'legal_id', 'le_contracts': 'client_id'},
}


def migrate(db):
    """Продажи по чеку: товар или услуга, проданные клиенту без сметы и договора (например, котёл). Оплаты ведутся в общей книге платежей."""
    db.execute("""CREATE TABLE IF NOT EXISTS client_sales(id INTEGER PRIMARY KEY, person_id INTEGER, legal_id INTEGER REFERENCES le_clients(id) ON DELETE RESTRICT,
        client_name TEXT DEFAULT '', title TEXT NOT NULL, sale_date TEXT NOT NULL DEFAULT '', amount REAL NOT NULL DEFAULT 0, receipt_no TEXT DEFAULT '', note TEXT DEFAULT '',
        CHECK((person_id IS NULL)<>(legal_id IS NULL)))""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_client_sales_person ON client_sales(person_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_client_sales_legal ON client_sales(legal_id)')
    db.execute("DROP TRIGGER IF EXISTS protect_paid_client_sales")
    db.execute("""CREATE TRIGGER protect_paid_client_sales BEFORE DELETE ON client_sales WHEN EXISTS(SELECT 1 FROM payments WHERE owner_type='client_sales' AND owner_id=old.id)
        BEGIN SELECT RAISE(ABORT,'По этой продаже есть оплаты. Сначала удалите оплаты.'); END""")


def sales(db, kind, cid):
    """Продажи клиента: [{'id','title','date','receipt','amount','paid','debt','note'}], новые сверху."""
    col = 'person_id' if kind == 'person' else 'legal_id'
    out = []
    for sid, title, day, amount, receipt, note in db.fetchall(f'SELECT id,title,sale_date,amount,receipt_no,note FROM client_sales WHERE {col}=? ORDER BY sale_date DESC,id DESC', (cid,)):
        s = payments_domain.summary(db, 'client_sales', sid)
        out.append(dict(id=sid, title=title, date=day, receipt=receipt or '', amount=_num(amount), paid=s['paid'], debt=s['debt'], note=note or ''))
    return out


def save_sale(db, kind, cid, values, sid=None, paid_now=False):
    """Сохраняет продажу по чеку. paid_now — сразу внести оплату на всю сумму датой продажи (новая запись)."""
    title = str(values.get('title') or '').strip()
    if not title:
        raise ValueError('Укажите, что куплено')
    amount = float(values.get('amount') or 0)
    if amount <= 0:
        raise ValueError('Сумма должна быть больше нуля')
    day = str(values.get('date') or '')
    from datetime import date as _date
    _date.fromisoformat(day)
    name = db.fetchone('SELECT name FROM crm.clients WHERE id=?', (cid,)) if kind == 'person' else db.fetchone('SELECT name FROM le_clients WHERE id=?', (cid,))
    if not name:
        raise ValueError('Клиент не найден')
    data = (name[0], title, day, amount, str(values.get('receipt') or '').strip(), str(values.get('note') or '').strip())
    with db.transaction():
        if sid:
            db.execute('UPDATE client_sales SET client_name=?,title=?,sale_date=?,amount=?,receipt_no=?,note=? WHERE id=?', (*data, sid))
        else:
            sid = db.execute('INSERT INTO client_sales(person_id,legal_id,client_name,title,sale_date,amount,receipt_no,note) VALUES(?,?,?,?,?,?,?,?)',
                             (cid if kind == 'person' else None, cid if kind == 'legal' else None, *data)).lastrowid
            if paid_now:
                payments_domain.add(db, 'client_sales', sid, amount, day, ('Чек №' + data[4]) if data[4] else 'Оплата по чеку')
    return sid


def delete_sale(db, sid):
    db.execute('DELETE FROM client_sales WHERE id=?', (sid,))


def _num(x):
    return Decimal(str(x or 0))


def client_info(db, kind, cid):
    if kind == 'legal':
        row = db.fetchone('SELECT name,full_name,unp,legal_address,head_name,phone,email,contact_person FROM le_clients WHERE id=?', (cid,))
        if not row:
            raise ValueError('Юрлицо не найдено')
        return dict(kind=kind, name=row[0], lines=[x for x in (row[1], f'УНП {row[2]}' if row[2] else '', row[3], f'Руководитель: {row[4]}' if row[4] else '',
                                                              row[7], row[5], row[6]) if x])
    row = db.fetchone('SELECT name,phone,address FROM crm.clients WHERE id=?', (cid,))
    if not row:
        raise ValueError('Клиент не найден')
    return dict(kind=kind, name=row[0], lines=[x for x in (row[1], row[2]) if x])


def client_dossier(db, kind, cid):
    """{'info','contracts','estimates','payments','notes','tasks','totals'} по клиенту ('person') или юрлицу ('legal')."""
    info = client_info(db, kind, cid)
    contracts, payments = [], []
    for table, column in OWNER_FILTER[kind].items():
        number, obj, day, signed, amount_col = NUMBER_COLUMN[table], OBJECT_COLUMN[table], DATE_COLUMN[table], SIGNED_COLUMN[table], AMOUNT_COLUMN[table]
        extra = ", coalesce(status,'')" if table in ('smr_contracts', 'to_contracts', 'ip_contracts', 'fl_contracts', 'le_contracts') else ", ''"
        est = 'estimate_id' if table != 'le_contracts' else 'NULL'
        for rid, num, o, d, sg, amount, estimate_id, status in db.fetchall(
                f"SELECT id,{number},{obj},{day},{signed},{amount_col},{est}{extra} FROM {table} WHERE {column}=? ORDER BY id DESC", (cid,)):
            s = payments_domain.summary(db, table, rid)
            contracts.append(dict(table=table, id=rid, section=SECTION_NAMES[table], number=num or '', object=o or '', date=d or '', signed=bool(sg), status=status,
                                  amount=_num(amount), paid=s['paid'], debt=s['debt'], estimate_id=estimate_id))
            for pid, pday, pamount, note in payments_domain.history(db, table, rid):
                payments.append(dict(id=pid, date=pday, amount=_num(pamount), section=SECTION_NAMES[table], label=num or '', note=note or ''))
    sale_rows = sales(db, kind, cid)
    for sale in sale_rows:
        for pid, pday, pamount, note in payments_domain.history(db, 'client_sales', sale['id']):
            payments.append(dict(id=pid, date=pday, amount=_num(pamount), section='Продажа по чеку', label=sale['title'] + (f" (чек №{sale['receipt']})" if sale['receipt'] else ''), note=note or ''))
    contracts.sort(key=lambda c: (c['date'], c['number']), reverse=True)
    # сметы клиента
    est_column = 'client_id' if kind == 'person' else 'le_client_id'
    linked = {c['estimate_id'] for c in contracts if c['estimate_id']}
    estimates = []
    for eid, title, day, total, paid in db.fetchall(f'SELECT id,title,date,total,paid FROM estimates WHERE {est_column}=? ORDER BY id DESC', (cid,)):
        own = eid not in linked
        contract = None if own else next((c for c in contracts if c['estimate_id'] == eid), None)
        estimates.append(dict(id=eid, title=title or '', date=day or '', total=_num(total), paid=_num(paid), debt=_num(total) - _num(paid), without_contract=own,
                              contract=f"{contract['section']} · {contract['number']}" if contract else ''))
        if own:       # оплаты сметы без договора; оплаты смет с договором уже учтены в договоре
            for pid, pday, pamount, note in payments_domain.history(db, 'estimates', eid):
                payments.append(dict(id=pid, date=pday, amount=_num(pamount), section='Смета', label=title or '', note=note or ''))
    payments.sort(key=lambda p: (p['date'], p['id']), reverse=True)
    # заметки и задачи: самого клиента и его договоров
    clauses, params = ["(link_table=? AND link_id=?)"], ['crm.clients' if kind == 'person' else 'le_clients', cid]
    task_clauses, task_params = [], []
    for c in contracts:
        clauses.append('(link_table=? AND link_id=?)')
        params += [c['table'], c['id']]
        task_clauses.append('(link_table=? AND link_id=?)')
        task_params += [c['table'], c['id']]
    notes = [dict(id=r[0], title=r[1], date=r[2], link=board.link_label(db, r[3], r[4]) if r[3] in board.LINK_SECTIONS else ('Клиент' if r[3] == 'crm.clients' else 'Юрлицо'))
             for r in db.fetchall(f"SELECT id,title,note_date,link_table,link_id FROM notes WHERE {' OR '.join(clauses)} ORDER BY note_date DESC,id DESC LIMIT 300", params)]
    if kind == 'person':
        task_clauses.append('client_id=?')
        task_params.append(cid)
    tasks = []
    if task_clauses:
        tasks = [dict(id=r[0], title=r[1], status=r[2] or '', due=r[3] or '', archived=bool(r[4]), link=board.link_label(db, r[5], r[6]) or '')
                 for r in db.fetchall(f"SELECT id,title,status_name,due_date,is_archived,link_table,link_id FROM kanban_tasks WHERE {' OR '.join(task_clauses)} ORDER BY is_archived,due_date LIMIT 300", task_params)]
    # итоги: договоры + сметы без договора (сметы внутри договоров не дублируются)
    money = lambda key: (sum((c[key] for c in contracts), Decimal(0)) + sum((e[{'amount': 'total'}.get(key, key)] for e in estimates if e['without_contract']), Decimal(0))
                         + sum((s_[key] for s_ in sale_rows), Decimal(0)))
    totals = dict(contracts=len(contracts), estimates=len(estimates), amount=money('amount'), paid=money('paid'), debt=money('debt'), notes=len(notes), tasks=len([t for t in tasks if not t['archived']]),
                  unsigned=len([c for c in contracts if not c['signed']]))
    return dict(info=info, contracts=contracts, estimates=estimates, sales=sale_rows, payments=payments, notes=notes, tasks=tasks, totals=totals)
