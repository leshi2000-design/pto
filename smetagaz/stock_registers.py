"""Журналы раздела «Списание»: приказы и акты перевода (передачи) материалов. Модуль не зависит от Qt.
Акты перевода только регистрируются (остатки склада они не меняют): остатки меняют поступления и акты списания."""
from datetime import date


def _day(value, label='Дата'):
    try:
        date.fromisoformat(str(value))
    except ValueError:
        raise ValueError(f'{label}: укажите дату') from None
    return str(value)


# --- ПРИКАЗЫ -----------------------------------------------------------------------------------

ORDER_KEYS = ('number', 'order_date', 'title', 'content', 'issued_by', 'valid_until', 'file_path', 'notes')


def next_order_number(db, day=None):
    year = (day or date.today().isoformat())[:4]
    count = db.fetchone("SELECT count(*) FROM stock_orders WHERE substr(order_date,1,4)=?", (year,))[0]
    return f'{count + 1}/{year[2:]}'


def save_order(db, data, oid=None):
    number, title = str(data.get('number', '')).strip(), str(data.get('title', '')).strip()
    if not number:
        raise ValueError('Укажите номер приказа')
    if not title:
        raise ValueError('Укажите, о чём приказ')
    day = _day(data.get('order_date'), 'Дата приказа')
    until = str(data.get('valid_until') or '')
    if until and _day(until, 'Срок действия') < day:
        raise ValueError('Срок действия не может быть раньше даты приказа')
    values = (number, day, title, data.get('content', '').strip(), data.get('issued_by', '').strip(), until, data.get('file_path', '') or '', data.get('notes', '').strip())
    dup = db.fetchone('SELECT id FROM stock_orders WHERE number=? AND substr(order_date,1,4)=? AND id<>?', (number, day[:4], oid or 0))
    if dup:
        raise ValueError(f'Приказ №{number} за {day[:4]} год уже зарегистрирован')
    with db.transaction():
        if oid:
            db.execute('UPDATE stock_orders SET ' + ','.join(k + '=?' for k in ORDER_KEYS) + ' WHERE id=?', (*values, oid))
            return oid
        return db.execute('INSERT INTO stock_orders(' + ','.join(ORDER_KEYS) + ') VALUES(' + ','.join('?' for _ in ORDER_KEYS) + ')', values).lastrowid


def delete_order(db, oid):
    db.execute('DELETE FROM stock_orders WHERE id=?', (oid,))


# --- АКТЫ ПЕРЕВОДА МАТЕРИАЛОВ --------------------------------------------------------------------

TRANSFER_KEYS = ('number', 'transfer_date', 'from_place', 'to_place', 'reason', 'approved_by', 'commission', 'file_path', 'notes')


def next_transfer_number(db, day=None):
    day = day or date.today().isoformat()
    count = db.fetchone("SELECT count(*) FROM stock_transfers WHERE substr(transfer_date,1,4)=?", (day[:4],))[0]
    return f'АП-{day[:4]}-{count + 1}'


def _num(value, label, positive=True):
    try:
        n = float(str(value).replace(',', '.').replace(' ', ''))
    except ValueError:
        raise ValueError(f'{label}: введите число') from None
    if positive and n <= 0:
        raise ValueError(f'{label}: число должно быть больше нуля')
    if n < 0:
        raise ValueError(f'{label}: число не может быть отрицательным')
    return n


def catalog_item(db, name, unit):
    """Позиция справочника цен («Справочник» → материалы) с таким названием и единицей: (id, закупочная, продажная, раздел, примечание) или None."""
    return db.fetchone("SELECT id,coalesce(purchase_price,0),coalesce(price,0),category_id,coalesce(note,'') FROM materials WHERE item_type='Материал' AND LOWER(name)=LOWER(?) AND LOWER(unit)=LOWER(?) ORDER BY id LIMIT 1",
                       (str(name).strip(), str(unit).strip()))


def default_cost(db, name, unit, qty):
    """Стоимость партии по справочнику: цена за прежнюю единицу × количество (None, если материала нет в справочнике)."""
    item = catalog_item(db, name, unit)
    if not item:
        return None
    price = item[1] or item[2]
    return round(price * float(qty), 2) if price else None


def unit_prices(cost, qty, new_qty):
    """Цена за единицу до и после перевода: стоимость партии не меняется, меняется количество и единица. Пример: 1 шт за 120 → 5,05 м³ даёт 23,7624 за м³."""
    return (round(cost / qty, 4) if qty else None, round(cost / new_qty, 4) if new_qty else None)


def save_transfer(db, data, lines, tid=None):
    """Акт перевода. lines: [{material_id, material_name, unit, quantity, note, new_unit, new_quantity, cost}].
    Строка с новой единицей и новым количеством — перевод единиц измерения (при проведении меняет склад и цену за единицу); без них — информационная."""
    number = str(data.get('number', '')).strip()
    if not number:
        raise ValueError('Укажите номер акта')
    day = _day(data.get('transfer_date'), 'Дата акта')
    src, dst = str(data.get('from_place', '')).strip(), str(data.get('to_place', '')).strip()
    if src and dst and src.casefold() == dst.casefold():
        raise ValueError('Место отправления и назначения совпадают')
    if tid and db.fetchone('SELECT posted FROM stock_transfers WHERE id=?', (tid,)) and db.fetchone('SELECT posted FROM stock_transfers WHERE id=?', (tid,))[0]:
        raise ValueError('Акт проведён: сначала отмените проведение, затем меняйте строки')
    clean = []
    for line in lines:
        name = str(line.get('material_name', '')).strip()
        if not name and not str(line.get('quantity', '')).strip():
            continue
        if not name:
            raise ValueError('Укажите материал в каждой строке')
        qty = _num(line.get('quantity', ''), f'«{name}»: количество')
        new_unit, new_q_raw = str(line.get('new_unit', '') or '').strip(), str(line.get('new_quantity', '') or '').strip()
        new_qty = cost = old_price = new_price = None
        if new_unit or new_q_raw:
            if not new_unit or not new_q_raw:
                raise ValueError(f'«{name}»: укажите и новую единицу, и новое количество')
            if new_unit.casefold() == str(line.get('unit', '')).strip().casefold():
                raise ValueError(f'«{name}»: новая единица совпадает со старой')
            new_qty = _num(new_q_raw, f'«{name}»: новое количество')
            raw_cost = str(line.get('cost', '') if line.get('cost', '') is not None else '').strip()
            cost = _num(raw_cost, f'«{name}»: стоимость', positive=False) if raw_cost else None
            if cost is None:
                cost = default_cost(db, name, line.get('unit', ''), qty)
            if cost is None:
                raise ValueError(f'«{name}»: укажите стоимость партии — в справочнике цен такого материала нет')
            old_price, new_price = unit_prices(cost, qty, new_qty)
        clean.append((line.get('material_id'), name, str(line.get('unit', '')).strip(), f'{qty:g}', str(line.get('note', '')).strip(),
                      new_unit, f'{new_qty:g}' if new_qty else '', cost, old_price, new_price))
    if not clean:
        raise ValueError('Добавьте хотя бы один материал')
    dup = db.fetchone('SELECT id FROM stock_transfers WHERE number=? AND substr(transfer_date,1,4)=? AND id<>?', (number, day[:4], tid or 0))
    if dup:
        raise ValueError(f'Акт перевода №{number} за {day[:4]} год уже зарегистрирован')
    values = tuple(str(data.get(k, '') or '').strip() if k != 'transfer_date' else day for k in TRANSFER_KEYS)
    with db.transaction():
        if tid:
            db.execute('UPDATE stock_transfers SET ' + ','.join(k + '=?' for k in TRANSFER_KEYS) + ' WHERE id=?', (*values, tid))
            db.execute('DELETE FROM stock_transfer_lines WHERE transfer_id=?', (tid,))
        else:
            tid = db.execute('INSERT INTO stock_transfers(' + ','.join(TRANSFER_KEYS) + ') VALUES(' + ','.join('?' for _ in TRANSFER_KEYS) + ')', values).lastrowid
        for row in clean:
            db.execute('INSERT INTO stock_transfer_lines(transfer_id,material_id,material_name,unit,quantity,note,new_unit,new_quantity,cost,old_price,new_price) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (tid, *row))
    return tid


def transfer_lines(db, tid):
    return db.fetchall('SELECT material_id,material_name,unit,quantity,note FROM stock_transfer_lines WHERE transfer_id=? ORDER BY id', (tid,))


def transfer_conversions(db, tid):
    """Строки акта полностью: словари (в том числе стоимость, новые единица / количество и цены за единицу)."""
    cur = db.execute('SELECT id,material_id,material_name,unit,quantity,note,new_unit,new_quantity,cost,old_price,new_price,new_material_id FROM stock_transfer_lines WHERE transfer_id=? ORDER BY id', (tid,))
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def is_posted(db, tid):
    row = db.fetchone('SELECT posted FROM stock_transfers WHERE id=?', (tid,))
    return bool(row and row[0])


def post_transfer(db, tid, update_catalog=True):
    """Проводит акт перевода: на складе прежний материал (в старой единице) списывается, новый (в новой единице) оприходуется на то же количество;
    цена за новую единицу = стоимость партии / новое количество записывается в справочник цен (создаётся позиция с новой единицей или обновляется существующая)."""
    from . import stock_domain as st
    t = db.fetchone('SELECT number,transfer_date,posted FROM stock_transfers WHERE id=?', (tid,))
    if not t:
        raise ValueError('Акт не найден')
    if t[2]:
        raise ValueError('Акт уже проведён')
    lines = [l for l in transfer_conversions(db, tid) if l['new_unit'] and l['new_quantity']]
    if not lines:
        raise ValueError('В акте нет строк перевода: укажите новую единицу и новое количество')
    note = f'Акт перевода № {t[0]}'
    with db.transaction():
        for l in lines:
            name = l['material_name']
            if not l['material_id']:
                raise ValueError(f'«{name}»: выберите материал из списка склада — вписанный вручную перевести нельзя')
            sname, category, old_unit = st.material(db, l['material_id'])
            qty, new_qty = st.units(l['quantity'], True), st.units(l['new_quantity'], True)
            row = db.fetchone('SELECT id FROM stock_materials WHERE LOWER(name)=LOWER(?) AND LOWER(unit)=LOWER(?) AND coalesce(active,1)=1', (sname, l['new_unit']))
            new_mid = row[0] if row else st.save_material(db, sname, category, l['new_unit'])
            db.execute('INSERT INTO stock_moves(material_id,move_date,qty,kind,note,transfer_id) VALUES(?,?,?,?,?,?)', (l['material_id'], t[1], -qty, 'transfer_out', note, tid))
            db.execute('INSERT INTO stock_moves(material_id,move_date,qty,kind,note,transfer_id) VALUES(?,?,?,?,?,?)', (new_mid, t[1], new_qty, 'transfer_in', note, tid))
            st.check_timeline(db, l['material_id'])
            st.check_timeline(db, new_mid)
            cat_id = prev_purchase = prev_price = None
            created = 0
            if update_catalog and l['new_price'] is not None:
                src = catalog_item(db, sname, old_unit)
                ratio = (src[2] / src[1]) if src and src[1] > 0 and src[2] > 0 else 1.0
                purchase, sell = l['new_price'], round(l['new_price'] * ratio, 2)
                dst = catalog_item(db, sname, l['new_unit'])
                if dst:
                    cat_id, prev_purchase, prev_price = dst[0], dst[1], dst[2]
                    db.execute('UPDATE materials SET purchase_price=?,price=? WHERE id=?', (purchase, sell, cat_id))
                else:
                    cat_id = db.execute("INSERT INTO materials(category_id,name,unit,price,purchase_price,item_type,note) VALUES(?,?,?,?,?,'Материал',?)",
                                        (src[3] if src else None, sname, l['new_unit'], sell, purchase, f'Из акта перевода № {t[0]}')).lastrowid
                    created = 1
            db.execute('UPDATE stock_transfer_lines SET new_material_id=?,cat_id=?,cat_prev_purchase=?,cat_prev_price=?,cat_created=? WHERE id=?', (new_mid, cat_id, prev_purchase, prev_price, created, l['id']))
        db.execute('UPDATE stock_transfers SET posted=1 WHERE id=?', (tid,))
    return len(lines)


def reverse_transfer(db, tid):
    """Отмена проведения: движения склада гасятся обратными, цены справочника возвращаются (созданная актом позиция удаляется)."""
    from . import stock_domain as st
    t = db.fetchone('SELECT number,transfer_date,posted FROM stock_transfers WHERE id=?', (tid,))
    if not t or not t[2]:
        raise ValueError('Акт не проведён')
    note = f'Отмена акта перевода № {t[0]}'
    with db.transaction():
        for qty_row in db.fetchall('SELECT material_id,qty FROM stock_moves WHERE transfer_id=? AND kind IN (?,?)', (tid, 'transfer_out', 'transfer_in')):
            db.execute('INSERT INTO stock_moves(material_id,move_date,qty,kind,note,transfer_id) VALUES(?,?,?,?,?,?)', (qty_row[0], date.today().isoformat(), -qty_row[1], 'transfer_reversal', note, tid))
        for mid in {r[0] for r in db.fetchall('SELECT material_id FROM stock_moves WHERE transfer_id=?', (tid,))}:
            st.check_timeline(db, mid)
        for l in db.fetchall('SELECT cat_id,cat_prev_purchase,cat_prev_price,cat_created FROM stock_transfer_lines WHERE transfer_id=? AND cat_id IS NOT NULL', (tid,)):
            if l[3]:
                db.execute('DELETE FROM materials WHERE id=?', (l[0],))
            else:
                db.execute('UPDATE materials SET purchase_price=?,price=? WHERE id=?', (l[1], l[2], l[0]))
        db.execute('UPDATE stock_transfers SET posted=0 WHERE id=?', (tid,))


def copy_transfer(db, tid):
    """Новый акт на основании существующего: те же стороны и материалы, новый номер, сегодняшняя дата."""
    row = db.fetchone('SELECT ' + ','.join(TRANSFER_KEYS) + ' FROM stock_transfers WHERE id=?', (tid,))
    if not row:
        raise ValueError('Акт не найден')
    data = dict(zip(TRANSFER_KEYS, row))
    today = date.today().isoformat()
    data.update(number=next_transfer_number(db, today), transfer_date=today, file_path='')
    lines = [dict(material_id=l['material_id'], material_name=l['material_name'], unit=l['unit'], quantity=l['quantity'], note=l['note'], new_unit=l['new_unit'],
                  new_quantity=l['new_quantity'], cost=l['cost']) for l in transfer_conversions(db, tid)]
    return save_transfer(db, data, lines)


def delete_transfer(db, tid):
    if is_posted(db, tid):
        raise ValueError('Акт проведён: сначала отмените проведение')
    db.execute('DELETE FROM stock_transfers WHERE id=?', (tid,))
