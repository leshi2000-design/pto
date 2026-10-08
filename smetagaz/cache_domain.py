"""Кэш тяжёлых сводок. Результат хранится не дольше TTL и сбрасывается при ЛЮБОМ изменении данных: ключ включает счётчик изменений соединения
(sqlite3 total_changes), текущую дату и «поколение» ручного сброса. Без зависимости от Qt."""
import copy
import threading
import time
from datetime import date

_lock = threading.RLock()
_store = {}
_generation = 0
STATS = {'hits': 0, 'misses': 0}


def version(db):
    """Состояние данных: любое изменение через это соединение (вставка, правка, удаление, триггеры) меняет число."""
    return (db.conn.total_changes, date.today().isoformat(), _generation)


def cached(db, key, compute, ttl=60.0):
    """Возвращает compute(), не пересчитывая, пока данные не менялись и не прошло ttl секунд."""
    full = (id(db), key)
    ver = version(db)
    now = time.monotonic()
    with _lock:
        hit = _store.get(full)
        if hit and hit[0] == ver and now - hit[1] < ttl:
            STATS['hits'] += 1
            return copy.deepcopy(hit[2])
    value = compute()
    with _lock:
        _store[full] = (version(db), now, value)
        STATS['misses'] += 1
        if len(_store) > 200:
            for stale in sorted(_store, key=lambda k: _store[k][1])[:50]:
                _store.pop(stale, None)
    return copy.deepcopy(value)


def invalidate():
    """Принудительный сброс всех сводок (например, после импорта или восстановления)."""
    global _generation
    with _lock:
        _generation += 1
        _store.clear()


# --- ИНДЕКСЫ ---------------------------------------------------------------------------------

INDEXES = [
    ('payments', 'idx_perf_payments_date', 'date'), ('payments', 'idx_perf_payments_est', 'estimate_id'),
    ('kanban_tasks', 'idx_perf_tasks_status', 'status,is_archived'),
    ('contracts', 'idx_perf_contracts_date', 'contract_date'), ('contracts', 'idx_perf_contracts_act', 'acceptance_act_date'),
    ('gsv_projects', 'idx_perf_gsv_date', 'contract_date'), ('gsv_projects', 'idx_perf_gsv_act', 'act_date'), ('gsv_projects', 'idx_perf_gsv_estimate', 'estimate_id'),
    ('gsn_projects', 'idx_perf_gsn_estimate', 'estimate_id'),
    ('le_contracts', 'idx_perf_le_date', 'contract_date'), ('le_contracts', 'idx_perf_le_status', 'status,signed'), ('le_acts', 'idx_perf_le_acts_date', 'act_date'),
    ('smr_contracts', 'idx_perf_smr_date', 'contract_date'), ('smr_contracts', 'idx_perf_smr_legal', 'legal_id'), ('smr_contracts', 'idx_perf_smr_person', 'person_id'),
    ('smr_contracts', 'idx_perf_smr_estimate', 'estimate_id'), ('smr_acts', 'idx_perf_smr_acts_date', 'act_date'),
    ('estimates', 'idx_perf_estimates_folder', 'folder_id'), ('estimates', 'idx_perf_estimates_le', 'le_client_id'),
    ('estimate_items', 'idx_perf_items_type', 'estimate_id,item_type'),
    ('le_clients', 'idx_perf_le_clients_name', 'name'), ('notes', 'idx_perf_notes_title', 'title'),
]


def migrate(db):
    """Индексы по датам, связям и статусам: ускоряют сводки «Сегодня», ведомость актов, реестры и поиск связанных записей."""
    for table, name, cols in INDEXES:
        have = {r[1] for r in db.fetchall(f'PRAGMA table_info({table})')}
        if have and all(c.strip() in have for c in cols.split(',')):
            db.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table}({cols})')
