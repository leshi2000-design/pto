"""Объёмы работ и материалов, потраченных на объект строительства (без цен), и смета, которую из них составляют.

Порядок «договор → работа → объёмы → смета»: объёмы вносятся в карточке договора, кнопка «Сформировать смету» создаёт смету с ценами из справочника
и привязывает её к договору. Обратный порядок: смета составлена заранее (предварительно), договор создан позже, смета привязана к нему —
кнопка «Внести объёмы из сметы» заполняет объёмы по позициям сметы."""
from datetime import datetime

OWNERS = {'contracts': 'Монтаж ГСВ', 'gsn_projects': 'Монтаж ГСН', 'smr_contracts': 'СМР (юрлица)', 'ip_contracts': 'СМР (ИП)', 'fl_contracts': 'СМР (физлица)'}
KINDS = ('Работа', 'Материал')
ACT_OWNERS = {'smr_contracts': 'smr_acts', 'ip_contracts': 'ip_acts', 'fl_contracts': 'fl_acts'}       # разделы, где договор имеет акты выполненных работ


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS volumes(id INTEGER PRIMARY KEY, owner_type TEXT NOT NULL, owner_id INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'Материал',
        name TEXT NOT NULL, unit TEXT DEFAULT '', quantity REAL NOT NULL DEFAULT 0, catalog_id INTEGER, note TEXT DEFAULT '', sort_order INTEGER DEFAULT 0)""")
    if 'act_id' not in {r[1] for r in db.fetchall('PRAGMA table_info(volumes)')}:
        db.execute('ALTER TABLE volumes ADD COLUMN act_id INTEGER')              # объёмы делятся по актам выполненных работ; пусто — «без акта»
    for owner in ACT_OWNERS:                                                     # удалили акт — его объёмы не пропадают, а переходят в «без акта»
        acts_table = ACT_OWNERS[owner]
        if db.fetchone('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', acts_table)):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS volumes_act_cleanup_{acts_table} AFTER DELETE ON {acts_table} BEGIN UPDATE volumes SET act_id=NULL WHERE owner_type='{owner}' AND act_id=old.id; END")
    db.execute('CREATE INDEX IF NOT EXISTS idx_volumes_owner ON volumes(owner_type,owner_id)')
    for table in OWNERS:         # удалённый договор не оставляет объёмов (номера записей могут использоваться повторно)
        if db.fetchone('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS volumes_cleanup_{table} AFTER DELETE ON {table} BEGIN DELETE FROM volumes WHERE owner_type='{table}' AND owner_id=old.id; END")


def _check(owner):
    if owner not in OWNERS:
        raise ValueError('В этом разделе вкладка «Объёмы» не предусмотрена')


def has_acts(owner):
    return owner in ACT_OWNERS


def acts(db, owner, oid):
    """Акты договора для выбора в объёмах: [(id, подпись)] по дате; для разделов без актов — пусто."""
    if not has_acts(owner):
        return []
    from . import contracts_core as cc
    mod = cc.CONTRACT_TABLES[owner]
    names = {o['id']: o['name'] for o in cc.objects(db, mod, oid)}
    order = {o['id']: i for i, o in enumerate(cc.objects(db, mod, oid))}
    rows = db.fetchall(f'SELECT id,act_number,act_date,{"object_id" if cc.has_objects(mod) else "NULL"} FROM {ACT_OWNERS[owner]} WHERE contract_id=? ORDER BY act_date,id', (oid,))
    rows = sorted(rows, key=lambda r: order.get(r[3], len(order)))                     # акты по объектам (порядок объектов), внутри объекта — по дате
    out = []
    for aid, number, day, object_id in rows:
        label = 'Акт № ' + (str(number).strip() or 'б/н')
        if day:
            y, m, d = (str(day)[:10].split('-') + ['', ''])[:3]
            label += f' от {d}.{m}.{y}' if d and m else f' от {day}'
        if object_id in names:
            label += f' · {names[object_id]}'
        out.append((aid, label))
    return out


def items(db, owner, oid):
    """Объёмы договора по порядку: сначала по актам (в порядке дат актов), затем «без акта»; act_id — номер акта или None."""
    _check(owner)
    cur = db.execute('SELECT id,kind,name,unit,quantity,catalog_id,note,act_id FROM volumes WHERE owner_type=? AND owner_id=? ORDER BY sort_order,id', (owner, oid))
    rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
    order = {aid: i for i, (aid, _l) in enumerate(acts(db, owner, oid))}
    rows.sort(key=lambda r: (order.get(r['act_id'], len(order) if r['act_id'] is None else len(order) + 1), 0))      # устойчивая сортировка: внутри акта порядок строк сохраняется
    return rows


def grouped(db, owner, oid):
    """[(act_id|None, подпись, [объёмы])]: ВСЕ акты договора (и пустые) по порядку, затем «Без акта» (если там что-то есть)."""
    rows = items(db, owner, oid)
    out = [(aid, label, [r for r in rows if r['act_id'] == aid]) for aid, label in acts(db, owner, oid)]
    loose = [r for r in rows if r['act_id'] is None or r['act_id'] not in {a for a, _l, _r in out}]
    if loose or not out:
        out.append((None, 'Без акта' if out else 'Объёмы договора', loose))
    return out


def save_items(db, owner, oid, rows):
    """Заменяет объёмы договора. rows: [{kind, name, unit, quantity, catalog_id, note, act_id}]; пустые строки пропускаются.
    act_id — акт этого договора (для СМР: объёмы делятся по актам); чужой или несуществующий акт — ошибка."""
    _check(owner)
    valid_acts = {aid for aid, _l in acts(db, owner, oid)}
    clean = []
    for r in rows:
        name = str(r.get('name') or '').strip()
        qty = float(str(r.get('quantity') or 0).replace(',', '.') or 0)
        if not name and not qty:
            continue
        if not name:
            raise ValueError('Укажите наименование работы или материала')
        if qty < 0:
            raise ValueError(f'«{name}»: количество не может быть отрицательным')
        act_id = r.get('act_id') or None
        if act_id is not None and (not has_acts(owner) or int(act_id) not in valid_acts):
            raise ValueError(f'«{name}»: выбран акт, которого нет в этом договоре')
        kind = r.get('kind') if r.get('kind') in KINDS else 'Материал'
        clean.append((kind, name, str(r.get('unit') or '').strip(), qty, r.get('catalog_id') or None, str(r.get('note') or '').strip(), int(act_id) if act_id else None))
    with db.transaction():
        db.execute('DELETE FROM volumes WHERE owner_type=? AND owner_id=?', (owner, oid))
        for i, row in enumerate(clean):
            db.execute('INSERT INTO volumes(owner_type,owner_id,kind,name,unit,quantity,catalog_id,note,act_id,sort_order) VALUES(?,?,?,?,?,?,?,?,?,?)', (owner, oid, *row, i))
    return len(clean)


def totals(db, owner, oid):
    """Общие объёмы договора (по всем актам): одинаковые позиции суммируются. [{kind,name,unit,quantity,catalog_id}]."""
    merged = {}
    for r in items(db, owner, oid):
        key = (r['kind'], str(r['name']).strip().casefold(), str(r['unit'] or '').strip().casefold())
        if key in merged:
            merged[key]['quantity'] += r['quantity']
        else:
            merged[key] = dict(kind=r['kind'], name=r['name'], unit=r['unit'], quantity=r['quantity'], catalog_id=r['catalog_id'], note='')
    return list(merged.values())


def estimate_id(db, owner, oid):
    _check(owner)
    row = db.fetchone(f'SELECT estimate_id FROM {owner} WHERE id=?', (oid,))
    return row[0] if row else None


def _catalog_price(db, row):
    """Позиция справочника для объёма: по сохранённой ссылке, иначе по совпадению названия и вида."""
    found = None
    if row.get('catalog_id'):
        found = db.fetchone('SELECT id,price,purchase_price,unit,labor_hours,hourly_rate,overhead_pct,profit_pct,other_costs FROM materials WHERE id=?', (row['catalog_id'],))
    if not found:
        found = db.fetchone('SELECT id,price,purchase_price,unit,labor_hours,hourly_rate,overhead_pct,profit_pct,other_costs FROM materials WHERE item_type=? AND LOWER(name)=LOWER(?) ORDER BY id LIMIT 1',
                            (row['kind'], row['name']))
    return found


def _sync(db, owner, oid, eid):
    from . import estimates_domain as ed
    ed.recalc(db, eid)
    if owner == 'contracts':
        from . import gsvm_domain as md
        return md.sync_estimate(db, oid)
    if owner == 'gsn_projects':
        from . import gsn_domain as gn
        return gn.sync_estimate(db, oid)
    from . import contracts_core as cc
    return cc.sync_estimate(db, oid, cc.CONTRACT_TABLES[owner])


def build_estimate(db, owner, oid, replace=False):
    """Формирует смету по объёмам. Нет сметы — создаётся и привязывается к договору; есть смета с позициями — только при replace=True (позиции заменяются).
    Цены берутся из справочника (по ссылке или по названию), позиции вне справочника получают цену 0 — её вводят в смете. Возвращает (id сметы, [названия без цены])."""
    from . import estimates_domain as ed
    _check(owner)
    rows = [r for r in totals(db, owner, oid) if r['quantity'] > 0]          # смета договора — по общим объёмам всех актов
    if not rows:
        raise ValueError('Внесите объёмы работ и материалов (количество больше нуля)')
    unpriced = []
    with db.transaction():
        eid = estimate_id(db, owner, oid)
        if not eid:
            from . import board_domain as board
            title = (board.link_label(db, owner, oid) or OWNERS[owner]).replace(' · ', ' ')
            eid = ed.create_estimate(db, title=f'Смета · {title}', contract=(owner, oid), link=True)
        else:
            existing = db.fetchone("SELECT count(*) FROM estimate_items WHERE estimate_id=? AND item_type<>'Раздел'", (eid,))[0]
            if existing and not replace:
                raise ValueError('В смете договора уже есть позиции. Подтвердите замену позиций сметы объёмами.')
            db.execute('DELETE FROM estimate_items WHERE estimate_id=?', (eid,))
        for i, r in enumerate(rows):
            cat = _catalog_price(db, r)
            price = float(cat[1] or 0) if cat else 0.0
            purchase = float(cat[2] or 0) if cat else 0.0
            unit = r['unit'] or (cat[3] if cat else '') or ''
            if not cat or not price:
                unpriced.append(r['name'])
            if r['kind'] == 'Работа' and cat:
                db.execute("""INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order,purchase_price,labor_hours,hourly_rate,overhead_pct,profit_pct,other_costs)
                              VALUES(?,'Работа',?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (eid, r['name'], unit, r['quantity'], price, round(price * r['quantity'], 2), i, purchase, cat[4] or 0, cat[5] or 0, cat[6] or 0, cat[7] or 0, cat[8] or 0))
            else:
                db.execute('INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order,purchase_price) VALUES(?,?,?,?,?,?,?,?,?)',
                           (eid, r['kind'], r['name'], unit, r['quantity'], price, round(price * r['quantity'], 2), i, purchase))
        _sync(db, owner, oid, eid)
    return eid, unpriced


def fill_from_estimate(db, owner, oid, replace=False):
    """Обратный порядок: объёмы заполняются по позициям привязанной сметы (без цен). Возвращает число внесённых строк."""
    _check(owner)
    eid = estimate_id(db, owner, oid)
    if not eid:
        raise ValueError('К договору не привязана смета')
    positions = db.fetchall("SELECT item_type,name,unit,quantity FROM estimate_items WHERE estimate_id=? AND item_type<>'Раздел' ORDER BY sort_order,id", (eid,))
    if not positions:
        raise ValueError('В смете нет позиций')
    current = items(db, owner, oid)
    if current and not replace:
        raise ValueError('Объёмы уже внесены. Подтвердите замену объёмов данными сметы.')
    rows = []
    for itype, name, unit, qty in positions:
        cat = db.fetchone('SELECT id FROM materials WHERE item_type=? AND LOWER(name)=LOWER(?) ORDER BY id LIMIT 1', (itype, name))
        rows.append(dict(kind=itype if itype in KINDS else 'Материал', name=name, unit=unit or '', quantity=qty or 0, catalog_id=cat[0] if cat else None, note=''))
    return save_items(db, owner, oid, rows)
