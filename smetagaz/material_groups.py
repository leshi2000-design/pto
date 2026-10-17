"""Группы товаров: именованные наборы позиций справочника (материалы и работы) с количествами по умолчанию.
В смете группа добавляется одним действием: позиции подставляются сразу, остаётся указать количество, лишнее убрать. Без Qt."""
from . import estimates_domain as ed

ITEM_COLUMNS = 'm.id,m.name,coalesce(m.unit,\'\'),coalesce(m.price,0),coalesce(m.purchase_price,0),coalesce(m.item_type,\'Материал\'),' \
               'coalesce(m.labor_hours,0),coalesce(m.hourly_rate,0),coalesce(m.overhead_pct,0),coalesce(m.profit_pct,0),coalesce(m.other_costs,0)'


def migrate(db):
    db.execute('CREATE TABLE IF NOT EXISTS material_groups(id INTEGER PRIMARY KEY, name TEXT NOT NULL, note TEXT DEFAULT "", sort_order INTEGER DEFAULT 0)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_material_groups_name ON material_groups(name COLLATE NOCASE)')
    db.execute('CREATE TABLE IF NOT EXISTS material_group_items(id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL, material_id INTEGER NOT NULL, quantity REAL DEFAULT 1, sort_order INTEGER DEFAULT 0)')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_group_items_unique ON material_group_items(group_id, material_id)')
    db.execute('CREATE TRIGGER IF NOT EXISTS material_group_cascade AFTER DELETE ON material_groups BEGIN DELETE FROM material_group_items WHERE group_id=old.id; END')
    db.execute('CREATE TRIGGER IF NOT EXISTS material_group_drop_material AFTER DELETE ON materials BEGIN DELETE FROM material_group_items WHERE material_id=old.id; END')


def _clean(name):
    name = str(name or '').strip()
    if not name:
        raise ValueError('Введите название группы')
    return name


def create(db, name, note=''):
    name = _clean(name)
    if db.fetchone('SELECT 1 FROM material_groups WHERE LOWER(name)=LOWER(?)', (name,)):
        raise ValueError(f'Группа «{name}» уже есть')
    order = (db.fetchone('SELECT max(sort_order) FROM material_groups')[0] or 0) + 1
    return db.execute('INSERT INTO material_groups(name,note,sort_order) VALUES(?,?,?)', (name, str(note or ''), order)).lastrowid


def rename(db, gid, name, note=None):
    name = _clean(name)
    if db.fetchone('SELECT 1 FROM material_groups WHERE LOWER(name)=LOWER(?) AND id<>?', (name, gid)):
        raise ValueError(f'Группа «{name}» уже есть')
    db.execute('UPDATE material_groups SET name=?, note=coalesce(?,note) WHERE id=?', (name, note, gid))


def delete(db, gid):
    db.execute('DELETE FROM material_groups WHERE id=?', (gid,))


def duplicate(db, gid, name=None):
    row = db.fetchone('SELECT name,note FROM material_groups WHERE id=?', (gid,))
    if not row:
        raise ValueError('Группа не найдена')
    base = name or f'{row[0]} (копия)'
    new_name, n = base, 2
    while db.fetchone('SELECT 1 FROM material_groups WHERE LOWER(name)=LOWER(?)', (new_name,)):
        new_name, n = f'{base} {n}', n + 1
    with db.transaction():
        new = create(db, new_name, row[1])
        db.execute('INSERT INTO material_group_items(group_id,material_id,quantity,sort_order) SELECT ?,material_id,quantity,sort_order FROM material_group_items WHERE group_id=?', (new, gid))
    return new


def groups(db):
    """[(id, название, примечание, число позиций)]"""
    return db.fetchall('SELECT g.id,g.name,coalesce(g.note,\'\'),(SELECT count(*) FROM material_group_items i WHERE i.group_id=g.id) FROM material_groups g ORDER BY g.sort_order,g.name COLLATE NOCASE')


def add_items(db, gid, material_ids, quantity=1.0):
    """Добавляет позиции справочника в группу (уже имеющиеся пропускаются). -> сколько добавлено."""
    added = 0
    order = (db.fetchone('SELECT max(sort_order) FROM material_group_items WHERE group_id=?', (gid,))[0] or 0)
    with db.transaction():
        for mid in material_ids:
            if not db.fetchone('SELECT 1 FROM materials WHERE id=?', (mid,)) or db.fetchone('SELECT 1 FROM material_group_items WHERE group_id=? AND material_id=?', (gid, mid)):
                continue
            order += 1
            db.execute('INSERT INTO material_group_items(group_id,material_id,quantity,sort_order) VALUES(?,?,?,?)', (gid, mid, quantity, order))
            added += 1
    return added


def remove_item(db, gid, material_id):
    db.execute('DELETE FROM material_group_items WHERE group_id=? AND material_id=?', (gid, material_id))


def set_quantity(db, gid, material_id, quantity):
    db.execute('UPDATE material_group_items SET quantity=? WHERE group_id=? AND material_id=?', (max(0.0, float(quantity or 0)), gid, material_id))


def move(db, gid, material_id, direction):
    rows = [r[0] for r in db.fetchall('SELECT material_id FROM material_group_items WHERE group_id=? ORDER BY sort_order,id', (gid,))]
    if material_id not in rows:
        return
    i = rows.index(material_id)
    j = i + direction
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
        for n, mid in enumerate(rows, 1):
            db.execute('UPDATE material_group_items SET sort_order=? WHERE group_id=? AND material_id=?', (n, gid, mid))


def items(db, gid):
    """Позиции группы с актуальными данными справочника: список словарей (id, name, unit, price, purchase_price, type, ..., quantity)."""
    out = []
    for r in db.fetchall(f'SELECT {ITEM_COLUMNS},i.quantity FROM material_group_items i JOIN materials m ON m.id=i.material_id WHERE i.group_id=? ORDER BY i.sort_order,i.id', (gid,)):
        out.append(dict(id=r[0], name=r[1], unit=r[2], price=r[3], purchase_price=r[4], type=r[5], labor_hours=r[6], hourly_rate=r[7], overhead_pct=r[8],
                        profit_pct=r[9], other_costs=r[10], quantity=r[11] if r[11] is not None else 1.0))
    return out


def groups_of_material(db, material_id):
    return [r[0] for r in db.fetchall('SELECT g.name FROM material_group_items i JOIN material_groups g ON g.id=i.group_id WHERE i.material_id=? ORDER BY g.name', (material_id,))]


def insert_into_estimate(db, eid, entries, section=None):
    """Вносит позиции группы в смету. entries — [(позиция из items(), количество)]; позиции с количеством 0 пропускаются.
    section: None — в конец сметы; id существующего раздела; ('new', 'Название') — создать раздел и положить позиции в него.
    Цены и состав стоимости работ запоминаются в строке сметы, как при обычном добавлении из справочника. -> id созданных строк."""
    def next_order():
        return (db.fetchone('SELECT max(sort_order) FROM estimate_items WHERE estimate_id=?', (eid,))[0] or 0) + 1
    created = []
    with db.transaction():
        section_id = section
        if isinstance(section, tuple):
            section_id = db.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order,purchase_price) VALUES(?, 'Раздел', ?, '', 0, 0, 0, ?, 0.0)",
                                    (eid, _clean(section[1]), next_order())).lastrowid
            ed.place_item(db, eid, section_id, None)
        for m, qty in entries:
            qty = float(qty or 0)
            if qty <= 0:
                continue
            total = qty * m['price']
            if m['type'] == 'Работа':
                new = db.execute("""INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order,purchase_price,labor_hours,hourly_rate,overhead_pct,profit_pct,other_costs)
                                    VALUES(?, 'Работа', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                 (eid, m['name'], m['unit'], qty, m['price'], total, next_order(), m['purchase_price'], m['labor_hours'], m['hourly_rate'], m['overhead_pct'], m['profit_pct'], m['other_costs'])).lastrowid
            else:
                new = db.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order,purchase_price) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                 (eid, m['type'], m['name'], m['unit'], qty, m['price'], total, next_order(), m['purchase_price'])).lastrowid
            ed.place_item(db, eid, new, section_id)
            created.append(new)
    return created
