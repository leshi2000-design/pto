"""Сотрудники и бригады: допуски и удостоверения со сроками, бригады, назначения на объекты и график занятости.
Сварщики остаются в своём модуле; здесь они отражаются как сотрудники (по ссылке), а срок их удостоверения учитывается в общем списке сроков."""
from datetime import date, datetime, timedelta

ROLES = ['Монтажник', 'Сварщик', 'Мастер / бригадир', 'Инженер ПТО', 'Водитель', 'Прочее']
DOC_KINDS = ['Удостоверение', 'Аттестат', 'Допуск к работам', 'Охрана труда', 'Медосмотр', 'Другое']
OWNERS = {'contracts': 'Монтаж ГСВ', 'gsn_projects': 'Монтаж ГСН', 'gsv_projects': 'Проекты ГСВ'}
WARN_DAYS = 30
ISO = '%Y-%m-%d'


def migrate(db):
    for sql in (
        """CREATE TABLE IF NOT EXISTS staff(id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT DEFAULT 'Монтажник', position TEXT DEFAULT '', phone TEXT DEFAULT '',
             birth_date TEXT DEFAULT '', hired_date TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1, welder_id INTEGER UNIQUE REFERENCES welders(id) ON DELETE SET NULL, note TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS staff_docs(id INTEGER PRIMARY KEY, staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE, kind TEXT DEFAULT 'Удостоверение',
             title TEXT NOT NULL, number TEXT DEFAULT '', issued_by TEXT DEFAULT '', issue_date TEXT DEFAULT '', valid_to TEXT DEFAULT '', file_path TEXT DEFAULT '', note TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS crews(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, leader_id INTEGER REFERENCES staff(id) ON DELETE SET NULL, active INTEGER NOT NULL DEFAULT 1, note TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS crew_members(crew_id INTEGER NOT NULL REFERENCES crews(id) ON DELETE CASCADE, staff_id INTEGER NOT NULL REFERENCES staff(id) ON DELETE CASCADE, PRIMARY KEY(crew_id,staff_id))""",
        """CREATE TABLE IF NOT EXISTS staff_assign(id INTEGER PRIMARY KEY, staff_id INTEGER REFERENCES staff(id) ON DELETE CASCADE, crew_id INTEGER REFERENCES crews(id) ON DELETE CASCADE,
             owner_type TEXT DEFAULT '', owner_id INTEGER, object_text TEXT DEFAULT '', start_date TEXT NOT NULL, end_date TEXT NOT NULL, note TEXT DEFAULT '',
             CHECK((staff_id IS NULL)<>(crew_id IS NULL)))""",
        'CREATE INDEX IF NOT EXISTS idx_staff_docs_valid ON staff_docs(valid_to)',
        'CREATE INDEX IF NOT EXISTS idx_staff_assign_dates ON staff_assign(start_date,end_date)',
    ):
        db.execute(sql)


def _day(value):
    try:
        return datetime.strptime(str(value or '')[:10], ISO).date()
    except ValueError:
        return None


# --- СОТРУДНИКИ -------------------------------------------------------------------------------

def sync_welders(db):
    """Каждый сварщик из модуля «Сварщики» получает карточку сотрудника (роль «Сварщик»); имя и телефон подтягиваются; возвращает число новых."""
    added = 0
    with db.transaction():
        for wid, name, phone in db.fetchall("SELECT id,name,coalesce(phone,'') FROM welders"):
            row = db.fetchone('SELECT id FROM staff WHERE welder_id=?', (wid,))
            if row:
                db.execute('UPDATE staff SET name=?,phone=? WHERE id=?', (name, phone, row[0]))
            else:
                db.execute("INSERT INTO staff(name,role,phone,welder_id) VALUES(?,?,?,?)", (name, 'Сварщик', phone, wid))
                added += 1
    return added


def save_staff(db, values, sid=None):
    name = str(values.get('name', '')).strip()
    if not name:
        raise ValueError('Укажите ФИО сотрудника')
    cols = ('name', 'role', 'position', 'phone', 'birth_date', 'hired_date', 'active', 'note')
    data = [name if c == 'name' else (int(bool(values.get(c, 1))) if c == 'active' else values.get(c, '') or '') for c in cols]
    if sid:
        db.execute('UPDATE staff SET ' + ','.join(f'{c}=?' for c in cols) + ' WHERE id=?', (*data, sid))
        return sid
    return db.execute('INSERT INTO staff(' + ','.join(cols) + ') VALUES(' + ','.join('?' for _ in cols) + ')', data).lastrowid


def delete_staff(db, sid):
    with db.transaction():
        db.execute('UPDATE crews SET leader_id=NULL WHERE leader_id=?', (sid,))
        db.execute('DELETE FROM staff WHERE id=?', (sid,))


def get_staff(db, sid):
    cur = db.execute('SELECT * FROM staff WHERE id=?', (sid,))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def staff_list(db, active_only=False, search=''):
    q = f'%{search.casefold()}%'
    return db.fetchall(f"""SELECT s.id,s.name,s.role,s.position,s.phone,s.active,
        coalesce((SELECT group_concat(c.name,', ') FROM crew_members m JOIN crews c ON c.id=m.crew_id WHERE m.staff_id=s.id),'') FROM staff s
        WHERE (?=0 OR s.active=1) AND LOWER(s.name||' '||coalesce(s.position,'')||' '||coalesce(s.phone,'')) LIKE ? ORDER BY s.active DESC, s.name""", (int(active_only), q))


# --- ДОПУСКИ И УДОСТОВЕРЕНИЯ ----------------------------------------------------------------------

def save_doc(db, staff_id, values, did=None):
    title = str(values.get('title', '')).strip()
    if not title:
        raise ValueError('Укажите название документа')
    cols = ('kind', 'title', 'number', 'issued_by', 'issue_date', 'valid_to', 'file_path', 'note')
    data = [values.get(c, '') or '' for c in cols]
    data[1] = title
    if did:
        db.execute('UPDATE staff_docs SET ' + ','.join(f'{c}=?' for c in cols) + ' WHERE id=? AND staff_id=?', (*data, did, staff_id))
        return did
    return db.execute('INSERT INTO staff_docs(staff_id,' + ','.join(cols) + ') VALUES(?,' + ','.join('?' for _ in cols) + ')', (staff_id, *data)).lastrowid


def delete_doc(db, did):
    db.execute('DELETE FROM staff_docs WHERE id=?', (did,))


def docs(db, sid):
    return db.fetchall('SELECT id,kind,title,number,issued_by,issue_date,valid_to,file_path,note FROM staff_docs WHERE staff_id=? ORDER BY coalesce(nullif(valid_to,\'\'),\'9999\'),id', (sid,))


def doc_state(valid_to, today=None, warn=WARN_DAYS):
    """('expired'|'soon'|'ok'|'none', дней до окончания)."""
    d = _day(valid_to)
    if not d:
        return 'none', None
    left = (d - (today or date.today())).days
    return ('expired' if left < 0 else 'soon' if left <= warn else 'ok'), left


def all_deadlines(db, today=None, warn=WARN_DAYS):
    """Все документы со сроком, включая удостоверения сварщиков из модуля «Сварщики»:
    [{'staff_id','staff','doc_id','kind','title','number','valid_to','state','left','source'}], ближайшие сроки первыми."""
    today = today or date.today()
    out = []
    for sid, name, did, kind, title, number, valid in db.fetchall(
            "SELECT s.id,s.name,d.id,d.kind,d.title,d.number,d.valid_to FROM staff_docs d JOIN staff s ON s.id=d.staff_id WHERE s.active=1 AND coalesce(d.valid_to,'')<>''"):
        state, left = doc_state(valid, today, warn)
        out.append(dict(staff_id=sid, staff=name, doc_id=did, kind=kind, title=title, number=number, valid_to=valid, state=state, left=left, source='staff'))
    for sid, name, wid, valid, grade in db.fetchall(
            "SELECT s.id,s.name,w.id,w.valid_until,coalesce(w.grade,'') FROM staff s JOIN welders w ON w.id=s.welder_id WHERE s.active=1 AND coalesce(w.valid_until,'')<>''"):
        state, left = doc_state(valid, today, warn)
        out.append(dict(staff_id=sid, staff=name, doc_id=None, kind='Удостоверение сварщика', title='Удостоверение сварщика' + (f' ({grade})' if grade else ''), number='', valid_to=valid, state=state, left=left, source='welder'))
    out.sort(key=lambda r: (r['valid_to'], r['staff']))
    return out


def expired_for(db, sid, on_date=None):
    """Просроченные на дату документы сотрудника (названия)."""
    on = on_date or date.today()
    return [r['title'] for r in all_deadlines(db, on) if r['staff_id'] == sid and r['state'] == 'expired']


# --- БРИГАДЫ ----------------------------------------------------------------------------------

def save_crew(db, name, leader_id=None, members=(), cid=None, note='', active=True):
    name = str(name or '').strip()
    if not name:
        raise ValueError('Укажите название бригады')
    dup = db.fetchone('SELECT id FROM crews WHERE LOWER(name)=LOWER(?) AND id<>?', (name, cid or 0))
    if dup:
        raise ValueError('Бригада с таким названием уже есть')
    with db.transaction():
        if cid:
            db.execute('UPDATE crews SET name=?,leader_id=?,note=?,active=? WHERE id=?', (name, leader_id, note, int(active), cid))
        else:
            cid = db.execute('INSERT INTO crews(name,leader_id,note,active) VALUES(?,?,?,?)', (name, leader_id, note, int(active))).lastrowid
        db.execute('DELETE FROM crew_members WHERE crew_id=?', (cid,))
        for m in dict.fromkeys(list(members) + ([leader_id] if leader_id else [])):
            db.execute('INSERT INTO crew_members(crew_id,staff_id) VALUES(?,?)', (cid, m))
    return cid


def delete_crew(db, cid):
    db.execute('DELETE FROM crews WHERE id=?', (cid,))


def crews(db, active_only=False):
    return db.fetchall("""SELECT c.id,c.name,coalesce(s.name,''),c.active,(SELECT count(*) FROM crew_members m WHERE m.crew_id=c.id),c.leader_id,c.note FROM crews c LEFT JOIN staff s ON s.id=c.leader_id
        WHERE (?=0 OR c.active=1) ORDER BY c.active DESC,c.name""", (int(active_only),))


def crew_members(db, cid):
    return [r[0] for r in db.fetchall('SELECT staff_id FROM crew_members WHERE crew_id=?', (cid,))]


# --- НАЗНАЧЕНИЯ И ГРАФИК ---------------------------------------------------------------------

def object_label(db, owner_type, owner_id, text=''):
    if not owner_type or not owner_id:
        return text or ''
    if owner_type == 'gsn_projects':
        r = db.fetchone("SELECT coalesce(contract_number,''),coalesce(title,''),coalesce(client_name,'') FROM gsn_projects WHERE id=?", (owner_id,))
    elif owner_type == 'contracts':
        r = db.fetchone("SELECT coalesce(contract_number,''),coalesce(object_name,''),coalesce(nullif(client_name,''),party_name,'') FROM contracts WHERE id=?", (owner_id,))
    elif owner_type == 'gsv_projects':
        r = db.fetchone("SELECT coalesce(pd_number,''),coalesce(object_name,''),coalesce(nullif(client_name,''),party_name,'') FROM gsv_projects WHERE id=?", (owner_id,))
    else:
        return text or ''
    if not r:
        return text or '(объект удалён)'
    return ' · '.join(x for x in (OWNERS[owner_type], r[0], r[1] or r[2]) if x)


def objects(db, search=''):
    """Объекты для выбора: [(owner_type, id, подпись)], свежие сверху."""
    q = f'%{search.casefold()}%'
    out = []
    for table in OWNERS:
        for (rid,) in db.fetchall(f'SELECT id FROM {table} ORDER BY id DESC LIMIT 300'):
            label = object_label(db, table, rid)
            if not search or q.strip('%') in label.casefold():
                out.append((table, rid, label))
    return out


def members_of(db, staff_id, crew_id):
    return [staff_id] if staff_id else crew_members(db, crew_id)


def conflicts(db, staff_id, crew_id, start, end, exclude=None):
    """Пересечения по датам: [(сотрудник, объект, c, по)] — кто из выбранных уже назначен на другие объекты в этот период."""
    mine = set(members_of(db, staff_id, crew_id))
    found = []
    for aid, sid, cid, otype, oid, text, s, e in db.fetchall(
            'SELECT id,staff_id,crew_id,owner_type,owner_id,object_text,start_date,end_date FROM staff_assign WHERE start_date<=? AND end_date>=? AND id<>?', (end, start, exclude or 0)):
        for m in set(members_of(db, sid, cid)) & mine:
            found.append((db.fetchone('SELECT name FROM staff WHERE id=?', (m,))[0], object_label(db, otype, oid, text), s, e))
    return found


def add_assignment(db, start, end, staff_id=None, crew_id=None, owner_type='', owner_id=None, object_text='', note='', aid=None):
    if bool(staff_id) == bool(crew_id):
        raise ValueError('Выберите сотрудника или бригаду')
    s, e = _day(start), _day(end)
    if not s or not e:
        raise ValueError('Укажите даты работы')
    if e < s:
        raise ValueError('Дата окончания раньше даты начала')
    if not (owner_type and owner_id) and not str(object_text).strip():
        raise ValueError('Выберите объект или впишите его название')
    args = (staff_id, crew_id, owner_type or '', owner_id, str(object_text).strip(), s.strftime(ISO), e.strftime(ISO), note or '')
    if aid:
        db.execute('UPDATE staff_assign SET staff_id=?,crew_id=?,owner_type=?,owner_id=?,object_text=?,start_date=?,end_date=?,note=? WHERE id=?', (*args, aid))
        return aid
    return db.execute('INSERT INTO staff_assign(staff_id,crew_id,owner_type,owner_id,object_text,start_date,end_date,note) VALUES(?,?,?,?,?,?,?,?)', args).lastrowid


def delete_assignment(db, aid):
    db.execute('DELETE FROM staff_assign WHERE id=?', (aid,))


def assignments(db, owner_type='', owner_id=None, search=''):
    rows = db.fetchall("""SELECT a.id,a.start_date,a.end_date,coalesce(s.name,''),coalesce(c.name,''),a.owner_type,a.owner_id,a.object_text,a.note,a.staff_id,a.crew_id
        FROM staff_assign a LEFT JOIN staff s ON s.id=a.staff_id LEFT JOIN crews c ON c.id=a.crew_id
        WHERE (?='' OR (a.owner_type=? AND a.owner_id=?)) ORDER BY a.start_date DESC,a.id DESC""", (owner_type or '', owner_type or '', owner_id))
    out = [dict(id=r[0], start=r[1], end=r[2], staff=r[3], crew=r[4], who=r[3] or f'Бригада «{r[4]}»', owner_type=r[5], owner_id=r[6], object=object_label(db, r[5], r[6], r[7]), note=r[8], staff_id=r[9], crew_id=r[10]) for r in rows]
    if search:
        needle = search.casefold()
        out = [r for r in out if needle in f'{r["who"]} {r["object"]} {r["note"]}'.casefold()]
    return out


def schedule(db, start, end):
    """График занятости за период: {id сотрудника: {день ISO: [подписи объектов]}} и словарь имён."""
    s, e = start.strftime(ISO), end.strftime(ISO)
    grid, names = {}, {}
    for aid, sid, cid, otype, oid, text, a, b in db.fetchall('SELECT id,staff_id,crew_id,owner_type,owner_id,object_text,start_date,end_date FROM staff_assign WHERE start_date<=? AND end_date>=?', (e, s)):
        label = object_label(db, otype, oid, text)
        d1, d2 = max(_day(a), start), min(_day(b), end)
        for m in members_of(db, sid, cid):
            names.setdefault(m, db.fetchone('SELECT name FROM staff WHERE id=?', (m,))[0])
            day = d1
            while day <= d2:
                grid.setdefault(m, {}).setdefault(day.strftime(ISO), []).append(label)
                day += timedelta(days=1)
    return grid, names


def object_team(db, owner_type, owner_id, on_date=None):
    """Кто назначен на объект на дату (по умолчанию — сегодня) с предупреждениями о просроченных допусках: [(имя, [просроченные документы])]."""
    on = on_date or date.today()
    iso = on.strftime(ISO)
    ids = []
    for sid, cid in db.fetchall('SELECT staff_id,crew_id FROM staff_assign WHERE owner_type=? AND owner_id=? AND start_date<=? AND end_date>=?', (owner_type, owner_id, iso, iso)):
        ids += members_of(db, sid, cid)
    return [(db.fetchone('SELECT name FROM staff WHERE id=?', (m,))[0], expired_for(db, m, on)) for m in dict.fromkeys(ids)]


def agenda_events(db, start, end, today=None):
    """События для календаря: окончание допусков и выход на объект. [(дата, вид, заголовок, подробности, ссылка)]."""
    today = today or date.today()
    out = []
    for r in all_deadlines(db, today):
        d = _day(r['valid_to'])
        if d and start <= d <= end:
            title = ('Допуск истёк: ' if r['state'] == 'expired' else 'Истекает допуск: ') + r['staff']
            out.append((d, 'permit', title, f'{r["title"]}' + (f' № {r["number"]}' if r['number'] else ''), ('staff', r['staff_id'])))
    s, e = start.strftime(ISO), end.strftime(ISO)
    for aid, sname, cname, otype, oid, text, a in db.fetchall(
            "SELECT a.id,coalesce(s.name,''),coalesce(c.name,''),a.owner_type,a.owner_id,a.object_text,a.start_date FROM staff_assign a LEFT JOIN staff s ON s.id=a.staff_id LEFT JOIN crews c ON c.id=a.crew_id WHERE a.start_date BETWEEN ? AND ?", (s, e)):
        out.append((_day(a), 'crew', f'На объект: {sname or "бригада «" + cname + "»"}', object_label(db, otype, oid, text), ('staff_assign', aid)))
    return out
