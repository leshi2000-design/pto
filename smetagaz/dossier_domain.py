"""Persistent executive dossiers, source certificates and incremental generation."""
from pathlib import Path
import hashlib
import json
import shutil
import threading
from functools import partial
from . import template_domain as domain

def migrate(db):
    for sql in [
      'CREATE TABLE IF NOT EXISTS dossiers(id INTEGER PRIMARY KEY,module TEXT NOT NULL,title TEXT NOT NULL,owner_type TEXT,owner_id INTEGER,folder_path TEXT DEFAULT \'\',created_at TEXT DEFAULT CURRENT_TIMESTAMP)',
      'CREATE INDEX IF NOT EXISTS idx_dossier_owner ON dossiers(owner_type,owner_id)',
      'CREATE TABLE IF NOT EXISTS dossier_certificates(dossier_id INTEGER REFERENCES dossiers(id) ON DELETE CASCADE,certificate_id INTEGER REFERENCES certificates(id) ON DELETE RESTRICT,PRIMARY KEY(dossier_id,certificate_id))',
      'CREATE TABLE IF NOT EXISTS dossier_files(id INTEGER PRIMARY KEY,dossier_id INTEGER REFERENCES dossiers(id) ON DELETE CASCADE,slot TEXT NOT NULL,title TEXT NOT NULL,file_path TEXT NOT NULL,signature TEXT NOT NULL,sha256 TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(dossier_id,slot))',
      'CREATE TABLE IF NOT EXISTS dossier_selection(dossier_id INTEGER REFERENCES dossiers(id) ON DELETE CASCADE,slot TEXT NOT NULL,PRIMARY KEY(dossier_id,slot))',
      "CREATE TABLE IF NOT EXISTS gsn_equipment(id INTEGER PRIMARY KEY,project_id INTEGER NOT NULL REFERENCES gsn_projects(id) ON DELETE CASCADE,equipment_name TEXT DEFAULT '',equipment_kind TEXT DEFAULT '',equipment_model TEXT DEFAULT '',certificate_number TEXT DEFAULT '',note TEXT DEFAULT '',linked_cert_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL)",
    ]:db.execute(sql)
    if db.get_setting('dossier_history_migrated','0')!='1':
        for owner,rid in db.fetchall('SELECT DISTINCT owner_type,owner_id FROM executive_generated'):
            domain.record(db,owner,rid);did=create(db,'ГСН' if owner=='gsn_projects' else 'ГСВ',owner,rid)
            for fid,title,file,sha,created in db.fetchall('SELECT id,title,file_path,sha256,created_at FROM executive_generated WHERE owner_type=? AND owner_id=?',(owner,rid)):
                db.execute('INSERT INTO dossier_files(dossier_id,slot,title,file_path,signature,sha256,updated_at) VALUES(?,?,?,?,?,?,?)',(did,'legacy:'+str(fid),title,file,'',sha or '',created))
        db.set_setting('dossier_history_migrated','1')
    for owner in domain.OWNERS:
        db.execute(f"CREATE TRIGGER IF NOT EXISTS protect_dossier_{owner} BEFORE DELETE ON {owner} WHEN EXISTS(SELECT 1 FROM dossiers WHERE owner_type='{owner}' AND owner_id=old.id) BEGIN SELECT RAISE(ABORT,'У договора есть исполнительная документация. Удаление запрещено для сохранения истории.'); END")

def create(db,module,owner=None,rid=None,title='',folder=''):
    if module not in ('ГСН','ГСВ'):raise ValueError('Выберите ГСН или ГСВ')
    if owner:
        data=domain.record(db,owner,rid)
        if (owner=='gsn_projects')!=(module=='ГСН'):raise ValueError('Договор относится к другому разделу')
        title=data.get('title') or data.get('object_name') or title
    if not title.strip():raise ValueError('Укажите объект')
    with db.transaction():
        did=db.execute('INSERT INTO dossiers(module,title,owner_type,owner_id,folder_path) VALUES(?,?,?,?,?)',(module,title.strip(),owner,rid,folder)).lastrowid
        for slot, in db.fetchall("SELECT slot FROM executive_templates WHERE module=? AND file_path<>''",(module,)):db.execute('INSERT INTO dossier_selection(dossier_id,slot) VALUES(?,?)',(did,slot))
        return did

def row(db,did):
    cur=db.execute('SELECT * FROM dossiers WHERE id=?',(did,));record=cur.fetchone()
    if not record:raise ValueError('Комплект не найден')
    return dict(zip([c[0] for c in cur.description],record))
def folder(db,did):
    data=row(db,did);base=data['folder_path']
    if data['owner_type']:base=domain.load_details(db,data['owner_type'],data['owner_id'])[0] or base
    if not base:raise ValueError('Укажите папку договора / объекта')
    root=domain.path(db,base)
    if not root.is_dir():raise ValueError('Папка объекта недоступна')
    return root/('ИД_'+data['module']+'_'+str(did))
def templates(db,did):
    data=row(db,did);result=[]
    for slot,label,file,name in db.fetchall('SELECT slot,label,file_path,output_name FROM executive_templates WHERE module=? ORDER BY id',(data['module'],)):
        override=db.fetchone('SELECT file_path,output_name FROM executive_overrides WHERE owner_type=? AND owner_id=? AND slot=?',(data['owner_type'],data['owner_id'],slot)) if data['owner_type'] else None
        result.append(dict(slot=slot,label=label,file_path=override[0] if override else file,output_name=override[1] if override else name))
    return result

def certificates(db,did):
    data=row(db,did);sources={}
    def collect(cid,label):
        if cid:sources.setdefault(cid,[]).append(label)
    owner,rid=data['owner_type'],data['owner_id']
    if owner:
        for m in domain.material_rows(db,owner,rid):collect(m['certificate_id'],'Материал: '+m['name'])
        table,key={'contracts':('contract_equipment','contract_id'),'gsn_projects':('gsn_equipment','project_id'),'gsv_projects':('gsv_equipment','project_id')}[owner]
        for name,cid in db.fetchall(f'SELECT equipment_name,linked_cert_id FROM {table} WHERE {key}=?',(rid,)):collect(cid,'Оборудование: '+name)
        if owner!='gsn_projects':
            for name,cid in db.fetchall('SELECT p.name,p.certificate_id FROM object_pipelines op JOIN gsv_pipelines p ON p.id=op.pipeline_id WHERE op.owner_type=? AND op.owner_id=?',(owner,rid)):collect(cid,'Трубопровод: '+name)
    for cid, in db.fetchall('SELECT certificate_id FROM dossier_certificates WHERE dossier_id=?',(did,)):collect(cid,'Добавлен в ИД')
    result=[]
    for cid,labels in sources.items():
        cert=db.fetchone('SELECT name,cert_number,file_path FROM certificates WHERE id=?',(cid,))
        if cert:result.append(dict(id=cid,name=cert[0],number=cert[1] or '',path=cert[2] or '',source='; '.join(labels),manual='Добавлен в ИД' in labels))
    return result

def context(db,did):
    data=row(db,did)
    if data['owner_type']:
        ctx,mats=domain.context(db,data['owner_type'],data['owner_id'])
        table,key={'contracts':('contract_equipment','contract_id'),'gsn_projects':('gsn_equipment','project_id'),'gsv_projects':('gsv_equipment','project_id')}[data['owner_type']]
        cur=db.execute(f'SELECT equipment_name name,equipment_kind kind,equipment_model model,certificate_number FROM {table} WHERE {key}=? ORDER BY id',(data['owner_id'],));equipment=[dict(zip([c[0] for c in cur.description],r)) for r in cur.fetchall()]
    else:ctx=dict(object_name=data['title'],объект=data['title'],module=data['module']);mats=[];equipment=[]
    certs=certificates(db,did);ctx['certificates']='\n'.join(c['name']+' № '+c['number'] for c in certs);ctx['сертификаты']=ctx['certificates'];ctx['dossier_title']=data['title'];ctx['equipment']='\n'.join(e['name']+' · '+(e['certificate_number'] or '') for e in equipment)
    return ctx,{'materials':mats,'equipment':equipment},certs

def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

_generation_lock=threading.Lock()

def _plan(db, did, slots=None, require_folder=False):
    from .template_engine import transform, filename
    with db.transaction():
        ctx, tables, certs = context(db, did)
        data = row(db, did)
        try:
            target = folder(db, did)
        except ValueError:
            if require_folder:
                raise
            target = Path('ИД_' + data['module'] + '_' + str(did))
        selected = set(slots) if slots is not None else {r[0] for r in db.fetchall('SELECT slot FROM dossier_selection WHERE dossier_id=?', (did,))}
        tpls = [t for t in templates(db, did) if t['slot'] in selected]
        old = {r[0]: r[1:] for r in db.fetchall('SELECT slot,file_path,signature,sha256 FROM dossier_files WHERE dossier_id=?', (did,))}
    jobs = []
    for template in tpls:
        if not template['file_path']:
            raise ValueError('Не подключён шаблон: ' + template['label'])
        source = domain.path(db, template['file_path'])
        out = target / (filename(template['label']) + '_' + template['slot'] + source.suffix.lower())
        jobs.append(dict(key=template['slot'], title=template['label'], source=source, path=out, tags=transform(source), copy=False))
    if data['owner_type'] in ('contracts', 'gsv_projects'):
        for docid, title, file in db.fetchall('SELECT d.id,d.title,d.file_path FROM object_welding_documents l JOIN welding_documents d ON d.id=l.document_id WHERE l.owner_type=? AND l.owner_id=?',
                                             (data['owner_type'], data['owner_id'])):
            source = domain.path(db, file)
            if not source.is_file():
                raise ValueError('Недоступен документ сварки: ' + title)
            jobs.append(dict(key='welding:' + str(docid), title=title, source=source, path=target / ('Сварка_' + str(docid) + '_' + filename(source.name)), tags=set(), copy=True))
    for cert in certs:
        source = domain.path(db, cert['path']) if cert['path'] else None
        if source is None or not source.is_file():
            raise ValueError('Недоступен файл сертификата: ' + cert['name'])
        jobs.append(dict(key='cert:' + str(cert['id']), title=cert['name'], source=source, path=target / ('Сертификат_' + str(cert['id']) + '_' + filename(source.name)), tags=set(), copy=True))
    if not jobs:
        raise ValueError('Подключите и выберите шаблоны или добавьте сертификаты')
    return ctx, tables, target, old, jobs


def planned_documents(db, did, slots=None):
    return _plan(db, did, slots)[4]


def generate(db, did, destinations=None):
    with _generation_lock:
        return _generate(db, did, destinations)


def _generate(db, did, destinations=None):
    from .table_templates import render
    from .document_files import validate_destinations, publish_files
    ctx, tables, target, old, jobs = _plan(db, did, require_folder=destinations is None)
    jobs = validate_destinations(jobs, destinations)
    ctx['document_register'] = '\n'.join(f'{i}. {job["title"]} — {job["path"].name}' for i, job in enumerate(jobs, 1))
    ctx['реестр'] = ctx['document_register']
    changed, unchanged, writers = [], [], []
    for job in jobs:
        slot, source, out, tags = job['key'], job['source'], job['path'], job['tags']
        dependency = {k: ctx.get(k, tables.get(k.split('.')[0])) for k in sorted(tags)}
        sig = hashlib.sha256((digest(source) + json.dumps(dependency, sort_keys=True, ensure_ascii=False, default=str)).encode()).hexdigest()
        previous = old.get(slot)
        same_path = previous and domain.path(db, previous[0]).resolve() == out.resolve()
        if previous and not same_path and domain.path(db, previous[0]).exists() and destinations is None:
            raise ValueError('Папка или имя ранее созданного файла изменены. Создайте новый комплект для другой папки.')
        if same_path and previous[1] == sig and out.is_file() and digest(out) == previous[2]:
            unchanged.append(str(out))
            continue
        if destinations is None and out.exists() and (not previous or digest(out) != previous[2]):
            raise ValueError('Файл изменён вручную или создан вне программы. Сохраните его отдельно и уберите из рабочей папки перед переформированием: ' + out.name)
        changed.append((job, sig))
        writer = partial(shutil.copyfile, source) if job['copy'] else partial(render, source, ctx, tables)
        writers.append((out, writer))
    def record(hashes):
        with db.transaction():
            row(db, did)
            for job, sig in changed:
                db.execute('INSERT INTO dossier_files(dossier_id,slot,title,file_path,signature,sha256) VALUES(?,?,?,?,?,?) ON CONFLICT(dossier_id,slot) DO UPDATE SET title=excluded.title,file_path=excluded.file_path,signature=excluded.signature,sha256=excluded.sha256,updated_at=CURRENT_TIMESTAMP',
                           (did, job['key'], job['title'], str(job['path']), sig, hashes[str(job['path'])]))
    publish_files(writers, record)
    parents = {str(job['path'].parent) for job in jobs}
    return {'changed': len(changed), 'unchanged': len(unchanged), 'folder': next(iter(parents)) if len(parents) == 1 else str(target),
            'paths': [str(job['path']) for job in jobs]}
