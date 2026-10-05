"""Раздел «Монтаж ГСВ»: договор, смета и её история, оборудование, трубопроводы и стыки, сертификаты, расход материалов.

Данные раздела хранятся в собственных таблицах `gsvm_*` и не связаны с модулем «Исполнительная документация»
и с другими разделами (общий у них только клиент). Модуль не зависит от Qt.
"""
import os
import re
import shutil
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .config import DATA_DIR
from .agenda_domain import short_name
from . import gsv_project_domain as gd

SECTION = 'contracts'
EQUIPMENT_KINDS = ['ПГ', 'Котел', 'Счётчик газа', 'Регулятор давления газа', 'Сигнализатор', 'Колонка']
EQUIPMENT_LABELS = {'ПГ': 'ПГ (плита газовая)'}
DEFAULT_END_DAYS = 60
CERT_GROUPS = {'equipment': 'Оборудование', 'pipeline': 'Трубопровод', 'dependent': 'Зависимый', 'default': 'По умолчанию', 'custom': 'Произвольный'}
RULE_TYPES = {'equipment_kind': 'Если в объекте есть оборудование', 'pipeline': 'Если в объекте есть трубопровод',
              'pipeline_text': 'Если в названии трубопровода есть текст (диаметр, производитель)'}
CERT_ROOT = DATA_DIR / 'certificates_storage'


# --- МИГРАЦИЯ --------------------------------------------------------------------------------

def migrate(db):
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(contracts)')}
    for name, ddl in (('contract_signed', 'INTEGER DEFAULT 0'), ('act_signed', 'INTEGER DEFAULT 0'), ('designer_code', "TEXT DEFAULT ''"),
                      ('designer', "TEXT DEFAULT ''"), ('project_month', "TEXT DEFAULT ''"), ('notes', "TEXT DEFAULT ''"),
                      ('contract_folder', "TEXT DEFAULT ''"), ('object_address', "TEXT DEFAULT ''"), ('seq_num', 'INTEGER'), ('year_num', 'INTEGER'),
                      ('est_rev_synced', 'INTEGER DEFAULT 0'), ('est_materials', 'REAL DEFAULT 0'), ('est_works', 'REAL DEFAULT 0'),
                      ('est_synced_at', "TEXT DEFAULT ''")):
        if name not in cols:
            db.execute(f'ALTER TABLE contracts ADD COLUMN {name} {ddl}')
    for sql in (
        """CREATE TABLE IF NOT EXISTS gsvm_equipment(id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
             kind TEXT NOT NULL DEFAULT '', model TEXT DEFAULT '', serial TEXT DEFAULT '', note TEXT DEFAULT '', file_path TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS gsvm_pipelines(id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
             pipeline_id INTEGER NOT NULL REFERENCES gsv_pipelines(id) ON DELETE RESTRICT, quantity REAL NOT NULL DEFAULT 0, note TEXT DEFAULT '',
             from_estimate INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS gsvm_joints(id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
             pipeline_id INTEGER REFERENCES gsv_pipelines(id) ON DELETE SET NULL, name TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0,
             note TEXT DEFAULT '', custom INTEGER NOT NULL DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS gsvm_cert_rules(id INTEGER PRIMARY KEY, cond_type TEXT NOT NULL, cond_value TEXT NOT NULL,
             certificate_id INTEGER NOT NULL REFERENCES certificates(id) ON DELETE CASCADE)""",
        'CREATE TABLE IF NOT EXISTS gsvm_default_certs(certificate_id INTEGER PRIMARY KEY REFERENCES certificates(id) ON DELETE CASCADE)',
        """CREATE TABLE IF NOT EXISTS gsvm_contract_certs(id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
             source TEXT NOT NULL CHECK(source IN ('custom','excluded')), key TEXT DEFAULT '', title TEXT DEFAULT '', file_path TEXT DEFAULT '',
             certificate_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL)""",
        """CREATE TABLE IF NOT EXISTS gsvm_docs(contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE, kind TEXT NOT NULL,
             file_path TEXT NOT NULL, data_hash TEXT NOT NULL DEFAULT '', generated_at TEXT NOT NULL DEFAULT '', linked INTEGER NOT NULL DEFAULT 0,
             PRIMARY KEY(contract_id,kind))""",
        """CREATE TABLE IF NOT EXISTS gsvm_attestations(contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
             document_id INTEGER NOT NULL REFERENCES welding_documents(id) ON DELETE CASCADE, PRIMARY KEY(contract_id,document_id))""",
        """CREATE TABLE IF NOT EXISTS gsvm_tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, source TEXT NOT NULL, fmt TEXT NOT NULL DEFAULT 'text',
             empty_text TEXT DEFAULT '', auto_key TEXT UNIQUE, enabled INTEGER NOT NULL DEFAULT 1, note TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS gsvm_consumption(id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
             job_id INTEGER, material_id INTEGER, name TEXT NOT NULL, unit TEXT DEFAULT '', qty TEXT NOT NULL, created_at TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS gsvm_jobs(job_id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
             joints_json TEXT NOT NULL DEFAULT '[]')""",
        """CREATE TABLE IF NOT EXISTS estimate_changes(id INTEGER PRIMARY KEY, estimate_id INTEGER NOT NULL, changed_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
             action TEXT NOT NULL, item_name TEXT DEFAULT '', detail TEXT DEFAULT '')""",
        'CREATE INDEX IF NOT EXISTS idx_estimate_changes ON estimate_changes(estimate_id,id)',
        'CREATE INDEX IF NOT EXISTS idx_gsvm_equipment ON gsvm_equipment(contract_id)',
        'CREATE INDEX IF NOT EXISTS idx_gsvm_pipelines ON gsvm_pipelines(contract_id)',
        'CREATE INDEX IF NOT EXISTS idx_gsvm_joints ON gsvm_joints(contract_id)',
    ):
        db.execute(sql)
    # История смет ведётся триггерами: любое изменение позиций или итога попадает в журнал независимо от того, где оно сделано.
    alive = 'EXISTS(SELECT 1 FROM estimates WHERE id={e}.estimate_id)'
    db.execute('DROP TRIGGER IF EXISTS estimate_log_insert')
    db.execute("""CREATE TRIGGER estimate_log_insert AFTER INSERT ON estimate_items WHEN new.item_type<>'Раздел' BEGIN
        INSERT INTO estimate_changes(estimate_id,action,item_name,detail) VALUES(new.estimate_id,'Добавлено',new.name,
          'кол-во '||coalesce(new.quantity,0)||', цена '||coalesce(new.price,0)||', сумма '||round(coalesce(new.sum,0),2)); END""")
    db.execute('DROP TRIGGER IF EXISTS estimate_log_delete')
    db.execute(f"""CREATE TRIGGER estimate_log_delete AFTER DELETE ON estimate_items WHEN old.item_type<>'Раздел' AND {alive.format(e='old')} BEGIN
        INSERT INTO estimate_changes(estimate_id,action,item_name,detail) VALUES(old.estimate_id,'Удалено',old.name,
          'было: кол-во '||coalesce(old.quantity,0)||', сумма '||round(coalesce(old.sum,0),2)); END""")
    db.execute('DROP TRIGGER IF EXISTS estimate_log_update')
    db.execute("""CREATE TRIGGER estimate_log_update AFTER UPDATE OF name,item_type,unit,quantity,price,sum ON estimate_items
        WHEN new.item_type<>'Раздел' AND (old.name IS NOT new.name OR old.quantity IS NOT new.quantity OR old.price IS NOT new.price OR old.sum IS NOT new.sum OR old.item_type IS NOT new.item_type) BEGIN
        INSERT INTO estimate_changes(estimate_id,action,item_name,detail) VALUES(new.estimate_id,'Изменено',new.name,
          'кол-во '||coalesce(old.quantity,0)||' → '||coalesce(new.quantity,0)||'; цена '||coalesce(old.price,0)||' → '||coalesce(new.price,0)||
          '; сумма '||round(coalesce(old.sum,0),2)||' → '||round(coalesce(new.sum,0),2)); END""")
    db.execute('DROP TRIGGER IF EXISTS estimate_log_total')
    db.execute("""CREATE TRIGGER estimate_log_total AFTER UPDATE OF total ON estimates WHEN old.total IS NOT new.total BEGIN
        INSERT INTO estimate_changes(estimate_id,action,item_name,detail) VALUES(new.id,'Итог','Итого по смете',
          round(coalesce(old.total,0),2)||' → '||round(coalesce(new.total,0),2)); END""")
    if db.get_setting('gsvm_migrated', '0') != '1':
        _import_legacy(db)
        db.set_setting('gsvm_migrated', '1')


def _import_legacy(db):
    """Однократно переносит оборудование и трубопроводы, уже внесённые в договоры монтажа ГСВ."""
    for cid, kind, model, cert, note, linked in db.fetchall('SELECT contract_id,equipment_kind,equipment_model,certificate_number,note,linked_cert_id FROM contract_equipment'):
        if not db.fetchone('SELECT 1 FROM contracts WHERE id=?', (cid,)):
            continue
        path = ''
        if linked:
            row = db.fetchone('SELECT file_path FROM certificates WHERE id=?', (linked,))
            path = row[0] if row and row[0] else ''
        db.execute('INSERT INTO gsvm_equipment(contract_id,kind,model,serial,note,file_path) VALUES(?,?,?,?,?,?)',
                   (cid, kind or '', model or '', '', ' · '.join(x for x in (f'сертификат № {cert}' if cert else '', note or '') if x), path))
    for cid, pid, qty, note in db.fetchall("SELECT owner_id,pipeline_id,quantity,note FROM object_pipelines WHERE owner_type='contracts'"):
        if db.fetchone('SELECT 1 FROM contracts WHERE id=?', (cid,)):
            db.execute('INSERT INTO gsvm_pipelines(contract_id,pipeline_id,quantity,note) VALUES(?,?,?,?)', (cid, pid, qty or 0, note or ''))
    for (cid,) in db.fetchall('SELECT DISTINCT contract_id FROM gsvm_pipelines'):
        sync_joints(db, cid)
    # ранее внесённые договоры считаются подписанными, а их папки из общего модуля переходят в карточку договора
    db.execute("UPDATE contracts SET contract_signed=1 WHERE coalesce(contract_date,'')<>''")
    db.execute("UPDATE contracts SET act_signed=1 WHERE coalesce(acceptance_act_date,'')<>''")
    for cid, folder in db.fetchall("SELECT owner_id,folder_path FROM executive_objects WHERE owner_type='contracts' AND coalesce(folder_path,'')<>''"):
        db.execute("UPDATE contracts SET contract_folder=? WHERE id=? AND coalesce(contract_folder,'')=''", (folder, cid))


# --- НОМЕР, ПАПКА ----------------------------------------------------------------------------

def next_number(db, contract_date=None):
    """(порядковый, год, '01-02/26'): номер договора монтажа ГСВ — порядок, раздел 02, год заключения."""
    day = gd._parse(contract_date) or date.today()
    yy = day.year % 100
    top = db.fetchone('SELECT coalesce(max(seq_num),0) FROM contracts WHERE year_num=?', (yy,))[0]
    for (number,) in db.fetchall("SELECT contract_number FROM contracts WHERE contract_number LIKE '%-02/%'"):
        m = re.match(r'^(\d+)-02/(\d{2})$', str(number or '').strip())
        if m and int(m.group(2)) == yy:
            top = max(top, int(m.group(1)))
    seq = top + 1
    return seq, yy, f'{seq:02}-02/{yy:02}'


def folder_name(number, address='', client=''):
    """«01-02.26, адрес объекта (Фамилия И.О.)»: в номере «/» заменяется на «.»."""
    name = str(number or '').strip().replace('/', '.')
    if str(address or '').strip():
        name += f', {" ".join(str(address).split())[:90]}'
    if str(client or '').strip():
        name += f' ({short_name(client)})'
    return gd.safe_name(name)


def contract_folder(db, cid):
    row = db.fetchone('SELECT contract_folder FROM contracts WHERE id=?', (cid,))
    return row[0] if row and row[0] and os.path.isdir(row[0]) else ''


def link_folder(db, cid, path, create=False):
    path = str(path)
    if create:
        os.makedirs(path, exist_ok=True)
    if not os.path.isdir(path):
        raise ValueError('Папка не найдена: ' + path)
    db.execute('UPDATE contracts SET contract_folder=? WHERE id=?', (path, cid))
    return path


def suggested_folder_name(db, cid):
    row = db.fetchone('SELECT contract_number,object_address,object_name,client_name FROM contracts WHERE id=?', (cid,))
    if not row:
        raise ValueError('Сначала сохраните договор')
    return folder_name(row[0], row[1] or row[2], row[3])


def default_end(contract_date):
    day = gd._parse(contract_date)
    return day + timedelta(days=DEFAULT_END_DAYS) if day else None


# --- СМЕТА -----------------------------------------------------------------------------------

def estimate_summary(db, eid):
    """{'materials','works','total','title'} по смете."""
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
    row = db.fetchone('SELECT estimate_id,est_rev_synced,est_synced_at FROM contracts WHERE id=?', (cid,))
    if not row or not row[0]:
        return 'none'
    if not row[2]:
        return 'unsynced'
    return 'stale' if last_change(db, row[0]) > (row[1] or 0) else 'fresh'


def sync_estimate(db, cid):
    """«Получить стоимость из сметы»: фиксирует материалы / работы и ставит итог сметы стоимостью работ договора."""
    row = db.fetchone('SELECT estimate_id FROM contracts WHERE id=?', (cid,))
    if not row or not row[0]:
        raise ValueError('К договору не привязана смета')
    s = estimate_summary(db, row[0])
    if not s:
        raise ValueError('Смета не найдена')
    db.execute('UPDATE contracts SET contract_amount=?, est_materials=?, est_works=?, est_rev_synced=?, est_synced_at=? WHERE id=?',
               (round(s['total'], 2), round(s['materials'], 2), round(s['works'], 2), last_change(db, row[0]), datetime.now().isoformat(timespec='seconds'), cid))
    return s


def estimate_history(db, eid, limit=500):
    return db.fetchall('SELECT changed_at,action,item_name,detail FROM estimate_changes WHERE estimate_id=? ORDER BY id DESC LIMIT ?', (eid, limit))


def link_estimate(db, cid, eid):
    from . import payments_domain
    other = db.fetchone('SELECT id FROM contracts WHERE estimate_id=? AND id<>?', (eid, cid))
    if other:
        raise ValueError('Эта смета уже привязана к другому договору')
    payments_domain.link(db, 'contracts', cid, eid)
    db.execute('UPDATE contracts SET est_synced_at=?, est_rev_synced=0 WHERE id=?', ('', cid))


# --- ОБОРУДОВАНИЕ ----------------------------------------------------------------------------

def equipment(db, cid):
    cur = db.execute('SELECT id,kind,model,serial,note,file_path FROM gsvm_equipment WHERE contract_id=? ORDER BY id', (cid,))
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def save_equipment(db, cid, rows):
    with db.transaction():
        db.execute('DELETE FROM gsvm_equipment WHERE contract_id=?', (cid,))
        for r in rows:
            if not any(str(r.get(k) or '').strip() for k in ('kind', 'model', 'serial', 'note', 'file_path')):
                continue
            if not str(r.get('kind') or '').strip():
                raise ValueError('Укажите тип оборудования (в строке «' + str(r.get('model') or r.get('serial') or '') + '»)')
            db.execute('INSERT INTO gsvm_equipment(contract_id,kind,model,serial,note,file_path) VALUES(?,?,?,?,?,?)',
                       (cid, r['kind'].strip(), (r.get('model') or '').strip(), (r.get('serial') or '').strip(), (r.get('note') or '').strip(), r.get('file_path') or ''))


def store_equipment_file(db, cid, source):
    """Копирует паспорт / сертификат оборудования в папку договора (подпапка «Оборудование»); возвращает новый путь."""
    folder = contract_folder(db, cid)
    if not folder:
        raise ValueError('Сначала привяжите или создайте папку договора')
    target_dir = Path(folder) / 'Оборудование'
    target_dir.mkdir(exist_ok=True)
    source = Path(source)
    if source.parent == target_dir:
        return str(source)
    target = target_dir / source.name
    n = 1
    while target.exists():
        target = target_dir / f'{source.stem} ({n}){source.suffix}'
        n += 1
    shutil.copy2(source, target)
    return str(target)


# --- ТРУБОПРОВОДЫ И СТЫКИ --------------------------------------------------------------------

def diameter_of(name):
    """Диаметр из названия трубопровода: «Труба ПЭ 32x3» → '32'; пусто, если числа нет."""
    m = re.search(r'(\d+(?:[.,]\d+)?)', str(name or ''))
    return m.group(1).replace(',', '.') if m else ''


def pipelines(db, cid):
    cur = db.execute("""SELECT g.id,g.pipeline_id,p.name,g.quantity,g.note,g.from_estimate,c.cert_number,c.file_path
        FROM gsvm_pipelines g JOIN gsv_pipelines p ON p.id=g.pipeline_id LEFT JOIN certificates c ON c.id=p.certificate_id WHERE g.contract_id=? ORDER BY g.id""", (cid,))
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def save_pipelines(db, cid, rows):
    """rows: [{pipeline_id, quantity, note, from_estimate}]; количество — в метрах, до 2 знаков."""
    with db.transaction():
        db.execute('DELETE FROM gsvm_pipelines WHERE contract_id=?', (cid,))
        for r in rows:
            if not r.get('pipeline_id'):
                continue
            qty = Decimal(str(r.get('quantity') or 0)).quantize(Decimal('0.01'))
            if qty < 0:
                raise ValueError('Количество не может быть отрицательным')
            db.execute('INSERT INTO gsvm_pipelines(contract_id,pipeline_id,quantity,note,from_estimate) VALUES(?,?,?,?,?)',
                       (cid, r['pipeline_id'], float(qty), (r.get('note') or '').strip(), int(bool(r.get('from_estimate')))))
        sync_joints(db, cid)


def joints(db, cid):
    cur = db.execute('SELECT id,pipeline_id,name,count,note,custom FROM gsvm_joints WHERE contract_id=? ORDER BY custom,id', (cid,))
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def sync_joints(db, cid):
    """Нижняя таблица повторяет трубопроводы верхней: добавляет недостающие строки, убирает лишние; произвольные стыки не трогает."""
    wanted = {}
    for r in pipelines(db, cid):
        wanted.setdefault(r['pipeline_id'], r['name'])
    existing = {r['pipeline_id']: r for r in joints(db, cid) if not r['custom']}
    for pid, name in wanted.items():
        if pid in existing:
            db.execute('UPDATE gsvm_joints SET name=? WHERE id=?', (name, existing[pid]['id']))
        else:
            db.execute('INSERT INTO gsvm_joints(contract_id,pipeline_id,name,count,custom) VALUES(?,?,?,0,0)', (cid, pid, name))
    for pid, r in existing.items():
        if pid not in wanted:
            db.execute('DELETE FROM gsvm_joints WHERE id=?', (r['id'],))


def save_joints(db, cid, rows):
    """rows: [{id|None, pipeline_id, name, count, note, custom}] — обновляет количество / примечание, добавляет и удаляет произвольные."""
    with db.transaction():
        keep = set()
        for r in rows:
            count = int(r.get('count') or 0)
            if count < 0:
                raise ValueError('Количество стыков не может быть отрицательным')
            name = str(r.get('name') or '').strip()
            if not name:
                raise ValueError('Укажите наименование трубопровода для стыков')
            if r.get('id'):
                db.execute('UPDATE gsvm_joints SET name=?,count=?,note=? WHERE id=? AND contract_id=?', (name, count, (r.get('note') or '').strip(), r['id'], cid))
                keep.add(r['id'])
            elif r.get('custom'):
                keep.add(db.execute('INSERT INTO gsvm_joints(contract_id,pipeline_id,name,count,note,custom) VALUES(?,?,?,?,?,1)',
                                    (cid, None, name, count, (r.get('note') or '').strip())).lastrowid)
        for r in joints(db, cid):
            if r['custom'] and r['id'] not in keep:
                db.execute('DELETE FROM gsvm_joints WHERE id=?', (r['id'],))


def joints_total(db, cid):
    return db.fetchone('SELECT coalesce(sum(count),0) FROM gsvm_joints WHERE contract_id=?', (cid,))[0]


def _norm(text):
    return ' '.join(str(text or '').split()).casefold()


def estimate_pipeline_quantities(db, cid):
    """{pipeline_id: количество} — позиции сметы, наименование которых совпадает с трубопроводом справочника ГСВ."""
    row = db.fetchone('SELECT estimate_id FROM contracts WHERE id=?', (cid,))
    if not row or not row[0]:
        return {}
    by_name = {_norm(name): pid for pid, name in db.fetchall('SELECT id,name FROM gsv_pipelines')}
    result = {}
    for name, qty in db.fetchall("SELECT name,coalesce(quantity,0) FROM estimate_items WHERE estimate_id=? AND item_type<>'Раздел'", (row[0],)):
        pid = by_name.get(_norm(name))
        if pid:
            result[pid] = round(result.get(pid, 0) + float(qty), 2)
    return result


def pipelines_from_estimate(db, cid):
    """Кнопка «Взять данные из сметы»: добавляет / обновляет трубопроводы по смете; возвращает число найденных позиций."""
    found = estimate_pipeline_quantities(db, cid)
    if not found:
        return 0
    rows = pipelines(db, cid)
    by_pipeline = {r['pipeline_id']: r for r in rows}
    out = [dict(pipeline_id=r['pipeline_id'], quantity=r['quantity'], note=r['note'], from_estimate=r['from_estimate']) for r in rows]
    for pid, qty in found.items():
        if pid in by_pipeline:
            for o in out:
                if o['pipeline_id'] == pid:
                    o.update(quantity=qty, from_estimate=1)
        else:
            out.append(dict(pipeline_id=pid, quantity=qty, note='', from_estimate=1))
    save_pipelines(db, cid, out)
    return len(found)


def refresh_estimate_pipelines(db, cid):
    """Строки, взятые из сметы, автоматически следуют за ней. Возвращает число изменённых строк."""
    rows = pipelines(db, cid)
    if not any(r['from_estimate'] for r in rows):
        return 0
    found = estimate_pipeline_quantities(db, cid)
    changed = 0
    for r in rows:
        if r['from_estimate']:
            qty = found.get(r['pipeline_id'], 0.0)
            if abs(qty - (r['quantity'] or 0)) > 0.0049:
                db.execute('UPDATE gsvm_pipelines SET quantity=? WHERE id=?', (qty, r['id']))
                changed += 1
    return changed


# --- СЕРТИФИКАТЫ -----------------------------------------------------------------------------

def cert_rules(db):
    return db.fetchall("""SELECT r.id,r.cond_type,r.cond_value,r.certificate_id,coalesce(c.name,''),coalesce(c.cert_number,'') FROM gsvm_cert_rules r
        LEFT JOIN certificates c ON c.id=r.certificate_id ORDER BY r.id""")


def add_cert_rule(db, cond_type, cond_value, cert_id):
    if cond_type not in RULE_TYPES or not str(cond_value).strip() or not cert_id:
        raise ValueError('Укажите условие и сертификат')
    return db.execute('INSERT INTO gsvm_cert_rules(cond_type,cond_value,certificate_id) VALUES(?,?,?)', (cond_type, str(cond_value).strip(), cert_id)).lastrowid


def default_certs(db):
    return [r[0] for r in db.fetchall('SELECT certificate_id FROM gsvm_default_certs ORDER BY rowid')]


def _cert_row(db, cert_id):
    return db.fetchone("SELECT id,name,coalesce(cert_number,''),coalesce(file_path,'') FROM certificates WHERE id=?", (cert_id,))


def collect_certs(db, cid, include_excluded=False):
    """Сертификаты договора: оборудование, трубопроводы, зависимые, по умолчанию и произвольные (без исключённых вручную)."""
    excluded = {r[0] for r in db.fetchall("SELECT key FROM gsvm_contract_certs WHERE contract_id=? AND source='excluded'", (cid,))}
    result, seen_certs = [], set()

    def add(group, key, title, number, path, cert_id, reason):
        if key in excluded and not include_excluded:
            return
        if cert_id and cert_id in seen_certs:
            return
        if cert_id:
            seen_certs.add(cert_id)
        result.append(dict(key=key, group=group, title=title, number=number or '', path=path or '', cert_id=cert_id, reason=reason, excluded=key in excluded))

    eq = equipment(db, cid)
    for e in eq:
        if e['file_path']:
            add('equipment', f'equipment:{e["id"]}', f'{e["kind"]} {e["model"]}'.strip(), e['serial'], e['file_path'], None, e['kind'])
    pipes = pipelines(db, cid)
    for p in pipes:
        row = db.fetchone('SELECT c.id,c.name,coalesce(c.cert_number,\'\'),coalesce(c.file_path,\'\') FROM gsv_pipelines g JOIN certificates c ON c.id=g.certificate_id WHERE g.id=?', (p['pipeline_id'],))
        if row:
            add('pipeline', f'pipeline:{row[0]}', row[1], row[2], row[3], row[0], p['name'])
    kinds = {_norm(e['kind']) for e in eq}
    pipeline_ids = {p['pipeline_id'] for p in pipes}
    names = [_norm(p['name']) for p in pipes]
    for rid, cond_type, value, cert_id, *_ in cert_rules(db):
        hit = ((cond_type == 'equipment_kind' and _norm(value) in kinds) or (cond_type == 'pipeline' and str(value).isdigit() and int(value) in pipeline_ids)
               or (cond_type == 'pipeline_text' and any(_norm(value) in n for n in names)))
        row = _cert_row(db, cert_id) if hit else None
        if row:
            add('dependent', f'dependent:{row[0]}', row[1], row[2], row[3], row[0], RULE_TYPES[cond_type].split(' (')[0] + f' «{value_label(db, cond_type, value)}»')
    for cert_id in default_certs(db):
        row = _cert_row(db, cert_id)
        if row:
            add('default', f'default:{row[0]}', row[1], row[2], row[3], row[0], 'всегда')
    for rid, title, path, cert_id in db.fetchall("SELECT id,title,file_path,certificate_id FROM gsvm_contract_certs WHERE contract_id=? AND source='custom' ORDER BY id", (cid,)):
        row = _cert_row(db, cert_id) if cert_id else None
        add('custom', f'custom:{rid}', row[1] if row else title, row[2] if row else '', row[3] if row else path, None, 'добавлен вручную')
    return result


def value_label(db, cond_type, value):
    if cond_type == 'pipeline' and str(value).isdigit():
        row = db.fetchone('SELECT name FROM gsv_pipelines WHERE id=?', (int(value),))
        return row[0] if row else value
    return value


def exclude_cert(db, cid, key):
    if key.startswith('custom:'):
        db.execute("DELETE FROM gsvm_contract_certs WHERE id=? AND contract_id=? AND source='custom'", (int(key.split(':')[1]), cid))
    elif not db.fetchone("SELECT 1 FROM gsvm_contract_certs WHERE contract_id=? AND source='excluded' AND key=?", (cid, key)):
        db.execute("INSERT INTO gsvm_contract_certs(contract_id,source,key) VALUES(?,'excluded',?)", (cid, key))


def restore_certs(db, cid):
    db.execute("DELETE FROM gsvm_contract_certs WHERE contract_id=? AND source='excluded'", (cid,))


def add_custom_cert(db, cid, title='', path='', cert_id=None):
    if not cert_id and not path:
        raise ValueError('Выберите сертификат из справочника или укажите файл')
    return db.execute("INSERT INTO gsvm_contract_certs(contract_id,source,title,file_path,certificate_id) VALUES(?,'custom',?,?,?)",
                      (cid, title or Path(path).stem, path, cert_id)).lastrowid


# --- АТТЕСТАТЫ ----------------------------------------------------------------------------------

def attestations(db, cid):
    return db.fetchall("""SELECT d.id,d.title,d.document_type,coalesce(w.name,''),coalesce(d.number,''),coalesce(d.document_date,''),d.file_path
        FROM gsvm_attestations a JOIN welding_documents d ON d.id=a.document_id LEFT JOIN welders w ON w.id=d.welder_id WHERE a.contract_id=? ORDER BY d.title""", (cid,))


def set_attestations(db, cid, ids):
    with db.transaction():
        db.execute('DELETE FROM gsvm_attestations WHERE contract_id=?', (cid,))
        for i in sorted(set(ids)):
            db.execute('INSERT INTO gsvm_attestations(contract_id,document_id) VALUES(?,?)', (cid, i))


# --- ГРАФИК РАБОТ И РАСХОД МАТЕРИАЛОВ --------------------------------------------------------

def guess_profile(db, name):
    """Профиль нормы расхода по диаметру трубопровода (Ду совпадает с первым числом в названии)."""
    d = diameter_of(name)
    if not d:
        return None
    row = db.fetchone('SELECT id FROM norm_profiles WHERE diameter=? ORDER BY id LIMIT 1', (d,))
    return row[0] if row else None


def calc_consumption(db, volumes):
    """volumes: [(profile_id, стыков)] → список материалов {material_id,name,unit,qty} по нормам модуля «Списание»."""
    from . import stock_domain
    volumes = [(p, n) for p, n in volumes if n]
    if not volumes:
        return []
    _lines, snapshots = stock_domain.calculate(db, volumes)
    totals = {}
    for snap in snapshots:
        for it in snap['items']:
            cur = totals.setdefault(it['material_id'], dict(material_id=it['material_id'], name=it['name'], unit=it['unit'], qty=Decimal(0)))
            cur['qty'] += Decimal(it['quantity'])
    return [dict(t, qty=format(t['qty'].normalize(), 'f')) for t in totals.values() if t['qty'] > 0]


def create_work_entry(db, cid, work_date, object_text, welder_id, welder_text, lines, consumption=None):
    """Запись в график сварочных работ. lines: [(наименование трубопровода, стыков)]. Возвращает id записи графика."""
    from .gsv_domain import save_job
    from .gsv_domain import set_work_day
    date.fromisoformat(work_date)
    title = 'Сварка: ' + ', '.join(n for n, c in lines if c) if any(c for _n, c in lines) else 'Сварка'
    notes = 'Стыков: ' + str(sum(c for _n, c in lines)) + ' (' + '; '.join(f'{n} — {c}' for n, c in lines if c) + ')'
    with db.transaction():
        jid = save_job(db, title, 'contracts', cid, welder_id, notes, None, None)
        db.execute('UPDATE welding_jobs SET object_text=?,welder_text=? WHERE id=?', (object_text, welder_text, jid))
        db.execute('DELETE FROM welding_days WHERE job_id=?', (jid,))
        set_work_day(db, jid, work_date, True)
        import json
        db.execute('INSERT OR REPLACE INTO gsvm_jobs(job_id,contract_id,joints_json) VALUES(?,?,?)', (jid, cid, json.dumps(lines, ensure_ascii=False)))
        for m in consumption or []:
            db.execute('INSERT INTO gsvm_consumption(contract_id,job_id,material_id,name,unit,qty,created_at) VALUES(?,?,?,?,?,?,?)',
                       (cid, jid, m['material_id'], m['name'], m['unit'], m['qty'], datetime.now().isoformat(timespec='seconds')))
    return jid


def consumption_summary(db, cid):
    """[(материал, ед., сумма)] по всем записям графика договора."""
    totals = {}
    for name, unit, qty in db.fetchall('SELECT name,unit,qty FROM gsvm_consumption WHERE contract_id=? ORDER BY id', (cid,)):
        key = (name, unit)
        totals[key] = totals.get(key, Decimal(0)) + Decimal(qty)
    return [(n, u, format(q.normalize(), 'f')) for (n, u), q in totals.items()]


def consumption_rows(db, cid):
    return db.fetchall("""SELECT c.created_at,coalesce((SELECT min(d.work_date) FROM welding_days d WHERE d.job_id=c.job_id),''),c.name,c.unit,c.qty
        FROM gsvm_consumption c WHERE c.contract_id=? ORDER BY c.id""", (cid,))
