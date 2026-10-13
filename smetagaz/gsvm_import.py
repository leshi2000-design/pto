"""Импорт договоров «Монтаж ГСВ» из таблицы Excel.

Столбцы: № договора, Адрес, Заказчик, Телефон, Паспортные данные, Дата заключения, Стоимость, Дата акта, Проект и отметки об оборудовании
(ПГ-4, Котел, Счетчик, Сигнализатор, Регулятор). Модуль не зависит от Qt."""
import re

from . import gsvm_domain as md
from .gsv_project_import import norm_header, read_table as _read_table, parse_date, parse_cost, cell_text, _save_client_for

# ключ -> (название графы, допустимые заголовки)
FIELDS = {
    'contract_number': ('№ договора', ['№ договора', 'номер договора', 'договор', '№']),
    'address': ('Адрес объекта', ['адрес', 'адрес объекта', 'адрес объекта строительства']),
    'client_address': ('Адрес клиента (если отличается)', ['адрес клиента', 'адрес заказчика']),
    'client_name': ('Заказчик', ['заказчик', 'клиент', 'фио', 'фио заказчика']),
    'phone': ('Телефон', ['телефон', 'телефоны', 'тел']),
    'passport': ('Паспортные данные', ['паспортные данные', 'паспорт']),
    'contract_date': ('Дата заключения', ['дата заключения', 'дата договора', 'дата заключения договора']),
    'cost': ('Стоимость', ['стоимость', 'сумма', 'цена']),
    'act_date': ('Дата акта', ['дата акта', 'акт']),
    'project': ('Проект (шифр проекта)', ['проект', 'номер проекта', 'проектная документация', 'шифр проекта']),
    'title': ('Название объекта', ['наименование объекта', 'наименование объекта строительства', 'объект', 'объект строительства']),
    'eq_pg': ('Оборудование: ПГ-4', ['пг 4', 'пг4', 'пг', 'плита']),
    'eq_boiler': ('Оборудование: Котел', ['котел', 'котёл']),
    'eq_meter': ('Оборудование: Счетчик', ['счетчик', 'счётчик']),
    'eq_alarm': ('Оборудование: Сигнализатор', ['сигнализатор']),
    'eq_regulator': ('Оборудование: Регулятор', ['регулятор']),
    'notes': ('Примечание', ['примечание', 'примечания', 'комментарий']),
}
EQUIPMENT = {'eq_pg': ('ПГ', 'ПГ-4'), 'eq_boiler': ('Котел', ''), 'eq_meter': ('Счётчик газа', ''), 'eq_alarm': ('Сигнализатор', ''), 'eq_regulator': ('Регулятор давления газа', '')}
DATE_FIELDS = ('contract_date', 'act_date')
NO = {'', '-', '—', '–', 'нет', 'н/д', '0', 'no', 'false', 'не требуется'}
MARKS = {'+', 'да', 'есть', 'x', 'х', 'v', '√', '✓', '1', 'yes', 'true'}


def auto_map(headers):
    """{индекс столбца: ключ графы} по названиям; каждая графа назначается одному столбцу."""
    synonyms = {norm_header(s): key for key, (_label, names) in FIELDS.items() for s in names}
    mapping, used = {}, set()
    for i, header in enumerate(headers):
        key = synonyms.get(norm_header(header))
        if key and key not in used:
            mapping[i] = key
            used.add(key)
    return mapping


def read_table(path):
    return _read_table(path, auto_map)


def equipment_rows(key, value):
    """Ячейка оборудования -> [(вид, модель)]. Пусто/«нет» — ничего; отметка — одна запись; число 2..9 — столько записей; текст — модель."""
    kind, base = EQUIPMENT[key]
    text = cell_text(value)
    low = text.casefold()
    if low in NO:
        return []
    if low in MARKS:
        return [(kind, base)]
    if re.fullmatch(r'\d+', text):
        return [(kind, base)] * min(int(text), 9)
    return [(kind, f'{base} {text}'.strip())]


def find_existing(db, data):
    """id договора: по номеру, а без номера — по заказчику, адресу и дате заключения."""
    num = data.get('contract_number')
    if num:
        row = db.fetchone('SELECT id FROM contracts WHERE contract_number=?', (num,))
    else:
        row = db.fetchone("SELECT id FROM contracts WHERE client_name=? AND coalesce(object_address,'')=? AND coalesce(contract_date,'')=?",
                          (data.get('client_name', ''), data.get('address', ''), data.get('contract_date') or ''))
    return row[0] if row else None


def prepare(db, rows, mapping, ctx=None):
    """Разбирает строки. status: new — будет создан, exists — договор с таким номером уже есть, error — пропускается."""
    by_field = {key: idx for idx, key in mapping.items() if key}
    result, seen = [], set()
    for number, row in enumerate(rows, 1):
        if ctx:
            ctx.progress(number, len(rows), f'Проверка строки {number} из {len(rows)}')
        data, messages, error = {}, [], False
        for key, idx in by_field.items():
            value = row[idx] if idx < len(row) else None
            if key in DATE_FIELDS:
                iso, bad = parse_date(value)
                data[key] = iso
                if bad:
                    messages.append(f'не распознана дата «{cell_text(value)}» ({FIELDS[key][0]})')
            elif key == 'cost':
                cost, bad = parse_cost(value)
                data[key] = cost
                if bad:
                    messages.append(f'не распознана стоимость «{cell_text(value)}»')
            elif key in EQUIPMENT:
                data[key] = equipment_rows(key, value)
            else:
                data[key] = cell_text(value)
        if not data.get('client_name'):
            messages.append('нет заказчика')
            error = True
        status = 'error' if error else 'new'
        num = data.get('contract_number')
        if not error and num:
            if num in seen:
                messages.append('номер договора повторяется в таблице выше')
                status = 'error'
            seen.add(num)
        if status != 'error' and find_existing(db, data):
            status = 'exists'
        result.append(dict(row=number, data=data, status=status, messages=messages))
    return result


def import_rows(db, prepared, on_exists='skip', ctx=None):
    """Создаёт (и при on_exists='update' обновляет) договоры монтажа ГСВ с клиентами и оборудованием."""
    import re as _re
    from .gsv_domain import get_client
    report = dict(created=0, updated=0, skipped=0, errors=[])
    for p in prepared:
        if p['status'] == 'error':
            report['errors'].append((p['row'], '; '.join(p['messages'])))
    todo = sorted((p for p in prepared if p['status'] != 'error'), key=lambda p: p['row'])
    for n, p in enumerate(todo, 1):
        if ctx:
            try:
                ctx.progress(n, len(todo), f'Импорт строки {p["row"]} ({n} из {len(todo)})')
            except Exception:       # отмена: уже сохранённые строки остаются, остальные не обрабатываются
                report['cancelled'] = len(todo) - n + 1
                break
        data = p['data']
        if p['status'] == 'exists' and on_exists != 'update':
            report['skipped'] += 1
            continue
        try:
            with db.transaction():
                cid = _save_client_for(db, dict(data, client_address=data.get('client_address') or data.get('address', '')))
                client = get_client(db, cid)
                date_c = data.get('contract_date') or ''
                act = data.get('act_date') or ''
                end = md.default_end(date_c)
                fields = dict(object_name=data.get('title') or data.get('address') or data.get('project') or client['name'], object_address=data.get('address', ''),
                              client_id=cid, client_name=client['name'], client_phone=client['phone'], client_address=client['address'],
                              passport_series_number=client['passport'], passport_issued_by=client['passport_issuer'], passport_issue_date=client['passport_date'],
                              contract_date=date_c, work_start_date=date_c, work_end_date=end.isoformat() if end else '',
                              contract_signed=int(bool(date_c)), acceptance_act_date=act, act_signed=int(bool(act)))
                if data.get('cost') is not None:
                    fields['contract_amount'] = data['cost']
                if data.get('project'):
                    fields['designer_code'] = data['project']
                if data.get('notes'):
                    fields['notes'] = data['notes']
                number = data.get('contract_number', '')
                rid = find_existing(db, data)
                if rid:
                    db.execute('UPDATE contracts SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), rid))
                    report['updated'] += 1
                else:
                    if number:
                        m = _re.match(r'^(\d+)-02/(\d{2})$', number)
                        seq, year = (int(m.group(1)), int(m.group(2))) if m else (None, None)
                    else:
                        seq, year, number = md.next_number(db, date_c)
                    fields.update(contract_number=number, seq_num=seq, year_num=year)
                    rid = db.execute('INSERT INTO contracts(' + ','.join(fields) + ') VALUES(' + ','.join('?' for _ in fields) + ')', tuple(fields.values())).lastrowid
                    report['created'] += 1
                for key, (kind, _base) in EQUIPMENT.items():
                    if key not in data:
                        continue            # столбец не импортируется — оборудование этого вида не трогаем
                    db.execute('DELETE FROM gsvm_equipment WHERE contract_id=? AND kind=?', (rid, kind))
                    for k, model in data[key]:
                        db.execute('INSERT INTO gsvm_equipment(contract_id,kind,model) VALUES(?,?,?)', (rid, k, model))
        except Exception as e:
            report['errors'].append((p['row'], str(e)))
    return report
