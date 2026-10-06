"""Shared clients and transactionally maintained Unicode FTS search."""
from pathlib import Path

SOURCES = {
 'crm.clients': ('Клиент','name',['name','phone','notes']),
 'estimates': ('Смета', 'title', ['title','client_name','client_phone','statuses']),
 'contracts': ('Договор','contract_number',['contract_number','object_name','client_address','client_name','client_phone']),
 'gsv_projects': ('ГСВ','pd_number',['pd_number','object_name','address','client_name','phone','notes']),
 'materials': ('Материал','name',['name','note','unit']),
 'certificates': ('Сертификат','name',['name','cert_number']),
 'kanban_tasks': ('Задача','title',['title','description','status_name','tags']),
 'calendar_events': ('Событие','title',['title','description','event_date']),
 'attachments': ('Файл','file_name',['file_name','file_path']),
 'gsn_projects': ('ГСН','title',['title','address','notes','contract_number','client_name','phone']),
 'welders': ('Сварщик','name',['name','certificate','notes']),
 'writeoffs': ('Списание','title',['title','notes']),
 'gsv_pipelines': ('Трубопровод','name',['name','notes']),
 'welding_documents': ('Документ сварки','title',['title','number','document_type','note']),
 'welding_jobs': ('Работа сварки','title',['title','object_text','welder_text','notes']),
 'stock_materials': ('Материал списания','name',['name','category','unit']),
 'norm_profiles': ('Норма расхода','name',['name','diameter','thickness','basis']),
 'stock_acts': ('Акт списания','number',['number','object_name','act_date','notes']),
 'defect_acts': ('Дефектный акт','number',['number','object_name','act_date','reason']),
 'le_clients': ('Юрлицо','name',['name','unp','contact_person','phone','email']),
 'le_contracts': ('Договор (юрлицо)','contract_number',['contract_number','direction','object_name','status','note']),
 'le_acts': ('Акт (юрлицо)','act_number',['act_number','description','note']),
 'le_outgoing': ('Исходящий документ','reg_number',['reg_number','recipient','subject','note']),
}

def initialize(db):
    if not any(r[1]=='crm' for r in db.fetchall('PRAGMA database_list')):
        db.execute('ATTACH DATABASE ? AS crm',(str(Path(db.db_name).with_name('clients.db')),))
    try:Path(db.db_name).with_name('clients.db').chmod(0o600)
    except OSError:pass
    db.execute('PRAGMA crm.journal_mode=DELETE')
    db.execute('PRAGMA crm.synchronous=FULL')
    with db.transaction():
        db.execute('CREATE TABLE IF NOT EXISTS crm.clients (id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT "", address TEXT DEFAULT "", passport TEXT DEFAULT "", notes TEXT DEFAULT "")')
        db.execute('CREATE INDEX IF NOT EXISTS crm.idx_clients_name ON clients(name)')
        db.execute('CREATE TABLE IF NOT EXISTS gsn_projects(id INTEGER PRIMARY KEY, title TEXT NOT NULL, address TEXT DEFAULT "", notes TEXT DEFAULT "", client_id INTEGER)')
        db.execute('CREATE TABLE IF NOT EXISTS welders(id INTEGER PRIMARY KEY, name TEXT NOT NULL, certificate TEXT DEFAULT "", notes TEXT DEFAULT "")')
        db.execute('CREATE TABLE IF NOT EXISTS writeoffs(id INTEGER PRIMARY KEY, title TEXT NOT NULL, notes TEXT DEFAULT "", client_id INTEGER)')
        for table in ['estimates','gsv_projects','contracts','kanban_tasks','calendar_events']:
            if 'client_id' not in [r[1] for r in db.fetchall(f'PRAGMA table_info({table})')]:
                db.execute(f'ALTER TABLE {table} ADD COLUMN client_id INTEGER')
            db.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_client ON {table}(client_id)')
        for child,parent,column in [('estimate_items','estimates','estimate_id'),('payments','estimates','estimate_id'),('attachments','estimates','estimate_id'),('contracts','estimates','estimate_id'),('contract_equipment','contracts','contract_id')]:
            db.execute(f'CREATE TRIGGER IF NOT EXISTS cascade_{child} AFTER DELETE ON {parent} BEGIN DELETE FROM {child} WHERE {column}=old.id; END')
        db.execute("""CREATE TEMP TRIGGER IF NOT EXISTS estimates_contract_client AFTER UPDATE OF client_id ON main.estimates BEGIN
          UPDATE contracts SET client_id=new.client_id WHERE estimate_id=new.id;
        END""")
        from .gsv_domain import migrate
        migrate(db)
        from .stock_domain import migrate as stock_migrate
        stock_migrate(db)
        from .template_domain import migrate as template_migrate
        template_migrate(db)
        from .report_templates import migrate as reports_migrate
        reports_migrate(db)
        from .payments_domain import migrate as payment_migrate
        payment_migrate(db)
        from .task_catalog import migrate as task_migrate
        task_migrate(db)
        from .agenda_domain import migrate as agenda_migrate
        agenda_migrate(db)
        from .gsv_project_domain import migrate as gsv_project_migrate
        gsv_project_migrate(db)
        from .gsvm_domain import migrate as gsvm_migrate
        gsvm_migrate(db)
        from .dossier_domain import migrate as dossier_migrate
        dossier_migrate(db)
        from .legal_entities_domain import migrate as legal_entities_migrate
        legal_entities_migrate(db)
        db.execute('CREATE INDEX IF NOT EXISTS idx_payments_est ON payments(estimate_id)')
        db.execute('CREATE INDEX IF NOT EXISTS idx_attachments_est ON attachments(estimate_id)')
        for table, phone in [('estimates','client_phone'),('gsv_projects','phone')]:
            # Migrate once. Never merge on name alone (namesakes are common).
            for rid,name,number in db.fetchall(f'SELECT id, client_name, {phone} FROM {table} WHERE client_id IS NULL AND trim(coalesce(client_name,""))<>""'):
                match=db.fetchone('SELECT id FROM crm.clients WHERE norm(name)=norm(?) AND phone=? AND phone<>""',(name,number or ''))
                cid=match[0] if match else db.execute('INSERT INTO crm.clients(name,phone) VALUES(?,?)',(name,number or '')).lastrowid
                db.execute(f'UPDATE {table} SET client_id=? WHERE id=?',(cid,rid))
            for action in ['INSERT','UPDATE OF client_name, '+phone]:
                suffix='insert' if action=='INSERT' else 'update'
                db.execute(f'''CREATE TEMP TRIGGER IF NOT EXISTS {table}_client_{suffix} AFTER {action} ON main.{table}
                WHEN trim(coalesce(new.client_name,''))<>'' BEGIN
                  INSERT INTO clients(name,phone) SELECT new.client_name,coalesce(new.{phone},'') WHERE new.client_id IS NULL;
                  UPDATE {table} SET client_id=last_insert_rowid() WHERE id=new.id AND client_id IS NULL;
                  UPDATE clients SET name=new.client_name,phone=coalesce(new.{phone},'')
                    WHERE id=(SELECT client_id FROM {table} WHERE id=new.id)
                    AND (name IS NOT new.client_name OR phone IS NOT coalesce(new.{phone},''));
                END''')
        db.execute('UPDATE contracts SET client_id=(SELECT client_id FROM estimates WHERE estimates.id=contracts.estimate_id) WHERE client_id IS NULL')
        if db.get_setting('schema_version') not in ('3','4','5','6'):
            from .gsv_domain import backfill_client_details
            backfill_client_details(db)
        db.execute("UPDATE contracts SET client_name=(SELECT name FROM crm.clients WHERE id=contracts.client_id),client_phone=(SELECT phone FROM crm.clients WHERE id=contracts.client_id) WHERE EXISTS(SELECT 1 FROM crm.clients c WHERE c.id=contracts.client_id AND (contracts.client_name IS NOT c.name OR contracts.client_phone IS NOT c.phone))")
        db.execute('DROP TRIGGER IF EXISTS temp.client_propagate')
        db.execute('''CREATE TEMP TRIGGER IF NOT EXISTS client_propagate AFTER UPDATE ON crm.clients BEGIN
            UPDATE contracts SET client_name=new.name,client_phone=new.phone WHERE client_id=new.id;
            UPDATE gsn_projects SET client_name=new.name,phone=new.phone WHERE client_id=new.id;
            UPDATE estimates SET client_name=new.name, client_phone=new.phone WHERE client_id=new.id AND (client_name IS NOT new.name OR client_phone IS NOT new.phone);
            UPDATE gsv_projects SET client_name=new.name,phone=new.phone WHERE client_id=new.id AND (client_name IS NOT new.name OR phone IS NOT new.phone);
        END''')
        db.execute('DROP TRIGGER IF EXISTS temp.contract_client')
        db.execute('''CREATE TEMP TRIGGER IF NOT EXISTS contract_client AFTER INSERT ON main.contracts WHEN new.client_id IS NULL BEGIN
            UPDATE contracts SET client_id=(SELECT client_id FROM estimates WHERE id=new.estimate_id) WHERE id=new.id;
        END''')
        db.execute('CREATE TABLE IF NOT EXISTS export_profiles (record_key TEXT PRIMARY KEY, options TEXT NOT NULL)')
        db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(kind UNINDEXED, record_id UNINDEXED, title, body, tokenize="unicode61")')
        rebuild=db.get_setting('fts_version')!='6'
        for table_idx, (table, (_,title,fields)) in enumerate(SOURCES.items(), 1):
            body=" || ' ' || ".join(f"coalesce(new.{f},'')" for f in fields)
            for action in ['insert','update','delete']:
                newrow='' if action=='delete' else f"INSERT OR REPLACE INTO search_index(rowid,kind,record_id,title,body) VALUES({table_idx}*1000000000000+new.id,'{table}',new.id,new.{title},{body});"
                oldrow='' if action=='insert' else f"DELETE FROM search_index WHERE rowid={table_idx}*1000000000000+old.id;"
                if rebuild:db.execute(f'DROP TRIGGER IF EXISTS {"temp." if table.startswith("crm.") else ""}search_{table.replace(".","_")}_{action}')
                db.execute(f'CREATE {"TEMP " if table.startswith("crm.") else ""}TRIGGER IF NOT EXISTS search_{table.replace(".","_")}_{action} AFTER {action} ON {table} BEGIN {oldrow}{newrow} END')
        if rebuild:
            db.execute('DELETE FROM search_index')
            for table_idx,(table,(_,title,fields)) in enumerate(SOURCES.items(),1):
                body=" || ' ' || ".join(f"coalesce({f},'')" for f in fields)
                db.execute(f"INSERT OR REPLACE INTO search_index(rowid,kind,record_id,title,body) SELECT {table_idx}*1000000000000+id,'{table}',id,{title},{body} FROM {table}")
            db.set_setting('fts_version','6')


def search(db, query, limit=100, offset=0):
    import re
    tokens=re.findall(r'\w+',query,flags=re.UNICODE)
    if not tokens: return []
    expression=' AND '.join('"'+t.replace('"','""')+'"*' for t in tokens)
    return db.fetchall('SELECT kind,record_id,title,snippet(search_index,3,"",""," … ",12) FROM search_index WHERE search_index MATCH ? ORDER BY rank LIMIT ? OFFSET ?', (expression,min(max(limit,1),500),max(offset,0)))


def link_client(db, table, rid, cid):
    if table not in {'estimates','contracts','gsv_projects','gsn_projects','kanban_tasks','calendar_events','writeoffs'}:
        raise ValueError('Этот модуль не связан с клиентами')
    row=db.fetchone('SELECT name,phone FROM crm.clients WHERE id=?',(cid,))
    if not row: raise ValueError('Клиент не найден')
    with db.transaction():
        db.execute(f'UPDATE {table} SET client_id=? WHERE id=?',(cid,rid))
        if table in ('estimates','gsv_projects'):
            phone='client_phone' if table=='estimates' else 'phone'
            db.execute(f'UPDATE {table} SET client_name=?,{phone}=? WHERE id=?',(*row,rid))
        if table=='estimates': db.execute('UPDATE contracts SET client_id=? WHERE estimate_id=?',(cid,rid))


# --- Удаление клиента ---------------------------------------------------------------------------------------------
CLIENT_LINKS = [
    ('estimates', 'Сметы', ('client_name', 'client_phone')),
    ('contracts', 'Монтаж ГСВ', ('client_name', 'client_phone', 'client_address', 'passport_series_number', 'passport_issued_by', 'passport_issue_date')),
    ('gsv_projects', 'Проекты ГСВ', ('client_name', 'phone', 'passport', 'client_address')),
    ('gsn_projects', 'Монтаж ГСН', ('client_name', 'phone', 'passport')),
    ('kanban_tasks', 'Задачи', ()),
    ('calendar_events', 'События календаря', ()),
    ('writeoffs', 'Списания', ()),
]


def client_links(db, cid):
    """{раздел: число записей}, где используется клиент."""
    return {label: n for table, label, _cols in CLIENT_LINKS if (n := db.fetchone(f'SELECT count(*) FROM {table} WHERE client_id=?', (cid,))[0])}


def delete_client(db, cid):
    """Удаляет клиента и обезличивает связанные записи: связь снимается, а ФИО, телефон, паспорт и адрес в договорах и сметах очищаются.

    Очистка обязательна: иначе при следующем запуске программа заново создала бы клиента по имени из сметы или проекта.
    Сами договоры, суммы, оплаты и документы остаются. Возвращает {раздел: число записей}.
    """
    if not db.fetchone('SELECT 1 FROM crm.clients WHERE id=?', (cid,)):
        raise ValueError('Клиент не найден')
    links = client_links(db, cid)
    with db.transaction():
        for table, _label, cols in CLIENT_LINKS:
            columns = {r[1] for r in db.fetchall(f'PRAGMA table_info({table})')}
            blank = ','.join(f"{c}=''" for c in cols if c in columns)
            db.execute(f'UPDATE {table} SET client_id=NULL' + (',' + blank if blank else '') + ' WHERE client_id=?', (cid,))
        db.execute('DELETE FROM crm.clients WHERE id=?', (cid,))
    try:
        db.execute('VACUUM crm')        # физически убирает удалённые данные из файла clients.db
    except Exception:
        pass
    return links
