"""Доска задач: быстрое добавление из строки, связь задач с договорами, предложения автозадач, строка итогов дня. Без зависимости от Qt."""
import re
from datetime import date, timedelta, datetime

from . import agenda_domain as agenda
from .agenda_domain import norm_date

DEFAULT_TAG_COLOR = '#3B82F6'
LINK_SECTIONS = {
    'gsv_projects': 'Проект ГСВ', 'contracts': 'Монтаж ГСВ', 'gsn_projects': 'Монтаж ГСН', 'le_contracts': 'Юрлица', 'smr_contracts': 'СМР',
}
WEEKDAYS = {'понедельник': 0, 'пн': 0, 'вторник': 1, 'вт': 1, 'среда': 2, 'среду': 2, 'ср': 2, 'четверг': 3, 'чт': 3, 'пятница': 4, 'пятницу': 4, 'пт': 4,
            'суббота': 5, 'субботу': 5, 'сб': 5, 'воскресенье': 6, 'вс': 6}
LEAD_WORDS = {'до', 'в', 'во', 'на', 'к', 'числа'}


def migrate(db):
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(kanban_tasks)')}
    for name, ddl in (('link_table', "TEXT DEFAULT ''"), ('link_id', 'INTEGER'), ('auto_key', "TEXT DEFAULT ''")):
        if name not in cols:
            db.execute(f'ALTER TABLE kanban_tasks ADD COLUMN {name} {ddl}')
    db.execute("CREATE INDEX IF NOT EXISTS idx_kanban_auto ON kanban_tasks(auto_key)")
    db.execute('CREATE TABLE IF NOT EXISTS board_dismissed(auto_key TEXT PRIMARY KEY)')


# --- БЫСТРОЕ ДОБАВЛЕНИЕ ----------------------------------------------------------------------

def _next_weekday(today, weekday):
    days = (weekday - today.weekday()) % 7
    return today + timedelta(days=days or 7)


def _day_of_month(today, day):
    """Ближайшая дата с этим числом месяца (сегодня, если число совпало)."""
    year, month = today.year, today.month
    for _ in range(14):
        try:
            candidate = date(year, month, day)
            if candidate >= today:
                return candidate
        except ValueError:
            pass
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return None


def parse_quick(text, today=None):
    """Разбирает строку «Сдать акт Иванова завтра #акт !» → (заголовок, срок ГГГГ-ММ-ДД или '', [теги], срочность).

    Понимает: сегодня, завтра, послезавтра, через N дней/недель, 15.10 / 15.10.2026, день недели (пт, в пятницу), 10-го / до 10 числа,
    #тег (подчёркивание — пробел), ! (высокая) и !! (критическая).
    """
    today = today or date.today()
    tokens = str(text or '').split()
    clean = [t.strip(',.;:') for t in tokens]
    used = [False] * len(tokens)
    due, tags, urgency = None, [], 'Обычная'
    i = 0
    while i < len(tokens):
        word = clean[i].casefold()
        raw = tokens[i]
        if raw.startswith('#') and len(raw) > 1:
            tags.append(raw[1:].strip(',.;:').replace('_', ' '))
            used[i] = True
        elif re.fullmatch(r'!+', raw):
            urgency = 'Критическая' if len(raw) >= 2 else 'Высокая'
            used[i] = True
        elif word in ('сегодня', 'завтра', 'послезавтра') and due is None:
            due = today + timedelta(days={'сегодня': 0, 'завтра': 1, 'послезавтра': 2}[word])
            used[i] = True
        elif word == 'через' and due is None and i + 2 < len(tokens) and clean[i + 1].isdigit():
            unit = clean[i + 2].casefold()
            if unit.startswith('дн') or unit.startswith('день'):
                due = today + timedelta(days=int(clean[i + 1]))
            elif unit.startswith('нед'):
                due = today + timedelta(days=7 * int(clean[i + 1]))
            elif unit.startswith('мес'):
                due = today + timedelta(days=30 * int(clean[i + 1]))
            if due is not None:
                used[i] = used[i + 1] = used[i + 2] = True
                i += 2
        elif word in WEEKDAYS and due is None:
            due = _next_weekday(today, WEEKDAYS[word])
            used[i] = True
        elif due is None and (m := re.fullmatch(r'(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?', clean[i])):
            day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
            try:
                if year:
                    year = int(year) + (2000 if len(year) == 2 else 0)
                    due = date(year, month, day)
                else:
                    due = date(today.year, month, day)
                    if due < today:
                        due = date(today.year + 1, month, day)
                used[i] = True
            except ValueError:
                due = None
        elif due is None and (m := re.fullmatch(r'(\d{1,2})-?(?:го|е|ое)', word)):
            due = _day_of_month(today, int(m.group(1)))
            used[i] = due is not None
        elif due is None and word.isdigit() and i + 1 < len(tokens) and clean[i + 1].casefold() == 'числа' and 1 <= int(word) <= 31:
            due = _day_of_month(today, int(word))
            if due is not None:
                used[i] = used[i + 1] = True
                i += 1
        i += 1
    # предлоги перед распознанной датой («до», «в», «к») убираем вместе с ней
    for i, flag in enumerate(used):
        if flag and i > 0 and not used[i - 1] and clean[i - 1].casefold() in LEAD_WORDS and not tokens[i].startswith(('#', '!')):
            used[i - 1] = True
    title = ' '.join(t for t, u in zip(tokens, used) if not u).strip(' ,.;:') or str(text or '').strip()
    return title, (due.isoformat() if due else ''), tags, urgency


def _set_task_tags(db, task_id, names):
    for name in names:
        row = db.fetchone('SELECT id FROM task_tags WHERE lower(name)=lower(?)', (name,))
        tid = row[0] if row else db.execute('INSERT INTO task_tags(name,color) VALUES(?,?)', (name, DEFAULT_TAG_COLOR)).lastrowid
        db.execute('INSERT OR IGNORE INTO task_tag_links(task_id,tag_id) VALUES(?,?)', (task_id, tid))
    db.execute("UPDATE kanban_tasks SET tags=coalesce((SELECT group_concat(name,', ') FROM (SELECT t.name FROM task_tag_links l JOIN task_tags t ON t.id=l.tag_id "
               "WHERE l.task_id=kanban_tasks.id ORDER BY t.name)),'') WHERE id=?", (task_id,))


def add_task(db, title, due='', urgency='Обычная', tags=(), description='', link=None, auto_key='', status=None):
    """Новая задача в первой колонке доски (или в указанном статусе)."""
    title = str(title or '').strip()
    if not title:
        raise ValueError('Введите текст задачи')
    if status is None:
        row = db.fetchone('SELECT code FROM task_statuses ORDER BY sort_order,id LIMIT 1')
        status = row[0] if row else 'todo'
    link_table, link_id = link or ('', None)
    if link_table and link_table not in LINK_SECTIONS:
        raise ValueError('Неизвестный раздел для связи')
    with db.transaction():
        tid = db.execute("INSERT INTO kanban_tasks(title,description,status,is_archived,created_at,urgency,due_date,link_table,link_id,auto_key) VALUES(?,?,?,0,?,?,?,?,?,?)",
                         (title, description, status, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), urgency, due, link_table, link_id, auto_key)).lastrowid
        _set_task_tags(db, tid, tags)
    return tid


def add_quick(db, text, today=None):
    title, due, tags, urgency = parse_quick(text, today)
    tid = add_task(db, title, due, urgency, tags)
    return dict(id=tid, title=title, due=due, tags=tags, urgency=urgency)


# --- СВЯЗЬ С ДОГОВОРАМИ ----------------------------------------------------------------------

def _record_label(db, table, rid):
    if table == 'gsv_projects':
        row = db.fetchone("SELECT pd_number,coalesce(nullif(client_name,''),party_name),object_name FROM gsv_projects WHERE id=?", (rid,))
        return None if not row else ' · '.join(x for x in (row[0], row[1], row[2]) if x)
    if table == 'contracts':
        row = db.fetchone("SELECT contract_number,coalesce(nullif(client_name,''),party_name),object_name FROM contracts WHERE id=?", (rid,))
        return None if not row else ' · '.join(x for x in (row[0], row[1], row[2]) if x)
    if table == 'gsn_projects':
        row = db.fetchone("SELECT contract_number,client_name,title FROM gsn_projects WHERE id=?", (rid,))
        return None if not row else ' · '.join(x for x in (row[0], row[1], row[2]) if x)
    if table in ('le_contracts', 'smr_contracts'):
        from . import contracts_core as cc
        mod = 'le' if table == 'le_contracts' else 'smr'
        try:
            c = cc.contract(db, mod, rid)
        except ValueError:
            return None
        return ' · '.join(x for x in (c['contract_number'], cc.party_label(db, mod, c), c.get('object_name')) if x)
    return None


def link_label(db, table, rid):
    """Подпись связи для карточки: «Юрлица · 01-04/26 · ООО Ромашка»; None — если запись удалена или связи нет."""
    if not table or not rid or table not in LINK_SECTIONS:
        return None
    label = _record_label(db, table, rid)
    return None if label is None else f'{LINK_SECTIONS[table]} · {label}'


def records(db, table, query='', limit=300):
    """[(id, подпись)] записей раздела для выбора связи."""
    if table not in LINK_SECTIONS:
        return []
    ids = [r[0] for r in db.fetchall(f'SELECT id FROM {table} ORDER BY id DESC LIMIT 2000')]
    q = str(query or '').casefold()
    out = []
    for rid in ids:
        label = _record_label(db, table, rid)
        if label and (not q or q in label.casefold()):
            out.append((rid, label))
            if len(out) >= limit:
                break
    return out


def next_tenth(today=None):
    today = today or date.today()
    candidate = date(today.year, today.month, 10)
    if candidate < today:
        candidate = date(today.year + (today.month == 12), today.month % 12 + 1, 10)
    return candidate


def default_task_for(db, table, rid, today=None):
    """Заготовка задачи из карточки договора: (заголовок, срок). Пример: «Сдать акт по договору 01-04/26 · ООО Ромашка», срок — ближайшее 10-е."""
    label = _record_label(db, table, rid) or ''
    return f'Сдать акт по договору {label}'.strip(), next_tenth(today).isoformat()


# --- ПРЕДЛОЖЕНИЯ АВТОЗАДАЧ -------------------------------------------------------------------

def _suggestion(key, title, link, urgency='Обычная', due='', reason=''):
    return dict(key=key, title=title, link=link, urgency=urgency, due=due, reason=reason)


def suggestions(db, today=None):
    """Задачи, которые программа предлагает создать. Уже созданные и скрытые пользователем не повторяются (результат кэшируется до изменения данных)."""
    from .cache_domain import cached
    day = today or date.today()
    return cached(db, ('suggestions', day.isoformat()), lambda: _suggestions(db, day))


def _suggestions(db, today):
    from . import contracts_core as cc, acts_statement, gsvm_domain as md
    today = today or date.today()
    found = []
    rows = lambda sql: db.fetchall(sql)
    for rid, num, who in rows("SELECT id,contract_number,coalesce(nullif(client_name,''),party_name) FROM contracts WHERE coalesce(contract_date,'')<>'' AND coalesce(contract_signed,1)=0"):
        found.append(_suggestion(f'sign_contract:contracts:{rid}', f'Подписать договор {num} · {who}', ('contracts', rid), 'Высокая', reason='договор не подписан'))
    for rid, num, who in rows("SELECT id,pd_number,coalesce(nullif(client_name,''),party_name) FROM gsv_projects WHERE coalesce(contract_date,'')<>'' AND coalesce(contract_signed,1)=0"):
        found.append(_suggestion(f'sign_contract:gsv_projects:{rid}', f'Подписать договор {num} · {who}', ('gsv_projects', rid), 'Высокая', reason='договор не подписан'))
    for mod in ('le', 'smr'):
        c = cc.cfg(mod)
        join, label = cc.party_join(mod)
        for rid, num, who in rows(f"SELECT c.id,c.contract_number,{label} FROM {c['contracts']} c {join} WHERE coalesce(c.contract_date,'')<>'' AND coalesce(c.signed,0)=0 AND c.status='Действует'"):
            found.append(_suggestion(f'sign_contract:{c["contracts"]}:{rid}', f'Подписать договор {num} · {who}', (c['contracts'], rid), 'Высокая', reason='договор не подписан'))
        for aid, anum, cid, cnum, who in rows(f"SELECT a.id,a.act_number,a.contract_id,c.contract_number,{label} FROM {c['acts']} a JOIN {c['contracts']} c ON c.id=a.contract_id {join} "
                                              f"WHERE coalesce(a.act_date,'')<>'' AND coalesce(a.signed,0)=0"):
            found.append(_suggestion(f'sign_act:{c["acts"]}:{aid}', f'Получить подпись акта {anum} · договор {cnum} · {who}', (c['contracts'], cid), 'Высокая', reason='акт не подписан'))
    for rid, num, who in rows("SELECT id,contract_number,coalesce(nullif(client_name,''),party_name) FROM contracts WHERE coalesce(acceptance_act_date,'')<>'' AND coalesce(act_signed,1)=0"):
        found.append(_suggestion(f'sign_act:contracts:{rid}', f'Получить подпись акта · договор {num} · {who}', ('contracts', rid), 'Высокая', reason='акт не подписан'))
    for rid, num, who in rows("SELECT id,pd_number,coalesce(nullif(client_name,''),party_name) FROM gsv_projects WHERE coalesce(act_date,'')<>'' AND coalesce(act_signed,1)=0"):
        found.append(_suggestion(f'sign_act:gsv_projects:{rid}', f'Получить подпись акта · проект {num} · {who}', ('gsv_projects', rid), 'Высокая', reason='акт не подписан'))
    # ведомость актов за прошлый месяц — до 10-го
    year, month = acts_statement.default_period(today)
    signed = 0
    for section in acts_statement.SECTIONS:
        signed += len(acts_statement.statement(db, section, year, month)['signed'])
    if signed:
        due = date(year + (month == 12), month % 12 + 1, 10)
        found.append(_suggestion(f'statement:{year}-{month:02d}', f'Сдать ведомость актов за {acts_statement.period_label(year, month)} до 10-го', None, 'Высокая', due.isoformat(),
                                 f'подписанных актов за месяц: {signed}'))
    # смета изменилась после получения стоимости
    for rid, num, who in rows("SELECT id,contract_number,coalesce(nullif(client_name,''),party_name) FROM contracts WHERE estimate_id IS NOT NULL"):
        if md.estimate_state(db, rid) == 'stale':
            found.append(_suggestion(f'estimate:contracts:{rid}', f'Смета изменена — обновите стоимость: договор {num} · {who}', ('contracts', rid), 'Обычная', reason='смета изменена'))
    for rid, num in rows("SELECT id,contract_number FROM smr_contracts WHERE estimate_id IS NOT NULL"):
        if cc.estimate_state(db, rid) == 'stale':
            who = cc.party_label(db, 'smr', cc.contract(db, 'smr', rid))
            found.append(_suggestion(f'estimate:smr_contracts:{rid}', f'Смета изменена — обновите стоимость: договор СМР {num} · {who}', ('smr_contracts', rid), 'Обычная', reason='смета изменена'))
    taken = {r[0] for r in db.fetchall("SELECT auto_key FROM kanban_tasks WHERE coalesce(auto_key,'')<>''")} | {r[0] for r in db.fetchall('SELECT auto_key FROM board_dismissed')}
    return [s for s in found if s['key'] not in taken]


def create_from_suggestion(db, s):
    return add_task(db, s['title'], s.get('due', ''), s.get('urgency', 'Обычная'), link=s.get('link'), auto_key=s['key'], description=s.get('reason', ''))


def dismiss(db, key):
    db.execute('INSERT OR IGNORE INTO board_dismissed(auto_key) VALUES(?)', (key,))


# --- СТРОКА ИТОГОВ ДНЯ -----------------------------------------------------------------------

def plural(n, forms):
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def summary(db, today=None):
    """{'overdue','acts','payments','today','text'} для строки итогов вверху экрана (кэшируется до изменения данных)."""
    from .cache_domain import cached
    day = today or date.today()
    return cached(db, ('summary', day.isoformat()), lambda: _summary(db, day))


def _summary(db, today):
    overdue = len(agenda.overdue_tasks(db, today))
    acts = 0
    for sql in ("SELECT count(*) FROM contracts WHERE coalesce(acceptance_act_date,'')<>'' AND coalesce(act_signed,1)=0",
                "SELECT count(*) FROM gsv_projects WHERE coalesce(act_date,'')<>'' AND coalesce(act_signed,1)=0",
                "SELECT count(*) FROM le_acts WHERE coalesce(act_date,'')<>'' AND coalesce(signed,0)=0",
                "SELECT count(*) FROM smr_acts WHERE coalesce(act_date,'')<>'' AND coalesce(signed,0)=0"):
        acts += db.fetchone(sql)[0]
    payments = db.fetchone('SELECT count(*) FROM payments WHERE date=?', (today.isoformat(),))[0]
    events = len(agenda.events_between(db, today, today))
    parts = []
    if overdue:
        parts.append(f'{overdue} просрочено')
    if acts:
        parts.append(f'{acts} {plural(acts, ("акт", "акта", "актов"))} к подписанию')
    parts.append(f'оплат на сегодня {payments}')
    parts.append(f'дел на сегодня {events}')
    return dict(overdue=overdue, acts=acts, payments=payments, today=events, text=' · '.join(parts))
