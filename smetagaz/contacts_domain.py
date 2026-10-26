"""Модуль «Контакты»: рабочая телефонная книга — организации, службы, поставщики, люди; по желанию связь с клиентом (физлицом) или юрлицом из справочников."""

CATEGORIES = ('Рабочие', 'Заказчики', 'Поставщики', 'Контролирующие органы', 'Лаборатории', 'Подрядчики', 'Прочие')


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY, name TEXT NOT NULL, organization TEXT DEFAULT '', position TEXT DEFAULT '', category TEXT DEFAULT 'Рабочие',
        phone TEXT DEFAULT '', email TEXT DEFAULT '', address TEXT DEFAULT '', note TEXT DEFAULT '', client_id INTEGER, legal_id INTEGER, favorite INTEGER NOT NULL DEFAULT 0)""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(name)')


FIELDS = ('name', 'organization', 'position', 'category', 'phone', 'email', 'address', 'note', 'client_id', 'legal_id', 'favorite')


def save_contact(db, values, cid=None):
    name = str(values.get('name') or '').strip()
    if not name:
        name = str(values.get('organization') or '').strip()
    if not name:
        raise ValueError('Укажите имя или организацию')
    data = []
    for k in FIELDS:
        v = values.get(k)
        data.append((v or None) if k in ('client_id', 'legal_id') else int(bool(v)) if k == 'favorite' else (name if k == 'name' else str(v or '').strip()))
    if data[FIELDS.index('category')] == '':
        data[FIELDS.index('category')] = 'Рабочие'
    if cid:
        db.execute('UPDATE contacts SET ' + ','.join(f'{k}=?' for k in FIELDS) + ' WHERE id=?', (*data, cid))
        return cid
    return db.execute(f'INSERT INTO contacts({",".join(FIELDS)}) VALUES({",".join("?" * len(FIELDS))})', data).lastrowid


def get_contact(db, cid):
    cur = db.execute('SELECT * FROM contacts WHERE id=?', (cid,))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def delete_contact(db, cid):
    db.execute('DELETE FROM contacts WHERE id=?', (cid,))


def listing(db, search='', category='', linked=''):
    """Контакты (избранные сверху). linked: '' — все, 'client' — связанные с клиентом, 'legal' — с юрлицом, 'free' — без связи."""
    where, params = ['1=1'], []
    if category:
        where.append('c.category=?')
        params.append(category)
    if linked == 'client':
        where.append('c.client_id IS NOT NULL')
    elif linked == 'legal':
        where.append('c.legal_id IS NOT NULL')
    elif linked == 'free':
        where.append('c.client_id IS NULL AND c.legal_id IS NULL')
    if search:
        where.append("LOWER(coalesce(c.name,'')||' '||coalesce(c.organization,'')||' '||coalesce(c.position,'')||' '||coalesce(c.phone,'')||' '||coalesce(c.email,'')||' '||coalesce(c.address,'')||' '||coalesce(c.note,'')) LIKE ?")
        params.append(f'%{search.casefold()}%')
    cur = db.execute(f"""SELECT c.*,coalesce(p.name,'') AS client_name,coalesce(l.name,'') AS legal_name FROM contacts c LEFT JOIN crm.clients p ON p.id=c.client_id
        LEFT JOIN le_clients l ON l.id=c.legal_id WHERE {' AND '.join(where)} ORDER BY c.favorite DESC, LOWER(c.name)""", params)
    return [dict(zip([x[0] for x in cur.description], r)) for r in cur.fetchall()]


def from_client(db, client_id):
    """Данные контакта из карточки клиента (физлица)."""
    row = db.fetchone('SELECT name,phone,address,notes FROM crm.clients WHERE id=?', (client_id,))
    if not row:
        raise ValueError('Клиент не найден')
    return dict(name=row[0], phone=row[1] or '', address=row[2] or '', note=row[3] or '', category='Заказчики', client_id=client_id)


def from_legal(db, legal_id):
    """Данные контакта из справочника юрлиц: организация, телефон, e-mail, адрес, контактное лицо."""
    row = db.fetchone("SELECT name,phone,email,coalesce(nullif(legal_address,''),address),contact_person FROM le_clients WHERE id=?", (legal_id,))
    if not row:
        raise ValueError('Юрлицо не найдено')
    return dict(name=row[4] or row[0], organization=row[0], phone=row[1] or '', email=row[2] or '', address=row[3] or '', category='Заказчики', legal_id=legal_id)


def add_from_directory(db, kind, ref_id):
    """Добавляет контакт из справочника; уже добавленный (по связи) повторно не создаётся — возвращается его id."""
    col = 'client_id' if kind == 'client' else 'legal_id'
    row = db.fetchone(f'SELECT id FROM contacts WHERE {col}=?', (ref_id,))
    if row:
        return row[0], False
    values = from_client(db, ref_id) if kind == 'client' else from_legal(db, ref_id)
    return save_contact(db, values), True
