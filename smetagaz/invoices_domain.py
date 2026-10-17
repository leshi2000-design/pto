"""Накладные: хранение разобранных накладных (шапка, поставщик, получатель, товары), поиск повторов, перенос в справочник материалов, на склад и в справочник юрлиц.
Разбор файлов — invoice_parse.py. Без Qt."""
import difflib
import re
from datetime import date, datetime

HEADER_FIELDS = ('kind', 'number', 'doc_date', 'currency', 'source', 'supplier_name', 'supplier_unp', 'supplier_address', 'supplier_account', 'supplier_bank', 'supplier_bic',
                 'buyer_name', 'buyer_unp', 'buyer_address', 'sum_total', 'vat_total', 'total_with_vat', 'note', 'file_path', 'incoming_id')
ITEM_FIELDS = ('name', 'unit', 'qty', 'price', 'sum', 'vat_rate', 'vat_sum', 'total')


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY, kind TEXT DEFAULT 'Накладная', number TEXT DEFAULT '', doc_date TEXT DEFAULT '', currency TEXT DEFAULT 'BYN',
        source TEXT DEFAULT '', supplier_name TEXT DEFAULT '', supplier_unp TEXT DEFAULT '', supplier_address TEXT DEFAULT '', supplier_account TEXT DEFAULT '', supplier_bank TEXT DEFAULT '',
        supplier_bic TEXT DEFAULT '', buyer_name TEXT DEFAULT '', buyer_unp TEXT DEFAULT '', buyer_address TEXT DEFAULT '', sum_total REAL, vat_total REAL, total_with_vat REAL,
        note TEXT DEFAULT '', file_path TEXT DEFAULT '', incoming_id INTEGER, legal_id INTEGER, stocked INTEGER DEFAULT 0, catalog_done INTEGER DEFAULT 0, created_at TEXT DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS invoice_items(id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL, pos INTEGER DEFAULT 0, name TEXT DEFAULT '', unit TEXT DEFAULT '',
        qty REAL, price REAL, sum REAL, vat_rate REAL, vat_sum REAL, total REAL, material_id INTEGER)""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_unp, number)')
    db.execute('CREATE TRIGGER IF NOT EXISTS invoice_cascade AFTER DELETE ON invoices BEGIN DELETE FROM invoice_items WHERE invoice_id=old.id; END')


def from_parsed(result):
    """Результат invoice_parse -> плоская запись для сохранения и показа (строковые поля, список строк)."""
    s, b, t = result.get('supplier') or {}, result.get('buyer') or {}, result.get('totals') or {}
    return dict(kind=result.get('kind') or 'Накладная', number=result.get('number') or '', doc_date=result.get('date') or '', currency=result.get('currency') or 'BYN', source=result.get('source') or '',
                supplier_name=s.get('name', ''), supplier_unp=s.get('unp', ''), supplier_address=s.get('address', ''), supplier_account=s.get('account', ''), supplier_bank=s.get('bank', ''),
                supplier_bic=s.get('bic', ''), buyer_name=b.get('name', ''), buyer_unp=b.get('unp', ''), buyer_address=b.get('address', ''),
                sum_total=t.get('sum'), vat_total=t.get('vat'), total_with_vat=t.get('total'),
                items=[{k: it.get(k) for k in ITEM_FIELDS} for it in result.get('items') or []])


def _num(value):
    try:
        return float(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def totals_of(items):
    s = round(sum(_num(i.get('sum')) or 0 for i in items), 2)
    t = round(sum(_num(i.get('total')) or _num(i.get('sum')) or 0 for i in items), 2)
    return s, round(t - s, 2), t


def validate(data):
    if not str(data.get('number') or '').strip():
        raise ValueError('Укажите номер накладной')
    if not str(data.get('supplier_name') or '').strip() and not str(data.get('supplier_unp') or '').strip():
        raise ValueError('Укажите поставщика (название или УНП)')
    unp = str(data.get('supplier_unp') or '').strip()
    if unp and not re.fullmatch(r'\d{9}', unp):
        raise ValueError('УНП — 9 цифр')
    if data.get('doc_date'):
        try:
            date.fromisoformat(data['doc_date'])
        except ValueError:
            raise ValueError('Дата накладной указана неверно')
    if not data.get('items'):
        raise ValueError('В накладной нет ни одной строки товаров')
    for n, it in enumerate(data['items'], 1):
        if not str(it.get('name') or '').strip():
            raise ValueError(f'Строка {n}: укажите наименование')


def find_duplicate(db, data, exclude=None):
    """Уже сохранённая накладная того же поставщика с тем же номером и датой."""
    unp = str(data.get('supplier_unp') or '').strip()
    name = str(data.get('supplier_name') or '').strip().casefold()
    number = str(data.get('number') or '').strip().casefold()
    for rid, u, n, num, day in db.fetchall('SELECT id,supplier_unp,supplier_name,number,doc_date FROM invoices'):
        if rid == exclude or str(num or '').strip().casefold() != number or str(day or '') != str(data.get('doc_date') or ''):
            continue
        if (unp and u == unp) or (not unp and str(n or '').strip().casefold() == name):
            return rid
    return None


def save(db, data, iid=None):
    """Сохраняет накладную со строками. Возвращает id. Повтор (тот же поставщик, номер, дата) — ValueError."""
    validate(data)
    dup = find_duplicate(db, data, iid)
    if dup:
        raise ValueError(f'Такая накладная уже сохранена (№ {dup}). Откройте её во вкладке «Накладные».')
    s, v, t = totals_of(data['items'])
    values = {k: data.get(k, '') for k in HEADER_FIELDS}
    values.update(sum_total=_num(data.get('sum_total')) if data.get('sum_total') is not None else s, vat_total=_num(data.get('vat_total')) if data.get('vat_total') is not None else v,
                  total_with_vat=_num(data.get('total_with_vat')) if data.get('total_with_vat') is not None else t)
    with db.transaction():
        if iid:
            db.execute('UPDATE invoices SET ' + ','.join(f'{k}=?' for k in values) + ' WHERE id=?', (*values.values(), iid))
            db.execute('DELETE FROM invoice_items WHERE invoice_id=?', (iid,))
        else:
            values['created_at'] = datetime.now().isoformat(timespec='seconds')
            iid = db.execute('INSERT INTO invoices(' + ','.join(values) + ') VALUES(' + ','.join('?' for _ in values) + ')', tuple(values.values())).lastrowid
        for pos, it in enumerate(data['items'], 1):
            db.execute('INSERT INTO invoice_items(invoice_id,pos,name,unit,qty,price,sum,vat_rate,vat_sum,total,material_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (iid, pos, str(it['name']).strip(), str(it.get('unit') or '').strip(), _num(it.get('qty')), _num(it.get('price')), _num(it.get('sum')),
                        _num(it.get('vat_rate')), _num(it.get('vat_sum')), _num(it.get('total')), it.get('material_id')))
    return iid


def get(db, iid):
    cols = ['id', 'legal_id', 'stocked', 'catalog_done', 'created_at'] + list(HEADER_FIELDS)
    row = db.fetchone('SELECT ' + ','.join(cols) + ' FROM invoices WHERE id=?', (iid,))
    if not row:
        return None
    data = dict(zip(cols, row))
    data['items'] = [dict(zip(('id',) + ITEM_FIELDS + ('material_id',), r)) for r in
                     db.fetchall('SELECT id,name,unit,qty,price,sum,vat_rate,vat_sum,total,material_id FROM invoice_items WHERE invoice_id=? ORDER BY pos,id', (iid,))]
    return data


def listing(db, search='', supplier_unp='', limit=500):
    sql = ('SELECT i.id,i.doc_date,i.number,i.supplier_name,i.supplier_unp,i.total_with_vat,(SELECT count(*) FROM invoice_items x WHERE x.invoice_id=i.id),i.stocked,i.source '
           'FROM invoices i WHERE 1=1')
    args = []
    if search.strip():
        like = '%' + search.strip().casefold() + '%'
        sql += (' AND (LOWER(i.number) LIKE ? OR LOWER(i.supplier_name) LIKE ? OR i.supplier_unp LIKE ? OR EXISTS(SELECT 1 FROM invoice_items x WHERE x.invoice_id=i.id AND LOWER(x.name) LIKE ?))')
        args += [like, like, like, like]
    if supplier_unp:
        sql += ' AND i.supplier_unp=?'
        args.append(supplier_unp)
    return db.fetchall(sql + ' ORDER BY coalesce(nullif(i.doc_date,\'\'),i.created_at) DESC, i.id DESC LIMIT ?', (*args, limit))


def delete(db, iid):
    db.execute('DELETE FROM invoices WHERE id=?', (iid,))


# --- СОПОСТАВЛЕНИЕ СО СПРАВОЧНИКОМ ---------------------------------------------------------------

def _norm(text):
    text = str(text or '').casefold().replace('ё', 'е')
    text = text.translate(str.maketrans('abcehkmoptxy', 'авсенкмортху'))        # латиница, похожая на кириллицу
    return re.sub(r'[^0-9a-zа-я]+', ' ', text).strip()


def catalog_index(db):
    """Справочник материалов, подготовленный для быстрого сопоставления (названия нормализованы один раз)."""
    out = []
    for rid, nm, price, buy, unit in db.fetchall('SELECT id,name,coalesce(price,0),coalesce(purchase_price,0),coalesce(unit,\'\') FROM materials'):
        norm = _norm(nm)
        if norm:
            out.append((rid, nm, price, buy, unit, norm, set(norm.split())))
    return out


def match_catalog(db, name, unit='', limit=3, index=None):
    """Похожие позиции справочника: [(id, название, цена, закупочная, доля сходства)] по убыванию сходства (≥ 0.6).
    index — результат catalog_index(db), чтобы не читать справочник заново для каждой строки."""
    target = _norm(name)
    if not target:
        return []
    words = set(target.split())
    scored = []
    matcher = difflib.SequenceMatcher(None)
    matcher.set_seq2(target)
    for rid, nm, price, buy, u, cand, cwords in (index if index is not None else catalog_index(db)):
        union = len(words | cwords)
        overlap = len(words & cwords) / union if union else 0
        matcher.set_seq1(cand)
        if overlap == 0 and (matcher.real_quick_ratio() < 0.6 or matcher.quick_ratio() < 0.6):
            continue
        score = max(matcher.ratio(), overlap)
        if unit and u and _norm(u) != _norm(unit):
            score -= 0.05
        if score >= 0.6:
            scored.append((rid, nm, price, buy, round(score, 2)))
    return sorted(scored, key=lambda r: -r[4])[:limit]


def apply_to_catalog(db, iid, markup_pct=0.0, update_existing=True, add_new=True):
    """Закупочные цены из накладной -> справочник. Совпавшие позиции (сходство ≥ 0.85 или точное) обновляют закупочную цену (и цену продажи, если она пуста или ниже закупочной);
    новые добавляются с ценой продажи = закупочная + наценка. -> {'updated': n, 'added': n, 'skipped': n}"""
    inv = get(db, iid)
    report = dict(updated=0, added=0, skipped=0)
    index = catalog_index(db)
    with db.transaction():
        for it in inv['items']:
            price = _num(it['price'])
            if price is None:
                report['skipped'] += 1
                continue
            match = (match_catalog(db, it['name'], it['unit'], 1, index) or [None])[0]
            if match and match[4] >= 0.85:
                if update_existing:
                    sell = match[2] if match[2] and match[2] >= price else round(price * (1 + markup_pct / 100), 2)
                    db.execute('UPDATE materials SET purchase_price=?, price=? WHERE id=?', (price, sell, match[0]))
                    db.execute('UPDATE invoice_items SET material_id=? WHERE id=?', (match[0], it['id']))
                    report['updated'] += 1
                else:
                    report['skipped'] += 1
            elif add_new:
                mid = db.execute("INSERT INTO materials(category_id,name,unit,price,purchase_price,item_type,note) VALUES(NULL,?,?,?,?, 'Материал', ?)",
                                 (it['name'], it['unit'], round(price * (1 + markup_pct / 100), 2), price, f'Из накладной № {inv["number"]} ({inv["supplier_name"]})')).lastrowid
                db.execute('UPDATE invoice_items SET material_id=? WHERE id=?', (mid, it['id']))
                report['added'] += 1
            else:
                report['skipped'] += 1
        db.execute('UPDATE invoices SET catalog_done=1 WHERE id=?', (iid,))
    return report


def receive_to_stock(db, iid, day=None):
    """Оприходовать товары накладной на склад (раздел «Списание → материалы»). Повторно оприходовать ту же накладную нельзя. -> число принятых позиций."""
    from . import stock_domain as st
    inv = get(db, iid)
    if inv['stocked']:
        raise ValueError('Эта накладная уже оприходована на склад')
    day = day or inv['doc_date'] or date.today().isoformat()
    note = f'Накладная № {inv["number"]} от {inv["doc_date"] or "—"}, {inv["supplier_name"] or inv["supplier_unp"]}'
    count = 0
    with db.transaction():
        for it in inv['items']:
            qty = _num(it['qty'])
            if not qty or qty <= 0:
                continue
            row = db.fetchone('SELECT id FROM stock_materials WHERE LOWER(name)=LOWER(?) AND LOWER(unit)=LOWER(?)', (it['name'].strip(), (it['unit'] or 'шт').strip()))
            mid = row[0] if row else st.save_material(db, it['name'], 'Из накладных', it['unit'] or 'шт')
            st.receive(db, mid, qty, day, note)
            count += 1
        db.execute('UPDATE invoices SET stocked=1 WHERE id=?', (iid,))
    return count


def ensure_supplier(db, data):
    """Добавляет поставщика в справочник юрлиц, если организации с таким УНП там ещё нет. -> (id, создан ли)."""
    from . import contracts_core as cc
    unp = str(data.get('supplier_unp') or '').strip()
    if unp:
        row = db.fetchone('SELECT id FROM le_clients WHERE unp=?', (unp,))
        if row:
            return row[0], False
    values = dict(name=data.get('supplier_name') or unp, unp=unp, full_name=data.get('supplier_name') or '', legal_address=data.get('supplier_address') or '',
                  account=data.get('supplier_account') or '', bank=data.get('supplier_bank') or '', bic=data.get('supplier_bic') or '', note='Добавлено из накладной')
    lid = cc.save_legal(db, values)
    return lid, True
