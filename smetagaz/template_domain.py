"""Shared GSN/GSV contract metadata, material certificates and document context."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import json

OWNERS=('gsn_projects','contracts','gsv_projects')
SLOTS=(('title','Титульник'),('hidden_tape','Акт скрытых работ — сигнальная лента'),('commissioning','Акт приёмки в эксплуатацию'),('revision','Акт ревизии технических устройств'),('warranty','Гарантийный паспорт'),('contract','Договор'),('incoming_pipe','Протокол входного контроля — труба'),('incoming_inlet','Протокол входного контроля — ввод'),('incoming_coupling','Протокол входного контроля — муфта'),('welding_printout','Распечатка со сварочного аппарата'),('register','Реестр'),('building_passport','Строительный паспорт'))
# Document set for ГСВ (внутреннее газоснабжение) — owner='contracts'.
GSV_SLOTS=(('title','Титульник'),('gsv_acceptance','Акт приёмки ГСВ'),('equipment_revision','Акт ревизии оборудования'),('tech_revision','Акт ревизии технических устройств ГСВ'),('hidden_works','Акты на скрытые работы'),('warranty','Гарантийный паспорт'),('register','Реестр ГСВ'),('building_passport','Строительный паспорт'))
SLOTS_BY_MODULE={'ГСН':SLOTS,'ГСВ':GSV_SLOTS}
MODULE_BY_OWNER={'gsn_projects':'ГСН','contracts':'ГСВ'}
KINDS={'cap':('Заглушки','шт'),'coupling':('Муфты','шт'),'inlet':('Газопроводы-вводы','шт'),'steel_pipe':('Стальная труба','м'),'pe_pipe':('Полиэтиленовая труба','м'),'transition':('Переходы сталь–полиэтилен','шт'),'other':('Прочие материалы','')}
# Quantities per kind are computed from the "Материалы и сертификаты" table (see save_details);
# they are not shown as manual fields anymore, but stay available as template tags.
QUANTITY_KEYS=[kind+'_quantity' for kind in KINDS if kind!='other']
FIELDS={'project_number':'Номер проектной документации','project_date':'Дата проектной документации','tu_number':'Номер технических условий','tu_date':'Дата технических условий','start_date':'Начало строительства','end_date':'Окончание строительства','object_address':'Адрес объекта','initials_first':'И.О.Фамилия (можно уточнить)','surname_first':'Фамилия И.О. (можно уточнить)'}
DATES={'project_date','tu_date','start_date','end_date'}

def migrate(db):
    columns={r[1] for r in db.fetchall('PRAGMA table_info(gsn_projects)')}
    for key in ('contract_number','contract_date','client_name','phone','passport'):
        if key not in columns:db.execute(f"ALTER TABLE gsn_projects ADD COLUMN {key} TEXT DEFAULT ''")
    if 'certificate_id' not in [r[1] for r in db.fetchall('PRAGMA table_info(materials)')]:db.execute('ALTER TABLE materials ADD COLUMN certificate_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL')
    for sql in [
      '''CREATE TABLE IF NOT EXISTS executive_objects(id INTEGER PRIMARY KEY,owner_type TEXT NOT NULL,owner_id INTEGER NOT NULL,folder_path TEXT DEFAULT '',fields_json TEXT NOT NULL DEFAULT '{}',UNIQUE(owner_type,owner_id))''',
      '''CREATE TABLE IF NOT EXISTS executive_materials(id INTEGER PRIMARY KEY,owner_type TEXT NOT NULL,owner_id INTEGER NOT NULL,material_id INTEGER REFERENCES materials(id) ON DELETE SET NULL,kind TEXT NOT NULL,name TEXT NOT NULL,unit TEXT NOT NULL,quantity TEXT NOT NULL,certificate_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL,note TEXT DEFAULT '')''',
      '''CREATE TABLE IF NOT EXISTS executive_templates(id INTEGER PRIMARY KEY,module TEXT NOT NULL,slot TEXT NOT NULL,label TEXT NOT NULL,file_path TEXT DEFAULT '',output_name TEXT DEFAULT '',UNIQUE(module,slot))''',
      '''CREATE TABLE IF NOT EXISTS executive_overrides(id INTEGER PRIMARY KEY,owner_type TEXT NOT NULL,owner_id INTEGER NOT NULL,slot TEXT NOT NULL,file_path TEXT NOT NULL,output_name TEXT DEFAULT '',UNIQUE(owner_type,owner_id,slot))''',
      '''CREATE TABLE IF NOT EXISTS executive_generated(id INTEGER PRIMARY KEY,owner_type TEXT NOT NULL,owner_id INTEGER NOT NULL,slot TEXT NOT NULL,title TEXT NOT NULL,file_path TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP,context_json TEXT NOT NULL DEFAULT '{}',sha256 TEXT NOT NULL DEFAULT '')''',
      'CREATE INDEX IF NOT EXISTS idx_executive_material_owner ON executive_materials(owner_type,owner_id)',
      'CREATE INDEX IF NOT EXISTS idx_executive_generated_owner ON executive_generated(owner_type,owner_id)',
      'CREATE INDEX IF NOT EXISTS idx_gsn_contract_date ON gsn_projects(contract_date)',
    ]:db.execute(sql)
    if db.get_setting('gsv_templates_separated','0')!='1':
        db.execute("UPDATE executive_templates SET module='ГСВ — архив ошибочного списка 2.3' WHERE module='ГСВ'")
        db.set_setting('gsv_templates_separated','1')
    for module,slots in SLOTS_BY_MODULE.items():
        for slot,label in slots:db.execute('INSERT OR IGNORE INTO executive_templates(module,slot,label,output_name) VALUES(?,?,?,?)',(module,slot,label,label+' {{contract_number}}'))
    for table in ('executive_objects','executive_materials','executive_overrides','executive_generated'):
        for action in ('INSERT','UPDATE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS validate_{table}_{action} BEFORE {action} ON {table} WHEN NOT (
              (new.owner_type='gsn_projects' AND EXISTS(SELECT 1 FROM gsn_projects WHERE id=new.owner_id)) OR
              (new.owner_type='contracts' AND EXISTS(SELECT 1 FROM contracts WHERE id=new.owner_id)) OR
              (new.owner_type='gsv_projects' AND EXISTS(SELECT 1 FROM gsv_projects WHERE id=new.owner_id)))
              BEGIN SELECT RAISE(ABORT,'Объект исполнительной документации не найден'); END''')
        for owner in OWNERS:db.execute(f"CREATE TRIGGER IF NOT EXISTS cleanup_{table}_{owner} AFTER DELETE ON {owner} BEGIN DELETE FROM {table} WHERE owner_type='{owner}' AND owner_id=old.id; END")

def require(db,owner,rid):
    if owner not in OWNERS or not rid or not db.fetchone(f'SELECT 1 FROM {owner} WHERE id=?',(rid,)):raise ValueError('Сначала сохраните карточку договора')

def path(db,value):
    p=Path(value).expanduser()
    return p if p.is_absolute() else Path(db.db_name).parent/p

def load_details(db,owner,rid):
    row=db.fetchone('SELECT folder_path,fields_json FROM executive_objects WHERE owner_type=? AND owner_id=?',(owner,rid))
    return (row[0],json.loads(row[1])) if row else ('',{})

def material_rows(db,owner,rid):
    cur=db.execute('''SELECT m.id,m.material_id,m.kind,m.name,m.unit,m.quantity,m.certificate_id,m.note,c.name certificate_name,c.cert_number certificate_number,c.valid_to certificate_valid_to,c.file_path certificate_path
    FROM executive_materials m LEFT JOIN certificates c ON c.id=m.certificate_id WHERE owner_type=? AND owner_id=? ORDER BY m.id''',(owner,rid))
    return [dict(zip([c[0] for c in cur.description],r)) for r in cur.fetchall()]

def save_details(db,owner,rid,folder,fields,materials):
    require(db,owner,rid);fields=dict(fields);totals={}
    for key in DATES:
        if fields.get(key):date.fromisoformat(fields[key])
    if fields.get('start_date') and fields.get('end_date') and fields['end_date']<fields['start_date']:raise ValueError('Окончание строительства раньше начала')
    from .stock_domain import decimal
    for key in QUANTITY_KEYS:
        if fields.get(key) not in (None,''):
            n=decimal(fields[key]);kind=key.removesuffix('_quantity')
            if n<0 or (KINDS[kind][1]=='шт' and n!=n.to_integral_value()):raise ValueError('Количество изделий должно быть целым и неотрицательным')
    with db.transaction():
        db.execute('DELETE FROM executive_materials WHERE owner_type=? AND owner_id=?',(owner,rid))
        for row in materials:
            kind=row.get('kind','other');name=row.get('name','').strip();unit=row.get('unit','').strip();n=decimal(row.get('quantity','0'))
            if kind not in KINDS or not name or not unit or n<=0:raise ValueError('В материале укажите наименование, вид, единицу и положительное количество')
            if kind!='other' and unit!=KINDS[kind][1]:raise ValueError(f'{KINDS[kind][0]}: укажите количество в {KINDS[kind][1]}')
            if unit=='шт' and n!=n.to_integral_value():raise ValueError('Количество изделий должно быть целым')
            totals[kind]=totals.get(kind,Decimal(0))+n
            db.execute('INSERT INTO executive_materials(owner_type,owner_id,material_id,kind,name,unit,quantity,certificate_id,note) VALUES(?,?,?,?,?,?,?,?,?)',(owner,rid,row.get('material_id'),kind,name,unit,str(n),row.get('certificate_id'),row.get('note','')))
        for kind,n in totals.items():
            if kind!='other':fields[kind+'_quantity']=str(n)
        db.execute('INSERT INTO executive_objects(owner_type,owner_id,folder_path,fields_json) VALUES(?,?,?,?) ON CONFLICT(owner_type,owner_id) DO UPDATE SET folder_path=excluded.folder_path,fields_json=excluded.fields_json',(owner,rid,folder.strip(),json.dumps(fields,ensure_ascii=False)))
    return fields

def record(db,owner,rid):
    require(db,owner,rid);cur=db.execute(f'SELECT * FROM {owner} WHERE id=?',(rid,));return dict(zip([c[0] for c in cur.description],cur.fetchone()))

MONTHS=('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')
def date_text(iso,short=False):
    if not iso:return ''
    d=date.fromisoformat(iso);return d.strftime('%d.%m.%y') if short else f'{d.day} {MONTHS[d.month-1]} {d.year} г.'

def names(value):
    parts=value.split()
    if len(parts)<2:return value,value
    initials=''.join(p[0]+'.' for p in parts[1:])
    return initials+parts[0],parts[0]+' '+initials

ALIASES={'дата_договора':'contract_date','номер_договора':'contract_number','дата_договора_кратко':'contract_date_short','фио':'full_name','ио_фамилия':'initials_first','фамилия_ио':'surname_first','фамилия_ио_с_запятой':'surname_comma_initials','паспорт':'passport_full','телефон':'phone','адрес':'address','объект':'object_name','проект_номер':'project_number','проект_дата':'project_date','проект':'project_number_date','начало_строительства':'start_date','окончание_строительства':'end_date','ту_номер':'tu_number','ту_дата':'tu_date','ту':'tu_number_date','количество_заглушек':'cap_quantity','количество_муфт':'coupling_quantity','количество_вводов':'inlet_quantity','труба_сталь_количество':'steel_pipe_quantity','труба_пэ_количество':'pe_pipe_quantity','количество_переходов':'transition_quantity','материалы':'materials','сертификаты':'certificates','реестр':'document_register'}

# Human-readable reference shown to the user before they open a card, so tags can be
# picked for a Word/Excel template without needing an existing record's live values.
TAG_REFERENCE_DESCRIPTIONS={
    'номер_договора':'Номер договора','дата_договора':'Дата договора прописью','дата_договора_кратко':'Дата договора, дд.мм.гг',
    'фио':'ФИО / наименование заказчика целиком','ио_фамилия':'Фамилия с инициалами: И.О. Фамилия',
    'фамилия_ио':'Фамилия с инициалами: Фамилия И.О.','фамилия_ио_с_запятой':'Фамилия, И.О.',
    'паспорт':'Паспортные данные целиком (серия/номер, кем и когда выдан)','телефон':'Телефон заказчика',
    'адрес':'Адрес заказчика / объекта','объект':'Название объекта строительства',
    'проект_номер':'Номер проектной документации','проект_дата':'Дата проектной документации','проект':'Номер и дата проекта вместе',
    'начало_строительства':'Дата начала строительства','окончание_строительства':'Дата окончания строительства',
    'ту_номер':'Номер технических условий','ту_дата':'Дата технических условий','ту':'Номер и дата ТУ вместе',
    'количество_заглушек':'Кол-во заглушек — считается по таблице «Материалы и сертификаты»',
    'количество_муфт':'Кол-во муфт — считается по таблице «Материалы и сертификаты»',
    'количество_вводов':'Кол-во газопроводов-вводов — считается по таблице «Материалы и сертификаты»',
    'труба_сталь_количество':'Метраж стальной трубы — считается по таблице «Материалы и сертификаты»',
    'труба_пэ_количество':'Метраж полиэтиленовой трубы — считается по таблице «Материалы и сертификаты»',
    'количество_переходов':'Кол-во переходов сталь-полиэтилен — считается по таблице «Материалы и сертификаты»',
    'материалы':'Полный список материалов объекта (по одной строке)','сертификаты':'Список сертификатов материалов',
    'реестр':'Список уже созданных документов по этому объекту',
}
# Fields not covered by ALIASES but still substituted directly under their own key.
TAG_REFERENCE_EXTRA={
    'contract_date_numeric':'Дата договора, дд.мм.гггг','module':'Раздел: «ГСН» или «ГСВ»',
}
def tag_reference(owner):
    """Static {tag: description} table for the given module, for reference before opening a card."""
    rows=dict(TAG_REFERENCE_DESCRIPTIONS)
    if owner=='contracts':
        # ContractCardDialog already has its own start/end date fields; ExecutiveWorkspace hides the duplicates there.
        for key in ('начало_строительства','окончание_строительства'):rows.pop(key,None)
    rows.update(TAG_REFERENCE_EXTRA)
    return sorted(rows.items())

def context(db,owner,rid):
    with db.transaction():
        data=record(db,owner,rid);folder,fields=load_details(db,owner,rid);mats=material_rows(db,owner,rid)
        if owner in ('contracts','gsv_projects'):
            cur=db.execute("""SELECT p.name,p.unit,op.quantity,c.id certificate_id,c.name certificate_name,c.cert_number certificate_number,c.valid_to certificate_valid_to,c.file_path certificate_path,op.note FROM object_pipelines op JOIN gsv_pipelines p ON p.id=op.pipeline_id LEFT JOIN certificates c ON c.id=p.certificate_id WHERE op.owner_type=? AND op.owner_id=? ORDER BY op.id""",(owner,rid))
            for row in cur.fetchall():
                entry=dict(zip([c[0] for c in cur.description],row));entry['kind']='other';mats.append(entry)
        from .gsv_domain import get_client
        client=get_client(db,data.get('client_id')) or {}
        full=client.get('name') or data.get('client_name') or '';initials,surname=names(full)
        ctx=dict(contract_number=data.get('contract_number') or '',contract_date_iso=data.get('contract_date') or '',full_name=full,initials_first=fields.get('initials_first') or initials,surname_first=fields.get('surname_first') or surname,
          passport=client.get('passport') or data.get('passport') or data.get('passport_series_number') or '',passport_issuer=client.get('passport_issuer') or data.get('passport_issued_by') or '',passport_date=date_text(client.get('passport_date') or data.get('passport_issue_date')),
          phone=client.get('phone') or data.get('phone') or data.get('client_phone') or '',address=client.get('address') or data.get('client_address') or data.get('address') or '',object_name=data.get('title') if owner=='gsn_projects' else data.get('object_name') or '',object_address=fields.get('object_address') or data.get('address') or '',module='ГСН' if owner=='gsn_projects' else 'ГСВ')
        ctx['surname_comma_initials']=ctx['surname_first'].replace(' ', ', ', 1)
        ctx['passport_full']=', '.join(str(v) for v in (ctx['passport'],('выдан '+ctx['passport_issuer']) if ctx['passport_issuer'] else '',ctx['passport_date']) if v)
        ctx['contract_date']=date_text(ctx['contract_date_iso']);ctx['contract_date_short']=date_text(ctx['contract_date_iso'],True);ctx['contract_date_numeric']=date.fromisoformat(ctx['contract_date_iso']).strftime('%d.%m.%Y') if ctx['contract_date_iso'] else ''
        for key in (*FIELDS,*QUANTITY_KEYS):
            if key not in ('initials_first','surname_first','object_address'):ctx[key]=fields.get(key,'')
        if not ctx['project_number'] and owner=='gsv_projects':ctx['project_number']=data.get('pd_number') or ''
        if owner=='contracts':ctx['start_date']=data.get('work_start_date') or ctx['start_date'];ctx['end_date']=data.get('work_end_date') or ctx['end_date']
        for key in DATES:
            ctx[key+'_iso']=ctx[key];ctx[key+'_short']=date_text(ctx[key],True);ctx[key]=date_text(ctx[key])
        for kind in ('project','tu'):ctx[kind+'_number_date']=' '.join(v for v in (('№ '+ctx[kind+'_number']) if ctx[kind+'_number'] else '',('от '+ctx[kind+'_date']) if ctx[kind+'_date'] else '') if v)
        ctx['materials']='\n'.join(f'{i}. {r["name"]} — {r["quantity"]} {r["unit"]}' for i,r in enumerate(mats,1))
        ctx['certificates']='\n'.join(f'{r["name"]}: {r["certificate_name"] or ""}, № {r["certificate_number"] or "не указан"}' for r in mats)
        for kind in KINDS:
            subset=[r for r in mats if r['kind']==kind]
            for key in ('name','certificate_name','certificate_number','certificate_valid_to'):
                ctx[kind+'_'+key]='; '.join(dict.fromkeys(str(r[key]) for r in subset if r.get(key)))
        for i,row in enumerate(mats,1):
            for key in ('name','unit','quantity','note','certificate_name','certificate_number','certificate_valid_to'):ctx[f'material_{i}_{key}']=row[key] or ''
        generated=db.fetchall('SELECT title,file_path,created_at FROM executive_generated WHERE owner_type=? AND owner_id=? ORDER BY id',(owner,rid))
        ctx['document_register']='\n'.join(f'{i}. {title} — {Path(file).name} — {created}' for i,(title,file,created) in enumerate(generated,1))
        for alias,key in ALIASES.items():ctx[alias]=ctx[key]
        return ctx,mats

def templates(db,owner,rid=None):
    module=MODULE_BY_OWNER.get(owner)
    if not module:return [] # No fixed document set for this module yet.
    result=[]
    for slot,label,file,name in db.fetchall('SELECT slot,label,file_path,output_name FROM executive_templates WHERE module=? ORDER BY id',(module,)):
        override=db.fetchone('SELECT file_path,output_name FROM executive_overrides WHERE owner_type=? AND owner_id=? AND slot=?',(owner,rid,slot)) if rid else None
        result.append(dict(slot=slot,label=label,file_path=override[0] if override else file,output_name=override[1] if override else name,override=bool(override)))
    return result

def save_template(db,owner,slot,file,name,rid=None):
    module=MODULE_BY_OWNER.get(owner)
    if not module or slot not in dict(SLOTS_BY_MODULE[module]):raise ValueError('Неизвестный шаблон')
    if file and Path(file).suffix.lower() not in ('.docx','.xlsx'):raise ValueError('Нужен файл .docx или .xlsx. Старые .doc/.xls сохраните в новом формате.')
    if rid:
        require(db,owner,rid);db.execute('INSERT INTO executive_overrides(owner_type,owner_id,slot,file_path,output_name) VALUES(?,?,?,?,?) ON CONFLICT(owner_type,owner_id,slot) DO UPDATE SET file_path=excluded.file_path,output_name=excluded.output_name',(owner,rid,slot,file,name))
    else:db.execute('UPDATE executive_templates SET file_path=?,output_name=? WHERE module=? AND slot=?',(file,name,module,slot))
