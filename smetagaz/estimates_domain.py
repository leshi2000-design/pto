"""Сметы: расчёт итога без начислений, клиент и договор сметы, расшифровка работ и маржа, теги шаблонов. Без зависимости от Qt.

Начисления на работы (СоцСтрах, ОХР и ОПР, плановая прибыль, НДС) из сметы убраны: каждая работа справочника уже содержит их в своей цене.
Остались скидки и наценки на материалы, работы и итог.
"""
import re
from datetime import date, datetime
from decimal import Decimal

from . import board_domain as board
from .gsvm_docs import FORMATS, apply_format

# разделы, у которых есть связь со сметой (столбец estimate_id)
CONTRACT_TABLES = {'contracts': 'Монтаж ГСВ', 'gsv_projects': 'Проект ГСВ', 'gsn_projects': 'Монтаж ГСН', 'smr_contracts': 'СМР'}
# значения прежних начислений в контексте шаблонов сохранены нулями, чтобы уже подключённые шаблоны не ломались
LEGACY_ZERO_KEYS = ('social_total', 'overhead_total', 'profit_total', 'vat_total')
HIDDEN_KEYS = {'has_overhead', 'overhead_pct', 'has_profit', 'profit_pct', 'has_vat', 'vat_pct', 'has_social', 'social_pct', *LEGACY_ZERO_KEYS}


def D(value):
    return Decimal(str(value or 0))


# --- МИГРАЦИЯ --------------------------------------------------------------------------------

def migrate(db):
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(estimates)')}
    for name, ddl in (('le_client_id', 'INTEGER'), ('party_name', "TEXT DEFAULT ''")):
        if name not in cols:
            db.execute(f'ALTER TABLE estimates ADD COLUMN {name} {ddl}')
    db.execute("""CREATE TABLE IF NOT EXISTS est_tags(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, source TEXT NOT NULL, fmt TEXT NOT NULL DEFAULT 'text',
        empty_text TEXT DEFAULT '', auto_key TEXT UNIQUE, enabled INTEGER NOT NULL DEFAULT 1, note TEXT DEFAULT '')""")
    if db.get_setting('est_no_surcharges', '0') != '1':
        # однократно: начисления отключаются, итоги пересчитываются по новой формуле (резервная копия делается при обновлении версии)
        db.execute('UPDATE estimates SET has_overhead=0,has_profit=0,has_vat=0,has_social=0')
        for (eid,) in db.fetchall('SELECT id FROM estimates'):
            recalc(db, eid)
        db.set_setting('est_no_surcharges', '1')


# --- ИТОГ ------------------------------------------------------------------------------------

def totals(db, eid):
    """База и итоги сметы с учётом скидок/наценок. Итого = (материалы + работы) с наценкой на итог; начислений нет."""
    sums = {'mat': Decimal(0), 'work': Decimal(0)}
    for itype, amount in db.fetchall('SELECT item_type,coalesce(sum,0) FROM estimate_items WHERE estimate_id=?', (eid,)):
        if itype == 'Раздел':
            continue
        sums['work' if itype == 'Работа' else 'mat'] += D(amount)
    row = db.fetchone('SELECT coalesce(mat_adj_pct,0),coalesce(work_adj_pct,0),coalesce(total_adj_pct,0) FROM estimates WHERE id=?', (eid,)) or (0, 0, 0)
    mat_adj, work_adj, tot_adj = D(row[0]), D(row[1]), D(row[2])
    adj_mat = sums['mat'] * (1 + mat_adj / 100)
    adj_work = sums['work'] * (1 + work_adj / 100)
    subtotal = adj_mat + adj_work
    total = subtotal * (1 + tot_adj / 100)
    return dict(base_mat=sums['mat'], base_work=sums['work'], base=sums['mat'] + sums['work'], adj_mat=adj_mat, adj_work=adj_work, subtotal=subtotal,
                total=total, mat_adj=mat_adj, work_adj=work_adj, tot_adj=tot_adj)


def recalc(db, eid):
    """Записывает итог сметы (с точностью до копейки). Возвращает число."""
    total = round(float(totals(db, eid)['total']), 2)
    db.execute('UPDATE estimates SET total=? WHERE id=?', (total, eid))
    return total


# --- РАСШИФРОВКА РАБОТ И МАРЖА ---------------------------------------------------------------

def rows(db, sql, params=()):
    cur = db.execute(sql, params)
    return [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]


def breakdown(db, eid):
    """(строки работ, строки материалов, итоги) для окна «Расшифровка и маржа» и шаблонов. Работы раскладываются по статьям формулы справочника."""
    from .work_pricing import compute_work_price, has_breakdown
    work_rows = rows(db, """SELECT name,unit,quantity,price,sum amount,purchase_price,labor_hours,hourly_rate,overhead_pct,profit_pct,other_costs
                            FROM estimate_items WHERE estimate_id=? AND item_type='Работа' ORDER BY sort_order,id""", (eid,))
    sums = {k: Decimal(0) for k in ('wage', 'overhead', 'profit', 'social', 'other', 'tax')}
    for r in work_rows:
        qty = D(r['quantity'])
        if has_breakdown(r['labor_hours'], r['hourly_rate'], r['overhead_pct'], r['profit_pct'], r['other_costs']):
            b = compute_work_price(r['labor_hours'], r['hourly_rate'], r['overhead_pct'], r['profit_pct'], r['other_costs'])
            r['has_breakdown'] = 'Да'
            for key in sums:
                r[key + '_unit'] = b[key]
                r[key + '_sum'] = b[key] * qty
                sums[key] += b[key] * qty
        else:
            r['has_breakdown'] = 'Нет данных'
            for key in sums:
                r[key + '_unit'] = 'нет данных'
                r[key + '_sum'] = 'нет данных'
        r['cost_sum'] = D(r['purchase_price']) * qty
        r['margin_sum'] = D(r['amount']) - r['cost_sum']
    materials = rows(db, "SELECT name,unit,quantity,price,purchase_price,sum amount FROM estimate_items WHERE estimate_id=? AND item_type<>'Работа' AND item_type<>'Раздел' ORDER BY sort_order,id", (eid,))
    margin_total = Decimal(0)
    for r in materials:
        qty, purch = D(r['quantity']), D(r['purchase_price'])
        r['margin_unit'] = D(r['price']) - purch
        r['margin_sum'] = D(r['amount']) - purch * qty
        r['cost_sum'] = purch * qty
        margin_total += r['margin_sum']
    info = {'work_' + k + '_total': v for k, v in sums.items()}
    info['works_total'] = sum((D(r['amount']) for r in work_rows), Decimal(0))
    info['materials_total'] = sum((D(r['amount']) for r in materials), Decimal(0))
    info['materials_margin_total'] = margin_total
    info['grand_total'] = info['works_total'] + info['materials_total']
    return work_rows, materials, info


def margin_summary(db, eid):
    """Себестоимость, продажа и маржа по смете с учётом скидок/наценок. Маржа = продажа − закупка (материалы) − себестоимость работ."""
    t = totals(db, eid)
    cost = {'mat': Decimal(0), 'work': Decimal(0)}
    for itype, qty, purchase in db.fetchall('SELECT item_type,quantity,purchase_price FROM estimate_items WHERE estimate_id=?', (eid,)):
        if itype == 'Раздел':
            continue
        cost['work' if itype == 'Работа' else 'mat'] += D(qty) * D(purchase)
    factor = 1 + t['tot_adj'] / 100
    sale_mat, sale_work = t['adj_mat'] * factor, t['adj_work'] * factor
    out = dict(cost_materials=cost['mat'], cost_works=cost['work'], cost_total=cost['mat'] + cost['work'], sale_base=t['base'], sale_materials=sale_mat,
               sale_works=sale_work, sale_total=t['total'], margin_materials=sale_mat - cost['mat'], margin_works=sale_work - cost['work'])
    out['margin_total'] = out['sale_total'] - out['cost_total']
    out['margin_pct'] = (out['margin_total'] / out['sale_total'] * 100) if out['sale_total'] else Decimal(0)
    return out


# --- КЛИЕНТ И ДОГОВОР СМЕТЫ ------------------------------------------------------------------

def client_label(db, eid):
    row = db.fetchone("SELECT coalesce(nullif(client_name,''),party_name) FROM estimates WHERE id=?", (eid,))
    return (row[0] if row else '') or ''


def contract_client(db, table, rid):
    """Клиент договора раздела: ('person', id клиента) / ('legal', id юрлица) / None."""
    if table in ('contracts', 'gsv_projects'):
        row = db.fetchone(f'SELECT client_id,le_client_id FROM {table} WHERE id=?', (rid,))
    elif table == 'gsn_projects':
        row = db.fetchone('SELECT client_id,NULL FROM gsn_projects WHERE id=?', (rid,))
    elif table == 'smr_contracts':
        row = db.fetchone("SELECT CASE WHEN party_type='person' THEN person_id END,CASE WHEN party_type='legal' THEN legal_id END FROM smr_contracts WHERE id=?", (rid,))
    elif table == 'le_contracts':
        row = db.fetchone('SELECT NULL,client_id FROM le_contracts WHERE id=?', (rid,))
    else:
        return None
    if not row:
        return None
    if row[1]:
        return ('legal', row[1])
    if row[0]:
        return ('person', row[0])
    return None


def contract_of(db, eid):
    """Договор, к которому привязана смета: {'table','id','section','label'} или None."""
    for table, section in CONTRACT_TABLES.items():
        row = db.fetchone(f'SELECT id FROM {table} WHERE estimate_id=?', (eid,))
        if row:
            return dict(table=table, id=row[0], section=section, label=board.link_label(db, table, row[0]) or f'{section} №{row[0]}')
    return None


def contract_candidates(db, query='', with_estimate=False, limit=300):
    """Договоры, к которым можно привязать смету (у них ещё нет сметы), и договоры для выбора клиента (with_estimate=True — любые, включая «Юрлица»)."""
    tables = dict(CONTRACT_TABLES)
    if with_estimate:
        tables['le_contracts'] = 'Юрлица'
    q = str(query or '').casefold()
    out = []
    for table, section in tables.items():
        cond = '' if with_estimate or table == 'le_contracts' else ' WHERE estimate_id IS NULL'
        for (rid,) in db.fetchall(f'SELECT id FROM {table}{cond} ORDER BY id DESC LIMIT 1000'):
            label = board.link_label(db, table, rid)
            if label and (not q or q in label.casefold()):
                out.append((table, rid, label))
                if len(out) >= limit:
                    return out
    return out


def set_client(db, eid, kind, client_id):
    """Клиент сметы: kind 'person' (клиент из «Клиентов») или 'legal' (юрлицо). У сметы с договором клиент задаётся в договоре."""
    if kind == 'person':
        from .data_services import link_client
        with db.transaction():
            db.execute("UPDATE estimates SET le_client_id=NULL,party_name='' WHERE id=?", (eid,))
            link_client(db, 'estimates', eid, client_id)
        return
    if kind != 'legal':
        raise ValueError('Неизвестный тип клиента')
    row = db.fetchone('SELECT name FROM le_clients WHERE id=?', (client_id,))
    if not row:
        raise ValueError('Юрлицо не найдено')
    linked = contract_of(db, eid)
    if linked:
        raise ValueError('Смета привязана к договору — клиента юрлица укажите в карточке договора, он передастся в смету.')
    db.execute("UPDATE estimates SET le_client_id=?,party_name=?,client_id=NULL,client_name='',client_phone='' WHERE id=?", (client_id, row[0], eid))


def apply_contract_client(db, eid, table, rid):
    """Берёт клиента из договора."""
    client = contract_client(db, table, rid)
    if not client:
        return None
    kind, cid = client
    if kind == 'person':
        set_client(db, eid, 'person', cid)
    else:
        row = db.fetchone('SELECT name FROM le_clients WHERE id=?', (cid,))
        if row:
            db.execute("UPDATE estimates SET le_client_id=?,party_name=?,client_id=NULL,client_name='',client_phone='' WHERE id=?", (cid, row[0], eid))
    return client


def link_contract(db, eid, table, rid):
    """Привязывает смету к договору раздела. Смета и договор связываются один к одному."""
    if table not in CONTRACT_TABLES:
        raise ValueError('К этому разделу смета не привязывается')
    if not db.fetchone('SELECT 1 FROM estimates WHERE id=?', (eid,)):
        raise ValueError('Смета не найдена')
    current = contract_of(db, eid)
    if current:
        raise ValueError(f'Смета уже привязана: {current["label"]}. Сначала отвяжите её.')
    row = db.fetchone(f'SELECT estimate_id FROM {table} WHERE id=?', (rid,))
    if not row:
        raise ValueError('Договор не найден')
    if row[0]:
        raise ValueError('У этого договора уже есть смета')
    with db.transaction():
        if table == 'contracts':
            from . import gsvm_domain as md
            md.link_estimate(db, rid, eid)
        elif table == 'smr_contracts':
            from . import contracts_core as cc
            cc.link_estimate(db, rid, eid)
        else:
            from . import payments_domain
            payments_domain.link(db, table, rid, eid)
        # клиент договора без клиента наследует клиента сметы (как раньше)
        if table in ('contracts',):
            db.execute('UPDATE contracts SET client_id=(SELECT client_id FROM estimates WHERE id=?) WHERE id=? AND client_id IS NULL', (eid, rid))


def unlink_contract(db, eid):
    """Отвязывает смету от договора. Если по смете есть оплаты, перепривязка запрещена, чтобы не переносить деньги между объектами."""
    current = contract_of(db, eid)
    if not current:
        return None
    from . import payments_domain
    with db.transaction():
        payments_domain.link(db, current['table'], current['id'], None)
        if current['table'] in ('contracts', 'smr_contracts'):
            db.execute(f"UPDATE {current['table']} SET est_synced_at='',est_rev_synced=0,est_materials=0,est_works=0 WHERE id=?", (current['id'],))
    return current


def create_estimate(db, title='', client=None, contract=None, link=False, folder_id=None, prepared_by=''):
    """Новая смета. По умолчанию — без договора.

    client   — ('person', id) или ('legal', id); None — без клиента;
    contract — (таблица, id): клиент берётся из карточки этого договора (если client не задан);
    link     — сразу привязать смету к этому договору (по умолчанию нет).
    """
    if contract and contract[0] not in CONTRACT_TABLES and contract[0] != 'le_contracts':
        raise ValueError('Неизвестный раздел договора')
    if link and (not contract or contract[0] not in CONTRACT_TABLES):
        raise ValueError('Привязать можно только договор раздела со сметами (ГСВ, монтаж, ГСН, СМР)')
    with db.transaction():
        eid = db.execute("INSERT INTO estimates(title,date,total,paid,statuses,folder_id,prepared_by) VALUES(?,?,0.0,0.0,'Предварительная смета',?,?)",
                         (str(title or '').strip() or 'Новая смета', date.today().isoformat(), folder_id, prepared_by or '')).lastrowid
        if client:
            if client[0] == 'person':
                set_client(db, eid, 'person', client[1])
            else:
                set_client(db, eid, 'legal', client[1])
        elif contract:
            apply_contract_client(db, eid, *contract)
        if link:
            link_contract(db, eid, *contract)
        if not str(title or '').strip():
            label = client_label(db, eid)
            db.execute('UPDATE estimates SET title=? WHERE id=?', (f'Смета · {label}' if label else f'Смета от {date.today():%d.%m.%Y}', eid))
    return eid


# --- ТЕГИ ШАБЛОНОВ ---------------------------------------------------------------------------

SOURCE_LABELS = {
    'title': 'Смета: объект / шифр', 'date': 'Смета: дата', 'total': 'Смета: итого', 'paid': 'Смета: оплачено', 'debt': 'Смета: долг', 'prepared_by': 'Смета: составил',
    'company': 'Организация (из настроек)', 'report_date': 'Дата формирования документа',
    'client_label': 'Клиент: ФИО / наименование', 'client_phone': 'Клиент: телефон', 'client_address': 'Клиент: адрес',
    'contract_number': 'Договор: номер', 'contract_date': 'Договор: дата', 'contract_section': 'Договор: раздел', 'contract_label': 'Договор: полное описание',
    'has_contract': 'Есть ли договор (Да / Нет)',
    'materials_total': 'Материалы: итого (с учётом скидок/наценок)', 'works_total': 'Работы: итого (с учётом скидок/наценок)', 'subtotal': 'Итого до наценки на итог',
    'calculated_total': 'Итого по расчёту', 'mat_adj_pct': 'Скидка/наценка на материалы, %', 'work_adj_pct': 'Скидка/наценка на работы, %',
    'total_adj_pct': 'Скидка/наценка на итог, %',
    'work_wage_total': 'Работы: ЗП (расшифровка)', 'work_overhead_total': 'Работы: ОХР и ОПР (расшифровка)', 'work_profit_total': 'Работы: плановая прибыль (расшифровка)',
    'work_social_total': 'Работы: СоцСтрах (расшифровка)', 'work_other_total': 'Работы: другие затраты (расшифровка)', 'work_tax_total': 'Работы: налог на прибыль (расшифровка)',
    'materials_margin_total': 'Материалы: маржа по позициям', 'grand_total': 'Расшифровка: материалы + работы',
    'cost_materials': 'Себестоимость материалов (закупка)', 'cost_works': 'Себестоимость работ', 'cost_total': 'Себестоимость всего', 'sale_total': 'Продажа (итого)',
    'margin_materials': 'Маржа по материалам', 'margin_works': 'Маржа по работам', 'margin_total': 'Маржа всего', 'margin_pct': 'Маржа, % от продажи',
}
BUILTIN_TAGS = [
    ('объект', 'title', 'text'), ('клиент', 'client_label', 'text'), ('телефон', 'client_phone', 'text'), ('адрес_клиента', 'client_address', 'text'),
    ('дата_сметы', 'date', 'date_long'), ('дата_сметы_кратко', 'date', 'date_short'), ('составил', 'prepared_by', 'text'), ('организация', 'company', 'text'),
    ('итого', 'total', 'money'), ('итого_прописью', 'total', 'money_words'), ('материалы', 'materials_total', 'money'), ('работы', 'works_total', 'money'),
    ('оплачено', 'paid', 'money'), ('долг', 'debt', 'money'),
    ('договор_номер', 'contract_number', 'text'), ('договор_дата', 'contract_date', 'date_long'), ('договор_раздел', 'contract_section', 'text'), ('есть_договор', 'has_contract', 'text'),
    ('скидка_материалы', 'mat_adj_pct', 'number2'), ('скидка_работы', 'work_adj_pct', 'number2'), ('скидка_итог', 'total_adj_pct', 'number2'),
    ('зп_итого', 'work_wage_total', 'money'), ('охр_итого', 'work_overhead_total', 'money'), ('прибыль_итого', 'work_profit_total', 'money'),
    ('соцстрах_итого', 'work_social_total', 'money'), ('другие_затраты_итого', 'work_other_total', 'money'), ('налог_итого', 'work_tax_total', 'money'),
    ('себестоимость_материалов', 'cost_materials', 'money'), ('себестоимость_работ', 'cost_works', 'money'), ('себестоимость', 'cost_total', 'money'),
    ('продажа', 'sale_total', 'money'), ('маржа_материалы', 'margin_materials', 'money'), ('маржа_работы', 'margin_works', 'money'), ('маржа', 'margin_total', 'money'),
    ('маржа_процент', 'margin_pct', 'number2'),
]
TABLE_TAGS = {
    'items': ('Позиции сметы', ['index', 'name', 'item_type', 'unit', 'quantity', 'price', 'amount']),
    'works': ('Работы (расшифровка)', ['index', 'name', 'unit', 'quantity', 'price', 'amount', 'purchase_price', 'cost_sum', 'margin_sum', 'has_breakdown', 'wage_unit', 'overhead_unit',
                                       'profit_unit', 'social_unit', 'other_unit', 'tax_unit', 'wage_sum', 'overhead_sum', 'profit_sum', 'social_sum', 'other_sum', 'tax_sum']),
    'materials': ('Материалы и маржа', ['index', 'name', 'unit', 'quantity', 'price', 'purchase_price', 'amount', 'cost_sum', 'margin_unit', 'margin_sum']),
    'payments': ('Оплаты', ['index', 'date', 'amount']),
}


def norm_tag(raw):
    name = re.sub(r'\s+', '_', str(raw).strip().lower())
    if not re.fullmatch(r'[0-9a-zа-яё_]+', name):
        raise ValueError('Имя тега: буквы, цифры и подчёркивание (пробелы заменяются на _)')
    return name


def sync_tags(db):
    for name, source, fmt in BUILTIN_TAGS:
        if not db.fetchone('SELECT 1 FROM est_tags WHERE auto_key=?', (f'b:{name}',)):
            base, n, nm = name, 1, name
            while db.fetchone('SELECT 1 FROM est_tags WHERE name=?', (nm,)):
                n += 1
                nm = f'{base}_{n}'
            db.execute('INSERT INTO est_tags(name,source,fmt,auto_key) VALUES(?,?,?,?)', (nm, source, fmt, f'b:{name}'))


def list_tags(db):
    sync_tags(db)
    return db.fetchall("SELECT id,name,source,fmt,empty_text,coalesce(auto_key,''),enabled,note FROM est_tags ORDER BY (auto_key IS NULL), id")


def save_tag(db, tag_id, name, source, fmt, empty_text='', enabled=True, note=''):
    name = norm_tag(name)
    if fmt not in FORMATS:
        raise ValueError('Неизвестный формат')
    if not source:
        raise ValueError('Выберите источник данных')
    if db.fetchone('SELECT id FROM est_tags WHERE name=? AND id IS NOT ?', (name, tag_id)):
        raise ValueError(f'Тег {{{{{name}}}}} уже существует')
    if tag_id:
        db.execute('UPDATE est_tags SET name=?,source=?,fmt=?,empty_text=?,enabled=?,note=? WHERE id=?', (name, source, fmt, empty_text, int(bool(enabled)), note, tag_id))
        return tag_id
    return db.execute('INSERT INTO est_tags(name,source,fmt,empty_text,enabled,note) VALUES(?,?,?,?,?,?)', (name, source, fmt, empty_text, int(bool(enabled)), note)).lastrowid


def delete_tag(db, tag_id):
    row = db.fetchone('SELECT auto_key FROM est_tags WHERE id=?', (tag_id,))
    if not row:
        return 'missing'
    if row[0]:
        db.execute('UPDATE est_tags SET enabled=0 WHERE id=?', (tag_id,))
        return 'disabled'
    db.execute('DELETE FROM est_tags WHERE id=?', (tag_id,))
    return 'deleted'


def source_choices(ctx_keys=()):
    """[(ключ, подпись)] — все значения, которые можно подставить в тег; необъяснённые ключи добавляются как есть."""
    labels = dict(SOURCE_LABELS)
    for key in ctx_keys:
        if key not in labels and key not in HIDDEN_KEYS and key not in ('report_title',):
            labels[key] = key
    return list(labels.items())


# --- КОНТЕКСТ ШАБЛОНОВ -----------------------------------------------------------------------

def extend_context(db, kind, eid, ctx, tables):
    """Дополняет контекст шаблонов сметы (и сметы-расшифровки): клиент, договор, маржа, таблицы работ и материалов, русские теги."""
    from .gsvm_docs import money  # noqa: F401  (используется apply_format)
    row = db.fetchone("SELECT coalesce(nullif(client_name,''),party_name),client_phone FROM estimates WHERE id=?", (eid,))
    ctx['client_label'] = (row[0] if row else '') or ''
    contract = contract_of(db, eid)
    ctx['has_contract'] = 'Да' if contract else 'Нет'
    ctx['contract_section'] = contract['section'] if contract else ''
    ctx['contract_label'] = contract['label'] if contract else ''
    ctx['contract_number'] = ctx['contract_date'] = ''
    if contract:
        t = contract['table']
        col = {'gsv_projects': 'contract_number', 'contracts': 'contract_number', 'gsn_projects': 'contract_number', 'smr_contracts': 'contract_number'}[t]
        r = db.fetchone(f'SELECT {col},contract_date FROM {t} WHERE id=?', (contract['id'],))
        if r:
            ctx['contract_number'], ctx['contract_date'] = r[0] or '', r[1] or ''
    for key in LEGACY_ZERO_KEYS:
        ctx[key] = Decimal(0)
    for key, value in margin_summary(db, eid).items():
        ctx[key] = value
    works, materials, info = breakdown(db, eid)
    for key, value in info.items():
        ctx.setdefault(key, value)
    if kind == 'estimates':
        tables.setdefault('works', works)
        tables.setdefault('materials', materials)
    else:
        tables.setdefault('items', rows(db, 'SELECT name,item_type,unit,quantity,price,sum amount FROM estimate_items WHERE estimate_id=? ORDER BY sort_order,id', (eid,)))
        tables.setdefault('payments', rows(db, 'SELECT date,amount FROM payments WHERE estimate_id=? ORDER BY date,id', (eid,)))
    ctx.setdefault('total', db.fetchone('SELECT total FROM estimates WHERE id=?', (eid,))[0] or 0)
    ctx.setdefault('debt', D(ctx.get('total')) - D(ctx.get('paid')))
    ctx.setdefault('prepared_by', db.get_setting('estimate_prepared_by', ''))
    # русские теги: значение берётся у источника, форматируется и подставляется; если пусто — «текст, если данных нет»
    sync_tags(db)
    for _id, name, source, fmt, empty_text, _auto, enabled, _note in db.fetchall("SELECT id,name,source,fmt,empty_text,coalesce(auto_key,''),enabled,note FROM est_tags"):
        if not enabled:
            continue
        value = ctx.get(source)
        text = apply_format(value if not isinstance(value, Decimal) else format(value, 'f'), fmt) if value not in (None, '') else ''
        ctx[name] = text if text != '' else (empty_text or '')
    return ctx
