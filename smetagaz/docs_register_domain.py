"""Журнал регистрации документов: входящие, исходящие и внутренние документы с номером, сроком исполнения, исполнителем и статусом."""
from datetime import date, datetime

DIRECTIONS = ('Входящий', 'Исходящий', 'Внутренний')
PREFIX = {'Входящий': 'Вх', 'Исходящий': 'Исх', 'Внутренний': 'Вн'}
KINDS = ('Письмо', 'Договор', 'Акт', 'Заявление', 'Приказ', 'Претензия', 'Счёт', 'Справка', 'Разрешение / допуск', 'Другое')
STATUSES = ('Зарегистрирован', 'На исполнении', 'Исполнен', 'В архиве')
OPEN = ('Зарегистрирован', 'На исполнении')
ISO = '%Y-%m-%d'


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS doc_register(id INTEGER PRIMARY KEY, direction TEXT NOT NULL DEFAULT 'Входящий', seq_num INTEGER, year_num INTEGER,
        reg_number TEXT NOT NULL, reg_date TEXT NOT NULL, kind TEXT DEFAULT 'Письмо', doc_number TEXT DEFAULT '', doc_date TEXT DEFAULT '', correspondent TEXT NOT NULL DEFAULT '',
        client_id INTEGER REFERENCES le_clients(id) ON DELETE SET NULL, subject TEXT DEFAULT '', executor TEXT DEFAULT '', due_date TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Зарегистрирован', answer_ref TEXT DEFAULT '', file_path TEXT DEFAULT '', note TEXT DEFAULT '', legacy_outgoing_id INTEGER UNIQUE)""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_doc_register_date ON doc_register(reg_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_doc_register_due ON doc_register(due_date)')


def _day(value):
    try:
        return datetime.strptime(str(value or '')[:10], ISO).date()
    except ValueError:
        return None


def next_number(db, direction, reg_date=None):
    """Номер в пределах направления и года: «Вх-12/26», «Исх-05/26», «Вн-03/26»."""
    if direction not in DIRECTIONS:
        raise ValueError('Неизвестное направление документа')
    yy = (_day(reg_date) or date.today()).year
    seq = (db.fetchone('SELECT coalesce(max(seq_num),0) FROM doc_register WHERE direction=? AND year_num=?', (direction, yy))[0] or 0) + 1
    return seq, yy, f'{PREFIX[direction]}-{seq:02d}/{yy % 100:02d}'


def save_doc(db, values, did=None):
    direction = values.get('direction') or 'Входящий'
    if direction not in DIRECTIONS:
        raise ValueError('Неизвестное направление документа')
    reg = _day(values.get('reg_date'))
    if not reg:
        raise ValueError('Укажите дату регистрации')
    if not str(values.get('correspondent') or '').strip():
        raise ValueError('Укажите корреспондента: от кого получен или кому адресован документ')
    if not str(values.get('subject') or '').strip():
        raise ValueError('Укажите содержание документа')
    due = values.get('due_date') or ''
    if due and (not _day(due) or _day(due) < reg):
        raise ValueError('Срок исполнения раньше даты регистрации')
    status = values.get('status') or 'Зарегистрирован'
    if status not in STATUSES:
        raise ValueError('Неизвестный статус')
    number = str(values.get('reg_number') or '').strip()
    with db.transaction():
        seq = None
        if not number:
            seq, yy, number = next_number(db, direction, values['reg_date'])
        else:
            yy = reg.year
        if db.fetchone('SELECT id FROM doc_register WHERE reg_number=? AND year_num=? AND id<>?', (number, yy, did or 0)):
            raise ValueError(f'Номер {number} за {yy} год уже занят')
        row = (direction, seq, yy, number, values['reg_date'], values.get('kind') or 'Письмо', str(values.get('doc_number') or '').strip(), values.get('doc_date') or '',
               str(values['correspondent']).strip(), values.get('client_id') or None, str(values['subject']).strip(), str(values.get('executor') or '').strip(), due, status,
               str(values.get('answer_ref') or '').strip(), str(values.get('file_path') or '').strip(), str(values.get('note') or '').strip())
        cols = 'direction,seq_num,year_num,reg_number,reg_date,kind,doc_number,doc_date,correspondent,client_id,subject,executor,due_date,status,answer_ref,file_path,note'
        if did:
            old = db.fetchone('SELECT seq_num FROM doc_register WHERE id=?', (did,))
            if seq is None and old:
                row = (row[0], old[0], *row[2:])
            db.execute('UPDATE doc_register SET ' + ','.join(f'{c}=?' for c in cols.split(',')) + ' WHERE id=?', (*row, did))
            return did
        return db.execute(f'INSERT INTO doc_register({cols}) VALUES({",".join("?" * 17)})', row).lastrowid


def get_doc(db, did):
    cur = db.execute('SELECT * FROM doc_register WHERE id=?', (did,))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def delete_doc(db, did):
    db.execute('DELETE FROM doc_register WHERE id=?', (did,))


def set_status(db, did, status):
    if status not in STATUSES:
        raise ValueError('Неизвестный статус')
    db.execute('UPDATE doc_register SET status=? WHERE id=?', (status, did))


def is_overdue(status, due_date, today=None):
    d = _day(due_date)
    return bool(d) and status in OPEN and d < (today or date.today())


def listing(db, search='', direction='', status='', overdue_only=False, limit=100, offset=0, today=None):
    """(всего, строки) — строки словарями; поиск по номеру, корреспонденту, содержанию, исполнителю."""
    where, params = ['1=1'], []
    if search:
        where.append("LOWER(coalesce(d.reg_number,'')||' '||coalesce(d.doc_number,'')||' '||coalesce(d.correspondent,'')||' '||coalesce(d.subject,'')||' '||coalesce(d.executor,'')) LIKE ?")
        params.append(f'%{search.casefold()}%')
    if direction:
        where.append('d.direction=?')
        params.append(direction)
    if status:
        where.append('d.status=?')
        params.append(status)
    if overdue_only:
        where.append("d.status IN ('Зарегистрирован','На исполнении') AND coalesce(d.due_date,'')<>'' AND d.due_date<?")
        params.append((today or date.today()).isoformat())
    cond = ' AND '.join(where)
    total = db.fetchone(f'SELECT count(*) FROM doc_register d WHERE {cond}', params)[0]
    cur = db.execute(f"""SELECT d.*,coalesce(c.name,'') AS client_name FROM doc_register d LEFT JOIN le_clients c ON c.id=d.client_id WHERE {cond}
        ORDER BY coalesce(d.year_num,0) DESC, d.direction, coalesce(d.seq_num,0) DESC, d.id DESC LIMIT ? OFFSET ?""", (*params, limit, offset))
    rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
    for r in rows:
        r['overdue'] = is_overdue(r['status'], r['due_date'], today)
    return total, rows


def import_outgoing(db):
    """Исходящие юрлиц (прежний журнал) попадают в общий журнал; повторный вызов добавляет только новые. Возвращает число добавленных."""
    n = 0
    with db.transaction():
        for oid, number, day, recipient, subject, client_id, note in db.fetchall(
                "SELECT id,coalesce(reg_number,''),coalesce(reg_date,''),coalesce(recipient,''),coalesce(subject,''),client_id,coalesce(note,'') FROM le_outgoing ORDER BY id"):
            if db.fetchone('SELECT 1 FROM doc_register WHERE legacy_outgoing_id=?', (oid,)):
                continue
            day = day[:10] if _day(day) else date.today().isoformat()
            yy = _day(day).year
            number = number or ''
            # прежний номер «7» превращается в «Исх-07/26»; занятый номер получает следующий свободный
            if number.isdigit():
                seq = int(number)
                cand = f'{PREFIX["Исходящий"]}-{seq:02d}/{yy % 100:02d}'
                if db.fetchone('SELECT 1 FROM doc_register WHERE reg_number=? AND year_num=?', (cand, yy)):
                    seq, yy, cand = next_number(db, 'Исходящий', day)
            else:
                seq, yy, cand = next_number(db, 'Исходящий', day)
            db.execute('INSERT INTO doc_register(direction,seq_num,year_num,reg_number,reg_date,kind,correspondent,client_id,subject,note,status,legacy_outgoing_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('Исходящий', seq, yy, cand, day, 'Письмо', recipient or '—', client_id, subject or '—', note, 'Исполнен', oid))
            n += 1
    return n
