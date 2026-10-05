"""Проекты ГСВ: статусы, теги документов, формирование Word / Excel, папки и выгрузка карточек.

Модуль не зависит от Qt. Данные раздела не смешиваются с монтажом ГСВ и ГСН: у проектов
свои шаблоны (настройки `gsvp_*`), свои теги и своя таблица статусов.
"""
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DATA_DIR

MONTHS_GENITIVE = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря"
]

def format_date_word(qdate_or_str) -> str:
    if not qdate_or_str: return "—"
    if hasattr(qdate_or_str, "isValid"):  # QDate без зависимости от Qt
        if not qdate_or_str.isValid(): return "—"
        d, m, y = qdate_or_str.day(), qdate_or_str.month(), qdate_or_str.year()
    else:
        try:
            dt = datetime.strptime(str(qdate_or_str)[:10], "%Y-%m-%d")
            d, m, y = dt.day, dt.month, dt.year
        except Exception: return str(qdate_or_str)

    if 1 <= m <= 12: return f"{d:02d} {MONTHS_GENITIVE[m]} {y} г."
    return str(qdate_or_str)

def get_initials_first(full_name: str) -> str:
    parts = full_name.strip().split()
    if not parts: return "—"
    if len(parts) == 1: return parts[0]
    if len(parts) == 2: return f"{parts[1][0].upper()}. {parts[0]}"
    return f"{parts[1][0].upper()}.{parts[2][0].upper()}. {parts[0]}"

def format_cost_rubles(amount: float) -> str:
    int_part = int(amount)
    cents_part = int(round((amount - int_part) * 100))
    formatted_int = f"{int_part:,}".replace(",", " ")

    last_two = int_part % 100
    last_digit = int_part % 10
    if 11 <= last_two <= 19: rub_word = "рублей"
    elif last_digit == 1: rub_word = "рубль"
    elif 2 <= last_digit <= 4: rub_word = "рубля"
    else: rub_word = "рублей"

    return f"{formatted_int},{cents_part:02d} {rub_word}"

def num_to_words_byn(amount: float) -> str:
    units_m = ["", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    units_f = ["", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
    teens = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
             "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
    tens = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
    hundreds = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]

    int_part = int(amount)
    cents_part = int(round((amount - int_part) * 100))

    if int_part == 0: words = "ноль"
    else:
        words_list = []
        millions = (int_part // 1_000_000) % 1_000
        if millions > 0:
            h, t = hundreds[millions // 100], millions % 100
            if h: words_list.append(h)
            if 10 <= t <= 19:
                words_list.append(teens[t - 10])
                m_word = "миллионов"
            else:
                if t // 10 > 1: words_list.append(tens[t // 10])
                u = t % 10
                if u > 0: words_list.append(units_m[u])
                if u == 1: m_word = "миллион"
                elif 2 <= u <= 4: m_word = "миллиона"
                else: m_word = "миллионов"
            words_list.append(m_word)

        thousands = (int_part // 1_000) % 1_000
        if thousands > 0:
            h, t = hundreds[thousands // 100], thousands % 100
            if h: words_list.append(h)
            if 10 <= t <= 19:
                words_list.append(teens[t - 10])
                th_word = "тысяч"
            else:
                if t // 10 > 1: words_list.append(tens[t // 10])
                u = t % 10
                if u > 0: words_list.append(units_f[u])
                if u == 1: th_word = "тысяча"
                elif 2 <= u <= 4: th_word = "тысячи"
                else: th_word = "тысяч"
            words_list.append(th_word)

        rem = int_part % 1_000
        if rem > 0:
            h, t = hundreds[rem // 100], rem % 100
            if h: words_list.append(h)
            if 10 <= t <= 19: words_list.append(teens[t - 10])
            else:
                if t // 10 > 1: words_list.append(tens[t // 10])
                u = t % 10
                if u > 0: words_list.append(units_m[u])
        words = " ".join(words_list).capitalize()

    last_two_int, last_digit = int_part % 100, int_part % 10
    if 11 <= last_two_int <= 19: rub_word = "белорусских рублей"
    elif last_digit == 1: rub_word = "белорусский рубль"
    elif 2 <= last_digit <= 4: rub_word = "белорусских рубля"
    else: rub_word = "белорусских рублей"

    last_two_cents, last_cent_digit = cents_part % 100, cents_part % 10
    if 11 <= last_two_cents <= 19: cent_word = "копеек"
    elif last_cent_digit == 1: cent_word = "копейка"
    elif 2 <= last_cent_digit <= 4: cent_word = "копейки"
    else: cent_word = "копеек"

    return f"{words} {rub_word} {cents_part:02d} {cent_word}"



# --- СТАТУСЫ ---------------------------------------------------------------------------------

DEFAULT_STATUSES = {
    'work': [('Не сделано', '#DC2626'), ('В работе', '#D97706'), ('Не хватает данных', '#7C3AED'), ('Сделано', '#16A34A')],
    'client': [('Договор не подписан', '#DC2626'), ('Договор подписан', '#2563EB'), ('Акт подписан', '#0D9488'),
               ('Передано клиенту', '#0891B2'), ('Не оплачено', '#D97706'), ('Оплачено', '#16A34A')],
}
KIND_TITLES = {'work': 'Статус работы', 'client': 'Статус клиента'}
LEGACY_STATUS_MAP = {'Не сделано': 'Не сделано', '🔥 Приоритет': 'В работе', 'Сделано': 'Сделано',
                     'Не подписан': 'Договор не подписан', 'Подписан': 'Договор подписан', 'Оплачен': 'Оплачено'}
DOC_KINDS = {
    'contract': ('Договор (Word)', 'gsvp_tpl_contract', 'Шаблон_договора_проект_ГСВ.docx', 'Договор'),
    'act': ('Акт (Word)', 'gsvp_tpl_act', 'Шаблон_акта_проект_ГСВ.docx', 'Акт'),
    'card': ('Карточка клиента (Excel)', 'gsvp_tpl_card', 'Шаблон_карточки_клиента_проект_ГСВ.xlsx', 'Карточка_клиента'),
}
SECTION_DIRS = {'gsv_projects': 'Проекты ГСВ', 'contracts': 'Монтаж ГСВ', 'gsn_projects': 'Монтаж ГСН'}
PROJECTS_DIR = DATA_DIR / 'projects'
TEMPLATES_DIR = DATA_DIR / 'templates'


def migrate(db):
    def columns(table):
        return {r[1] for r in db.fetchall(f'PRAGMA table_info({table})')}
    cols = columns('gsv_projects')
    for name in ('contract_signed', 'act_signed'):
        if name not in cols:
            db.execute(f'ALTER TABLE gsv_projects ADD COLUMN {name} INTEGER DEFAULT 0')
    if 'tu_text' not in cols:
        db.execute("ALTER TABLE gsv_projects ADD COLUMN tu_text TEXT DEFAULT ''")
    for sql in (
        """CREATE TABLE IF NOT EXISTS gsv_status_catalog(
             id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('work','client')), name TEXT NOT NULL,
             color TEXT DEFAULT '#2563EB', sort_order INTEGER NOT NULL DEFAULT 0, UNIQUE(kind,name))""",
        """CREATE TABLE IF NOT EXISTS gsv_project_statuses(
             project_id INTEGER NOT NULL REFERENCES gsv_projects(id) ON DELETE CASCADE,
             status_id INTEGER NOT NULL REFERENCES gsv_status_catalog(id) ON DELETE RESTRICT,
             PRIMARY KEY(project_id,status_id))""",
        """CREATE TABLE IF NOT EXISTS gsv_project_docs(
             project_id INTEGER NOT NULL REFERENCES gsv_projects(id) ON DELETE CASCADE,
             kind TEXT NOT NULL, file_path TEXT NOT NULL, data_hash TEXT NOT NULL, generated_at TEXT NOT NULL,
             PRIMARY KEY(project_id,kind))""",
        'CREATE INDEX IF NOT EXISTS idx_gsv_project_statuses_status ON gsv_project_statuses(status_id)',
    ):
        db.execute(sql)
    if not db.fetchone('SELECT 1 FROM gsv_status_catalog LIMIT 1'):
        for kind, items in DEFAULT_STATUSES.items():
            for order, (name, color) in enumerate(items, 1):
                db.execute('INSERT INTO gsv_status_catalog(kind,name,color,sort_order) VALUES(?,?,?,?)', (kind, name, color, order))
    if db.get_setting('gsvp_migrated', '0') != '1':
        # прежние одиночные статусы и «подписан» по дате акта переносятся один раз
        for pid, work, client, act, contract_date in db.fetchall('SELECT id,work_status,client_status,act_date,contract_date FROM gsv_projects'):
            ids = []
            for kind, legacy in (('work', work), ('client', client)):
                name = LEGACY_STATUS_MAP.get(legacy or '')
                found = db.fetchone('SELECT id FROM gsv_status_catalog WHERE kind=? AND name=?', (kind, name)) if name else None
                if found:
                    ids.append(found[0])
            for sid in ids:
                db.execute('INSERT OR IGNORE INTO gsv_project_statuses(project_id,status_id) VALUES(?,?)', (pid, sid))
            db.execute('UPDATE gsv_projects SET contract_signed=?, act_signed=? WHERE id=?',
                       (int(client in ('Подписан', 'Оплачен')), int(bool(act)), pid))
            set_project_statuses(db, pid, project_status_ids(db, pid))     # текстовые копии статусов получают новые названия
        db.set_setting('gsvp_migrated', '1')
    unlink_empty_auto_folders(db)


def catalog(db, kind):
    return db.fetchall('SELECT id,name,coalesce(color,?) FROM gsv_status_catalog WHERE kind=? ORDER BY sort_order,id', ('#2563EB', kind))


def project_status_ids(db, pid):
    return {r[0] for r in db.fetchall('SELECT status_id FROM gsv_project_statuses WHERE project_id=?', (pid,))}


def project_statuses(db, pid, kind):
    return [r[0] for r in db.fetchall(
        'SELECT c.name FROM gsv_project_statuses p JOIN gsv_status_catalog c ON c.id=p.status_id WHERE p.project_id=? AND c.kind=? ORDER BY c.sort_order,c.id', (pid, kind))]


def set_project_statuses(db, pid, status_ids):
    """Сохраняет набор статусов и дублирует их текстом в work_status / client_status (поиск, отчёты, старые выгрузки)."""
    with db.transaction():
        db.execute('DELETE FROM gsv_project_statuses WHERE project_id=?', (pid,))
        for sid in sorted(set(status_ids)):
            db.execute('INSERT INTO gsv_project_statuses(project_id,status_id) VALUES(?,?)', (pid, sid))
        db.execute('UPDATE gsv_projects SET work_status=?, client_status=? WHERE id=?',
                   (', '.join(project_statuses(db, pid, 'work')), ', '.join(project_statuses(db, pid, 'client')), pid))


def status_usage(db, status_id):
    return db.fetchone('SELECT count(*) FROM gsv_project_statuses WHERE status_id=?', (status_id,))[0]


# --- ТЕЛЕФОНЫ --------------------------------------------------------------------------------

def parse_phones(text):
    """«375291112233 (основной); 375447778899 (жена)» -> [(номер, пояснение)]."""
    result = []
    for part in re.split(r'[;\n]+', str(text or '')):
        part = part.strip()
        if not part:
            continue
        match = re.match(r'^(.*?)\s*\((.*)\)\s*$', part)
        result.append((match.group(1).strip(), match.group(2).strip()) if match else (part, ''))
    return result


def join_phones(pairs):
    return '; '.join(f'{phone} ({note})' if note else phone for phone, note in ((p.strip(), n.strip()) for p, n in pairs) if phone or note)


# --- ТЕГИ ДОКУМЕНТОВ -------------------------------------------------------------------------

TAGS = [
    ('НОМЕР_ДОГОВОРА', 'Номер договора, например 01-03/26'),
    ('НОМЕР_ПД', 'Номер проектной документации, например 01-26 ГСВ'),
    ('ДАТА_ЗАКЛЮЧЕНИЯ_П', 'Дата заключения: 12 ноября 2026г.'),
    ('ДАТА_ЗАКЛЮЧЕНИЯ_С', 'Дата заключения: 12.11.2026г.'),
    ('СРОК_ИСПОЛНЕНИЯ_П', 'Срок исполнения: 12 ноября 2026г.'),
    ('СРОК_ИСПОЛНЕНИЯ_С', 'Срок исполнения: 12.11.2026г.'),
    ('ДАТА_АКТА_П', 'Дата акта: 12 ноября 2026г.'),
    ('ДАТА_АКТА_С', 'Дата акта: 12.11.2026г.'),
    ('КЛИЕНТ', 'Полное наименование клиента (ФИО)'),
    ('КЛИЕНТ_СОКР', 'Инициалы и фамилия, например Иванов И.И.'),
    ('СТОИМОСТЬ', 'Стоимость цифрами'),
    ('СУММА_ПРОПИСЬЮ', 'Сумма прописью'),
    ('ТЕЛЕФОН', 'Телефоны клиента с пояснениями'),
    ('ПАСПОРТ', 'Серия и номер паспорта'),
    ('ДАТА_ВЫДАЧИ', 'Дата выдачи паспорта'),
    ('КЕМ_ВЫДАН', 'Кем выдан паспорт'),
    ('АДРЕС_КЛИЕНТА', 'Адрес клиента'),
    ('ОБЪЕКТ', 'Объект проектирования'),
    ('АДРЕС_ОБЪЕКТА', 'Адрес объекта'),
    ('ТУ', 'Номер и дата технических условий, выданных клиенту'),
    ('ПРИМЕЧАНИЕ', 'Примечания по объекту'),
    ('СТАТУС_РАБОТЫ', 'Статусы работы через запятую'),
    ('СТАТУС_КЛИЕНТА', 'Статусы клиента через запятую'),
    ('ДОГОВОР_ПОДПИСАН', 'Да / Нет'),
    ('АКТ_ПОДПИСАН', 'Да / Нет'),
    ('ОПЛАЧЕНО', 'Всего оплачено'),
    ('ОСТАТОК', 'Остаток к оплате'),
    ('ДАТА_ОПЛАТЫ', 'Дата оплаты (в Excel — отдельный столбец на каждую оплату)'),
    ('СУММА_ОПЛАТЫ', 'Сумма оплаты (в Excel — отдельный столбец на каждую оплату)'),
    ('ПРИМЕЧАНИЕ_ОПЛАТЫ', 'Примечание к оплате (в Excel — отдельный столбец на каждую оплату)'),
]
PAYMENT_TAGS = ('ДАТА_ОПЛАТЫ', 'СУММА_ОПЛАТЫ', 'ПРИМЕЧАНИЕ_ОПЛАТЫ')
# теги прежнего шаблона договора остаются рабочими
LEGACY_ALIASES = {'ЗАКАЗЧИК': 'КЛИЕНТ', 'ЗАКАЗЧИК_СОКР': 'КЛИЕНТ_СОКР', 'ЗАКАЗЧИК_ИНИЦИАЛЫ': 'КЛИЕНТ_СОКР', 'ДАТА_ЗАКЛЮЧЕНИЯ': 'ДАТА_ЗАКЛЮЧЕНИЯ_П',
                  'СРОК_ИСПОЛНЕНИЯ': 'СРОК_ИСПОЛНЕНИЯ_П', 'ДАТА_АКТА': 'ДАТА_АКТА_П', 'СТОИМОСТЬ_ПРОПИСЬЮ': 'СУММА_ПРОПИСЬЮ',
                  'АДРЕС': 'АДРЕС_ОБЪЕКТА', 'ПРИМЕЧАНИЯ': 'ПРИМЕЧАНИЕ'}
TAG_RE = re.compile(r'\{([^{}\n]{1,60})\}')


def tag_key(raw):
    key = re.sub(r'\s+', '_', raw.strip().upper())
    return LEGACY_ALIASES.get(key, key)


def date_long(value):
    day = _parse(value)
    return f'{day.day} {MONTHS_GENITIVE[day.month]} {day.year}г.' if day else ''


def date_short(value):
    day = _parse(value)
    return day.strftime('%d.%m.%Y') + 'г.' if day else ''


def _parse(value):
    text = str(value or '')[:10]
    try:
        return datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        return None


def money(value):
    return f'{float(value or 0):.2f}'.replace('.', ',')


def default_due(contract_date):
    """Срок исполнения по умолчанию — 30 дней с даты заключения."""
    day = contract_date if isinstance(contract_date, date) else _parse(contract_date)
    return (day + timedelta(days=30)) if day else None


def payments_list(db, pid):
    from . import payments_domain
    return sorted(((d, float(a), n or '') for _id, d, a, n in payments_domain.history(db, 'gsv_projects', pid)), key=lambda p: p[0])


def project_tags(db, pid):
    cur = db.execute('SELECT * FROM gsv_projects WHERE id=?', (pid,))
    row = cur.fetchone()
    if not row:
        raise ValueError('Сначала сохраните договор')
    p = dict(zip([c[0] for c in cur.description], row))
    client = {}
    if p.get('client_id'):
        from .gsv_domain import get_client
        client = get_client(db, p['client_id']) or {}
    name = client.get('name') or p.get('client_name') or ''
    cost = float(p.get('cost') or 0)
    pays = payments_list(db, pid)
    paid = sum(a for _d, a, _n in pays)
    yes = lambda v: 'Да' if v else 'Нет'
    tags = {
        'НОМЕР_ДОГОВОРА': p.get('contract_number') or '', 'НОМЕР_ПД': p.get('pd_number') or '',
        'ДАТА_ЗАКЛЮЧЕНИЯ_П': date_long(p.get('contract_date')), 'ДАТА_ЗАКЛЮЧЕНИЯ_С': date_short(p.get('contract_date')),
        'СРОК_ИСПОЛНЕНИЯ_П': date_long(p.get('due_date')), 'СРОК_ИСПОЛНЕНИЯ_С': date_short(p.get('due_date')),
        'ДАТА_АКТА_П': date_long(p.get('act_date')), 'ДАТА_АКТА_С': date_short(p.get('act_date')),
        'КЛИЕНТ': name, 'КЛИЕНТ_СОКР': get_initials_first(name) if name else '',
        'СТОИМОСТЬ': money(cost), 'СУММА_ПРОПИСЬЮ': num_to_words_byn(cost),
        'ТЕЛЕФОН': client.get('phone') or p.get('phone') or '', 'ПАСПОРТ': client.get('passport') or p.get('passport') or '',
        'ДАТА_ВЫДАЧИ': date_short(client.get('passport_date')).rstrip('г.') if client.get('passport_date') else '',
        'КЕМ_ВЫДАН': client.get('passport_issuer') or '', 'АДРЕС_КЛИЕНТА': client.get('address') or p.get('client_address') or '',
        'ОБЪЕКТ': p.get('object_name') or '', 'АДРЕС_ОБЪЕКТА': p.get('address') or '', 'ТУ': p.get('tu_text') or '', 'ПРИМЕЧАНИЕ': p.get('notes') or '',
        'СТАТУС_РАБОТЫ': ', '.join(project_statuses(db, pid, 'work')), 'СТАТУС_КЛИЕНТА': ', '.join(project_statuses(db, pid, 'client')),
        'ДОГОВОР_ПОДПИСАН': yes(p.get('contract_signed')), 'АКТ_ПОДПИСАН': yes(p.get('act_signed')),
        'ОПЛАЧЕНО': money(paid), 'ОСТАТОК': money(cost - paid),
        # в Word все оплаты перечисляются по строкам; в Excel каждая оплата получает свои столбцы
        'ДАТА_ОПЛАТЫ': '\n'.join(date_short(d).rstrip('г.') for d, _a, _n in pays),
        'СУММА_ОПЛАТЫ': '\n'.join(money(a) for _d, a, _n in pays),
        'ПРИМЕЧАНИЕ_ОПЛАТЫ': '\n'.join(n for _d, _a, n in pays),
    }
    return tags


def data_hash(db, pid):
    return hashlib.sha256(json.dumps(project_tags(db, pid), ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


# --- ШАБЛОНЫ ---------------------------------------------------------------------------------

def template_path(db, kind):
    """Файл шаблона из настроек; если не задан или пропал — создаётся шаблон по умолчанию."""
    _title, key, default_name, _prefix = DOC_KINDS[kind]
    path = db.get_setting(key, '')
    if path and os.path.exists(path):
        return path
    return str(create_default_template(kind))


def create_default_template(kind):
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    path = TEMPLATES_DIR / DOC_KINDS[kind][2]
    if path.exists():
        return path
    if kind == 'card':
        import openpyxl
        from openpyxl.styles import Font, Alignment
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Карточка клиента'
        ws['A1'] = 'Карточка клиента — проект ГСВ {НОМЕР_ПД}'
        ws['A1'].font = Font(bold=True, size=14)
        rows = [('Договор №', '{НОМЕР_ДОГОВОРА}'), ('Дата заключения', '{ДАТА_ЗАКЛЮЧЕНИЯ_С}'), ('Срок исполнения', '{СРОК_ИСПОЛНЕНИЯ_С}'),
                ('Дата акта', '{ДАТА_АКТА_С}'), ('Клиент', '{КЛИЕНТ}'), ('Телефон', '{ТЕЛЕФОН}'), ('Паспорт', '{ПАСПОРТ}'),
                ('Кем выдан', '{КЕМ_ВЫДАН}'), ('Дата выдачи', '{ДАТА_ВЫДАЧИ}'), ('Адрес клиента', '{АДРЕС_КЛИЕНТА}'),
                ('Объект', '{ОБЪЕКТ}'), ('Адрес объекта', '{АДРЕС_ОБЪЕКТА}'), ('ТУ (номер и дата)', '{ТУ}'), ('Стоимость, BYN', '{СТОИМОСТЬ}'),
                ('Оплачено, BYN', '{ОПЛАЧЕНО}'), ('Остаток, BYN', '{ОСТАТОК}'), ('Статус работы', '{СТАТУС_РАБОТЫ}'),
                ('Статус клиента', '{СТАТУС_КЛИЕНТА}'), ('Примечание', '{ПРИМЕЧАНИЕ}')]
        for r, (label, tag) in enumerate(rows, 3):
            ws.cell(r, 1, label).font = Font(bold=True)
            ws.cell(r, 2, tag)
        start = len(rows) + 5
        ws.cell(start - 1, 1, 'Оплаты (на каждую оплату добавляются свои столбцы)').font = Font(bold=True)
        for c, (label, tag) in enumerate((('Дата оплаты', '{ДАТА_ОПЛАТЫ}'), ('Сумма оплаты', '{СУММА_ОПЛАТЫ}'), ('Примечание', '{ПРИМЕЧАНИЕ_ОПЛАТЫ}')), 1):
            ws.cell(start, c, label).font = Font(bold=True)
            ws.cell(start + 1, c, tag)
        ws.column_dimensions['A'].width = 24
        ws.column_dimensions['B'].width = 40
        ws.column_dimensions['C'].width = 28
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical='top')
        wb.save(path)
        return path
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    doc = docx.Document()
    if kind == 'contract':
        title = doc.add_heading('ДОГОВОР № {НОМЕР_ДОГОВОРА}', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph('на разработку проектной документации {НОМЕР_ПД}')
        doc.add_paragraph('г. ____________                                                       {ДАТА_ЗАКЛЮЧЕНИЯ_П}')
        doc.add_paragraph('Заказчик: {КЛИЕНТ}, паспорт {ПАСПОРТ}, выдан {КЕМ_ВЫДАН} {ДАТА_ВЫДАЧИ}, проживающий: {АДРЕС_КЛИЕНТА}, тел.: {ТЕЛЕФОН}.')
        doc.add_paragraph('Объект проектирования: {ОБЪЕКТ}, адрес объекта: {АДРЕС_ОБЪЕКТА}.')
        doc.add_paragraph('Технические условия: {ТУ}.')
        doc.add_paragraph('Стоимость работ: {СТОИМОСТЬ} BYN ({СУММА_ПРОПИСЬЮ}).')
        doc.add_paragraph('Срок исполнения: {СРОК_ИСПОЛНЕНИЯ_П}.')
        doc.add_paragraph('Примечание: {ПРИМЕЧАНИЕ}')
        doc.add_paragraph('\nПодписи сторон:\nЗаказчик: ______________ {КЛИЕНТ_СОКР}')
    else:
        title = doc.add_heading('АКТ сдачи-приёмки работ', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.add_paragraph('к договору № {НОМЕР_ДОГОВОРА} от {ДАТА_ЗАКЛЮЧЕНИЯ_С}')
        doc.add_paragraph('{ДАТА_АКТА_П}')
        doc.add_paragraph('Исполнитель сдал, а Заказчик {КЛИЕНТ} принял проектную документацию {НОМЕР_ПД} по объекту: {ОБЪЕКТ}, {АДРЕС_ОБЪЕКТА}.')
        doc.add_paragraph('Стоимость работ: {СТОИМОСТЬ} BYN ({СУММА_ПРОПИСЬЮ}). Оплачено: {ОПЛАЧЕНО} BYN, остаток: {ОСТАТОК} BYN.')
        doc.add_paragraph('Работы выполнены в срок {СРОК_ИСПОЛНЕНИЯ_С}, претензий по объёму и качеству Заказчик не имеет.')
        doc.add_paragraph('\nЗаказчик: ______________ {КЛИЕНТ_СОКР}')
    doc.save(path)
    return path


def _replace_text(text, tags, normalize=None):
    normalize = normalize or tag_key

    def sub(match):
        key = normalize(match.group(1))
        return str(tags[key]) if key in tags else match.group(0)
    return TAG_RE.sub(sub, text)


def _fill_paragraph(paragraph, tags, normalize=None):
    text = ''.join(run.text for run in paragraph.runs)
    if '{' not in text:
        return
    new = _replace_text(text, tags, normalize)
    if new == text or not paragraph.runs:
        return
    first = paragraph.runs[0]
    for run in paragraph.runs[1:]:
        run.text = ''
    first.text = new


def _walk_paragraphs(container):
    yield from container.paragraphs
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from _walk_paragraphs(cell)


def render_docx(template, out_path, tags, normalize=None):
    import docx
    doc = docx.Document(template)
    for paragraph in _walk_paragraphs(doc):
        _fill_paragraph(paragraph, tags, normalize)
    for section in doc.sections:
        for part in (section.header, section.footer):
            for paragraph in _walk_paragraphs(part):
                _fill_paragraph(paragraph, tags, normalize)
    _save_atomic(lambda p: doc.save(p), out_path)


def render_xlsx(template, out_path, tags, payments, normalize=None):
    """Подставляет теги; для каждой оплаты повторяет блок столбцов с ДАТА_ОПЛАТЫ / СУММА_ОПЛАТЫ / ПРИМЕЧАНИЕ_ОПЛАТЫ вправо."""
    import copy
    import openpyxl
    from openpyxl.utils import get_column_letter
    normalize = normalize or tag_key
    wb = openpyxl.load_workbook(template)
    pay_values = [{'ДАТА_ОПЛАТЫ': date_short(d).rstrip('г.'), 'СУММА_ОПЛАТЫ': a, 'ПРИМЕЧАНИЕ_ОПЛАТЫ': n} for d, a, n in payments]
    for ws in wb.worksheets:
        pay_cells = []
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and '{' in cell.value:
                    keys = {normalize(m) for m in TAG_RE.findall(cell.value)}
                    if keys & set(PAYMENT_TAGS):
                        pay_cells.append(cell)
                    else:
                        cell.value = _replace_text(cell.value, tags, normalize)
        by_row = {}
        for cell in pay_cells:
            by_row.setdefault(cell.row, []).append(cell)
        for r, cells in by_row.items():
            width = max(c.column for c in cells) - min(c.column for c in cells) + 1
            originals = [(c.column, c.value, copy.copy(c._style)) for c in cells]
            for i in range(max(len(pay_values), 1)):
                values = pay_values[i] if pay_values else {}
                for col, template_value, style in originals:
                    target = ws.cell(r, col + i * width)
                    keys = [normalize(m) for m in TAG_RE.findall(template_value)]
                    if len(keys) == 1 and template_value.strip() == '{' + TAG_RE.findall(template_value)[0] + '}' and isinstance(values.get(keys[0]), float):
                        target.value = values[keys[0]]
                    else:
                        target.value = TAG_RE.sub(lambda m: str(values.get(normalize(m.group(1)), tags.get(normalize(m.group(1)), m.group(0)))), template_value)
                    target._style = copy.copy(style)
                    if i:
                        letter = get_column_letter(col + i * width)
                        source = ws.column_dimensions[get_column_letter(col)].width
                        if source and not ws.column_dimensions[letter].width:
                            ws.column_dimensions[letter].width = source
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = 's'
    _save_atomic(lambda p: wb.save(p), out_path)


def _save_atomic(save, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=out_path.suffix, dir=out_path.parent)
    os.close(fd)
    try:
        save(tmp)
        os.replace(tmp, out_path)
    except PermissionError:
        Path(tmp).unlink(missing_ok=True)
        raise PermissionError(f'Не удалось записать {out_path.name}. Закройте файл в Word / Excel и повторите.')
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


# --- ПАПКИ -----------------------------------------------------------------------------------

def safe_name(text):
    return re.sub(r'\s+', ' ', re.sub(r'[\\/:*?"<>|]', '_', str(text or '')).strip())[:80] or 'без_названия'


def folder_name(number, address='', client=''):
    """Имя новой папки договора: «01-26 ГСВ - адрес объекта (ФИО клиента)»."""
    name = str(number or '').strip().replace('/', '-')
    if str(address or '').strip():
        name += f' - {" ".join(str(address).split())[:90]}'
    if str(client or '').strip():
        name += f' ({" ".join(str(client).split())})'
    return safe_name(name)


def section_root(section):
    return PROJECTS_DIR / SECTION_DIRS[section]


def project_folder_name(db, pid):
    """Предлагаемое имя папки проекта: № ПД - адрес объекта (ФИО клиента)."""
    row = db.fetchone('SELECT p.pd_number,p.address,p.client_address,(SELECT address FROM crm.clients WHERE id=p.client_id),p.object_name,p.client_name '
                      'FROM gsv_projects p WHERE p.id=?', (pid,))
    if not row:
        raise ValueError('Сначала сохраните договор')
    # адрес объекта; если не заполнен — адрес клиента, затем наименование объекта
    return folder_name(row[0], row[1] or row[2] or row[3] or row[4], row[5])


def project_folder(db, pid):
    """Привязанная папка проекта или '' — сама по себе папка не создаётся (только по кнопке «Папка договора»)."""
    row = db.fetchone('SELECT project_folder FROM gsv_projects WHERE id=?', (pid,))
    if not row:
        raise ValueError('Сначала сохраните договор')
    return row[0] if row[0] and os.path.isdir(row[0]) else ''


def link_folder(db, pid, path, create=False):
    """Привязывает к проекту существующую папку или (create=True) создаёт новую."""
    path = str(path)
    if create:
        os.makedirs(path, exist_ok=True)
    if not os.path.isdir(path):
        raise ValueError('Папка не найдена: ' + path)
    db.execute('UPDATE gsv_projects SET project_folder=? WHERE id=?', (path, pid))
    return path


def unlink_empty_auto_folders(db):
    """Однократно отвязывает пустые папки, созданные программой автоматически ранее (непустые не трогаются)."""
    if db.get_setting('gsvp_folders_unlinked', '0') == '1':
        return 0
    removed = 0
    root = str(PROJECTS_DIR)
    candidates = [('gsv_projects', pid, p) for pid, p in db.fetchall("SELECT id,project_folder FROM gsv_projects WHERE coalesce(project_folder,'')<>''")]
    candidates += [('executive_objects', rid, p) for rid, p in db.fetchall("SELECT id,folder_path FROM executive_objects WHERE coalesce(folder_path,'')<>''")]
    for table, rid, path in candidates:
        if not str(path).startswith(root):
            continue
        try:
            if os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
            elif os.path.isdir(path):
                continue
        except OSError:
            continue
        column = 'folder_path' if table == 'executive_objects' else 'project_folder'
        db.execute(f'UPDATE {table} SET {column}=? WHERE id=?', ('', rid))
        removed += 1
    db.set_setting('gsvp_folders_unlinked', '1')
    return removed


# --- ДОКУМЕНТЫ -------------------------------------------------------------------------------

def doc_path(db, pid, kind):
    row = db.fetchone('SELECT file_path FROM gsv_project_docs WHERE project_id=? AND kind=?', (pid, kind))
    return row[0] if row else ''


def doc_state(db, pid, kind):
    """'none' — не создавался, 'missing' — файл удалён, 'stale' — данные изменились, 'fresh' — актуален."""
    row = db.fetchone('SELECT file_path,data_hash FROM gsv_project_docs WHERE project_id=? AND kind=?', (pid, kind))
    if not row:
        return 'none'
    if not os.path.exists(row[0]):
        return 'missing'
    return 'fresh' if row[1] == data_hash(db, pid) else 'stale'


def generate(db, pid, kind):
    """Формирует договор / акт (Word) или карточку клиента (Excel) в папке договора; возвращает путь к файлу."""
    if kind not in DOC_KINDS:
        raise ValueError('Неизвестный документ')
    tags = project_tags(db, pid)
    if kind == 'act' and not tags['ДАТА_АКТА_С']:
        raise ValueError('Укажите дату акта в карточке договора')
    folder = project_folder(db, pid)
    if not folder:
        raise ValueError('Сначала привяжите или создайте папку договора кнопкой «Папка договора»')
    template = template_path(db, kind)
    prefix = DOC_KINDS[kind][3]
    ext = '.xlsx' if kind == 'card' else '.docx'
    number = tags['НОМЕР_ПД'] if kind == 'card' else tags['НОМЕР_ДОГОВОРА']
    out = os.path.join(folder, safe_name(f'{prefix}_{number}').replace(' ', '_') + ext)
    if kind == 'card':
        render_xlsx(template, out, tags, payments_list(db, pid))
    else:
        render_docx(template, out, tags)
    db.execute('INSERT OR REPLACE INTO gsv_project_docs(project_id,kind,file_path,data_hash,generated_at) VALUES(?,?,?,?,?)',
               (pid, kind, out, data_hash(db, pid), datetime.now().isoformat(timespec='seconds')))
    return out


# --- ВЫГРУЗКА ВСЕХ КАРТОЧЕК ------------------------------------------------------------------

EXPORT_FILENAME = 'Проекты_ГСВ_карточки.xlsx'
EXPORT_HEADERS = ['№ ПД', '№ договора', 'Объект', 'Адрес объекта', 'ТУ', 'Клиент', 'Телефоны', 'Адрес клиента', 'Паспорт', 'Кем выдан', 'Дата выдачи',
                  'Стоимость, BYN', 'Оплачено', 'Остаток', 'Дата заключения', 'Договор подписан', 'Срок исполнения', 'Дата акта', 'Акт подписан',
                  'Статусы работы', 'Статусы клиента', 'Оплаты', 'Примечание', 'Папка']


def export_cards(db, destination):
    """Перезаписывает файл выгрузкой всех карточек договоров на проекты ГСВ; возвращает число строк."""
    import openpyxl
    from openpyxl.styles import Font
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Проекты ГСВ'
    ws.append(EXPORT_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ids = [r[0] for r in db.fetchall('SELECT id FROM gsv_projects ORDER BY seq_num DESC, id DESC')]
    for pid in ids:
        t = project_tags(db, pid)
        pays = payments_list(db, pid)
        folder = db.fetchone('SELECT project_folder FROM gsv_projects WHERE id=?', (pid,))[0] or ''
        ws.append([t['НОМЕР_ПД'], t['НОМЕР_ДОГОВОРА'], t['ОБЪЕКТ'], t['АДРЕС_ОБЪЕКТА'], t['ТУ'], t['КЛИЕНТ'], t['ТЕЛЕФОН'], t['АДРЕС_КЛИЕНТА'], t['ПАСПОРТ'],
                   t['КЕМ_ВЫДАН'], t['ДАТА_ВЫДАЧИ'], float(t['СТОИМОСТЬ'].replace(',', '.')), float(t['ОПЛАЧЕНО'].replace(',', '.')),
                   float(t['ОСТАТОК'].replace(',', '.')), t['ДАТА_ЗАКЛЮЧЕНИЯ_С'], t['ДОГОВОР_ПОДПИСАН'], t['СРОК_ИСПОЛНЕНИЯ_С'], t['ДАТА_АКТА_С'],
                   t['АКТ_ПОДПИСАН'], t['СТАТУС_РАБОТЫ'], t['СТАТУС_КЛИЕНТА'],
                   '; '.join(f'{date_short(d).rstrip("г.")}: {money(a)}' + (f' ({n})' if n else '') for d, a, n in pays), t['ПРИМЕЧАНИЕ'], folder])
    for col in ws.columns:
        width = max((len(str(c.value)) for c in col if c.value is not None), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 50)
    for row in ws.iter_rows():
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'
    _save_atomic(lambda p: wb.save(p), destination)
    return len(ids)
