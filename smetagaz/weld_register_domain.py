"""Модуль «Сварщики»: журнал заявок, писем и протоколов механических испытаний. Протоколы действуют около месяца и каждый раз оформляются заново."""
from datetime import date, datetime, timedelta

ZAYAVKA, LETTER, PROTOCOL = 'Заявка', 'Письмо', 'Протокол механических испытаний'
KINDS = (ZAYAVKA, LETTER, PROTOCOL)
STATUSES = {ZAYAVKA: ('Подготовлена', 'Подана', 'Исполнена'), LETTER: ('Подготовлено', 'Отправлено', 'Получен ответ'), PROTOCOL: ('Действует', 'Заменён', 'Архив')}
WARN_DAYS = 7
ISO = '%Y-%m-%d'


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS weld_register(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, number TEXT DEFAULT '', doc_date TEXT NOT NULL, counterparty TEXT DEFAULT '',
        subject TEXT DEFAULT '', valid_to TEXT DEFAULT '', status TEXT NOT NULL, basis TEXT DEFAULT '', file_path TEXT DEFAULT '', note TEXT DEFAULT '',
        renews_id INTEGER REFERENCES weld_register(id) ON DELETE SET NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS weld_register_welders(reg_id INTEGER NOT NULL REFERENCES weld_register(id) ON DELETE CASCADE,
        welder_id INTEGER NOT NULL REFERENCES welders(id) ON DELETE CASCADE, PRIMARY KEY(reg_id,welder_id))""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_weld_register_date ON weld_register(doc_date)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_weld_register_valid ON weld_register(valid_to)')


def _day(value):
    try:
        return datetime.strptime(str(value or '')[:10], ISO).date()
    except ValueError:
        return None


def add_month(day):
    """Дата через месяц (31 января → 28/29 февраля): срок действия протокола по умолчанию."""
    y, m = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    d = day.day
    while True:
        try:
            return date(y, m, d)
        except ValueError:
            d -= 1


def save_item(db, values, welders=(), rid=None):
    kind = values.get('kind')
    if kind not in KINDS:
        raise ValueError('Выберите вид: заявка, письмо или протокол')
    if not _day(values.get('doc_date')):
        raise ValueError('Укажите дату документа')
    status = values.get('status') or STATUSES[kind][0]
    if status not in STATUSES[kind]:
        raise ValueError('Статус не подходит к этому виду документа')
    valid_to = values.get('valid_to') or ''
    if kind == PROTOCOL:
        if not valid_to:
            raise ValueError('Укажите, до какого числа действует протокол')
        if _day(valid_to) < _day(values['doc_date']):
            raise ValueError('Срок действия протокола раньше его даты')
    else:
        valid_to = ''
    number = str(values.get('number') or '').strip()
    year = values['doc_date'][:4]
    if number and db.fetchone('SELECT id FROM weld_register WHERE kind=? AND number=? AND substr(doc_date,1,4)=? AND id<>?', (kind, number, year, rid or 0)):
        raise ValueError(f'{kind} № {number} за {year} год уже зарегистрирован(а)')
    if not number and kind != PROTOCOL and not str(values.get('subject') or '').strip():
        raise ValueError('Введите номер или содержание документа')
    row = (kind, number, values['doc_date'], str(values.get('counterparty') or '').strip(), str(values.get('subject') or '').strip(), valid_to, status,
           str(values.get('basis') or '').strip(), str(values.get('file_path') or '').strip(), str(values.get('note') or '').strip())
    cols = 'kind,number,doc_date,counterparty,subject,valid_to,status,basis,file_path,note'
    with db.transaction():
        if rid:
            db.execute('UPDATE weld_register SET ' + ','.join(f'{c}=?' for c in cols.split(',')) + ' WHERE id=?', (*row, rid))
        else:
            rid = db.execute(f'INSERT INTO weld_register({cols}) VALUES({",".join("?" * 10)})', row).lastrowid
        db.execute('DELETE FROM weld_register_welders WHERE reg_id=?', (rid,))
        for w in dict.fromkeys(welders or ()):
            db.execute('INSERT INTO weld_register_welders(reg_id,welder_id) VALUES(?,?)', (rid, w))
    return rid


def get_item(db, rid):
    cur = db.execute('SELECT * FROM weld_register WHERE id=?', (rid,))
    row = cur.fetchone()
    if not row:
        return None
    d = dict(zip([c[0] for c in cur.description], row))
    d['welders'] = [r[0] for r in db.fetchall('SELECT welder_id FROM weld_register_welders WHERE reg_id=?', (rid,))]
    return d


def delete_item(db, rid):
    db.execute('DELETE FROM weld_register WHERE id=?', (rid,))


def set_status(db, rid, status):
    d = get_item(db, rid)
    if not d or status not in STATUSES[d['kind']]:
        raise ValueError('Статус не подходит к этому виду документа')
    db.execute('UPDATE weld_register SET status=? WHERE id=?', (status, rid))


def state(kind, status, valid_to, today=None):
    """Для протокола: 'expired' (срок истёк), 'soon' (истекает в течение 7 дней), иначе ''. Для заявок и писем всегда ''."""
    if kind != PROTOCOL or status != 'Действует':
        return ''
    d = _day(valid_to)
    if not d:
        return ''
    today = today or date.today()
    if d < today:
        return 'expired'
    return 'soon' if d <= today + timedelta(days=WARN_DAYS) else ''


def renew_protocol(db, rid, day=None):
    """Протокол оформляется заново: копия на месяц от новой даты (сварщики те же), прежний получает статус «Заменён». Номер и файл нового вводятся вручную."""
    old = get_item(db, rid)
    if not old or old['kind'] != PROTOCOL:
        raise ValueError('Продлевается только протокол механических испытаний')
    day = day or date.today()
    with db.transaction():
        new = save_item(db, dict(kind=PROTOCOL, number='', doc_date=day.strftime(ISO), counterparty=old['counterparty'], subject=old['subject'], valid_to=add_month(day).strftime(ISO),
                                 status='Действует', basis=old['basis'], note=old['note']), old['welders'])
        db.execute('UPDATE weld_register SET renews_id=? WHERE id=?', (rid, new))
        db.execute("UPDATE weld_register SET status='Заменён' WHERE id=?", (rid,))
    return new


def listing(db, kind='', search='', status='', active_only=False, limit=100, offset=0, today=None):
    where, params = ['1=1'], []
    if kind:
        where.append('r.kind=?')
        params.append(kind)
    if status:
        where.append('r.status=?')
        params.append(status)
    if search:
        where.append("LOWER(coalesce(r.number,'')||' '||coalesce(r.counterparty,'')||' '||coalesce(r.subject,'')||' '||coalesce(r.basis,'')||' '||coalesce(r.note,'')||' '||"
                     "coalesce((SELECT group_concat(w.name,' ') FROM weld_register_welders x JOIN welders w ON w.id=x.welder_id WHERE x.reg_id=r.id),'')) LIKE ?")
        params.append(f'%{search.casefold()}%')
    if active_only:
        where.append("r.kind=? AND r.status='Действует' AND coalesce(r.valid_to,'')>=?")
        params += [PROTOCOL, (today or date.today()).isoformat()]
    cond = ' AND '.join(where)
    total = db.fetchone(f'SELECT count(*) FROM weld_register r WHERE {cond}', params)[0]
    cur = db.execute(f"""SELECT r.*,coalesce((SELECT group_concat(w.name,', ') FROM weld_register_welders x JOIN welders w ON w.id=x.welder_id WHERE x.reg_id=r.id),'') AS welder_names
        FROM weld_register r WHERE {cond} ORDER BY r.doc_date DESC, r.id DESC LIMIT ? OFFSET ?""", (*params, limit, offset))
    rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
    for r in rows:
        r['state'] = state(r['kind'], r['status'], r['valid_to'], today)
    return total, rows


def summary(db, today=None):
    """(действующих протоколов, истекает в течение 7 дней, истёкших, но не заменённых)."""
    today = today or date.today()
    rows = db.fetchall("SELECT valid_to FROM weld_register WHERE kind=? AND status='Действует'", (PROTOCOL,))
    states = [state(PROTOCOL, 'Действует', v, today) for (v,) in rows]
    return sum(1 for s in states if s != 'expired'), states.count('soon'), states.count('expired')


def welder_protocols(db, welder_id, today=None):
    """Действующие протоколы, в которые включён сварщик (для проверки допуска к работам)."""
    today = (today or date.today()).isoformat()
    return db.fetchall("SELECT r.id,r.number,r.valid_to FROM weld_register r JOIN weld_register_welders x ON x.reg_id=r.id WHERE x.welder_id=? AND r.kind=? AND r.status='Действует' AND r.valid_to>=? ORDER BY r.valid_to DESC",
                       (welder_id, PROTOCOL, today))


def agenda_events(db, start, end, today=None):
    """События календаря: окончание срока действия протоколов. [(дата, вид, заголовок, подробности, ссылка)]."""
    today = today or date.today()
    out = []
    for rid, number, valid_to, subject in db.fetchall("SELECT id,number,valid_to,subject FROM weld_register WHERE kind=? AND status='Действует' AND coalesce(valid_to,'')<>''", (PROTOCOL,)):
        d = _day(valid_to)
        if d and start <= d <= end:
            title = ('Протокол испытаний истёк' if d < today else 'Истекает протокол испытаний') + (f' № {number}' if number else '')
            out.append((d, 'permit', title, subject or 'Нужно оформить новый протокол', ('weld_register', rid)))
    return out


def move_from_outgoing(db, doc_ids, kind, remove=True):
    """Переносит записи из «Регистрации исходящих» (модуль «Документы») в этот журнал; remove — удалить их из исходящих. Возвращает число перенесённых."""
    if kind not in KINDS:
        raise ValueError('Выберите вид документа')
    n = 0
    with db.transaction():
        for did in doc_ids:
            d = db.fetchone("SELECT reg_number,reg_date,correspondent,subject,due_date,file_path,note,answer_ref FROM doc_register WHERE id=? AND register='out'", (did,))
            if not d:
                continue
            number, day, party, subject, due, path, note, answer = d
            valid = due if kind == PROTOCOL and due else (add_month(_day(day)).strftime(ISO) if kind == PROTOCOL else '')
            exists = number and db.fetchone('SELECT id FROM weld_register WHERE kind=? AND number=? AND substr(doc_date,1,4)=?', (kind, number, day[:4]))
            save_item(db, dict(kind=kind, number='' if exists else number, doc_date=day, counterparty=party, subject=subject, valid_to=valid, file_path=path,
                               note=' · '.join(x for x in (note, 'Перенесено из исходящих' + (f' (№ {number})' if exists else '')) if x)))
            if remove:
                db.execute('DELETE FROM doc_register WHERE id=?', (did,))
            n += 1
    return n
