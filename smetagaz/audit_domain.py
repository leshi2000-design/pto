"""История изменений и корзина: триггеры SQLite пишут в журнал создание, изменение и удаление записей основных таблиц.
Удалённую запись (вместе с её дочерними записями, удалёнными в тот же момент) можно восстановить. Модуль не зависит от Qt."""
import json
from datetime import datetime, timedelta

# таблица -> (схема, название раздела для человека)
AUDITED = {
    'contracts': ('main', 'Монтаж ГСВ · договор'), 'gsn_projects': ('main', 'Монтаж ГСН · договор'), 'gsv_projects': ('main', 'Проекты ГСВ'),
    'le_contracts': ('main', 'Юрлица · договор'), 'le_acts': ('main', 'Юрлица · акт'), 'smr_contracts': ('main', 'СМР · договор'), 'smr_acts': ('main', 'СМР · акт'),
    'estimates': ('main', 'Смета'), 'payments': ('main', 'Оплата'), 'le_clients': ('main', 'Юрлицо'), 'le_contacts': ('main', 'Юрлицо · контакт'),
    'notes': ('main', 'Заметка'), 'kanban_tasks': ('main', 'Задача'), 'welders': ('main', 'Сварщик'), 'writeoffs': ('main', 'Списание'),
    'contract_equipment': ('main', 'Договор · оборудование'), 'gsvm_equipment': ('main', 'Монтаж ГСВ · оборудование'),
    'gsvm_pipelines': ('main', 'Монтаж ГСВ · трубопровод'), 'gsvm_joints': ('main', 'Монтаж ГСВ · стыки'), 'gsn_equipment': ('main', 'Монтаж ГСН · оборудование'),
    'clients': ('crm', 'Клиент'),
    'defect_acts': ('main', 'Дефектный акт'), 'defect_lines': ('main', 'Дефектный акт · работа'), 'stock_materials': ('main', 'Материал списания'),
    'stock_moves': ('main', 'Движение материала'), 'writeoff_objects': ('main', 'Объект списания'),
}
NOISY = {'est_synced_at', 'est_rev_synced', 'est_materials', 'est_works', 'updated_at'}      # служебные поля: их смена не считается изменением
LABEL_COLUMNS = ('contract_number', 'pd_number', 'number', 'name', 'title', 'object_name', 'client_name', 'text')
KEEP_DAYS = 400
RESTORE_WINDOW_SECONDS = 10
TS = "strftime('%Y-%m-%d %H:%M:%S','now','localtime')"


def _q(name):
    return '"' + name.replace('"', '') + '"'


def _columns(db, schema, table):
    rows = db.fetchall(f'PRAGMA {schema}.table_info({table})')
    return [(r[1], (r[2] or '').upper()) for r in rows], any(r[5] for r in rows if r[1] == 'id')


def _label_expr(cols, prefix):
    names = [c for c in LABEL_COLUMNS if c in cols][:2]
    if not names:
        return "''"
    first, rest = names[0], names[1:]
    expr = f"coalesce({prefix}.{_q(first)},'')"
    for c in rest:
        expr += f" || CASE WHEN coalesce({prefix}.{_q(c)},'')<>'' THEN ' · ' || {prefix}.{_q(c)} ELSE '' END"
    return expr


def _json_expr(cols, prefix):
    return 'json_object(' + ','.join(f"'{c}',{prefix}.{_q(c)}" for c in cols) + ')'


def migrate(db):
    """Создаёт журнал и триггеры (пересоздаются при изменении состава столбцов). Старые записи журнала удаляются через KEEP_DAYS дней."""
    for schema in ('main', 'crm'):
        db.execute(f"""CREATE TABLE IF NOT EXISTS {schema}.audit_log(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, table_name TEXT NOT NULL, record_id INTEGER,
                       action TEXT NOT NULL, label TEXT DEFAULT '', old_json TEXT, new_json TEXT, restored INTEGER NOT NULL DEFAULT 0)""")
        db.execute(f'CREATE INDEX IF NOT EXISTS {schema}.idx_audit_ts ON audit_log(ts)')
        db.execute(f'CREATE INDEX IF NOT EXISTS {schema}.idx_audit_rec ON audit_log(table_name,record_id)')
    for table, (schema, _title) in AUDITED.items():
        if not db.fetchone(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (table,)):
            continue
        cols_types, has_id = _columns(db, schema, table)
        cols = [c for c, t in cols_types if t != 'BLOB']
        if not has_id or 'id' not in cols:
            continue
        fingerprint = ','.join(cols)
        key = f'audit_cols_{table}'
        existing = db.fetchone(f"SELECT 1 FROM {schema}.sqlite_master WHERE type='trigger' AND name=?", (f'audit_{table}_d',))
        if existing and db.get_setting(key, '') == fingerprint:
            continue
        for suffix in ('i', 'u', 'd'):
            db.execute(f'DROP TRIGGER IF EXISTS {schema}.audit_{table}_{suffix}')
        changed = ' OR '.join(f'OLD.{_q(c)} IS NOT NEW.{_q(c)}' for c in cols if c not in NOISY) or '0'
        db.execute(f"""CREATE TRIGGER {schema}.audit_{table}_i AFTER INSERT ON {table} BEGIN
            INSERT INTO audit_log(ts,table_name,record_id,action,label) VALUES({TS},'{table}',NEW.id,'I',{_label_expr(cols, 'NEW')}); END""")
        db.execute(f"""CREATE TRIGGER {schema}.audit_{table}_u AFTER UPDATE ON {table} WHEN {changed} BEGIN
            INSERT INTO audit_log(ts,table_name,record_id,action,label,old_json,new_json)
            VALUES({TS},'{table}',NEW.id,'U',{_label_expr(cols, 'NEW')},{_json_expr(cols, 'OLD')},{_json_expr(cols, 'NEW')}); END""")
        db.execute(f"""CREATE TRIGGER {schema}.audit_{table}_d AFTER DELETE ON {table} BEGIN
            INSERT INTO audit_log(ts,table_name,record_id,action,label,old_json)
            VALUES({TS},'{table}',OLD.id,'D',{_label_expr(cols, 'OLD')},{_json_expr(cols, 'OLD')}); END""")
        db.set_setting(key, fingerprint)
    limit = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime('%Y-%m-%d %H:%M:%S')
    for schema in ('main', 'crm'):
        db.execute(f'DELETE FROM {schema}.audit_log WHERE ts<?', (limit,))


def entries(db, table='', action='', text='', limit=300, offset=0, only_unrestored_deleted=False):
    """Записи журнала обеих баз, новые сверху. Возвращает список dict."""
    result = []
    for schema in ('main', 'crm'):
        where, params = [], []
        if table:
            where.append('table_name=?'); params.append(table)
        if action:
            where.append('action=?'); params.append(action)
        if text:
            where.append("(label LIKE ? OR coalesce(old_json,'') LIKE ?)"); params += [f'%{text}%', f'%{text}%']
        if only_unrestored_deleted:
            where.append("action='D' AND restored=0")
        sql = f"SELECT id,ts,table_name,record_id,action,label,old_json,new_json,restored FROM {schema}.audit_log" + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY ts DESC,id DESC LIMIT ?'
        for r in db.fetchall(sql, (*params, limit + offset)):
            result.append(dict(id=r[0], ts=r[1], table=r[2], record_id=r[3], action=r[4], label=r[5], old=r[6], new=r[7], restored=r[8], schema=schema))
    result.sort(key=lambda e: (e['ts'], e['id']), reverse=True)
    return result[offset:offset + limit]


def diff(entry):
    """[(поле, было, стало)] для изменения; для удаления — все поля как «было»."""
    old = json.loads(entry['old']) if entry.get('old') else {}
    new = json.loads(entry['new']) if entry.get('new') else {}
    keys = [k for k in {**old, **new} if k not in NOISY]
    if entry['action'] == 'U':
        return [(k, old.get(k), new.get(k)) for k in keys if old.get(k) != new.get(k)]
    return [(k, old.get(k), None) for k in keys if old.get(k) not in (None, '')]


def _children(db, table):
    """[(дочерняя таблица, столбец связи)] среди журналируемых таблиц по внешним ключам."""
    result = []
    for child, (schema, _t) in AUDITED.items():
        if schema != AUDITED[table][0] or child == table:
            continue
        try:
            for fk in db.fetchall(f'PRAGMA {schema}.foreign_key_list({child})'):
                if fk[2] == table:
                    result.append((child, fk[3]))
        except Exception:
            continue
    result += [(c, col) for c, col in LEGACY_CHILDREN.get(table, []) if (c, col) not in result]
    return result


# связи без внешнего ключа в схеме (каскад делают триггеры приложения)
LEGACY_CHILDREN = {'contracts': [('contract_equipment', 'contract_id'), ('gsvm_equipment', 'contract_id'), ('gsvm_pipelines', 'contract_id'), ('gsvm_joints', 'contract_id')],
                   'estimates': [('payments', 'estimate_id'), ('contracts', 'estimate_id')], 'gsn_projects': [('gsn_equipment', 'project_id')],
                   'le_clients': [('le_contacts', 'client_id')]}


def restore(db, entry_id, schema='main'):
    """Восстанавливает удалённую запись и её дочерние записи, удалённые в тот же момент. Возвращает число восстановленных строк."""
    row = db.fetchone(f"SELECT id,ts,table_name,record_id,action,old_json,restored FROM {schema}.audit_log WHERE id=?", (entry_id,))
    if not row or row[4] != 'D':
        raise ValueError('Восстановить можно только удалённую запись')
    if row[6]:
        raise ValueError('Эта запись уже восстановлена')
    count = _restore_row(db, schema, row, set())
    if not count:
        raise ValueError('Запись не восстановлена')
    return count


def _restore_row(db, schema, row, done):
    eid, ts, table, record_id, _action, old_json, _restored = row
    if (table, record_id) in done:
        return 0
    done.add((table, record_id))
    data = json.loads(old_json)
    present = {c for c, _t in _columns(db, AUDITED[table][0], table)[0]}
    data = {k: v for k, v in data.items() if k in present}
    if db.fetchone(f'SELECT 1 FROM {AUDITED[table][0]}.{table} WHERE id=?', (record_id,)):
        raise ValueError(f'Запись «{table} №{record_id}» уже существует')
    with db.transaction():
        db.execute(f'INSERT INTO {AUDITED[table][0]}.{table}(' + ','.join(_q(k) for k in data) + ') VALUES(' + ','.join('?' for _ in data) + ')', tuple(data.values()))
        db.execute(f'UPDATE {schema}.audit_log SET restored=1 WHERE id=?', (eid,))
        count = 1
        moment = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
        low, high = (moment - timedelta(seconds=RESTORE_WINDOW_SECONDS)).strftime('%Y-%m-%d %H:%M:%S'), (moment + timedelta(seconds=RESTORE_WINDOW_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')
        for child, column in _children(db, table):
            child_schema = AUDITED[child][0]
            for c in db.fetchall(f"SELECT id,ts,table_name,record_id,action,old_json,restored FROM {child_schema}.audit_log WHERE table_name=? AND action='D' AND restored=0 AND ts BETWEEN ? AND ? "
                                 f"AND json_extract(old_json,'$.{column}')=? ORDER BY id", (child, low, high, record_id)):
                try:
                    count += _restore_row(db, child_schema, c, done)
                except ValueError:
                    continue       # дочерняя запись уже существует — пропускаем
    return count
