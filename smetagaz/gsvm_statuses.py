"""Статусы договоров «Монтаж ГСВ» (свои, редактируемые, независимые от «Проектов ГСВ») и данные о передаче исполнительной документации."""
KINDS = {'work': 'Статусы работы', 'client': 'Статусы клиента'}
DEFAULTS = {
    'work': [('Не начат', '#64748B'), ('Монтаж', '#D97706'), ('Испытания', '#7C3AED'), ('Сдан', '#16A34A')],
    'client': [('Договор не подписан', '#DC2626'), ('Договор подписан', '#2563EB'), ('Акт подписан', '#0D9488'), ('ИД передана', '#0891B2'),
               ('Не оплачено', '#D97706'), ('Оплачено', '#16A34A')],
}
RECIPIENTS = ['Клиенту', 'Напрямую в ГорГАЗ']


def migrate(db):
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(contracts)')}
    for name, ddl in (('statuses_text', "TEXT DEFAULT ''"), ('id_transferred', 'INTEGER DEFAULT 0'), ('id_recipient', "TEXT DEFAULT ''"), ('id_transfer_date', "TEXT DEFAULT ''")):
        if name not in cols:
            db.execute(f'ALTER TABLE contracts ADD COLUMN {name} {ddl}')
    db.execute("""CREATE TABLE IF NOT EXISTS gsvm_status_catalog(
        id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('work','client')), name TEXT NOT NULL, color TEXT DEFAULT '#2563EB',
        sort_order INTEGER NOT NULL DEFAULT 0, UNIQUE(kind,name))""")
    db.execute("""CREATE TABLE IF NOT EXISTS gsvm_contract_statuses(
        contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
        status_id INTEGER NOT NULL REFERENCES gsvm_status_catalog(id) ON DELETE RESTRICT, PRIMARY KEY(contract_id,status_id))""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_gsvm_cs_status ON gsvm_contract_statuses(status_id)')
    if not db.fetchone('SELECT 1 FROM gsvm_status_catalog LIMIT 1'):
        for kind, items in DEFAULTS.items():
            for order, (name, color) in enumerate(items, 1):
                db.execute('INSERT INTO gsvm_status_catalog(kind,name,color,sort_order) VALUES(?,?,?,?)', (kind, name, color, order))
    if db.get_setting('gsvm_statuses_seeded', '0') != '1':
        # уже существующие договоры: подписанный договор/акт отражаются стартовыми статусами
        ids = {name: sid for sid, name in db.fetchall("SELECT id,name FROM gsvm_status_catalog WHERE kind='client'")}
        for cid, signed, act in db.fetchall('SELECT id,coalesce(contract_signed,0),coalesce(act_signed,0) FROM contracts'):
            if db.fetchone('SELECT 1 FROM gsvm_contract_statuses WHERE contract_id=?', (cid,)):
                continue
            wanted = [ids.get('Договор подписан' if signed else 'Договор не подписан')] + ([ids.get('Акт подписан')] if act else [])
            wanted = [w for w in wanted if w]
            if wanted:
                set_contract_statuses(db, cid, wanted)
        db.set_setting('gsvm_statuses_seeded', '1')


def catalog(db, kind):
    return db.fetchall('SELECT id,name,coalesce(color,?) FROM gsvm_status_catalog WHERE kind=? ORDER BY sort_order,id', ('#2563EB', kind))


def contract_status_ids(db, cid):
    return {r[0] for r in db.fetchall('SELECT status_id FROM gsvm_contract_statuses WHERE contract_id=?', (cid,))}


def contract_statuses(db, cid):
    """[(название, цвет)] статусов договора: сначала работа, затем клиент."""
    return db.fetchall("SELECT c.name,coalesce(c.color,'#2563EB') FROM gsvm_contract_statuses s JOIN gsvm_status_catalog c ON c.id=s.status_id "
                       "WHERE s.contract_id=? ORDER BY CASE c.kind WHEN 'work' THEN 0 ELSE 1 END,c.sort_order,c.id", (cid,))


def _text(db, cid):
    return ', '.join(name for name, _color in contract_statuses(db, cid))


def set_contract_statuses(db, cid, status_ids):
    """Сохраняет набор статусов и дублирует названия текстом в contracts.statuses_text (поиск, реестр, выгрузки)."""
    with db.transaction():
        db.execute('DELETE FROM gsvm_contract_statuses WHERE contract_id=?', (cid,))
        for sid in sorted(set(status_ids)):
            db.execute('INSERT INTO gsvm_contract_statuses(contract_id,status_id) VALUES(?,?)', (cid, sid))
        db.execute('UPDATE contracts SET statuses_text=? WHERE id=?', (_text(db, cid), cid))


def refresh_texts(db):
    """Пересчитывает текстовые копии статусов у всех договоров (после переименования статуса)."""
    for (cid,) in db.fetchall('SELECT DISTINCT contract_id FROM gsvm_contract_statuses'):
        db.execute('UPDATE contracts SET statuses_text=? WHERE id=?', (_text(db, cid), cid))


def status_usage(db, status_id):
    return db.fetchone('SELECT count(*) FROM gsvm_contract_statuses WHERE status_id=?', (status_id,))[0]


def save_status(db, kind, name, color, status_id=None):
    name = str(name or '').strip()
    if not name:
        raise ValueError('Введите название статуса')
    if kind not in KINDS:
        raise ValueError('Неизвестный вид статуса')
    try:
        with db.transaction():
            if status_id:
                db.execute('UPDATE gsvm_status_catalog SET name=?,color=? WHERE id=?', (name, color, status_id))
            else:
                order = (db.fetchone('SELECT max(sort_order) FROM gsvm_status_catalog WHERE kind=?', (kind,))[0] or 0) + 1
                status_id = db.execute('INSERT INTO gsvm_status_catalog(kind,name,color,sort_order) VALUES(?,?,?,?)', (kind, name, color, order)).lastrowid
            refresh_texts(db)
    except Exception as e:
        if 'UNIQUE' in str(e):
            raise ValueError('Такой статус уже есть') from None
        raise
    return status_id


def delete_status(db, status_id):
    if status_usage(db, status_id):
        raise ValueError('Сначала снимите этот статус с договоров, где он выбран')
    db.execute('DELETE FROM gsvm_status_catalog WHERE id=?', (status_id,))


def move_status(db, kind, status_id, direction):
    ids = [r[0] for r in catalog(db, kind)]
    i = ids.index(status_id)
    j = i + direction
    if not 0 <= j < len(ids):
        return
    ids[i], ids[j] = ids[j], ids[i]
    with db.transaction():
        for order, sid in enumerate(ids, 1):
            db.execute('UPDATE gsvm_status_catalog SET sort_order=? WHERE id=?', (order, sid))
