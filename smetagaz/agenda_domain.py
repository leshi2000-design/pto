"""Данные экрана «Сегодня»: сроки задач, повторяющиеся даты и единая лента событий для календаря.

Модуль не зависит от Qt, поэтому его можно проверять обычными тестами.
"""
import calendar
import re
from datetime import date, datetime, timedelta

ISO = '%Y-%m-%d'

# Вид события -> (подпись, цвет маркера, значок)
KINDS = {
    'task': ('Срок задачи', '#2563EB', '📋'),
    'overdue': ('Просроченная задача', '#DC2626', '⏰'),
    'contract': ('Договор', '#7C3AED', '✍️'),
    'act': ('Акт', '#0D9488', '✅'),
    'payment': ('Оплата', '#16A34A', '💰'),
    'work': ('Работы', '#EA580C', '🛠'),
    'project': ('Проект / срок', '#0891B2', '📐'),
    'event': ('Событие', '#64748B', '🕒'),
    'recurring': ('Ежемесячная дата', '#DB2777', '🔁'),
    'note': ('Заметка', '#CA8A04', '📝'),
}
# Порядок маркеров в ячейке календаря и в списке дня
KIND_ORDER = ['overdue', 'task', 'contract', 'payment', 'work', 'act', 'project', 'recurring', 'note', 'event']

SHIFTS = [('none', 'Не переносить'), ('prev', 'Перенести на пятницу, если выходной'), ('next', 'Перенести на понедельник, если выходной')]
RECURRING_PRESETS = ['Зарплата', 'Аванс', 'Сдача актов', 'Оплата аренды', 'Налоги и взносы', 'Другое']
PALETTE = ['#DC2626', '#EA580C', '#D97706', '#16A34A', '#0D9488', '#0891B2', '#2563EB', '#7C3AED', '#DB2777', '#64748B']
URGENCY_ORDER = {'Критическая': 1, 'Высокая': 2, 'Обычная': 3, 'Низкая': 4}


def migrate(db):
    """Добавляет срок задач, цвета/порядок статусов, описание тегов и таблицу ежемесячных дат."""
    def columns(table):
        return {r[1] for r in db.fetchall(f'PRAGMA table_info({table})')}
    if 'due_date' not in columns('kanban_tasks'):
        db.execute("ALTER TABLE kanban_tasks ADD COLUMN due_date TEXT DEFAULT ''")
    db.execute('CREATE INDEX IF NOT EXISTS idx_kanban_due ON kanban_tasks(due_date)')
    cols = columns('task_statuses')
    if 'color' not in cols:
        db.execute("ALTER TABLE task_statuses ADD COLUMN color TEXT DEFAULT '#2563EB'")
        for code, color in (('todo', '#DC2626'), ('in_progress', '#D97706'), ('done', '#16A34A')):
            db.execute('UPDATE task_statuses SET color=? WHERE code=?', (color, code))
    if 'is_done' not in cols:
        db.execute('ALTER TABLE task_statuses ADD COLUMN is_done INTEGER DEFAULT 0')
        db.execute("UPDATE task_statuses SET is_done=1 WHERE code='done'")
    if 'sort_order' not in cols:
        db.execute('ALTER TABLE task_statuses ADD COLUMN sort_order INTEGER DEFAULT 1000000')
        db.execute('UPDATE task_statuses SET sort_order=id')
    if 'description' not in columns('task_tags'):
        db.execute("ALTER TABLE task_tags ADD COLUMN description TEXT DEFAULT ''")
    db.execute('''CREATE TABLE IF NOT EXISTS recurring_dates(
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        day_of_month INTEGER NOT NULL CHECK(day_of_month BETWEEN 0 AND 31),
        shift TEXT NOT NULL DEFAULT 'none',
        color TEXT DEFAULT '#DB2777',
        note TEXT DEFAULT '',
        start_month TEXT DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1)''')


def norm_date(value):
    """Приводит дату из любого формата, встречающегося в базе, к ГГГГ-ММ-ДД; пусто — если не распознана."""
    text = str(value or '').strip()
    if not text:
        return ''
    match = re.match(r'^(\d{4})-(\d{2})-(\d{2})', text)
    if match:
        y, m, d = map(int, match.groups())
    else:
        match = re.match(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})', text)
        if not match:
            return ''
        d, m, y = map(int, match.groups())
    try:
        return date(y, m, d).strftime(ISO)
    except ValueError:
        return ''


def due_state(due, today=None, done=False):
    """('overdue'|'today'|'soon'|'later'|'none'|'done', дней до срока; отрицательное — просрочено)."""
    due = norm_date(due)
    if not due:
        return 'none', None
    today = today or date.today()
    days = (datetime.strptime(due, ISO).date() - today).days
    if done:
        return 'done', days
    if days < 0:
        return 'overdue', days
    if days == 0:
        return 'today', 0
    return ('soon' if days <= 2 else 'later'), days


def plural(n, forms):
    n = abs(int(n))
    if 11 <= n % 100 <= 14:
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if 2 <= n % 10 <= 4 else forms[2]


def due_label(due, today=None, done=False):
    """Текст для карточки задачи: «Просрочено на 3 дня», «Срок сегодня», «Срок 12.10.2026»."""
    state, days = due_state(due, today, done)
    pretty = datetime.strptime(norm_date(due), ISO).strftime('%d.%m.%Y') if state != 'none' else ''
    if state == 'overdue':
        return f'Просрочено на {-days} {plural(days, ("день", "дня", "дней"))}'
    if state == 'today':
        return 'Срок сегодня'
    if state == 'soon' and days == 1:
        return 'Срок завтра'
    if state == 'none':
        return ''
    return f'Срок {pretty}'


def occurrence(day_of_month, shift, year, month):
    """Дата ежемесячного события в конкретном месяце: 0 — последний день, 31 в коротком месяце — последний день."""
    last = calendar.monthrange(year, month)[1]
    day = last if day_of_month == 0 else min(day_of_month, last)
    result = date(year, month, day)
    if shift == 'prev':
        while result.weekday() >= 5:
            result -= timedelta(days=1)
    elif shift == 'next':
        while result.weekday() >= 5:
            result += timedelta(days=1)
    return result


def _months(start, end):
    y, m = start.year, start.month
    # на месяц шире окна: перенос с выходных может сдвинуть дату в соседний месяц
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    ey, em = (end.year + 1, 1) if end.month == 12 else (end.year, end.month + 1)
    while (y, m) <= (ey, em):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def recurring_between(db, start, end):
    result = []
    for rid, title, dom, shift, color, note, start_month in db.fetchall(
            'SELECT id,title,day_of_month,shift,color,note,start_month FROM recurring_dates WHERE active=1 ORDER BY day_of_month,title'):
        for y, m in _months(start, end):
            if start_month and f'{y:04d}-{m:02d}' < start_month[:7]:
                continue
            day = occurrence(dom, shift, y, m)
            if start <= day <= end:
                result.append((day, rid, title, color, note))
    return result


def _event(day, kind, title, detail='', ref=None, color=None, time=''):
    label, kind_color, icon = KINDS[kind]
    return {'date': day, 'kind': kind, 'title': title, 'detail': detail, 'ref': ref,
            'color': color or kind_color, 'icon': icon, 'time': time, 'kind_label': label}


def short_name(full):
    """«Иванов Иван Иванович» -> «Иванов И.И.»."""
    parts = str(full or '').split()
    if len(parts) < 2:
        return parts[0] if parts else ''
    return f'{parts[0]} ' + ''.join(f'{p[0].upper()}.' for p in parts[1:3])


def _money(value):
    return f'{float(value or 0):,.2f}'.replace(',', ' ').replace('.', ',') + ' ₽'


def events_between(db, start, end, today=None):
    """Все события периода [start; end] (объекты date) в виде словарей; отсортированы по дню и виду."""
    today = today or date.today()
    s, e = start.strftime(ISO), end.strftime(ISO)
    out = []
    # --- задачи со сроком; просроченные показываются и в сегодняшнем дне ---
    for tid, title, due, urgency, done in db.fetchall(
            "SELECT k.id,k.title,k.due_date,k.urgency,coalesce(s.is_done,0) FROM kanban_tasks k "
            "LEFT JOIN task_statuses s ON s.code=k.status WHERE k.is_archived=0 AND coalesce(k.due_date,'')<>''"):
        due = norm_date(due)
        if not due:
            continue
        state, days = due_state(due, today, bool(done))
        day = datetime.strptime(due, ISO).date()
        if start <= day <= end:
            out.append(_event(day, 'overdue' if state == 'overdue' else 'task', title,
                              (due_label(due, today, bool(done)) + (f' · {urgency}' if urgency else '')), ('kanban_tasks', tid)))
    # --- договоры, акты, сроки: первичный документ каждого раздела отмечается в календаре ---
    # (SQL, вид, раздел, таблица, столбец клиента, условие «подписан»)
    contracts = (
        ("SELECT id,contract_date,contract_number,object_name,coalesce(nullif(client_name,''),party_name),coalesce(contract_signed,1) FROM contracts WHERE coalesce(contract_date,'')<>''", 'contract', 'Монтаж ГСВ', 'contracts'),
        ("SELECT id,contract_date,contract_number,object_name,coalesce(nullif(client_name,''),party_name),coalesce(contract_signed,1) FROM gsv_projects WHERE coalesce(contract_date,'')<>''", 'contract', 'Проект ГСВ', 'gsv_projects'),
        ("SELECT id,contract_date,contract_number,title,client_name,1 FROM gsn_projects WHERE coalesce(contract_date,'')<>''", 'contract', 'Монтаж ГСН', 'gsn_projects'),
        ("SELECT id,acceptance_act_date,contract_number,object_name,coalesce(nullif(client_name,''),party_name),coalesce(act_signed,1) FROM contracts WHERE coalesce(acceptance_act_date,'')<>''", 'act', 'Монтаж ГСВ', 'contracts'),
        ("SELECT id,act_date,contract_number,object_name,coalesce(nullif(client_name,''),party_name),coalesce(act_signed,1) FROM gsv_projects WHERE coalesce(act_date,'')<>''", 'act', 'Проект ГСВ', 'gsv_projects'),
        ("SELECT id,work_start_date,contract_number,object_name,coalesce(nullif(client_name,''),party_name),1 FROM contracts WHERE coalesce(work_start_date,'')<>''", 'work', 'Монтаж ГСВ · начало работ', 'contracts'),
        ("SELECT id,work_end_date,contract_number,object_name,coalesce(nullif(client_name,''),party_name),1 FROM contracts WHERE coalesce(work_end_date,'')<>''", 'work', 'Монтаж ГСВ · окончание работ', 'contracts'),
        ("SELECT id,due_date,contract_number,object_name,coalesce(nullif(client_name,''),party_name),1 FROM gsv_projects WHERE coalesce(due_date,'')<>''", 'project', 'Срок проекта ГСВ', 'gsv_projects'),
    )
    for sql, kind, section, table in contracts:
        # даты могли быть записаны как ГГГГ-ММ-ДД или ДД.ММ.ГГГГ, поэтому диапазон проверяется после нормализации
        for rid, day, number, name, client, signed in db.fetchall(sql):
            day = norm_date(day)
            if not day or not s <= day <= e:
                continue
            short = short_name(client)
            number = f'№{number}' if number else 'без номера'
            if kind == 'contract':
                title = f'Заключение договора {short}'.strip() + ('' if signed else ' (не подписан)')
                detail = f'{section} · {number} · {name or "без названия"}'
            elif kind == 'act':
                title = ('Подписан акт ' if signed else 'Акт (не подписан) ') + short
                detail = f'{section} · {number} · {name or "без названия"}'
            else:
                title = f'{section} {number}'
                detail = ' · '.join(x for x in (name, short) if x)
            out.append(_event(datetime.strptime(day, ISO).date(), kind, title.strip(), detail, (table, rid)))
    # --- договоры и акты «Юрлиц» и «СМР» ---
    from . import contracts_core as cc
    for mod, section in (('le', 'Юрлица'), ('smr', 'СМР')):
        c = cc.cfg(mod)
        for table, day_col, kind, num_col in ((c['contracts'], 'contract_date', 'contract', 'contract_number'), (c['contracts'], 'end_date', 'work', 'contract_number')):
            for rid, day, number, name in db.fetchall(f"SELECT id,{day_col},{num_col},coalesce(nullif(object_address,''),object_name) FROM {table} WHERE coalesce({day_col},'')<>''"):
                day = norm_date(day)
                if not day or not s <= day <= e:
                    continue
                ct = cc.contract(db, mod, rid)
                short = cc.party_label(db, mod, ct)
                number = f'№{number}' if number else 'без номера'
                if kind == 'contract':
                    title = f'Заключение договора {short}'.strip() + ('' if ct['signed'] else ' (не подписан)')
                    detail = f'{section} · {number} · {name or "без названия"}'
                else:
                    title, detail = f'{section} · окончание работ {number}', ' · '.join(x for x in (name, short) if x)
                out.append(_event(datetime.strptime(day, ISO).date(), kind, title.strip(), detail, (table, rid)))
        for aid, day, number, signed, cid in db.fetchall(f"SELECT id,act_date,act_number,coalesce(signed,0),contract_id FROM {c['acts']} WHERE coalesce(act_date,'')<>''"):
            day = norm_date(day)
            if not day or not s <= day <= e:
                continue
            ct = cc.contract(db, mod, cid)
            short = cc.party_label(db, mod, ct)
            out.append(_event(datetime.strptime(day, ISO).date(), 'act', ('Подписан акт ' if signed else 'Акт (не подписан) ') + short,
                              f'{section} · акт №{number or "б/н"} · договор {ct["contract_number"] or "без номера"}', (c['contracts'], cid)))
    # --- оплаты (единая книга платежей) ---
    from .payments_domain import report
    try:
        for row in report(db, s, e):
            out.append(_event(datetime.strptime(row['date'], ISO).date(), 'payment', f'Оплата {_money(row["amount"])}',
                              f'{row["section"]} · {row["object_name"]}', ('payments', row.get('id'))))
    except (KeyError, ValueError):
        pass
    # --- сварочные и иные работы ---
    for jid, day, title, welder, place in db.fetchall(
            "SELECT j.id,d.work_date,j.title,coalesce(nullif(j.welder_text,''),w.name),j.object_text FROM welding_days d "
            "JOIN welding_jobs j ON j.id=d.job_id LEFT JOIN welders w ON w.id=j.welder_id WHERE d.work_date BETWEEN ? AND ? ORDER BY j.title", (s, e)):
        out.append(_event(datetime.strptime(day, ISO).date(), 'work', f'Работы: {title}',
                          ' · '.join(x for x in (welder or 'Сварщик не назначен', place) if x), ('welding_jobs', jid)))
    # --- заметки (независимые и привязанные к договорам, клиентам) ---
    from . import notes_domain
    for nid, day, title, body, ltable, lid in db.fetchall("SELECT id,note_date,title,body,link_table,link_id FROM notes WHERE note_date BETWEEN ? AND ?", (s, e)):
        label = notes_domain.link_label(db, ltable, lid) if ltable else ''
        detail = ' · '.join(x for x in (label, (body or '').replace('\n', ' ')[:80]) if x)
        out.append(_event(datetime.strptime(day, ISO).date(), 'note', title or 'Заметка', detail, ('notes', nid)))
    # --- ручные события и ежемесячные даты ---
    for eid, day, time, title, desc in db.fetchall(
            "SELECT id,event_date,event_time,title,description FROM calendar_events WHERE event_date BETWEEN ? AND ?", (s, e)):
        out.append(_event(datetime.strptime(day, ISO).date(), 'event', title or 'Событие', (desc or '').replace('\n', ' '), ('calendar_events', eid), time=time or ''))
    for day, rid, title, color, note in recurring_between(db, start, end):
        out.append(_event(day, 'recurring', title, ('Каждый месяц' + (f' · {note}' if note else '')), ('recurring_dates', rid), color=color))
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    out.sort(key=lambda ev: (ev['date'], order.get(ev['kind'], 99), ev['time'], ev['title']))
    return out


def overdue_tasks(db, today=None):
    """Просроченные незавершённые задачи: [(id, title, due, urgency)], самые давние первыми."""
    today = (today or date.today()).strftime(ISO)
    return db.fetchall(
        "SELECT k.id,k.title,k.due_date,k.urgency FROM kanban_tasks k LEFT JOIN task_statuses s ON s.code=k.status "
        "WHERE k.is_archived=0 AND coalesce(s.is_done,0)=0 AND coalesce(k.due_date,'')<>'' AND k.due_date<? ORDER BY k.due_date,k.id", (today,))


def month_summary(events):
    """{'ГГГГ-ММ-ДД': {вид: количество}} для разметки календаря."""
    marks = {}
    for ev in events:
        marks.setdefault(ev['date'].strftime(ISO), {}).setdefault(ev['kind'], 0)
        marks[ev['date'].strftime(ISO)][ev['kind']] += 1
    return marks
