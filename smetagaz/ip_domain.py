"""Модуль «СМР (ИП)»: договоры и акты индивидуального предпринимателя, сметы и оплаты без договора, ведомость работ и оплат по месяцам, подоходный налог.
Связан только со справочником клиентов и сметами. Без Qt."""
import calendar
from datetime import date, datetime

from . import contracts_core as cc

MONTHS = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
ISO = '%Y-%m-%d'
# значения по умолчанию; меняются вручную в начале года (вкладка «Налог»)
DEFAULTS = dict(expense_rate=20.0, tax_rate=20.0, poverty_threshold=1308.0, poverty_deduction=216.0, child_deduction=120.0, dependent_deduction=63.0, children=0, dependents=0, monthly=1)
PARAM_COLUMNS = tuple(DEFAULTS)


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS ip_estimates(estimate_id INTEGER PRIMARY KEY REFERENCES estimates(id) ON DELETE CASCADE, client_id INTEGER, added_at TEXT DEFAULT '')""")
    db.execute("""CREATE TABLE IF NOT EXISTS ip_income(id INTEGER PRIMARY KEY, client_id INTEGER, client_name TEXT DEFAULT '', income_date TEXT NOT NULL, amount REAL NOT NULL,
        title TEXT DEFAULT '', note TEXT DEFAULT '')""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_ip_income_date ON ip_income(income_date)')
    db.execute("""CREATE TABLE IF NOT EXISTS ip_manual(id INTEGER PRIMARY KEY, year INTEGER NOT NULL, quarter INTEGER NOT NULL CHECK(quarter BETWEEN 1 AND 4),
        month INTEGER NOT NULL DEFAULT 0 CHECK(month BETWEEN 0 AND 12), kind TEXT NOT NULL CHECK(kind IN ('revenue','tax_paid')), amount REAL NOT NULL, note TEXT DEFAULT '')""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_ip_manual_year ON ip_manual(year)')
    db.execute("""CREATE TABLE IF NOT EXISTS ip_tax_params(year INTEGER PRIMARY KEY, expense_rate REAL, tax_rate REAL, poverty_threshold REAL, poverty_deduction REAL,
        child_deduction REAL, dependent_deduction REAL, children INTEGER DEFAULT 0, dependents INTEGER DEFAULT 0, monthly INTEGER DEFAULT 1)""")


def money(v):
    return f'{float(v or 0):,.2f}'.replace(',', ' ').replace('.', ',')


def _day(value):
    try:
        return datetime.strptime(str(value or '')[:10], ISO).date()
    except ValueError:
        return None


# --- СМЕТЫ БЕЗ ДОГОВОРА -------------------------------------------------------------------------

def add_estimate(db, client_id=None, title='', client_name=''):
    """Новая смета ИП без договора. Клиент — из справочника «Клиенты» или введённый вручную (client_name); вручную введённый клиент попадает в «Клиенты» по общему правилу программы (смета с именем создаёт клиента)."""
    from . import estimates_domain as ed
    client_name = str(client_name or '').strip()
    if client_id:
        if not db.fetchone('SELECT 1 FROM crm.clients WHERE id=?', (client_id,)):
            raise ValueError('Клиент не найден')
        eid = ed.create_estimate(db, title, client=('person', client_id))
    elif client_name:
        eid = ed.create_estimate(db, title or f'Смета · {client_name}')
        db.execute('UPDATE estimates SET client_name=? WHERE id=?', (client_name, eid))
    else:
        raise ValueError('Выберите клиента или впишите его вручную')
    db.execute('INSERT INTO ip_estimates(estimate_id,client_id,added_at) VALUES(?,?,?)', (eid, client_id, date.today().isoformat()))
    return eid


def attach_estimate(db, eid, client_id=None):
    """Относит существующую смету к ИП (без договора). Смета с договором другого раздела не принимается."""
    if db.fetchone('SELECT 1 FROM ip_estimates WHERE estimate_id=?', (eid,)):
        return
    for table in ('contracts', 'gsv_projects', 'gsn_projects', 'smr_contracts', 'to_contracts', 'fl_contracts'):
        if db.fetchone(f'SELECT 1 FROM {table} WHERE estimate_id=?', (eid,)):
            raise ValueError('Эта смета привязана к договору другого раздела')
    if client_id is None:
        row = db.fetchone('SELECT client_id FROM estimates WHERE id=?', (eid,))
        client_id = row[0] if row else None
    db.execute('INSERT INTO ip_estimates(estimate_id,client_id,added_at) VALUES(?,?,?)', (eid, client_id, date.today().isoformat()))


def detach_estimate(db, eid):
    db.execute('DELETE FROM ip_estimates WHERE estimate_id=?', (eid,))


def estimates(db):
    """Сметы ИП: без договора и по договорам ИП. [{'id','title','date','client','total','paid','debt','contract','without_contract'}]."""
    from . import payments_domain
    out = []
    seen = set()
    for cid, number, eid in db.fetchall('SELECT id,contract_number,estimate_id FROM ip_contracts WHERE estimate_id IS NOT NULL'):
        row = db.fetchone('SELECT title,date,total,paid,client_name FROM estimates WHERE id=?', (eid,))
        if row:
            seen.add(eid)
            out.append(dict(id=eid, title=row[0] or '', date=row[1] or '', client=row[4] or '', total=float(row[2] or 0), paid=float(row[3] or 0), contract=f'№{number}', without_contract=False))
    for (eid,) in db.fetchall('SELECT estimate_id FROM ip_estimates'):
        if eid in seen:
            continue
        row = db.fetchone('SELECT title,date,total,paid,client_name FROM estimates WHERE id=?', (eid,))
        if row:
            out.append(dict(id=eid, title=row[0] or '', date=row[1] or '', client=row[4] or '', total=float(row[2] or 0), paid=float(row[3] or 0), contract='', without_contract=True))
    for e in out:
        e['debt'] = round(e['total'] - e['paid'], 2)
    out.sort(key=lambda e: (e['date'], e['id']), reverse=True)
    return out


# --- ОПЛАТЫ БЕЗ ДОГОВОРА ----------------------------------------------------------------------

def save_income(db, values, iid=None):
    """Оплата работы клиентом без договора и без сметы."""
    amount = float(values.get('amount') or 0)
    if amount <= 0:
        raise ValueError('Сумма должна быть больше нуля')
    day = str(values.get('date') or '')
    date.fromisoformat(day)
    client_id = values.get('client_id')
    name = ''
    if client_id:
        row = db.fetchone('SELECT name FROM crm.clients WHERE id=?', (client_id,))
        name = row[0] if row else ''
    elif str(values.get('client_name') or '').strip():
        name = str(values['client_name']).strip()
    else:
        raise ValueError('Выберите клиента')
    data = (client_id, name, day, amount, str(values.get('title') or '').strip(), str(values.get('note') or '').strip())
    if iid:
        db.execute('UPDATE ip_income SET client_id=?,client_name=?,income_date=?,amount=?,title=?,note=? WHERE id=?', (*data, iid))
        return iid
    return db.execute('INSERT INTO ip_income(client_id,client_name,income_date,amount,title,note) VALUES(?,?,?,?,?,?)', data).lastrowid


def delete_income(db, iid):
    db.execute('DELETE FROM ip_income WHERE id=?', (iid,))


def incomes(db, start, end):
    """Все поступления ИП за период [start; end] (даты date), по дате: оплаты по договорам, по сметам без договора и оплаты без договора.
    [{'date','amount','kind','client','label','ref'}]."""
    s, e = start.strftime(ISO), end.strftime(ISO)
    contract_est = {r[0]: r[1] for r in db.fetchall('SELECT estimate_id,id FROM ip_contracts WHERE estimate_id IS NOT NULL')}
    free_est = {r[0] for r in db.fetchall('SELECT estimate_id FROM ip_estimates')}
    out = []
    for pid, day, amount, owner, oid, eid in db.fetchall('SELECT id,date,amount,owner_type,owner_id,estimate_id FROM payments WHERE date BETWEEN ? AND ? ORDER BY date,id', (s, e)):
        contract_id = contract_est.get(eid) if eid else None
        if contract_id is None and owner == 'ip_contracts':
            contract_id = oid
        if contract_id is not None:
            try:
                c = cc.contract(db, 'ip', contract_id)
            except ValueError:
                continue
            out.append(dict(date=day, amount=float(amount), kind='По договору', client=cc.party_label(db, 'ip', c), label=f'Договор №{c["contract_number"]}', ref=('ip_contracts', contract_id)))
        elif eid in free_est:
            row = db.fetchone('SELECT title,client_name FROM estimates WHERE id=?', (eid,))
            out.append(dict(date=day, amount=float(amount), kind='По смете', client=(row[1] if row else '') or '', label=f'Смета «{row[0] if row else ""}»', ref=('estimates', eid)))
    for iid, day, amount, name, title, note in db.fetchall('SELECT id,income_date,amount,client_name,title,note FROM ip_income WHERE income_date BETWEEN ? AND ? ORDER BY income_date,id', (s, e)):
        out.append(dict(date=day, amount=float(amount), kind='Без договора', client=name or '', label=title or note or 'Оплата работы', ref=('ip_income', iid)))
    out.sort(key=lambda r: (r['date'], r['kind']))
    return out


# --- ВЕДОМОСТЬ ПО МЕСЯЦАМ ------------------------------------------------------------------------

def month_range(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def works(db, start, end):
    """Выполненные работы за период: подписанные акты по договорам ИП и сметы без договора (по дате сметы). Неподписанные акты показаны отдельно (counted=False)."""
    s, e = start.strftime(ISO), end.strftime(ISO)
    out = []
    for aid, num, day, amount, signed, cid in db.fetchall(
            "SELECT a.id,a.act_number,a.act_date,a.amount,coalesce(a.signed,0),a.contract_id FROM ip_acts a WHERE a.act_date BETWEEN ? AND ? ORDER BY a.act_date,a.id", (s, e)):
        c = cc.contract(db, 'ip', cid)
        out.append(dict(date=day, amount=float(amount or 0), kind='Акт', label=f'Акт №{num or "б/н"} · договор №{c["contract_number"]}', client=cc.party_label(db, 'ip', c),
                        counted=bool(signed), ref=('ip_acts', aid)))
    for (eid,) in db.fetchall('SELECT estimate_id FROM ip_estimates'):
        row = db.fetchone('SELECT title,date,total,client_name FROM estimates WHERE id=?', (eid,))
        if row and s <= str(row[1] or '') <= e:
            out.append(dict(date=row[1], amount=float(row[2] or 0), kind='Смета без договора', label=f'Смета «{row[0]}»', client=row[3] or '', counted=True, ref=('estimates', eid)))
    out.sort(key=lambda r: (r['date'], r['kind']))
    return out


def statement(db, year, month):
    """Ведомость за месяц: {'works','payments','works_total','paid_total','balance'}."""
    start, end = month_range(year, month)
    w, p = works(db, start, end), incomes(db, start, end)
    works_total = round(sum(r['amount'] for r in w if r['counted']), 2)
    paid_total = round(sum(r['amount'] for r in p), 2)
    return dict(works=w, payments=p, works_total=works_total, paid_total=paid_total, balance=round(works_total - paid_total, 2))


def year_summary(db, year):
    """По месяцам года: [(месяц, выполнено работ, получено оплат)]."""
    out = []
    for m in range(1, 13):
        st = statement(db, year, m)
        out.append((m, st['works_total'], st['paid_total']))
    return out


def export_statement(db, year, month, path):
    import openpyxl
    from openpyxl.styles import Font
    st = statement(db, year, month)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Ведомость'
    ws.append([f'Ведомость работ и оплат ИП за {MONTHS[month]} {year}'])
    ws['A1'].font = Font(bold=True, size=13)
    ws.append([])
    ws.append(['Выполненные работы'])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.append(['Дата', 'Вид', 'Основание', 'Клиент', 'Сумма', 'Учтено'])
    for r in st['works']:
        ws.append([r['date'], r['kind'], r['label'], r['client'], r['amount'], 'да' if r['counted'] else 'нет (не подписан)'])
    ws.append(['', '', '', 'Итого выполнено', st['works_total']])
    ws.append([])
    ws.append(['Оплаты'])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.append(['Дата', 'Вид', 'Основание', 'Клиент', 'Сумма'])
    for r in st['payments']:
        ws.append([r['date'], r['kind'], r['label'], r['client'], r['amount']])
    ws.append(['', '', '', 'Итого получено', st['paid_total']])
    ws.append(['', '', '', 'Не оплачено за месяц', st['balance']])
    for col, width in zip('ABCDEF', (12, 20, 42, 30, 14, 20)):
        ws.column_dimensions[col].width = width
    from .dates import localize_workbook
    localize_workbook(wb)
    wb.save(path)
    return path


# --- РУЧНЫЕ ДАННЫЕ ДЛЯ НАЛОГА -----------------------------------------------------------------------

MANUAL_KINDS = {'revenue': 'Выручка (сумма)', 'tax_paid': 'Уплаченный налог'}


def save_manual(db, year, quarter, month, kind, amount, note='', mid=None):
    """Данные, которых нет в договорах и актах (например, суммы за 1–2 кварталы 2026): month=0 — сумма за весь квартал, иначе за указанный месяц квартала."""
    if kind not in MANUAL_KINDS:
        raise ValueError('Неизвестный вид записи')
    quarter, month = int(quarter), int(month)
    if quarter not in (1, 2, 3, 4):
        raise ValueError('Квартал — от 1 до 4')
    if month and not quarter * 3 - 2 <= month <= quarter * 3:
        raise ValueError('Месяц не входит в выбранный квартал')
    amount = float(amount or 0)
    if amount <= 0:
        raise ValueError('Сумма должна быть больше нуля')
    if mid:
        db.execute('UPDATE ip_manual SET year=?,quarter=?,month=?,kind=?,amount=?,note=? WHERE id=?', (year, quarter, month, kind, amount, str(note or '').strip(), mid))
        return mid
    return db.execute('INSERT INTO ip_manual(year,quarter,month,kind,amount,note) VALUES(?,?,?,?,?,?)', (year, quarter, month, kind, amount, str(note or '').strip())).lastrowid


def delete_manual(db, mid):
    db.execute('DELETE FROM ip_manual WHERE id=?', (mid,))


def manual_list(db, year):
    return db.fetchall('SELECT id,quarter,month,kind,amount,note FROM ip_manual WHERE year=? ORDER BY quarter,month,id', (year,))


def manual_revenue_by_month(db, year, quarter):
    """{месяц: ручная выручка}: суммы по месяцам плюс сумма за квартал, разделённая поровну на три месяца (копейки — в последнем)."""
    months = [quarter * 3 - 2, quarter * 3 - 1, quarter * 3]
    out = {m: 0.0 for m in months}
    for _id, _q, month, kind, amount, _note in manual_list(db, year):
        if _q != quarter or kind != 'revenue':
            continue
        if month:
            out[month] += amount
        else:
            part = round(amount / 3, 2)
            out[months[0]] += part
            out[months[1]] += part
            out[months[2]] += round(amount - 2 * part, 2)
    return {m: round(v, 2) for m, v in out.items()}


def manual_paid(db, year, quarter):
    return round(sum(a for _i, q, _m, kind, a, _n in manual_list(db, year) if q == quarter and kind == 'tax_paid'), 2)


# --- ПОДОХОДНЫЙ НАЛОГ -----------------------------------------------------------------------------

def params(db, year):
    """Параметры налога года. Если для года ещё нет записи, берутся значения предыдущего года (или стандартные) и сохраняются — их можно изменить вручную."""
    row = db.fetchone(f"SELECT {','.join(PARAM_COLUMNS)} FROM ip_tax_params WHERE year=?", (year,))
    if row:
        return dict(zip(PARAM_COLUMNS, row))
    prev = db.fetchone(f"SELECT {','.join(PARAM_COLUMNS)} FROM ip_tax_params WHERE year<? ORDER BY year DESC LIMIT 1", (year,))
    values = dict(zip(PARAM_COLUMNS, prev)) if prev else dict(DEFAULTS)
    db.execute(f"INSERT INTO ip_tax_params(year,{','.join(PARAM_COLUMNS)}) VALUES(?,{','.join('?' for _ in PARAM_COLUMNS)})", (year, *[values[k] for k in PARAM_COLUMNS]))
    return values


def save_params(db, year, values):
    params(db, year)
    data = {}
    for k in PARAM_COLUMNS:
        v = float(values.get(k, DEFAULTS[k]) or 0)
        if v < 0:
            raise ValueError('Значения не могут быть отрицательными')
        data[k] = int(v) if k in ('children', 'dependents', 'monthly') else v
    if not 0 <= data['tax_rate'] <= 100 or not 0 <= data['expense_rate'] <= 100:
        raise ValueError('Ставки — от 0 до 100 %')
    db.execute('UPDATE ip_tax_params SET ' + ','.join(f'{k}=?' for k in PARAM_COLUMNS) + ' WHERE year=?', (*[data[k] for k in PARAM_COLUMNS], year))


def month_tax(revenue, p):
    """Расчёт за месяц: {'revenue','expenses','poverty','children','dependents','base_raw','base','tax'}.
    База = выручка − выручка×20 % − вычет на бедность (если выручка за месяц не больше порога) − вычеты на детей и иждивенцев.
    Налог = база × 20 %. База за месяц не бывает отрицательной."""
    revenue = round(float(revenue or 0), 2)
    expenses = round(revenue * p['expense_rate'] / 100, 2)
    poverty = p['poverty_deduction'] if 0 < revenue <= p['poverty_threshold'] else 0.0
    children = round(p['children'] * p['child_deduction'], 2)
    dependents = round(p['dependents'] * p['dependent_deduction'], 2)
    raw = round(revenue - expenses - poverty - children - dependents, 2) if revenue > 0 else 0.0
    base = max(0.0, raw)
    return dict(revenue=revenue, expenses=expenses, poverty=poverty, children=children, dependents=dependents, base_raw=raw, base=base, tax=round(base * p['tax_rate'] / 100, 2))


def quarter_report(db, year, quarter, today=None):
    """Налог за квартал по поступившей выручке на сегодняшний день: {'months': [...], 'revenue','base','tax','params','complete'}.
    Пересчитывается при каждом открытии — в любой момент квартала видно, сколько будет к уплате по текущим данным."""
    if quarter not in (1, 2, 3, 4):
        raise ValueError('Квартал — от 1 до 4')
    today = today or date.today()
    p = params(db, year)
    months, revenue_total, manual_total = [], 0.0, 0.0
    manual = manual_revenue_by_month(db, year, quarter)
    for m in range(quarter * 3 - 2, quarter * 3 + 1):
        start, end = month_range(year, m)
        recorded = sum(r['amount'] for r in incomes(db, start, min(end, today))) if start <= today else 0.0
        revenue = recorded + manual[m]
        row = month_tax(revenue, p)
        row.update(month=m, name=MONTHS[m], recorded=round(recorded, 2), manual=manual[m])
        months.append(row)
        revenue_total += revenue
        manual_total += manual[m]
    if p['monthly']:
        base = round(sum(r['base'] for r in months), 2)
        tax = round(sum(r['tax'] for r in months), 2)
    else:                                       # вычеты суммируются за квартал целиком, база квартала не меньше нуля
        raw = round(sum(r['base_raw'] for r in months), 2)
        base = max(0.0, raw)
        tax = round(base * p['tax_rate'] / 100, 2)
    last_day = month_range(year, quarter * 3)[1]
    paid = manual_paid(db, year, quarter)
    return dict(year=year, quarter=quarter, months=months, revenue=round(revenue_total, 2), manual=round(manual_total, 2), base=base, tax=tax, paid=paid, to_pay=round(tax - paid, 2),
                params=p, complete=today >= last_day)


def year_report(db, year, today=None):
    return [quarter_report(db, year, q, today) for q in (1, 2, 3, 4)]
