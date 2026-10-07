"""A single payment ledger, shared by an estimate and its linked contract."""
from decimal import Decimal
from datetime import date
OWNERS={'estimates':('total','Сметы'),'contracts':('contract_amount','ГСВ'),'gsn_projects':('contract_amount','ГСН'),'gsv_projects':('cost','Проектирование ГСВ'),'le_contracts':('amount','Юрлица'),'smr_contracts':('amount','СМР')}
def migrate(db):
    for table,additions in {'payments':{'owner_type':'TEXT','owner_id':'INTEGER','note':"TEXT DEFAULT ''"},'gsn_projects':{'estimate_id':'INTEGER REFERENCES estimates(id)','contract_amount':'REAL DEFAULT 0'},'gsv_projects':{'estimate_id':'INTEGER REFERENCES estimates(id)'},'estimates':{'payment_opening':'REAL DEFAULT 0'}}.items():
        cols={r[1] for r in db.fetchall(f'PRAGMA table_info({table})')}
        for col,typ in additions.items():
            if col not in cols:db.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
    db.execute('CREATE INDEX IF NOT EXISTS idx_payment_owner ON payments(owner_type,owner_id,date)')
    if db.get_setting('payment_opening_migrated','0')!='1':
        db.execute('UPDATE estimates SET payment_opening=max(0,round(coalesce(paid,0)-coalesce((SELECT sum(amount) FROM payments WHERE estimate_id=estimates.id),0),2))')
        db.execute('UPDATE estimates SET paid=round(coalesce(payment_opening,0)+coalesce((SELECT sum(amount) FROM payments WHERE estimate_id=estimates.id),0),2)')
        db.set_setting('payment_opening_migrated','1')
    for action in ('INSERT','UPDATE','DELETE'):
        refs=('new',) if action=='INSERT' else ('old',) if action=='DELETE' else ('old','new')
        sql=' '.join(f'UPDATE estimates SET paid=round(coalesce(payment_opening,0)+coalesce((SELECT sum(amount) FROM payments WHERE estimate_id=estimates.id),0),2),payment_date=(SELECT max(date) FROM payments WHERE estimate_id=estimates.id) WHERE id={ref}.estimate_id;' for ref in refs)
        db.execute(f'CREATE TRIGGER IF NOT EXISTS sync_payment_{action} AFTER {action} ON payments BEGIN {sql} END')
    for owner in ('contracts','gsn_projects','gsv_projects'):
        # Payment history must not disappear with a contract.
        db.execute(f'DROP TRIGGER IF EXISTS protect_paid_{owner}')
        db.execute(f"CREATE TRIGGER IF NOT EXISTS protect_paid_{owner} BEFORE DELETE ON {owner} WHEN EXISTS(SELECT 1 FROM payments WHERE (owner_type='{owner}' AND owner_id=old.id) OR (old.estimate_id IS NOT NULL AND estimate_id=old.estimate_id)) BEGIN SELECT RAISE(ABORT,'У договора есть оплаты. Сохраните договор для истории расчётов.'); END")

def record(db,owner,rid):
    if owner not in OWNERS:raise ValueError('Неверный раздел оплаты')
    cur=db.execute(f'SELECT * FROM {owner} WHERE id=?',(rid,));row=cur.fetchone()
    if not row:raise ValueError('Сначала сохраните документ')
    return dict(zip([c[0] for c in cur.description],row))
def account(db,owner,rid):
    data=record(db,owner,rid);eid=rid if owner=='estimates' else data.get('estimate_id')
    if eid:
        db.execute('UPDATE estimates SET payment_opening=max(0,round(coalesce(paid,0)-coalesce((SELECT sum(amount) FROM payments WHERE estimate_id=estimates.id),0),2)) WHERE id=? AND round(coalesce(paid,0)-coalesce(payment_opening,0)-coalesce((SELECT sum(amount) FROM payments WHERE estimate_id=estimates.id),0),2)<>0',(eid,))
    return (eid,data)
def history(db,owner,rid):
    eid,data=account(db,owner,rid)
    return db.fetchall('SELECT id,date,amount,note FROM payments WHERE '+('estimate_id=?' if eid else 'estimate_id IS NULL AND owner_type=? AND owner_id=?')+' ORDER BY date DESC,id DESC',(eid,) if eid else (owner,rid))
def summary(db,owner,rid):
    eid,data=account(db,owner,rid);opening=db.fetchone('SELECT payment_opening FROM estimates WHERE id=?',(eid,))[0] or 0 if eid else 0
    paid=Decimal(str(opening))+sum((Decimal(str(r[2])) for r in history(db,owner,rid)),Decimal(0));total=Decimal(str(data.get(OWNERS[owner][0]) or 0))
    return {'total':total,'paid':paid,'debt':total-paid,'opening':Decimal(str(opening)),'estimate_id':eid}
def add(db,owner,rid,amount,day,note=''):
    n=Decimal(str(amount));date.fromisoformat(day)
    if not n.is_finite() or n<=0 or n!=n.quantize(Decimal('.01')):raise ValueError('Введите положительную сумму с точностью до копейки')
    with db.transaction():
        eid,data=account(db,owner,rid)
        return db.execute('INSERT INTO payments(estimate_id,owner_type,owner_id,amount,date,note) VALUES(?,?,?,?,?,?)',(eid,owner,rid,float(n),day,note)).lastrowid

def link(db,owner,rid,eid):
    if owner=='estimates':raise ValueError('Выберите договор')
    with db.transaction():
        _,data=account(db,owner,rid);old=data.get('estimate_id')
        if old==eid:return
        if old and history(db,owner,rid):raise ValueError('У связанной сметы есть оплаты. Перепривязка запрещена, чтобы не переносить деньги между объектами.')
        if eid:
            account(db,'estimates',eid)
            for table in ('contracts','gsn_projects','gsv_projects','smr_contracts'):
                found=db.fetchone(f'SELECT id FROM {table} WHERE estimate_id=?',(eid,))
                if found and (table!=owner or found[0]!=rid):raise ValueError('Эта смета уже связана с другим договором')
        db.execute(f'UPDATE {owner} SET estimate_id=? WHERE id=?',(eid,rid))
        db.execute('UPDATE payments SET estimate_id=? WHERE owner_type=? AND owner_id=? AND estimate_id IS NULL',(eid,owner,rid))
def report(db,start,end,section=''):
    date.fromisoformat(start);date.fromisoformat(end)
    if start>end:raise ValueError('Начало периода позже окончания')
    result=[]
    for pid,day,amount,owner,rid,eid,note in db.fetchall('SELECT id,date,amount,owner_type,owner_id,estimate_id,note FROM payments WHERE date BETWEEN ? AND ? ORDER BY date,id',(start,end)):
        if eid:
            owner,rid='estimates',eid
            for table in ('contracts','gsn_projects','gsv_projects','smr_contracts'):
                found=db.fetchone(f'SELECT id FROM {table} WHERE estimate_id=?',(eid,))
                if found:owner,rid=table,found[0];break
        if owner not in OWNERS:owner,rid='estimates',eid
        if not rid:continue
        if section and owner!=section:continue
        data=record(db,owner,rid);result.append(dict(id=pid,date=day,amount=amount,section=OWNERS[owner][1],number=data.get('contract_number') or str(rid),object_name=data.get('title') or data.get('object_name',''),client_name=_client_label(db,owner,data),note=note or ''))
    return result

def _client_label(db,owner,data):
    if owner=='le_contracts':
        from . import contracts_core as cc
        return cc.party_label(db,'le',data)
    if owner=='smr_contracts':
        from . import contracts_core as cc
        return cc.party_label(db,'smr',data)
    return data.get('client_name') or data.get('party_name') or ''
