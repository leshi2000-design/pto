"""Модуль «Документы»: три журнала регистрации — исходящие, приказы и прочие документы по организации. У каждого свой номер, набор видов и статусов."""
from datetime import date, datetime, timedelta

OUT, ORDER, OTHER = 'out', 'order', 'other'
REGISTERS = {
    OUT: dict(title='Регистрация исходящих', prefix='Исх', direction='Исходящий',
              kinds=('Письмо', 'Ответ на обращение', 'Претензия', 'Коммерческое предложение', 'Заявка', 'Акт сверки', 'Уведомление', 'Другое'),
              statuses=('Зарегистрирован', 'Отправлен', 'Получен ответ', 'В архиве'), open=('Зарегистрирован', 'Отправлен')),
    ORDER: dict(title='Регистрация приказов', prefix='Пр', direction='Внутренний',
                kinds=('По основной деятельности', 'По личному составу', 'Об охране труда', 'О назначении ответственных', 'О командировке', 'Об отпуске', 'Другой'),
                statuses=('Действует', 'Исполнен', 'Отменён', 'В архиве'), open=('Действует',)),
    OTHER: dict(title='Прочие документы по организации', prefix='Д', direction='Внутренний',
                kinds=('Устав / учредительные', 'Свидетельство о регистрации', 'Лицензия / разрешение', 'Аттестат / допуск организации', 'Протокол', 'Доверенность', 'Страховой полис',
                       'Договор аренды', 'Справка / выписка', 'Другое'),
                statuses=('Действует', 'В архиве'), open=('Действует',)),
}
WARN_DAYS = 30
ISO = '%Y-%m-%d'
# совместимость с версией 4.7.0
DIRECTIONS = ('Входящий', 'Исходящий', 'Внутренний')


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS doc_register(id INTEGER PRIMARY KEY, direction TEXT NOT NULL DEFAULT 'Входящий', seq_num INTEGER, year_num INTEGER,
        reg_number TEXT NOT NULL, reg_date TEXT NOT NULL, kind TEXT DEFAULT 'Письмо', doc_number TEXT DEFAULT '', doc_date TEXT DEFAULT '', correspondent TEXT NOT NULL DEFAULT '',
        client_id INTEGER REFERENCES le_clients(id) ON DELETE SET NULL, subject TEXT DEFAULT '', executor TEXT DEFAULT '', due_date TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Зарегистрирован', answer_ref TEXT DEFAULT '', file_path TEXT DEFAULT '', note TEXT DEFAULT '', legacy_outgoing_id INTEGER UNIQUE)""")
    if 'register' not in {r[1] for r in db.fetchall('PRAGMA table_info(doc_register)')}:
        db.execute("ALTER TABLE doc_register ADD COLUMN register TEXT NOT NULL DEFAULT 'other'")
        db.execute("UPDATE doc_register SET register='out' WHERE direction='Исходящий'")
        db.execute("UPDATE doc_register SET status='Действует' WHERE register='other' AND status IN ('Зарегистрирован','На исполнении','Исполнен')")
    db.execute('CREATE INDEX IF NOT EXISTS idx_doc_register_date ON doc_register(reg_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_doc_register_due ON doc_register(due_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_doc_register_reg ON doc_register(register,year_num)')


def _day(value):
    try:
        return datetime.strptime(str(value or '')[:10], ISO).date()
    except ValueError:
        return None


def _cfg(register):
    if register not in REGISTERS:
        raise ValueError('Неизвестный журнал')
    return REGISTERS[register]


def next_number(db, register, reg_date=None):
    """Номер в пределах журнала и года: исходящие «Исх-05/26», приказы «Пр-03/26», прочие «Д-02/26»."""
    cfg = _cfg(register)
    yy = (_day(reg_date) or date.today()).year
    seq = (db.fetchone('SELECT coalesce(max(seq_num),0) FROM doc_register WHERE register=? AND year_num=?', (register, yy))[0] or 0) + 1
    return seq, yy, f'{cfg["prefix"]}-{seq:02d}/{yy % 100:02d}'


def save_doc(db, values, did=None):
    register = values.get('register') or OUT
    cfg = _cfg(register)
    reg = _day(values.get('reg_date'))
    if not reg:
        raise ValueError('Укажите дату регистрации')
    party = str(values.get('correspondent') or '').strip()
    if register == OUT and not party:
        raise ValueError('Укажите, кому адресован документ')
    if not str(values.get('subject') or '').strip():
        raise ValueError('Укажите содержание документа')
    due = values.get('due_date') or ''
    if due and not _day(due):
        raise ValueError('Неверный срок')
    if due and register != OTHER and _day(due) < reg:
        raise ValueError('Срок исполнения раньше даты регистрации')
    status = values.get('status') or cfg['statuses'][0]
    if status not in cfg['statuses']:
        raise ValueError('Неизвестный статус')
    number = str(values.get('reg_number') or '').strip()
    with db.transaction():
        seq = None
        if not number:
            seq, yy, number = next_number(db, register, values['reg_date'])
        else:
            yy = reg.year
        if db.fetchone('SELECT id FROM doc_register WHERE reg_number=? AND year_num=? AND register=? AND id<>?', (number, yy, register, did or 0)):
            raise ValueError(f'Номер {number} за {yy} год уже занят')
        row = (register, cfg['direction'], seq, yy, number, values['reg_date'], values.get('kind') or cfg['kinds'][0], str(values.get('doc_number') or '').strip(),
               values.get('doc_date') or '', party, values.get('client_id') or None, str(values['subject']).strip(), str(values.get('executor') or '').strip(), due, status,
               str(values.get('answer_ref') or '').strip(), str(values.get('file_path') or '').strip(), str(values.get('note') or '').strip())
        cols = 'register,direction,seq_num,year_num,reg_number,reg_date,kind,doc_number,doc_date,correspondent,client_id,subject,executor,due_date,status,answer_ref,file_path,note'
        if did:
            old = db.fetchone('SELECT seq_num FROM doc_register WHERE id=?', (did,))
            if seq is None and old:
                row = (*row[:2], old[0], *row[3:])
            db.execute('UPDATE doc_register SET ' + ','.join(f'{c}=?' for c in cols.split(',')) + ' WHERE id=?', (*row, did))
            return did
        return db.execute(f'INSERT INTO doc_register({cols}) VALUES({",".join("?" * 18)})', row).lastrowid


def get_doc(db, did):
    cur = db.execute('SELECT * FROM doc_register WHERE id=?', (did,))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def delete_doc(db, did):
    db.execute('DELETE FROM doc_register WHERE id=?', (did,))


def set_status(db, did, status):
    d = get_doc(db, did)
    if not d or status not in _cfg(d['register'])['statuses']:
        raise ValueError('Неизвестный статус')
    db.execute('UPDATE doc_register SET status=? WHERE id=?', (status, did))


def state(register, status, due_date, today=None):
    """'overdue' — срок прошёл (для «Прочих» — документ истёк), 'soon' — срок действия «Прочих» истекает в течение 30 дней, иначе ''."""
    d = _day(due_date)
    if not d or status not in _cfg(register)['open']:
        return ''
    today = today or date.today()
    if d < today:
        return 'overdue'
    if register == OTHER and d <= today + timedelta(days=WARN_DAYS):
        return 'soon'
    return ''


def listing(db, register, search='', status='', problems_only=False, limit=100, offset=0, today=None):
    """(всего, строки словарями) журнала; problems_only — только просроченные / истёкшие."""
    cfg = _cfg(register)
    where, params = ['d.register=?'], [register]
    if search:
        where.append("LOWER(coalesce(d.reg_number,'')||' '||coalesce(d.doc_number,'')||' '||coalesce(d.correspondent,'')||' '||coalesce(d.subject,'')||' '||coalesce(d.executor,'')||' '||coalesce(d.kind,'')) LIKE ?")
        params.append(f'%{search.casefold()}%')
    if status:
        where.append('d.status=?')
        params.append(status)
    if problems_only:
        marks = ','.join('?' for _ in cfg['open'])
        where.append(f"d.status IN ({marks}) AND coalesce(d.due_date,'')<>'' AND d.due_date<?")
        params += [*cfg['open'], (today or date.today()).isoformat()]
    cond = ' AND '.join(where)
    total = db.fetchone(f'SELECT count(*) FROM doc_register d WHERE {cond}', params)[0]
    cur = db.execute(f"""SELECT d.*,coalesce(c.name,'') AS client_name FROM doc_register d LEFT JOIN le_clients c ON c.id=d.client_id WHERE {cond}
        ORDER BY coalesce(d.year_num,0) DESC, coalesce(d.seq_num,0) DESC, d.id DESC LIMIT ? OFFSET ?""", (*params, limit, offset))
    rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
    for r in rows:
        r['state'] = state(register, r['status'], r['due_date'], today)
    return total, rows


def problems(db, register, today=None):
    return listing(db, register, problems_only=True, limit=1, today=today)[0]


def import_outgoing(db):
    """Прежний журнал исходящих юрлиц (le_outgoing) попадает в «Регистрацию исходящих»; повторный вызов добавляет только новые. Возвращает число добавленных."""
    if not db.fetchone("SELECT 1 FROM sqlite_master WHERE type='table' AND name='le_outgoing'"):
        return 0
    n = 0
    with db.transaction():
        for oid, number, day, recipient, subject, client_id, note in db.fetchall(
                "SELECT id,coalesce(reg_number,''),coalesce(reg_date,''),coalesce(recipient,''),coalesce(subject,''),client_id,coalesce(note,'') FROM le_outgoing ORDER BY id"):
            if db.fetchone('SELECT 1 FROM doc_register WHERE legacy_outgoing_id=?', (oid,)):
                continue
            day = day[:10] if _day(day) else date.today().isoformat()
            yy = _day(day).year
            if number.isdigit():
                seq = int(number)
                cand = f'{REGISTERS[OUT]["prefix"]}-{seq:02d}/{yy % 100:02d}'
                if db.fetchone("SELECT 1 FROM doc_register WHERE reg_number=? AND year_num=? AND register='out'", (cand, yy)):
                    seq, yy, cand = next_number(db, OUT, day)
            else:
                seq, yy, cand = next_number(db, OUT, day)
            db.execute('INSERT INTO doc_register(register,direction,seq_num,year_num,reg_number,reg_date,kind,correspondent,client_id,subject,note,status,legacy_outgoing_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (OUT, 'Исходящий', seq, yy, cand, day, 'Письмо', recipient or '—', client_id, subject or '—', note, 'Отправлен', oid))
            n += 1
    return n
