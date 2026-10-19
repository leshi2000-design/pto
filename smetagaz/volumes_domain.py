"""Объёмы работ и материалов, потраченных на объект строительства (без цен), и смета, которую из них составляют.

Порядок «договор → работа → объёмы → смета»: объёмы вносятся в карточке договора, кнопка «Сформировать смету» создаёт смету с ценами из справочника
и привязывает её к договору. Обратный порядок: смета составлена заранее (предварительно), договор создан позже, смета привязана к нему —
кнопка «Внести объёмы из сметы» заполняет объёмы по позициям сметы."""
from datetime import datetime

OWNERS = {'contracts': 'Монтаж ГСВ', 'gsn_projects': 'Монтаж ГСН', 'smr_contracts': 'СМР (юрлица)', 'ip_contracts': 'СМР (ИП)', 'fl_contracts': 'СМР (физлица)'}
KINDS = ('Работа', 'Материал')


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS volumes(id INTEGER PRIMARY KEY, owner_type TEXT NOT NULL, owner_id INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'Материал',
        name TEXT NOT NULL, unit TEXT DEFAULT '', quantity REAL NOT NULL DEFAULT 0, catalog_id INTEGER, note TEXT DEFAULT '', sort_order INTEGER DEFAULT 0)""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_volumes_owner ON volumes(owner_type,owner_id)')
    for table in OWNERS:         # удалённый договор не оставляет объёмов (номера записей могут использоваться повторно)
        if db.fetchone('SELECT 1 FROM sqlite_master WHERE type=? AND name=?', ('table', table)):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS volumes_cleanup_{table} AFTER DELETE ON {table} BEGIN DELETE FROM volumes WHERE owner_type='{table}' AND owner_id=old.id; END")


def _check(owner):
    if owner not in OWNERS:
        raise ValueError('В этом разделе вкладка «Объёмы» не предусмотрена')


def items(db, owner, oid):
    _check(owner)
    cur = db.execute('SELECT id,kind,name,unit,quantity,catalog_id,note FROM volumes WHERE owner_type=? AND owner_id=? ORDER BY sort_order,id', (owner, oid))
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def save_items(db, owner, oid, rows):
    """Заменяет объёмы договора. rows: [{kind, name, unit, quantity, catalog_id, note}]; пустые строки пропускаются."""
    _check(owner)
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
        kind = r.get('kind') if r.get('kind') in KINDS else 'Материал'
        clean.append((kind, name, str(r.get('unit') or '').strip(), qty, r.get('catalog_id') or None, str(r.get('note') or '').strip()))
    with db.transaction():
        db.execute('DELETE FROM volumes WHERE owner_type=? AND owner_id=?', (owner, oid))
        for i, row in enumerate(clean):
            db.execute('INSERT INTO volumes(owner_type,owner_id,kind,name,unit,quantity,catalog_id,note,sort_order) VALUES(?,?,?,?,?,?,?,?,?)', (owner, oid, *row, i))
    return len(clean)


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
    rows = [r for r in items(db, owner, oid) if r['quantity'] > 0]
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
