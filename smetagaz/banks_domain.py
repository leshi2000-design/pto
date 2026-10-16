"""Реестр банков: название, БИК и адрес банка подставляются в реквизиты юрлиц. Изменение банка в реестре обновляет реквизиты всех юрлиц, выбравших этот банк."""


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS banks(id INTEGER PRIMARY KEY, name TEXT NOT NULL, bic TEXT DEFAULT '', address TEXT DEFAULT '', unp TEXT DEFAULT '', note TEXT DEFAULT '')""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_banks_name ON banks(name)')
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(le_clients)')}
    for name in ('bank_address', 'bank_id'):
        if name not in cols:
            db.execute(f"ALTER TABLE le_clients ADD COLUMN {name} {'INTEGER' if name == 'bank_id' else 'TEXT DEFAULT ' + chr(39) * 2}")


def listing(db, search=''):
    q = f'%{str(search or "").casefold()}%'
    return db.fetchall("""SELECT b.id,b.name,b.bic,b.address,b.unp,b.note,(SELECT count(*) FROM le_clients WHERE bank_id=b.id)
        FROM banks b WHERE LOWER(b.name||' '||b.bic||' '||b.address||' '||b.unp) LIKE ? ORDER BY b.name COLLATE NOCASE""", (q,))


def get(db, bid):
    cur = db.execute('SELECT * FROM banks WHERE id=?', (bid,))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def save(db, values, bid=None):
    name = str(values.get('name') or '').strip()
    if not name:
        raise ValueError('Укажите название банка')
    bic = str(values.get('bic') or '').strip().upper()
    if bic and not (8 <= len(bic) <= 11):
        raise ValueError('БИК (SWIFT) банка — 8–11 символов')
    dup = db.fetchone('SELECT id FROM banks WHERE LOWER(name)=LOWER(?) AND coalesce(bic,\'\')=? AND id<>?', (name, bic, bid or 0))
    if dup:
        raise ValueError('Такой банк уже есть в реестре')
    data = (name, bic, str(values.get('address') or '').strip(), str(values.get('unp') or '').strip(), str(values.get('note') or '').strip())
    with db.transaction():
        if bid:
            db.execute('UPDATE banks SET name=?,bic=?,address=?,unp=?,note=? WHERE id=?', (*data, bid))
            refresh_clients(db, bid)
        else:
            bid = db.execute('INSERT INTO banks(name,bic,address,unp,note) VALUES(?,?,?,?,?)', data).lastrowid
    return bid


def refresh_clients(db, bid):
    """Обновляет банковские реквизиты юрлиц, выбравших этот банк."""
    b = get(db, bid)
    if b:
        db.execute('UPDATE le_clients SET bank=?,bic=?,bank_address=? WHERE bank_id=?', (b['name'], b['bic'], b['address'], bid))


def delete(db, bid):
    """Банк, который выбран у юрлиц, можно удалить: реквизиты у юрлиц остаются текстом, связь снимается."""
    with db.transaction():
        db.execute('UPDATE le_clients SET bank_id=NULL WHERE bank_id=?', (bid,))
        db.execute('DELETE FROM banks WHERE id=?', (bid,))


def apply_to_client(db, legal_id, bid):
    """Подставляет название, БИК и адрес банка юрлицу и запоминает выбор."""
    if bid is None:
        db.execute('UPDATE le_clients SET bank_id=NULL WHERE id=?', (legal_id,))
        return
    b = get(db, bid)
    if not b:
        raise ValueError('Банк не найден')
    db.execute('UPDATE le_clients SET bank=?,bic=?,bank_address=?,bank_id=? WHERE id=?', (b['name'], b['bic'], b['address'], bid, legal_id))
