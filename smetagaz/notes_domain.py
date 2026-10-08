"""Заметки: независимые и привязанные к договору, проекту, клиенту или юрлицу. У каждой заметки есть дата — она попадает в календарь. Без Qt."""
from datetime import date, datetime

from . import board_domain as board

LINK_TABLES = dict(board.LINK_SECTIONS)
LINK_TABLES.update({'crm.clients': 'Клиент', 'le_clients': 'Юрлицо (справочник)'})


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '', note_date TEXT NOT NULL DEFAULT '',
        link_table TEXT NOT NULL DEFAULT '', link_id INTEGER, created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '')""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_notes_date ON notes(note_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_notes_link ON notes(link_table,link_id)')
    # заметки привязанной карточки исчезают вместе с ней
    for table in ('contracts', 'gsv_projects', 'gsn_projects', 'le_contracts', 'smr_contracts', 'le_clients'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS cleanup_notes_{table} AFTER DELETE ON {table} BEGIN DELETE FROM notes WHERE link_table='{table}' AND link_id=old.id; END")


def link_label(db, table, rid):
    if table == 'crm.clients':
        row = db.fetchone('SELECT name FROM crm.clients WHERE id=?', (rid,))
        return f'Клиент · {row[0]}' if row else None
    if table == 'le_clients':
        row = db.fetchone('SELECT name FROM le_clients WHERE id=?', (rid,))
        return f'Юрлицо · {row[0]}' if row else None
    return board.link_label(db, table, rid)


def records(db, table, query=''):
    q = str(query or '').casefold()
    if table == 'crm.clients':
        return [(i, n) for i, n in db.fetchall('SELECT id,name FROM crm.clients ORDER BY name') if q in (n or '').casefold()]
    if table == 'le_clients':
        return [(i, n) for i, n in db.fetchall('SELECT id,name FROM le_clients ORDER BY name') if q in (n or '').casefold()]
    return board.records(db, table, query)


def save_note(db, title, body='', note_date=None, link=None, note_id=None):
    title = str(title or '').strip()
    body = str(body or '').strip()
    if not title and not body:
        raise ValueError('Введите заголовок или текст заметки')
    day = str(note_date or date.today().isoformat())
    date.fromisoformat(day)
    table, rid = link or ('', None)
    if table and (table not in LINK_TABLES or not rid):
        raise ValueError('Выберите запись для привязки заметки')
    if not title:
        title = body.splitlines()[0][:60]
    now = datetime.now().isoformat(timespec='seconds')
    if note_id:
        db.execute('UPDATE notes SET title=?,body=?,note_date=?,link_table=?,link_id=?,updated_at=? WHERE id=?', (title, body, day, table, rid if table else None, now, note_id))
        return note_id
    return db.execute('INSERT INTO notes(title,body,note_date,link_table,link_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                      (title, body, day, table, rid if table else None, now, now)).lastrowid


def get_note(db, note_id):
    cur = db.execute('SELECT * FROM notes WHERE id=?', (note_id,))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def delete_note(db, note_id):
    db.execute('DELETE FROM notes WHERE id=?', (note_id,))


def _search_clause(q):
    """SQL-условие поиска: заголовок, текст и название привязанной записи (клиент, юрлицо, номер договора)."""
    like = '%' + q + '%'
    parts = ["lower(n.title||' '||n.body) LIKE ?"]
    params = [like]
    for table, expr in (('crm.clients', 'name'), ('le_clients', 'name'), ('le_contracts', "contract_number||' '||object_name"), ('smr_contracts', "contract_number||' '||object_name"),
                        ('contracts', "contract_number||' '||object_name"), ('gsv_projects', "pd_number||' '||object_name"), ('gsn_projects', "contract_number||' '||title")):
        parts.append(f"(n.link_table='{table}' AND n.link_id IN (SELECT id FROM {table} WHERE lower(coalesce({expr},'')) LIKE ?))")
        params.append(like)
    return '(' + ' OR '.join(parts) + ')', params


def page_notes(db, scope='all', query='', link=None, day=None, limit=100, offset=0):
    """Страница заметок и общее число найденных: ([{id,title,body,date,link_table,link_id,link}], total). scope: all | free | linked."""
    where, params = ['1=1'], []
    if link:
        where.append('n.link_table=? AND n.link_id=?')
        params += [link[0], link[1]]
    elif scope == 'free':
        where.append("n.link_table=''")
    elif scope == 'linked':
        where.append("n.link_table<>''")
    if day:
        where.append('n.note_date=?')
        params.append(day)
    q = str(query or '').strip().casefold()
    if q:
        clause, qp = _search_clause(q)
        where.append(clause)
        params += qp
    cond = ' AND '.join(where)
    total = db.fetchone(f'SELECT count(*) FROM notes n WHERE {cond}', params)[0]
    rows = db.fetchall(f'SELECT n.id,n.title,n.body,n.note_date,n.link_table,n.link_id FROM notes n WHERE {cond} ORDER BY n.note_date DESC,n.id DESC LIMIT ? OFFSET ?',
                       (*params, limit, offset))
    out = []
    for row in rows:
        label = link_label(db, row[4], row[5]) if row[4] else ''
        out.append(dict(id=row[0], title=row[1], body=row[2], date=row[3], link_table=row[4], link_id=row[5], link=label or ('(запись удалена)' if row[4] else '')))
    return out, total


def list_notes(db, scope='all', query='', link=None, day=None):
    """Все подходящие заметки (без постраничности) — для небольших выборок, например заметок одной карточки."""
    return page_notes(db, scope, query, link, day, limit=1_000_000)[0]


def count_for(db, table, rid):
    return db.fetchone('SELECT count(*) FROM notes WHERE link_table=? AND link_id=?', (table, rid))[0]
