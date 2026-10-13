"""Импорт договоров «Монтаж ГСН» из таблицы Excel.

Столбцы: № договора, Адрес, Заказчик, Телефон, Паспортные данные, Дата заключения, Стоимость, Дата акта, Проект и отметки об оборудовании
(ПГ-4, Котел, Счетчик, Сигнализатор, Регулятор). Модуль не зависит от Qt."""
import json
import re
from datetime import datetime

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
    'project': ('Проект (номер проектной документации)', ['проект', 'номер проекта', 'проектная документация', 'шифр проекта']),
    'title': ('Название объекта строительства', ['наименование объекта', 'наименование объекта строительства', 'объект', 'объект строительства']),
    'eq_pg': ('Оборудование: ПГ-4', ['пг 4', 'пг4', 'пг', 'плита']),
    'eq_boiler': ('Оборудование: Котел', ['котел', 'котёл']),
    'eq_meter': ('Оборудование: Счетчик', ['счетчик', 'счётчик']),
    'eq_alarm': ('Оборудование: Сигнализатор', ['сигнализатор']),
    'eq_regulator': ('Оборудование: Регулятор', ['регулятор']),
    'notes': ('Примечание', ['примечание', 'примечания', 'комментарий']),
}
EQUIPMENT = {'eq_pg': ('ПГ', 'ПГ-4'), 'eq_boiler': ('Котел', ''), 'eq_meter': ('Счетчик', ''), 'eq_alarm': ('Сигнализатор', ''), 'eq_regulator': ('Регулятор', '')}
DATE_FIELDS = ('contract_date', 'act_date')
NO = {'', '-', '—', '–', 'нет', 'н/д', '0', 'no', 'false', 'не требуется'}
MARKS = {'+', 'да', 'есть', 'x', 'х', 'v', '√', '✓', '1', 'yes', 'true'}


def migrate(db):
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(gsn_projects)')}
    for name, ddl in (('act_date', "TEXT DEFAULT ''"), ('act_signed', 'INTEGER DEFAULT 0')):
        if name not in cols:
            db.execute(f'ALTER TABLE gsn_projects ADD COLUMN {name} {ddl}')


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


def prepare(db, rows, mapping):
    """Разбирает строки. status: new — будет создан, exists — договор с таким номером уже есть, error — пропускается."""
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
            if status != 'error' and db.fetchone('SELECT 1 FROM gsn_projects WHERE contract_number=?', (num,)):
                status = 'exists'
        result.append(dict(row=number, data=data, status=status, messages=messages))
    return result


def _set_project(db, pid, project):
    row = db.fetchone("SELECT fields_json FROM executive_objects WHERE owner_type='gsn_projects' AND owner_id=?", (pid,))
    fields = json.loads(row[0]) if row else {}
    fields['project_number'] = project
    db.execute("INSERT INTO executive_objects(owner_type,owner_id,folder_path,fields_json) VALUES('gsn_projects',?,'',?) "
               "ON CONFLICT(owner_type,owner_id) DO UPDATE SET fields_json=excluded.fields_json", (pid, json.dumps(fields, ensure_ascii=False)))


def import_rows(db, prepared, on_exists='skip'):
    """Создаёт (и при on_exists='update' обновляет) договоры ГСН с клиентами, оборудованием и номером проекта."""
    report = dict(created=0, updated=0, skipped=0, errors=[])
    for p in prepared:
        if p['status'] == 'error':
            report['errors'].append((p['row'], '; '.join(p['messages'])))
    for p in sorted((p for p in prepared if p['status'] != 'error'), key=lambda p: p['row']):
        data = p['data']
        if p['status'] == 'exists' and on_exists != 'update':
            report['skipped'] += 1
            continue
        try:
            with db.transaction():
                from .gsv_domain import get_client
                cid = _save_client_for(db, dict(data, client_address=data.get('client_address') or data.get('address', '')))
                client = get_client(db, cid)
                title = data.get('title') or data.get('address') or data.get('project') or client['name']
                act = data.get('act_date', '')
                fields = dict(title=title, address=data.get('address', ''), client_id=cid, client_name=client['name'], phone=client['phone'], passport=client['passport'],
                              contract_date=data.get('contract_date') or None, act_date=act, act_signed=int(bool(act)))
                if data.get('cost') is not None:
                    fields['contract_amount'] = data['cost']
                if data.get('notes'):
                    fields['notes'] = data['notes']
                existing = db.fetchone('SELECT id FROM gsn_projects WHERE contract_number=?', (data['contract_number'],)) if data.get('contract_number') else None
                if existing:
                    pid = existing[0]
                    db.execute('UPDATE gsn_projects SET ' + ','.join(f'{k}=?' for k in fields) + ' WHERE id=?', (*fields.values(), pid))
                    report['updated'] += 1
                else:
                    fields['contract_number'] = data.get('contract_number', '')
                    pid = db.execute('INSERT INTO gsn_projects(' + ','.join(fields) + ') VALUES(' + ','.join('?' for _ in fields) + ')', tuple(fields.values())).lastrowid
                    report['created'] += 1
                if data.get('project'):
                    _set_project(db, pid, data['project'])
                for key, (kind, _base) in EQUIPMENT.items():
                    if key not in data:
                        continue            # столбец не импортируется — оборудование этого вида не трогаем
                    db.execute('DELETE FROM gsn_equipment WHERE project_id=? AND equipment_kind=?', (pid, kind))
                    for k, model in data[key]:
                        name = f'{k} {model}'.strip() if model and not model.startswith(k) else (model or k)
                        db.execute('INSERT INTO gsn_equipment(project_id,equipment_name,equipment_kind,equipment_model) VALUES(?,?,?,?)', (pid, name, k, model))
        except Exception as e:
            report['errors'].append((p['row'], str(e)))
    return report
