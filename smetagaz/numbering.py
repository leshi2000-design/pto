"""Номера договоров в «Проектах ГСВ» и «Монтаже ГСВ»: ручное изменение, обмен номерами между карточками и резерв номеров (пустые карточки).

Номер проекта ГСВ состоит из порядкового номера и года: «07-26 ГСВ» (проект) и «07-03/26» (договор) — меняются вместе. У монтажа ГСВ номер вида «07-02/26»;
допускается и произвольный текст (старые договоры), тогда порядковый номер не определяется."""
import re
from datetime import date

from . import section_codes as sc

SECTIONS = {
    'contracts': dict(title='Монтаж ГСВ', code='02'),          # код здесь — значение по умолчанию; действующий номер раздела задаётся в настройках (section_codes)
    'gsv_projects': dict(title='Проекты ГСВ', code='03'),
}
RESERVE_TEXT = 'Резерв номера'


class NumberTaken(ValueError):
    def __init__(self, number, other_id, other_label):
        super().__init__(f'Номер {number} уже занят: {other_label}')
        self.number, self.other_id, self.other_label = number, other_id, other_label


def migrate(db):
    for table in SECTIONS:
        cols = {r[1] for r in db.fetchall(f'PRAGMA table_info({table})')}
        if 'reserved' not in cols:
            db.execute(f'ALTER TABLE {table} ADD COLUMN reserved INTEGER DEFAULT 0')


def _check(section):
    if section not in SECTIONS:
        raise ValueError('Номера меняются только в разделах «Проекты ГСВ» и «Монтаж ГСВ»')


def _db(db):
    if db is not None:
        return db
    from .database import db as default
    return default


def format_number(section, seq, year, db=None):
    """(номер договора, номер проекта или None)."""
    _check(section)
    return sc.format_number(_db(db), section, seq, year), (f'{seq:02}-{year:02} ГСВ' if section == 'gsv_projects' else None)


def parse(section, text, db=None):
    """Из текста номера достаёт (порядковый, год) или (None, None). Узнаются и прежние номера раздела."""
    m = sc.regex(_db(db), section).match(str(text or ''))
    if m:
        return int(m.group(1)), int(m.group(2))
    if section == 'gsv_projects':
        m = re.match(r'^\s*(\d+)-(\d{2})\s*ГСВ\s*$', str(text or ''), re.I)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def label(db, section, rid):
    if section == 'contracts':
        r = db.fetchone("SELECT contract_number,coalesce(nullif(client_name,''),party_name,''),coalesce(object_name,''),coalesce(reserved,0) FROM contracts WHERE id=?", (rid,))
    else:
        r = db.fetchone("SELECT pd_number,coalesce(nullif(client_name,''),party_name,''),coalesce(object_name,''),coalesce(reserved,0) FROM gsv_projects WHERE id=?", (rid,))
    if not r:
        return ''
    who = r[1] or r[2] or (RESERVE_TEXT.lower() if r[3] else 'без данных')
    return f'{r[0]} — {who}'


def others(db, section, rid):
    """Остальные карточки раздела для выбора при обмене: [(id, подпись)], свежие номера сверху."""
    _check(section)
    ids = [r[0] for r in db.fetchall(f'SELECT id FROM {section} WHERE id<>? ORDER BY coalesce(year_num,0) DESC, coalesce(seq_num,0) DESC, id DESC LIMIT 500', (rid,))]
    return [(i, label(db, section, i)) for i in ids]


def _holder(db, section, number, pd_number, exclude):
    if section == 'gsv_projects':
        r = db.fetchone('SELECT id FROM gsv_projects WHERE id<>? AND (contract_number=? OR pd_number=?)', (exclude, number, pd_number))
    else:
        r = db.fetchone('SELECT id FROM contracts WHERE id<>? AND contract_number=?', (exclude, number))
    return r[0] if r else None


def change_number(db, section, rid, text):
    """Меняет номер карточки. Для проекта ГСВ text — «порядковый-год» вроде «7-26» или полный номер; для монтажа — «07-02/26» или любой текст.
    Если номер занят — NumberTaken (интерфейс предложит поменять местами)."""
    _check(section)
    text = str(text or '').strip()
    if not text:
        raise ValueError('Введите номер')
    if section == 'gsv_projects':
        seq, year = parse(section, text, db)
        if seq is None:
            m = re.match(r'^(\d+)[-/ ](\d{2})$', text)
            if not m:
                raise ValueError('Для проекта ГСВ введите порядковый номер и год, например 07-26')
            seq, year = int(m.group(1)), int(m.group(2))
        number, pd = format_number(section, seq, year, db)
    else:
        seq, year = parse(section, text, db)
        number, pd = text, None
    other = _holder(db, section, number, pd, rid)
    if other:
        raise NumberTaken(pd or number, other, label(db, section, other))
    with db.transaction():
        if section == 'gsv_projects':
            db.execute('UPDATE gsv_projects SET pd_number=?,contract_number=?,seq_num=?,year_num=? WHERE id=?', (pd, number, seq, year, rid))
        else:
            db.execute('UPDATE contracts SET contract_number=?,seq_num=?,year_num=? WHERE id=?', (number, seq, year, rid))
    return pd or number


def swap_numbers(db, section, a, b):
    """Меняет местами номера двух карточек (клиенты и данные остаются при своих карточках)."""
    _check(section)
    if a == b:
        raise ValueError('Выберите другую карточку')
    cols = 'pd_number,contract_number,seq_num,year_num' if section == 'gsv_projects' else 'contract_number,seq_num,year_num'
    names = cols.split(',')
    ra = db.fetchone(f'SELECT {cols} FROM {section} WHERE id=?', (a,))
    rb = db.fetchone(f'SELECT {cols} FROM {section} WHERE id=?', (b,))
    if not ra or not rb:
        raise ValueError('Карточка не найдена')
    with db.transaction():
        if section == 'gsv_projects':       # pd_number уникален: сначала освобождаем номер первой карточки
            db.execute('UPDATE gsv_projects SET pd_number=? WHERE id=?', (f'~swap~{a}', a))
            db.execute('UPDATE gsv_projects SET pd_number=? WHERE id=?', (f'~swap~{b}', b))
        db.execute(f'UPDATE {section} SET ' + ','.join(f'{n}=?' for n in names) + ' WHERE id=?', (*rb, a))
        db.execute(f'UPDATE {section} SET ' + ','.join(f'{n}=?' for n in names) + ' WHERE id=?', (*ra, b))


def reserve(db, section, count, on_date=None):
    """Создаёт count пустых карточек с подряд идущими номерами под резерв; возвращает [(id, номер)]."""
    _check(section)
    count = int(count)
    if not 1 <= count <= 100:
        raise ValueError('Количество резервных номеров — от 1 до 100')
    day = on_date or date.today()
    created = []
    with db.transaction():
        for _ in range(count):
            if section == 'contracts':
                from . import gsvm_domain as md
                seq, year, number = md.next_number(db, day)
                rid = db.execute("INSERT INTO contracts(contract_number,contract_date,object_name,seq_num,year_num,reserved) VALUES(?,?,?,?,?,1)",
                                 (number, '', '', seq, year, )).lastrowid
                created.append((rid, number))
            else:
                year = day.year % 100
                seq = db.fetchone('SELECT coalesce(max(seq_num),0)+1 FROM gsv_projects WHERE year_num=?', (year,))[0]
                number, pd = format_number(section, seq, year, db)
                rid = db.execute("INSERT INTO gsv_projects(pd_number,seq_num,year_num,contract_number,object_name,client_name,cost,reserved) VALUES(?,?,?,?,?,?,0,1)",
                                 (pd, seq, year, number, '', '')).lastrowid
                created.append((rid, pd))
    return created


def release_if_filled(db, section, rid):
    """После сохранения карточки: если в ней появились данные, снимает отметку резерва."""
    _check(section)
    if section == 'contracts':
        sql = "UPDATE contracts SET reserved=0 WHERE id=? AND reserved=1 AND (coalesce(client_name,'')<>'' OR coalesce(party_name,'')<>'' OR coalesce(object_name,'')<>'')"
    else:
        sql = "UPDATE gsv_projects SET reserved=0 WHERE id=? AND reserved=1 AND (coalesce(client_name,'')<>'' OR coalesce(party_name,'')<>'' OR coalesce(object_name,'')<>'')"
    db.execute(sql, (rid,))
