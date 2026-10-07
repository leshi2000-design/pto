"""Проверка целостности базы: связи между записями, пропавшие файлы и папки, служебные проверки SQLite. Только чтение, кроме явного исправления."""
import os

# (таблица, поле клиента, подпись раздела, поле с названием для сообщений)
CLIENT_TABLES = [('estimates', 'Сметы', 'title'), ('contracts', 'Монтаж ГСВ', 'contract_number'), ('gsv_projects', 'Проекты ГСВ', 'pd_number'), ('gsn_projects', 'Монтаж ГСН', 'contract_number')]
FILE_CHECKS = [
    ('certificates', 'id', 'name', 'file_path', 'Сертификаты', 'Файл сертификата'),
    ('gsvm_equipment', 'contract_id', "kind||' '||model", 'file_path', 'Монтаж ГСВ · оборудование', 'Паспорт / сертификат оборудования'),
    ('gsvm_contract_certs', 'contract_id', "title", 'file_path', 'Монтаж ГСВ · сертификаты', 'Произвольный сертификат'),
    ('gsvm_docs', 'contract_id', "kind", 'file_path', 'Монтаж ГСВ · документы', 'Документ договора'),
    ('gsv_project_docs', 'project_id', "kind", 'file_path', 'Проекты ГСВ · документы', 'Документ проекта'),
    ('welding_documents', 'id', 'title', 'file_path', 'Сварщики', 'Аттестат / документ сварщика'),
    ('attachments', 'estimate_id', 'file_name', 'file_path', 'Сметы', 'Вложение сметы'),
    ('le_docs', 'ref_id', "kind", 'file_path', 'Юрлица · документы', 'Документ'),
    ('smr_docs', 'ref_id', "kind", 'file_path', 'СМР · документы', 'Документ'),
]
FOLDER_CHECKS = [
    ('contracts', 'id', "coalesce(contract_number,'')||' '||coalesce(nullif(client_name,''),party_name)", 'contract_folder', 'Монтаж ГСВ'),
    ('gsv_projects', 'id', "coalesce(pd_number,'')||' '||coalesce(nullif(client_name,''),party_name)", 'project_folder', 'Проекты ГСВ'),
    ('executive_objects', 'id', "owner_type||' №'||owner_id", 'folder_path', 'Исполнительная документация'),
    ('le_contracts', 'id', "coalesce(contract_number,'')||' '||coalesce(object_name,'')", 'folder', 'Юрлица'),
    ('smr_contracts', 'id', "coalesce(contract_number,'')||' '||coalesce(object_name,'')", 'folder', 'СМР'),
]
TEMPLATE_SETTINGS = ['gsvp_tpl_contract', 'gsvp_tpl_act', 'gsvp_tpl_card', 'custom_template_path', 'export_excel_template', 'export_word_template']
LIMIT = 300


def _finding(level, category, text, ref=None, fix=None):
    return dict(level=level, category=category, text=text, ref=ref, fix=fix)


def _table_exists(db, name):
    return bool(db.fetchone("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)))


def _columns(db, table):
    return {r[1] for r in db.fetchall(f'PRAGMA table_info({table})')}


def check(db):
    """Возвращает список замечаний; пустой список — всё в порядке."""
    found = []
    # --- служебные проверки SQLite ---
    for schema, label in (('main', 'smetagaz.db'), ('crm', 'clients.db')):
        rows = [r[0] for r in db.fetchall(f'PRAGMA {schema}.integrity_check')]
        if rows != ['ok']:
            found += [_finding('error', 'База данных', f'{label}: {r}') for r in rows[:10]]
    for table, rowid, parent, _fk in db.fetchall('PRAGMA foreign_key_check')[:LIMIT]:
        found.append(_finding('error', 'Связи', f'Запись {rowid} таблицы {table} ссылается на несуществующую запись ({parent})'))
    # --- клиенты ---
    for table, label, title in CLIENT_TABLES:
        if not _table_exists(db, table) or 'client_id' not in _columns(db, table):
            continue
        for rid, name, cid in db.fetchall(f"SELECT id,{title},client_id FROM {table} WHERE client_id IS NOT NULL AND client_id NOT IN (SELECT id FROM crm.clients) LIMIT {LIMIT}"):
            found.append(_finding('error', 'Клиенты', f'{label}: «{name or rid}» ссылается на удалённого клиента №{cid}', (table, rid), 'client_link'))
        if table != 'estimates':
            for rid, name in db.fetchall(f"SELECT id,{title} FROM {table} WHERE client_id IS NULL AND {'le_client_id IS NULL AND ' if 'le_client_id' in _columns(db, table) else ''}trim(coalesce(client_name,''))='' LIMIT {LIMIT}"):
                found.append(_finding('warn', 'Клиенты', f'{label}: договор «{name or rid}» без клиента', (table, rid)))
    dup = db.fetchall("SELECT lower(trim(name)),count(*),group_concat(id) FROM crm.clients GROUP BY lower(trim(name)) HAVING count(*)>1 LIMIT 100")
    for name, n, ids in dup:
        found.append(_finding('info', 'Клиенты', f'Повторяющееся ФИО «{name}»: {n} записи (№ {ids}) — возможно, дубли'))
    # --- оплаты и сметы ---
    if _table_exists(db, 'payments'):
        for pid, amount, day, owner, oid, eid in db.fetchall("SELECT id,amount,date,owner_type,owner_id,estimate_id FROM payments"):
            if eid and not db.fetchone('SELECT 1 FROM estimates WHERE id=?', (eid,)):
                found.append(_finding('error', 'Оплаты', f'Оплата {amount} от {day}: смета №{eid} не существует'))
            elif not eid and not owner:
                found.append(_finding('error', 'Оплаты', f'Оплата {amount} от {day} не привязана ни к одному договору или смете'))
            elif not eid and owner in ('contracts', 'gsv_projects', 'gsn_projects', 'estimates', 'le_contracts', 'smr_contracts') and not db.fetchone(f'SELECT 1 FROM {owner} WHERE id=?', (oid,)):
                found.append(_finding('error', 'Оплаты', f'Оплата {amount} от {day}: договор ({owner} №{oid}) не существует'))
            if (amount or 0) <= 0:
                found.append(_finding('warn', 'Оплаты', f'Оплата от {day} с нулевой или отрицательной суммой'))
    for table, label in (('contracts', 'Монтаж ГСВ'), ('gsv_projects', 'Проекты ГСВ'), ('gsn_projects', 'Монтаж ГСН')):
        if 'estimate_id' in _columns(db, table):
            for rid, eid in db.fetchall(f'SELECT id,estimate_id FROM {table} WHERE estimate_id IS NOT NULL AND estimate_id NOT IN (SELECT id FROM estimates)'):
                found.append(_finding('error', 'Сметы', f'{label}: договор №{rid} привязан к несуществующей смете №{eid}', (table, rid)))
    # --- подписи и даты ---
    for rid, num in db.fetchall("SELECT id,contract_number FROM contracts WHERE act_signed=1 AND coalesce(acceptance_act_date,'')=''"):
        found.append(_finding('warn', 'Договоры', f'Монтаж ГСВ «{num}»: акт отмечен подписанным, но дата акта не указана', ('contracts', rid)))
    for rid, num in db.fetchall("SELECT id,pd_number FROM gsv_projects WHERE act_signed=1 AND coalesce(act_date,'')=''"):
        found.append(_finding('warn', 'Договоры', f'Проект «{num}»: акт отмечен подписанным, но дата акта не указана', ('gsv_projects', rid)))
    for num, n in db.fetchall("SELECT contract_number,count(*) FROM contracts WHERE coalesce(contract_number,'')<>'' GROUP BY contract_number HAVING count(*)>1"):
        found.append(_finding('warn', 'Договоры', f'Монтаж ГСВ: номер договора «{num}» повторяется {n} раза'))
    # --- юрлица и СМР ---
    for mod, label in (('le', 'Юрлица'), ('smr', 'СМР')):
        ct, ac = f'{mod}_contracts', f'{mod}_acts'
        if not _table_exists(db, ct):
            continue
        for rid, num, amount, acts_sum in db.fetchall(f"SELECT c.id,c.contract_number,c.amount,(SELECT coalesce(sum(amount),0) FROM {ac} WHERE contract_id=c.id) FROM {ct} c"):
            if (acts_sum or 0) - (amount or 0) > 0.005:
                found.append(_finding('warn', 'Договоры', f'{label}: по договору «{num}» актов на {acts_sum:.2f}, что больше суммы договора {amount or 0:.2f}', (ct, rid)))
        for rid, num in db.fetchall(f"SELECT a.id,a.act_number FROM {ac} a WHERE a.signed=1 AND coalesce(a.act_date,'')=''"):
            found.append(_finding('warn', 'Договоры', f'{label}: акт «{num}» отмечен подписанным, но дата акта не указана', (ac, rid)))
        for num, n in db.fetchall(f"SELECT contract_number,count(*) FROM {ct} WHERE coalesce(contract_number,'')<>'' GROUP BY contract_number HAVING count(*)>1"):
            found.append(_finding('warn', 'Договоры', f'{label}: номер договора «{num}» повторяется {n} раза'))
    for rid, num in db.fetchall("SELECT id,contract_number FROM smr_contracts WHERE (party_type='person' AND (person_id IS NULL OR person_id NOT IN (SELECT id FROM crm.clients))) OR (party_type='legal' AND legal_id IS NULL)"):
        found.append(_finding('error', 'Клиенты', f'СМР: у договора «{num}» нет контрагента или клиент удалён', ('smr_contracts', rid)))
    # --- файлы и папки ---
    for table, key, label, column, section, what in FILE_CHECKS:
        if not _table_exists(db, table) or column not in _columns(db, table):
            continue
        for rid, name, path in db.fetchall(f"SELECT {key},{label},{column} FROM {table} WHERE coalesce({column},'')<>'' LIMIT 5000"):
            if not os.path.isfile(path):
                found.append(_finding('warn', 'Файлы', f'{section}: {what} «{(name or "").strip()}» — файл не найден: {path}', (table, rid)))
    for table, key, label, column, section in FOLDER_CHECKS:
        if not _table_exists(db, table) or column not in _columns(db, table):
            continue
        for rid, name, path in db.fetchall(f"SELECT {key},{label},{column} FROM {table} WHERE coalesce({column},'')<>'' LIMIT 5000"):
            if not os.path.isdir(path):
                found.append(_finding('warn', 'Папки', f'{section}: «{(name or "").strip()}» — папка не найдена: {path}', (table, rid)))
    for key in TEMPLATE_SETTINGS + [r[0] for r in db.fetchall("SELECT key FROM settings WHERE key LIKE 'gsvm_tpl_%' OR key LIKE 'le_tpl_%' OR key LIKE 'smr_tpl_%'")]:
        path = db.get_setting(key, '')
        if path and not os.path.isfile(path):
            found.append(_finding('warn', 'Шаблоны', f'Шаблон ({key}) не найден: {path}'))
    order = {'error': 0, 'warn': 1, 'info': 2}
    found.sort(key=lambda f: order[f['level']])
    return found


def fix_dangling_clients(db):
    """Безопасное исправление: снимает ссылки на несуществующих клиентов. Возвращает число исправленных записей."""
    total = 0
    with db.transaction():
        for table, _label, _title in CLIENT_TABLES:
            if _table_exists(db, table) and 'client_id' in _columns(db, table):
                total += db.execute(f'UPDATE {table} SET client_id=NULL WHERE client_id IS NOT NULL AND client_id NOT IN (SELECT id FROM crm.clients)').rowcount
    return total


def summary(findings):
    counts = {'error': 0, 'warn': 0, 'info': 0}
    for f in findings:
        counts[f['level']] += 1
    return counts
