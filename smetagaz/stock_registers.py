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


def save_transfer(db, data, lines, tid=None):
    """lines: [{material_id|None, material_name, unit, quantity, note}]. Без хотя бы одной строки с количеством акт не сохраняется."""
    number = str(data.get('number', '')).strip()
    if not number:
        raise ValueError('Укажите номер акта')
    day = _day(data.get('transfer_date'), 'Дата акта')
    src, dst = str(data.get('from_place', '')).strip(), str(data.get('to_place', '')).strip()
    if not src or not dst:
        raise ValueError('Укажите, откуда и куда переводятся материалы')
    if src.casefold() == dst.casefold():
        raise ValueError('Место отправления и назначения совпадают')
    clean = []
    for line in lines:
        name = str(line.get('material_name', '')).strip()
        if not name and not str(line.get('quantity', '')).strip():
            continue
        if not name:
            raise ValueError('Укажите материал в каждой строке')
        try:
            qty = float(str(line.get('quantity', '')).replace(',', '.').replace(' ', ''))
        except ValueError:
            raise ValueError(f'«{name}»: количество должно быть числом') from None
        if qty <= 0:
            raise ValueError(f'«{name}»: количество должно быть больше нуля')
        clean.append((line.get('material_id'), name, str(line.get('unit', '')).strip(), f'{qty:g}', str(line.get('note', '')).strip()))
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
        for mid, name, unit, qty, note in clean:
            db.execute('INSERT INTO stock_transfer_lines(transfer_id,material_id,material_name,unit,quantity,note) VALUES(?,?,?,?,?,?)', (tid, mid, name, unit, qty, note))
    return tid


def transfer_lines(db, tid):
    return db.fetchall('SELECT material_id,material_name,unit,quantity,note FROM stock_transfer_lines WHERE transfer_id=? ORDER BY id', (tid,))


def copy_transfer(db, tid):
    """Новый акт на основании существующего: те же стороны и материалы, новый номер, сегодняшняя дата."""
    row = db.fetchone('SELECT ' + ','.join(TRANSFER_KEYS) + ' FROM stock_transfers WHERE id=?', (tid,))
    if not row:
        raise ValueError('Акт не найден')
    data = dict(zip(TRANSFER_KEYS, row))
    today = date.today().isoformat()
    data.update(number=next_transfer_number(db, today), transfer_date=today, file_path='')
    lines = [dict(material_id=m, material_name=n, unit=u, quantity=q, note=note) for m, n, u, q, note in transfer_lines(db, tid)]
    return save_transfer(db, data, lines)


def delete_transfer(db, tid):
    db.execute('DELETE FROM stock_transfers WHERE id=?', (tid,))
