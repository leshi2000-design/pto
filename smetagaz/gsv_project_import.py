"""Импорт договоров «Проекты ГСВ» из таблицы Excel.

Каждый столбец таблицы привязывается к графе карточки договора (см. FIELDS). Модуль не зависит от Qt.
"""
import re
from datetime import date, datetime, timedelta

from . import gsv_project_domain as gd
from .gsv_domain import save_client

# ключ графы -> (название графы в карточке, допустимые заголовки столбцов)
FIELDS = {
    'pd_number': ('№ ПД  {НОМЕР_ПД}', ['№ пд', 'номер пд', 'пд', 'номер проекта']),
    'object_name': ('Объект  {ОБЪЕКТ}', ['наименование объекта строительства', 'наименование объекта', 'объект', 'объект строительства', 'объект проектирования']),
    'client_address': ('Адрес клиента  {АДРЕС_КЛИЕНТА}', ['адрес', 'адрес клиента', 'адрес заказчика']),
    'object_address': ('Адрес объекта  {АДРЕС_ОБЪЕКТА}', ['адрес объекта', 'адрес объекта строительства']),
    'client_name': ('Клиент  {КЛИЕНТ}', ['заказчик', 'клиент', 'фио', 'фио заказчика']),
    'phone': ('Телефон  {ТЕЛЕФОН}', ['телефон', 'телефоны', 'тел']),
    'passport': ('Паспорт  {ПАСПОРТ}', ['паспортные данные', 'паспорт']),
    'passport_issuer': ('Кем выдан  {КЕМ_ВЫДАН}', ['кем выдан', 'орган выдачи']),
    'passport_date': ('Дата выдачи паспорта  {ДАТА_ВЫДАЧИ}', ['дата выдачи', 'дата выдачи паспорта']),
    'contract_number': ('Номер договора  {НОМЕР_ДОГОВОРА}', ['№ договора', 'номер договора', 'договор']),
    'contract_date': ('Дата заключения  {ДАТА_ЗАКЛЮЧЕНИЯ_П}', ['дата заключения', 'дата договора', 'дата заключения договора']),
    'act_date': ('Дата акта  {ДАТА_АКТА_П}', ['дата акта', 'акт']),
    'cost': ('Стоимость  {СТОИМОСТЬ}', ['стоимость', 'сумма', 'цена']),
    'due_date': ('Срок исполнения  {СРОК_ИСПОЛНЕНИЯ_П}', ['срок выполнения', 'срок исполнения', 'срок сдачи', 'срок']),
    'tu_text': ('ТУ  {ТУ}', ['ту', 'технические условия', 'тех условия', 'номер и дата ту']),
    'notes': ('Примечание  {ПРИМЕЧАНИЕ}', ['примечание', 'примечания', 'комментарий']),
}
DATE_FIELDS = ('contract_date', 'act_date', 'due_date', 'passport_date')
MONTHS = {name: i for i, name in enumerate(gd.MONTHS_GENITIVE) if name}


def norm_header(text):
    text = str(text or '').casefold().replace('ё', 'е')
    text = re.sub(r'[^\w\s№]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def auto_map(headers):
    """{индекс столбца: ключ графы} по названиям столбцов; каждая графа назначается одному столбцу."""
    synonyms = {norm_header(s): key for key, (_label, names) in FIELDS.items() for s in names}
    mapping, used = {}, set()
    for i, header in enumerate(headers):
        key = synonyms.get(norm_header(header))
        if key and key not in used:
            mapping[i] = key
            used.add(key)
    return mapping


def read_table(path):
    """(заголовки, строки, номер строки заголовка). Строка заголовков ищется среди первых 15 строк по совпадению с известными названиями."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    best, best_score = 0, -1
    for i, row in enumerate(rows[:15]):
        score = len(auto_map(row))
        if score > best_score:
            best, best_score = i, score
    headers = [str(c).strip() if c is not None else '' for c in rows[best]] if rows else []
    body = [r for r in rows[best + 1:] if any(c not in (None, '') for c in r)]
    return headers, body, best + 1


# --- разбор значений ---------------------------------------------------------------------------

def parse_date(value):
    """-> ('ГГГГ-ММ-ДД' | '', ошибка?). Понимает даты Excel, «12.11.2026», «12 ноября 2026г.», «2026-11-12»."""
    if value is None or str(value).strip() == '':
        return '', False
    if isinstance(value, datetime):
        return value.date().isoformat(), False
    if isinstance(value, date):
        return value.isoformat(), False
    if isinstance(value, (int, float)) and 20000 < value < 80000:       # серийный номер даты Excel
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat(), False
    text = str(value).strip().casefold().replace('ё', 'е')
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', text)
    parts = None
    if m:
        parts = tuple(map(int, m.groups()))
    else:
        m = re.match(r'^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})', text)
        if m:
            d_, mo, y = map(int, m.groups())
            parts = (y + 2000 if y < 100 else y, mo, d_)
        else:
            m = re.match(r'^(\d{1,2})\s+([а-я]+)\s+(\d{4})', text)
            if m and m.group(2) in MONTHS:
                parts = (int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    try:
        return (date(*parts).isoformat(), False) if parts else ('', True)
    except ValueError:
        return '', True


def parse_cost(value):
    """-> (число | None, ошибка?)."""
    if value is None or str(value).strip() == '':
        return None, False
    if isinstance(value, (int, float)):
        return float(value), False
    text = re.sub(r'[^\d,.\-]', '', str(value).replace('\xa0', ' ')).strip('.,')
    # последний разделитель — десятичный, остальные (разряды тысяч) убираются
    last = max(text.rfind(','), text.rfind('.'))
    if last >= 0:
        text = re.sub(r'[,.]', '', text[:last]) + '.' + text[last + 1:]
    try:
        return float(text), False
    except ValueError:
        return None, True


def parse_pd(value):
    """«01-26 ГСВ» -> (номер, год, нормализованный текст)."""
    m = re.match(r'^\s*(\d+)\s*[-/.]\s*(\d{2})\b', str(value or ''))
    if not m:
        return None, None, str(value or '').strip()
    seq, year = int(m.group(1)), int(m.group(2))
    return seq, year, f'{seq:02}-{year:02} ГСВ'


def cell_text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


# --- подготовка и импорт -----------------------------------------------------------------------

def prepare(db, rows, mapping):
    """Разбирает строки по привязке столбцов. Возвращает список {row, data, status, messages}.

    status: new — будет создан, exists — ПД уже есть в программе, error — строка пропускается.
    """
    by_field = {key: idx for idx, key in mapping.items() if key}
    result, seen = [], set()
    for number, row in enumerate(rows, 1):
        data, messages, error = {}, [], False
        for key, idx in by_field.items():
            value = row[idx] if idx < len(row) else None
            if key in DATE_FIELDS:
                iso, bad = parse_date(value)
                data[key] = iso
                if bad:
                    messages.append(f'не распознана дата «{cell_text(value)}» ({FIELDS[key][0].split("  ")[0]})')
            elif key == 'cost':
                cost, bad = parse_cost(value)
                data[key] = cost
                if bad:
                    messages.append(f'не распознана стоимость «{cell_text(value)}»')
            else:
                data[key] = cell_text(value)
        if not data.get('client_name'):
            messages.append('нет заказчика')
            error = True
        seq = year = None
        if data.get('pd_number'):
            seq, year, data['pd_number'] = parse_pd(data['pd_number'])
            if seq is None:
                messages.append(f'не распознан номер ПД «{data["pd_number"]}», ожидается вид 01-26 ГСВ')
                error = True
        data['seq'], data['year'] = seq, year
        status = 'error' if error else 'new'
        if not error and data.get('pd_number'):
            if data['pd_number'] in seen:
                messages.append('номер ПД повторяется в таблице выше')
                status = 'error'
            seen.add(data['pd_number'])
            if db.fetchone('SELECT 1 FROM gsv_projects WHERE pd_number=?', (data['pd_number'],)):
                status = 'exists'
        result.append(dict(row=number, data=data, status=status, messages=messages))
    return result


def _client_key(name):
    return ' '.join(str(name or '').split()).casefold()


def find_client(db, name):
    key = _client_key(name)
    for cid, cname in db.fetchall('SELECT id,name FROM crm.clients ORDER BY id'):
        if _client_key(cname) == key:
            return cid
    return None


def _save_client_for(db, data):
    cid = find_client(db, data['client_name'])
    values = dict(name=data['client_name'], phone=data.get('phone', ''), address=data.get('client_address', ''), passport=data.get('passport', ''),
                  passport_issuer=data.get('passport_issuer', ''), passport_date=data.get('passport_date', ''))
    if cid:      # существующий клиент: пустые поля дополняются, заполненные не затираются
        from .gsv_domain import get_client
        current = get_client(db, cid)
        for key, value in values.items():
            if current.get(key):
                values[key] = current[key]
    return save_client(db, values, cid)


def import_rows(db, prepared, on_exists='skip', infer_statuses=True):
    """Создаёт (и при on_exists='update' обновляет) договоры. Возвращает счётчики и список ошибок."""
    report = dict(created=0, updated=0, skipped=0, errors=[])
    todo = sorted((p for p in prepared if p['status'] != 'error'), key=lambda p: (p['data']['year'] or 99, p['data']['seq'] or 9999, p['row']))
    for p in prepared:
        if p['status'] == 'error':
            report['errors'].append((p['row'], '; '.join(p['messages'])))
    ids = {r[1]: r[0] for kind in ('work', 'client') for r in gd.catalog(db, kind)}
    for p in todo:
        data = p['data']
        if p['status'] == 'exists' and on_exists != 'update':
            report['skipped'] += 1
            continue
        try:
            with db.transaction():
                cid = _save_client_for(db, data)
                from .gsv_domain import get_client
                client = get_client(db, cid)       # в карточке договора хранится копия данных клиента из «Клиенты»
                data = dict(data, client_name=client['name'], phone=client['phone'], passport=client['passport'], client_address=client['address'])
                contract, act = data.get('contract_date', ''), data.get('act_date', '')
                due = data.get('due_date') or (gd.default_due(contract).isoformat() if contract else '')
                fields = dict(object_name=data.get('object_name', ''), address=data.get('object_address', ''), client_name=data['client_name'],
                              phone=data.get('phone', ''), passport=data.get('passport', ''), client_id=cid, client_address=data.get('client_address', ''),
                              contract_date=contract or None, due_date=due or None, act_date=act or None, tu_text=data.get('tu_text', ''),
                              contract_signed=int(bool(contract)), act_signed=int(bool(act)))
                if data.get('cost') is not None:
                    fields['cost'] = data['cost']
                if data.get('notes'):
                    fields['notes'] = data['notes']
                existing = db.fetchone('SELECT id FROM gsv_projects WHERE pd_number=?', (data.get('pd_number'),)) if data.get('pd_number') else None
                if existing:
                    pid = existing[0]
                    db.execute('UPDATE gsv_projects SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), pid))
                    if data.get('contract_number'):
                        db.execute('UPDATE gsv_projects SET contract_number=? WHERE id=?', (data['contract_number'], pid))
                    report['updated'] += 1
                else:
                    year = data['year'] if data.get('year') is not None else datetime.now().year % 100
                    seq = data['seq'] if data.get('seq') is not None else db.fetchone('SELECT coalesce(max(seq_num),0)+1 FROM gsv_projects WHERE year_num=?', (year,))[0]
                    pd_number = data.get('pd_number') or f'{seq:02}-{year:02} ГСВ'
                    fields.update(pd_number=pd_number, seq_num=seq, year_num=year, contract_number=data.get('contract_number') or f'{seq:02}-03/{year:02}')
                    fields.setdefault('cost', 250.0)
                    pid = db.execute('INSERT INTO gsv_projects(' + ','.join(fields) + ') VALUES(' + ','.join('?' for _ in fields) + ')', tuple(fields.values())).lastrowid
                    report['created'] += 1
                    if infer_statuses:
                        names = ['Акт подписан', 'Сделано'] if act else ['Договор подписан'] if contract else ['Договор не подписан']
                        gd.set_project_statuses(db, pid, [ids[n] for n in names if n in ids])
        except Exception as e:
            report['errors'].append((p['row'], str(e)))
    return report
