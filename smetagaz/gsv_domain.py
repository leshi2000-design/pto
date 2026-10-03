"""Transactional GSV/welding records; external document bytes are never imported."""
from datetime import date

EQUIPMENT_KINDS = ('Счетчик', 'Сигнализатор', 'Котел', 'Колонка', 'ПГ', 'Регулятор')
OWNER_TYPES = ('contracts', 'gsv_projects')
DOCUMENT_CATEGORIES = {'welder':'Документы сварщика', 'attestation':'Аттестация', 'contract_act':'Договоры и акты'}
DOCUMENT_TYPES = ('Аттестация','Протокол','Договор','Акт механических испытаний','Паспорт','Другое')
CLIENT_FIELDS = ('name','phone','address','passport','passport_issuer','passport_date')

def migrate(db):
    additions = {
        'contracts': {'client_name':"TEXT DEFAULT ''", 'client_phone':"TEXT DEFAULT ''"},
        'gsv_projects': {'client_address':"TEXT DEFAULT ''"},
        'crm.clients': {'passport_issuer':"TEXT DEFAULT ''", 'passport_date':"TEXT DEFAULT ''"},
        'welders': {'birth_date':"TEXT DEFAULT ''",'phone':"TEXT DEFAULT ''",'welding_type':"TEXT DEFAULT ''",'stamp':"TEXT DEFAULT ''",'grade':"TEXT DEFAULT ''",'valid_until':"TEXT DEFAULT ''"},
        'contract_equipment': {'equipment_kind':"TEXT DEFAULT ''",'equipment_model':"TEXT DEFAULT ''"},
    }
    for table, fields in additions.items():
        pragma='PRAGMA crm.table_info(clients)' if table=='crm.clients' else f'PRAGMA table_info({table})'
        existing={r[1] for r in db.fetchall(pragma)}
        for name,kind in fields.items():
            if name not in existing: db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
    statements=[
        '''CREATE TABLE IF NOT EXISTS gsv_equipment(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES gsv_projects(id) ON DELETE CASCADE,equipment_name TEXT DEFAULT '',equipment_kind TEXT DEFAULT '',equipment_model TEXT DEFAULT '',certificate_number TEXT DEFAULT '',note TEXT DEFAULT '',linked_cert_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL)''',
        '''CREATE TABLE IF NOT EXISTS gsv_pipelines(id INTEGER PRIMARY KEY,name TEXT NOT NULL,unit TEXT NOT NULL DEFAULT 'м',certificate_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL,notes TEXT DEFAULT '',active INTEGER NOT NULL DEFAULT 1)''',
        '''CREATE TABLE IF NOT EXISTS object_pipelines(id INTEGER PRIMARY KEY,owner_type TEXT NOT NULL CHECK(owner_type IN ('contracts','gsv_projects')),owner_id INTEGER NOT NULL,pipeline_id INTEGER NOT NULL REFERENCES gsv_pipelines(id) ON DELETE RESTRICT,quantity REAL NOT NULL DEFAULT 0 CHECK(quantity>=0),note TEXT DEFAULT '')''',
        '''CREATE TABLE IF NOT EXISTS welding_documents(id INTEGER PRIMARY KEY,title TEXT NOT NULL,category TEXT NOT NULL CHECK(category IN ('welder','attestation','contract_act')),document_type TEXT NOT NULL DEFAULT 'Другое',file_path TEXT NOT NULL,welder_id INTEGER REFERENCES welders(id) ON DELETE SET NULL,number TEXT DEFAULT '',document_date TEXT DEFAULT '',note TEXT DEFAULT '')''',
        '''CREATE TABLE IF NOT EXISTS object_welding_documents(owner_type TEXT NOT NULL CHECK(owner_type IN ('contracts','gsv_projects')),owner_id INTEGER NOT NULL,document_id INTEGER NOT NULL REFERENCES welding_documents(id) ON DELETE CASCADE,PRIMARY KEY(owner_type,owner_id,document_id))''',
        '''CREATE TABLE IF NOT EXISTS welding_jobs(id INTEGER PRIMARY KEY,title TEXT NOT NULL,owner_type TEXT CHECK(owner_type IN ('contracts','gsv_projects')),owner_id INTEGER,estimate_item_id INTEGER REFERENCES estimate_items(id) ON DELETE SET NULL,welder_id INTEGER REFERENCES welders(id) ON DELETE SET NULL,notes TEXT DEFAULT '',CHECK((owner_type IS NULL)=(owner_id IS NULL)))''',
        '''CREATE TABLE IF NOT EXISTS welding_days(id INTEGER PRIMARY KEY,job_id INTEGER NOT NULL REFERENCES welding_jobs(id) ON DELETE CASCADE,work_date TEXT NOT NULL,UNIQUE(job_id,work_date))''',
        'CREATE INDEX IF NOT EXISTS idx_gsv_equipment_project ON gsv_equipment(project_id)',
        'CREATE INDEX IF NOT EXISTS idx_object_pipelines ON object_pipelines(owner_type,owner_id)',
        'CREATE INDEX IF NOT EXISTS idx_welding_docs_welder ON welding_documents(welder_id,category)',
        'CREATE INDEX IF NOT EXISTS idx_welding_jobs_owner ON welding_jobs(owner_type,owner_id)',
        'CREATE INDEX IF NOT EXISTS idx_welding_days_date ON welding_days(work_date,job_id)',
    ]
    for statement in statements: db.execute(statement)
    for owner in OWNER_TYPES:
        db.execute(f'''CREATE TRIGGER IF NOT EXISTS cleanup_{owner}_gsv AFTER DELETE ON {owner} BEGIN
          DELETE FROM object_pipelines WHERE owner_type='{owner}' AND owner_id=old.id;
          DELETE FROM object_welding_documents WHERE owner_type='{owner}' AND owner_id=old.id;
          UPDATE welding_jobs SET owner_type=NULL,owner_id=NULL,estimate_item_id=NULL WHERE owner_type='{owner}' AND owner_id=old.id;
        END''')
    # SQLite cannot declare a polymorphic foreign key: enforce references in triggers.
    for table in ('object_pipelines','object_welding_documents','welding_jobs'):
        for action in ('INSERT','UPDATE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS validate_{table}_{action} BEFORE {action} ON {table}
            WHEN new.owner_type IS NOT NULL AND NOT (
             (new.owner_type='contracts' AND EXISTS(SELECT 1 FROM contracts WHERE id=new.owner_id)) OR
             (new.owner_type='gsv_projects' AND EXISTS(SELECT 1 FROM gsv_projects WHERE id=new.owner_id)))
            BEGIN SELECT RAISE(ABORT,'Объект не найден'); END''')



def get_client(db,cid):
    row=db.fetchone(f'SELECT {",".join(CLIENT_FIELDS)} FROM crm.clients WHERE id=?',(cid,))
    return dict(zip(CLIENT_FIELDS,row)) if row else None


def save_client(db,values,cid=None):
    data={key:str(values.get(key) or '').strip() for key in CLIENT_FIELDS}
    if not data['name']:raise ValueError('Введите ФИО или название клиента')
    if data['passport_date']:date.fromisoformat(data['passport_date'])
    if cid:
        if not get_client(db,cid):raise ValueError('Выбранный клиент удалён')
        db.execute('UPDATE crm.clients SET '+','.join(f'{k}=?' for k in CLIENT_FIELDS)+' WHERE id=?',(*data.values(),cid))
        return cid
    return db.execute(f'INSERT INTO crm.clients({",".join(CLIENT_FIELDS)}) VALUES({",".join("?" for _ in CLIENT_FIELDS)})',tuple(data.values())).lastrowid


def require_owner(db,owner,rid):
    if owner not in OWNER_TYPES or not rid or not db.fetchone(f'SELECT 1 FROM {owner} WHERE id=?',(rid,)):
        raise ValueError('Сначала сохраните договор / объект')


def owner_label(db,owner,rid):
    if not owner or not rid:return 'Пользовательская работа'
    if owner not in OWNER_TYPES:raise ValueError('Неизвестный объект')
    field='contract_number' if owner=='contracts' else 'pd_number'
    row=db.fetchone(f'SELECT {field},object_name FROM {owner} WHERE id=?',(rid,))
    return (('Договор ГСВ' if owner=='contracts' else 'Проект ГСВ')+f' №{row[0] or rid} · {row[1] or ""}') if row else 'Объект удалён'


def save_equipment(db,owner,rid,rows):
    from .template_domain import require
    require(db,owner,rid)
    table,key={'contracts':('contract_equipment','contract_id'),'gsv_projects':('gsv_equipment','project_id'),'gsn_projects':('gsn_equipment','project_id')}[owner]
    with db.transaction():
        db.execute(f'DELETE FROM {table} WHERE {key}=?',(rid,))
        for row in rows:
            kind=row.get('equipment_kind','');model=row.get('equipment_model','').strip()
            if kind and kind not in EQUIPMENT_KINDS:raise ValueError('Неизвестный вид оборудования')
            name=' '.join(filter(None,[kind,model])) or row.get('equipment_name','').strip()
            if not name:continue
            db.execute(f'INSERT INTO {table}({key},equipment_name,equipment_kind,equipment_model,certificate_number,note,linked_cert_id) VALUES(?,?,?,?,?,?,?)',(rid,name,kind,model,row.get('certificate_number',''),row.get('note',''),row.get('linked_cert_id')))


def save_pipelines(db,owner,rid,rows):
    require_owner(db,owner,rid)
    with db.transaction():
        db.execute('DELETE FROM object_pipelines WHERE owner_type=? AND owner_id=?',(owner,rid))
        for pipeline_id,quantity,note in rows:
            if not db.fetchone('SELECT 1 FROM gsv_pipelines WHERE id=?',(pipeline_id,)):raise ValueError('Трубопровод не найден')
            db.execute('INSERT INTO object_pipelines(owner_type,owner_id,pipeline_id,quantity,note) VALUES(?,?,?,?,?)',(owner,rid,pipeline_id,quantity,note))


def add_document(db,values,doc_id=None):
    fields=('title','category','document_type','file_path','welder_id','number','document_date','note')
    data={f:values.get(f) for f in fields}
    if not str(data['title'] or '').strip():raise ValueError('Введите название документа')
    if data['category'] not in DOCUMENT_CATEGORIES:raise ValueError('Выберите раздел документов')
    if not str(data['file_path'] or '').strip():raise ValueError('Укажите путь к файлу')
    # Retain Windows paths unchanged when moving a database between operating systems.
    data['file_path']=str(data['file_path']).strip()
    if data['document_date']:date.fromisoformat(data['document_date'])
    with db.transaction():
        if doc_id:
            db.execute('UPDATE welding_documents SET '+','.join(f'{f}=?' for f in fields)+' WHERE id=?',(*data.values(),doc_id))
            return doc_id
        return db.execute(f'INSERT INTO welding_documents({",".join(fields)}) VALUES({",".join("?" for _ in fields)})',tuple(data.values())).lastrowid


def link_documents(db,owner,rid,document_ids):
    require_owner(db,owner,rid)
    with db.transaction():
        for document_id in set(document_ids):
            db.execute('INSERT OR IGNORE INTO object_welding_documents VALUES(?,?,?)',(owner,rid,document_id))


def dossier(db,owner,rid):
    require_owner(db,owner,rid);result=[]
    table,key=('contract_equipment','contract_id') if owner=='contracts' else ('gsv_equipment','project_id')
    rows=db.fetchall(f'''SELECT e.equipment_name,e.certificate_number,c.name,c.file_path,c.id
      FROM {table} e LEFT JOIN certificates c ON c.id=e.linked_cert_id WHERE e.{key}=? ORDER BY e.id''',(rid,))
    for name,number,title,path,docid in rows:
        result.append(dict(source='Оборудование',title=title or name,number=number or '',path=path or '',reference=docid,removable=False))
    for name,number,title,path,docid in db.fetchall('''SELECT p.name,c.cert_number,c.name,c.file_path,c.id FROM object_pipelines op
      JOIN gsv_pipelines p ON p.id=op.pipeline_id LEFT JOIN certificates c ON c.id=p.certificate_id
      WHERE op.owner_type=? AND op.owner_id=? ORDER BY op.id''',(owner,rid)):
        result.append(dict(source='Трубопровод: '+name,title=title or name,number=number or '',path=path or '',reference=docid,removable=False))
    for docid,title,number,path,kind in db.fetchall('''SELECT d.id,d.title,d.number,d.file_path,d.document_type FROM object_welding_documents l
      JOIN welding_documents d ON d.id=l.document_id WHERE l.owner_type=? AND l.owner_id=? ORDER BY d.id''',(owner,rid)):
        result.append(dict(source='Сварка · '+kind,title=title,number=number or '',path=path,reference=docid,removable=True))
    from .template_domain import material_rows,path as document_path
    for m in material_rows(db,owner,rid):
        result.append(dict(source="Материал: "+m["name"],title=m["certificate_name"] or m["name"],number=m["certificate_number"] or "",path=str(document_path(db,m["certificate_path"])) if m["certificate_path"] else "",reference=m["certificate_id"],removable=False))
    for title,file in db.fetchall("SELECT title,file_path FROM executive_generated WHERE owner_type=? AND owner_id=? ORDER BY id DESC",(owner,rid)):
        result.append(dict(source="Созданный документ",title=title,number="",path=str(document_path(db,file)),reference=None,removable=False))
    return result


def save_job(db,title,owner=None,rid=None,welder_id=None,notes='',item_id=None,job_id=None):
    title=title.strip()
    if not title:raise ValueError('Укажите наименование работы')
    if owner:require_owner(db,owner,rid)
    else:rid=None
    if item_id:
        if owner!='contracts' or not db.fetchone('SELECT 1 FROM estimate_items i JOIN contracts c ON c.estimate_id=i.estimate_id WHERE c.id=? AND i.id=? AND i.item_type=?',(rid,item_id,'Работа')):
            raise ValueError('Работа не относится к выбранному договору')
    values=(title,owner,rid,item_id,welder_id,notes)
    with db.transaction():
        if job_id:
            db.execute('UPDATE welding_jobs SET title=?,owner_type=?,owner_id=?,estimate_item_id=?,welder_id=?,notes=? WHERE id=?',(*values,job_id));return job_id
        return db.execute('INSERT INTO welding_jobs(title,owner_type,owner_id,estimate_item_id,welder_id,notes) VALUES(?,?,?,?,?,?)',values).lastrowid


def set_work_day(db,job_id,day,worked):
    date.fromisoformat(day)
    if worked:db.execute('INSERT OR IGNORE INTO welding_days(job_id,work_date) VALUES(?,?)',(job_id,day))
    else:db.execute('DELETE FROM welding_days WHERE job_id=? AND work_date=?',(job_id,day))

def backfill_client_details(db):
    """Fill missing shared fields once from old contract snapshots; keep originals intact."""
    for cid,address,passport,issuer,issued in db.fetchall('''SELECT c.client_id,c.client_address,c.passport_series_number,c.passport_issued_by,c.passport_issue_date
      FROM contracts c JOIN crm.clients cl ON cl.id=c.client_id ORDER BY c.id'''):
        db.execute("""UPDATE crm.clients SET address=CASE WHEN coalesce(address,'')='' THEN ? ELSE address END,
          passport=CASE WHEN coalesce(passport,'')='' THEN ? ELSE passport END,
          passport_issuer=CASE WHEN coalesce(passport_issuer,'')='' THEN ? ELSE passport_issuer END,
          passport_date=CASE WHEN coalesce(passport_date,'')='' THEN ? ELSE passport_date END WHERE id=?""",
          (address or '',passport or '',issuer or '',issued or '',cid))
    for cid,passport in db.fetchall("SELECT client_id,passport FROM gsv_projects WHERE client_id IS NOT NULL AND coalesce(passport,'')<>'' ORDER BY id"):
        db.execute("UPDATE crm.clients SET passport=? WHERE id=? AND coalesce(passport,'')=''",(passport,cid))
