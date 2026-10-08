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


def list_notes(db, scope='all', query='', link=None, day=None):
    """scope: all | free (независимые) | linked (привязанные). link=(таблица, id) — заметки одной карточки."""
    sql, params = 'SELECT id,title,body,note_date,link_table,link_id FROM notes WHERE 1=1', []
    if link:
        sql += ' AND link_table=? AND link_id=?'
        params += [link[0], link[1]]
    elif scope == 'free':
        sql += " AND link_table=''"
    elif scope == 'linked':
        sql += " AND link_table<>''"
    if day:
        sql += ' AND note_date=?'
        params.append(day)
    sql += ' ORDER BY note_date DESC,id DESC'
    q = str(query or '').casefold()
    out = []
    for row in db.fetchall(sql, tuple(params)):
        label = link_label(db, row[4], row[5]) if row[4] else ''
        if q and q not in f'{row[1]} {row[2]} {label or ""}'.casefold():
            continue
        out.append(dict(id=row[0], title=row[1], body=row[2], date=row[3], link_table=row[4], link_id=row[5], link=label or ('(запись удалена)' if row[4] else '')))
    return out


def count_for(db, table, rid):
    return db.fetchone('SELECT count(*) FROM notes WHERE link_table=? AND link_id=?', (table, rid))[0]
