"""Модуль «Монтаж ГСН»: данные карточки договора, смета, трубопроводы и врезка, материалы, сертификаты и аттестаты. Не зависит от Qt.

Модуль самостоятелен: общим с остальными разделами у него только «Клиенты» и «Сметы». Свой справочник сертификатов (Справочник ГСН), свои теги и документы.
Юрлица заказчиками в «Монтаже ГСН» быть не могут — заказчик всегда клиент-физлицо из раздела «Клиенты»."""
import os
import re
from datetime import date, datetime, timedelta

from . import gsv_project_domain as gd
from .agenda_domain import short_name

DEFAULT_END_DAYS = 60
ROLES = {'pe_pipe': 'ПЭ труба', 'steel_pipe': 'Стальная труба', 'transition': 'Неразъёмное соединение ПЭ/сталь', 'plug': 'Заглушка', 'coupling': 'Муфта'}
PRESSURES = {'low': 'Низкое давление', 'medium': 'Среднее давление'}
PRESSURE_TEXT = {'low': 'низкого давления', 'medium': 'среднего давления'}
TIE_INS = {'steel': 'В сталь', 'pe': 'В ПЭ'}
TIE_TEXT = {'steel': 'в стальной газопровод', 'pe': 'в полиэтиленовый газопровод'}
ATTEST_MODES = {'always': 'Для всех объектов ГСН', 'steel': 'Только при врезке в сталь', 'pe': 'Только при врезке в ПЭ'}
PE_DIAMETER, STEEL_DIAMETER = '32 ПЭ', '25 сталь'

CARD_COLUMNS = (('designer_code', "TEXT DEFAULT ''"), ('designer', "TEXT DEFAULT ''"), ('project_month', "TEXT DEFAULT ''"), ('tu_text', "TEXT DEFAULT ''"),
                ('contract_signed', 'INTEGER DEFAULT 0'), ('work_start_date', "TEXT DEFAULT ''"), ('work_end_date', "TEXT DEFAULT ''"),
                ('client_address', "TEXT DEFAULT ''"), ('passport_issuer', "TEXT DEFAULT ''"), ('passport_issue_date', "TEXT DEFAULT ''"),
                ('est_materials', 'REAL DEFAULT 0'), ('est_works', 'REAL DEFAULT 0'), ('est_rev_synced', 'INTEGER DEFAULT 0'), ('est_synced_at', "TEXT DEFAULT ''"),
                ('contract_folder', "TEXT DEFAULT ''"), ('pe_length', 'REAL DEFAULT 0'), ('steel_length', 'REAL DEFAULT 0'), ('steel_under_length', 'REAL DEFAULT 0'), ('steel_above_length', 'REAL DEFAULT 0'), ('pressure_type', "TEXT DEFAULT ''"),
                ('tie_in', "TEXT DEFAULT ''"), ('couplings', 'INTEGER DEFAULT 0'))


def migrate(db):
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(gsn_projects)')}
    for name, ddl in CARD_COLUMNS:
        if name not in cols:
            db.execute(f'ALTER TABLE gsn_projects ADD COLUMN {name} {ddl}')
    if 'role' not in {r[1] for r in db.fetchall('PRAGMA table_info(gsn_items)')}:
        db.execute("ALTER TABLE gsn_items ADD COLUMN role TEXT DEFAULT ''")
    for sql in (
        """CREATE TABLE IF NOT EXISTS gsn_docs(contract_id INTEGER NOT NULL REFERENCES gsn_projects(id) ON DELETE CASCADE, kind TEXT NOT NULL, file_path TEXT NOT NULL,
             data_hash TEXT NOT NULL DEFAULT '', generated_at TEXT NOT NULL DEFAULT '', linked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(contract_id,kind))""",
        """CREATE TABLE IF NOT EXISTS gsn_tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, source TEXT NOT NULL, fmt TEXT NOT NULL DEFAULT 'text',
             empty_text TEXT DEFAULT '', auto_key TEXT UNIQUE, enabled INTEGER NOT NULL DEFAULT 1, note TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS gsn_contract_items(contract_id INTEGER NOT NULL REFERENCES gsn_projects(id) ON DELETE CASCADE, role TEXT NOT NULL,
             item_id INTEGER REFERENCES gsn_items(id) ON DELETE SET NULL, PRIMARY KEY(contract_id,role))""",
        """CREATE TABLE IF NOT EXISTS gsn_attest_rules(document_id INTEGER PRIMARY KEY REFERENCES welding_documents(id) ON DELETE CASCADE,
             mode TEXT NOT NULL CHECK(mode IN ('always','steel','pe')))""",
    ):
        db.execute(sql)
    # прежняя протяжённость стали считалась подземной
    db.execute('UPDATE gsn_projects SET steel_under_length=steel_length WHERE coalesce(steel_under_length,0)=0 AND coalesce(steel_above_length,0)=0 AND coalesce(steel_length,0)>0')
    # для уже существующих договоров стартовые значения сроков и «подписан»
    db.execute("UPDATE gsn_projects SET work_start_date=contract_date WHERE coalesce(work_start_date,'')='' AND coalesce(contract_date,'')<>''")


# --- НОМЕР, ПАПКА ----------------------------------------------------------------------------

def folder_name(number, address='', client=''):
    """«101.03.26, адрес объекта (Фамилия И.О.)»: в номере «/» заменяется на «.»."""
    name = str(number or '').strip().replace('/', '.')
    if str(address or '').strip():
        name += f', {" ".join(str(address).split())[:90]}'
    if str(client or '').strip():
        name += f' ({short_name(client)})'
    return gd.safe_name(name)


def contract_folder(db, cid):
    row = db.fetchone('SELECT contract_folder FROM gsn_projects WHERE id=?', (cid,))
    return row[0] if row and row[0] and os.path.isdir(row[0]) else ''


def link_folder(db, cid, path, create=False):
    path = str(path)
    if create:
        os.makedirs(path, exist_ok=True)
    if not os.path.isdir(path):
        raise ValueError('Папка не найдена: ' + path)
    db.execute('UPDATE gsn_projects SET contract_folder=? WHERE id=?', (path, cid))
    return path


def suggested_folder_name(db, cid):
    row = db.fetchone("SELECT contract_number,address,title,client_name FROM gsn_projects WHERE id=?", (cid,))
    if not row:
        raise ValueError('Сначала сохраните договор')
    return folder_name(row[0], row[1] or row[2], row[3])


def default_end(contract_date):
    day = gd._parse(contract_date)
    return day + timedelta(days=DEFAULT_END_DAYS) if day else None


# --- ДОГОВОР ---------------------------------------------------------------------------------

def get(db, cid):
    cur = db.execute('SELECT * FROM gsn_projects WHERE id=?', (cid,))
    row = cur.fetchone()
    if not row:
        raise ValueError('Договор ГСН не найден')
    return dict(zip([c[0] for c in cur.description], row))


def validate(v):
    if not str(v.get('title') or '').strip():
        raise ValueError('Укажите наименование объекта (согласно названию проекта и технических условий)')
    start, end = str(v.get('work_start_date') or ''), str(v.get('work_end_date') or '')
    if start and end and end < start:
        raise ValueError('Окончание работ раньше начала работ')
    for key, label in (('pe_length', 'ПЭ'), ('steel_length', 'стального'), ('steel_under_length', 'подземного стального'), ('steel_above_length', 'надземного стального')):
        if float(v.get(key) or 0) < 0:
            raise ValueError(f'Протяжённость {label} трубопровода не может быть отрицательной')
    if int(v.get('couplings') or 0) < 0:
        raise ValueError('Количество муфт не может быть отрицательным')
    if v.get('tie_in') not in ('', None, *TIE_INS):
        raise ValueError('Неизвестный тип врезки')
    if v.get('pressure_type') not in ('', None, *PRESSURES):
        raise ValueError('Неизвестный тип газопровода')


FIELDS = ('contract_number', 'contract_date', 'title', 'address', 'notes', 'designer_code', 'designer', 'project_month', 'tu_text', 'contract_signed', 'work_start_date',
          'work_end_date', 'act_date', 'act_signed', 'contract_amount', 'pe_length', 'steel_length', 'steel_under_length', 'steel_above_length', 'pressure_type', 'tie_in', 'couplings')


def save_card(db, values, client, client_id=None, cid=None, items=None):
    """Сохраняет договор, клиента (общий раздел «Клиенты») и выбранные позиции справочника. Возвращает (id договора, id клиента).
    values — поля договора (FIELDS); client — dict с ФИО, телефонами, адресом, паспортом (как в «Клиентах»)."""
    from .gsv_domain import save_client
    values = dict(values)
    values.setdefault('work_start_date', values.get('contract_date') or '')
    validate(values)
    with db.transaction():
        client_id = save_client(db, client, client_id)
        snap = dict(client_id=client_id, client_name=client.get('name', '').strip(), phone=client.get('phone', ''), passport=client.get('passport', ''),
                    client_address=client.get('address', ''), passport_issuer=client.get('passport_issuer', ''), passport_issue_date=client.get('passport_date', ''))
        row = {k: values.get(k) for k in FIELDS if k in values}
        row.update(snap)
        for key in ('contract_signed', 'act_signed', 'couplings'):
            if key in row:
                row[key] = int(row[key] or 0)
        for key in ('contract_amount', 'pe_length', 'steel_length', 'steel_under_length', 'steel_above_length'):
            if key in row:
                row[key] = float(row[key] or 0)
        if 'steel_under_length' in row or 'steel_above_length' in row:
            row['steel_length'] = float(row.get('steel_under_length') or 0) + float(row.get('steel_above_length') or 0)
        if cid:
            db.execute('UPDATE gsn_projects SET ' + ','.join(f'{k}=?' for k in row) + ' WHERE id=?', (*row.values(), cid))
        else:
            cid = db.execute('INSERT INTO gsn_projects(' + ','.join(row) + ') VALUES(' + ','.join('?' for _ in row) + ')', tuple(row.values())).lastrowid
        if items is not None:
            set_chosen_items(db, cid, items)
    return cid, client_id


# --- СМЕТА -----------------------------------------------------------------------------------

def estimate_summary(db, eid):
    if not eid:
        return None
    row = db.fetchone('SELECT title,total FROM estimates WHERE id=?', (eid,))
    if not row:
        return None
    sums = dict(db.fetchall("SELECT item_type,coalesce(sum(sum),0) FROM estimate_items WHERE estimate_id=? GROUP BY item_type", (eid,)))
    return dict(title=row[0] or '', total=float(row[1] or 0), materials=float(sums.get('Материал', 0)), works=float(sums.get('Работа', 0)))


def last_change(db, eid):
    return db.fetchone('SELECT coalesce(max(id),0) FROM estimate_changes WHERE estimate_id=?', (eid,))[0] if eid else 0


def estimate_state(db, cid):
    """'none' — смета не привязана, 'unsynced' — данные ещё не получены, 'stale' — смета изменена, 'fresh' — данные актуальны."""
    row = db.fetchone('SELECT estimate_id,est_rev_synced,est_synced_at FROM gsn_projects WHERE id=?', (cid,))
    if not row or not row[0]:
        return 'none'
    if not row[2]:
        return 'unsynced'
    return 'stale' if last_change(db, row[0]) > (row[1] or 0) else 'fresh'


def sync_estimate(db, cid):
    """«Получить стоимость из сметы»: фиксирует стоимость материалов и работ и ставит итог сметы стоимостью работ договора."""
    row = db.fetchone('SELECT estimate_id FROM gsn_projects WHERE id=?', (cid,))
    if not row or not row[0]:
        raise ValueError('К договору не привязана смета')
    s = estimate_summary(db, row[0])
    if not s:
        raise ValueError('Смета не найдена')
    db.execute('UPDATE gsn_projects SET contract_amount=?, est_materials=?, est_works=?, est_rev_synced=?, est_synced_at=? WHERE id=?',
               (round(s['total'], 2), round(s['materials'], 2), round(s['works'], 2), last_change(db, row[0]), datetime.now().isoformat(timespec='seconds'), cid))
    return s


def estimate_history(db, eid, limit=500):
    return db.fetchall('SELECT changed_at,action,item_name,detail FROM estimate_changes WHERE estimate_id=? ORDER BY id DESC LIMIT ?', (eid, limit))


def link_estimate(db, cid, eid):
    from . import payments_domain
    payments_domain.link(db, 'gsn_projects', cid, eid)
    db.execute("UPDATE gsn_projects SET est_synced_at='', est_rev_synced=0 WHERE id=?", (cid,))


# --- ПОЗИЦИИ СПРАВОЧНИКА ПО РОЛЯМ, МАТЕРИАЛЫ ---------------------------------------------------

def role_items(db, role):
    """Позиции Справочника ГСН с этой ролью: [(id, название)]."""
    return db.fetchall("SELECT id,name FROM gsn_items WHERE role=? AND coalesce(active,1)=1 ORDER BY name,id", (role,))


def chosen_items(db, cid):
    """{роль: id позиции}: выбранное в карточке или первая позиция справочника с этой ролью."""
    explicit = dict(db.fetchall('SELECT role,item_id FROM gsn_contract_items WHERE contract_id=?', (cid,))) if cid else {}
    result = {}
    for role in ROLES:
        ids = [i for i, _n in role_items(db, role)]
        pick = explicit.get(role)
        result[role] = pick if pick in ids else (ids[0] if ids else None)
    return result


def set_chosen_items(db, cid, items):
    db.execute('DELETE FROM gsn_contract_items WHERE contract_id=?', (cid,))
    for role, item_id in (items or {}).items():
        if role in ROLES and item_id:
            db.execute('INSERT INTO gsn_contract_items(contract_id,role,item_id) VALUES(?,?,?)', (cid, role, item_id))


def materials(db, cid=None, c=None, picked=None):
    """Материалы объекта по протяжённости и типу врезки: [{'role','label','quantity','unit','item_id','name'}].
    ПЭ и сталь — по метражу; в сталь — 1 неразъёмное соединение ПЭ/сталь + муфты; в ПЭ — 1 заглушка + муфты."""
    c = c or get(db, cid)
    picked = picked or (chosen_items(db, c['id']) if c.get('id') else {r: (role_items(db, r)[0][0] if role_items(db, r) else None) for r in ROLES})
    wanted = []
    if float(c.get('pe_length') or 0) > 0:
        wanted.append(('pe_pipe', float(c['pe_length']), 'м'))
    if float(c.get('steel_length') or 0) > 0:
        wanted.append(('steel_pipe', float(c['steel_length']), 'м'))
    if c.get('tie_in') == 'steel':
        wanted.append(('transition', 1, 'шт'))
    elif c.get('tie_in') == 'pe':
        wanted.append(('plug', 1, 'шт'))
    if c.get('tie_in') and int(c.get('couplings') or 0) > 0:
        wanted.append(('coupling', int(c['couplings']), 'шт'))
    result = []
    for role, qty, unit in wanted:
        item_id = picked.get(role)
        row = db.fetchone('SELECT name,coalesce(unit,\'\') FROM gsn_items WHERE id=?', (item_id,)) if item_id else None
        result.append(dict(role=role, label=ROLES[role], quantity=qty, unit=(row[1] if row and row[1] else unit), item_id=item_id, name=row[0] if row else ROLES[role]))
    return result


# --- СЕРТИФИКАТЫ И АТТЕСТАТЫ -------------------------------------------------------------------

def certificates(db, cid=None, c=None, picked=None):
    """Сертификаты объекта: по умолчанию (отмечены «всегда» в Справочнике ГСН) и зависимые (привязаны к материалам этого договора).
    [{'id','name','number','path','valid_to','kind': 'default'|'dependent','reason'}]."""
    from .gsn_catalog import cert_state
    found, seen = [], set()

    def add(row, kind, reason):
        if row[0] in seen:
            return
        seen.add(row[0])
        found.append(dict(id=row[0], name=row[1], number=row[2] or '', path=row[3] or '', valid_to=row[4] or '', kind=kind, reason=reason, state=cert_state(row[4])[0]))
    for row in db.fetchall("SELECT id,name,number,file_path,valid_to FROM gsn_certificates WHERE always=1 ORDER BY id"):
        add(row, 'default', 'по умолчанию для всех объектов ГСН')
    for m in materials(db, cid, c, picked):
        if not m['item_id']:
            continue
        for row in db.fetchall("SELECT c.id,c.name,c.number,c.file_path,c.valid_to FROM gsn_item_certs l JOIN gsn_certificates c ON c.id=l.cert_id WHERE l.item_id=? ORDER BY c.id", (m['item_id'],)):
            add(row, 'dependent', f'{m["label"]}: {m["name"]}')
    return found


def set_attestation_mode(db, document_id, mode):
    """mode: 'always' / 'steel' / 'pe' или '' (не используется для ГСН)."""
    if mode and mode not in ATTEST_MODES:
        raise ValueError('Неизвестное правило аттестата')
    if mode:
        db.execute('INSERT INTO gsn_attest_rules(document_id,mode) VALUES(?,?) ON CONFLICT(document_id) DO UPDATE SET mode=excluded.mode', (document_id, mode))
    else:
        db.execute('DELETE FROM gsn_attest_rules WHERE document_id=?', (document_id,))


def attestation_rules(db):
    """[(id документа, название, тип, сварщик, номер, дата, файл, правило или '')] — все документы модуля «Сварщики»."""
    return db.fetchall("""SELECT d.id,d.title,d.document_type,coalesce(w.name,''),coalesce(d.number,''),coalesce(d.document_date,''),coalesce(d.file_path,''),coalesce(r.mode,'')
        FROM welding_documents d LEFT JOIN welders w ON w.id=d.welder_id LEFT JOIN gsn_attest_rules r ON r.document_id=d.id ORDER BY d.title""")


def attestations(db, cid=None, c=None):
    """Аттестаты сварщиков объекта: для всех объектов ГСН плюс зависящие от типа врезки (в сталь — «на металл», в ПЭ — «на ПЭ»)."""
    tie = (c or get(db, cid)).get('tie_in') or ''
    rows = db.fetchall("""SELECT d.id,d.title,d.document_type,coalesce(w.name,''),coalesce(d.number,''),coalesce(d.document_date,''),coalesce(d.file_path,''),r.mode
        FROM gsn_attest_rules r JOIN welding_documents d ON d.id=r.document_id LEFT JOIN welders w ON w.id=d.welder_id
        WHERE r.mode='always' OR r.mode=? ORDER BY d.title""", (tie,))
    return [dict(id=r[0], title=r[1], type=r[2], welder=r[3], number=r[4], date=r[5], path=r[6], kind='default' if r[7] == 'always' else 'dependent',
                 reason='для всех объектов ГСН' if r[7] == 'always' else ('при врезке в сталь' if r[7] == 'steel' else 'при врезке в ПЭ')) for r in rows]
