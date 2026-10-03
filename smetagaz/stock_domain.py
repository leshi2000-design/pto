"""Inventory quantities use integer millionths; posting is atomic and idempotent."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import date
import json

SCALE=1000000
CATEGORIES=('Ацетилен','Кислород','Сварочная проволока','Краска','Отрезные круги','Прочее')
BASES=('стык','м','м²','шт','объект')

def decimal(value):
    try:d=Decimal(str(value).replace(',','.').strip())
    except (InvalidOperation,ValueError):raise ValueError('Введите корректное число')
    if not d.is_finite() or abs(d)>Decimal('1000000000'):raise ValueError('Число вне допустимого диапазона')
    return d

def units(value,positive=False):
    d=decimal(value)
    if d<0 or (positive and d<=0):raise ValueError('Количество должно быть положительным' if positive else 'Количество не может быть отрицательным')
    n=int((d*SCALE).to_integral_value(rounding=ROUND_HALF_UP))
    if positive and n==0:raise ValueError('Минимальное количество: 0,000001')
    return n

def fmt(value):
    s=format(Decimal(value)/SCALE,'.6f');return s.rstrip('0').rstrip('.')

def migrate(db):
    statements=[
    '''CREATE TABLE IF NOT EXISTS stock_materials(id INTEGER PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,unit TEXT NOT NULL,notes TEXT DEFAULT '',active INTEGER DEFAULT 1)''',
    '''CREATE TABLE IF NOT EXISTS norm_profiles(id INTEGER PRIMARY KEY,name TEXT NOT NULL,diameter TEXT DEFAULT '',thickness TEXT DEFAULT '',basis TEXT NOT NULL,notes TEXT DEFAULT '')''',
    '''CREATE TABLE IF NOT EXISTS norm_items(id INTEGER PRIMARY KEY,profile_id INTEGER NOT NULL REFERENCES norm_profiles(id) ON DELETE CASCADE,material_id INTEGER NOT NULL REFERENCES stock_materials(id),rate TEXT,UNIQUE(profile_id,material_id))''',
    '''CREATE TABLE IF NOT EXISTS defect_acts(id INTEGER PRIMARY KEY,number TEXT NOT NULL,act_date TEXT NOT NULL,object_name TEXT NOT NULL,owner_type TEXT,owner_id INTEGER,organization TEXT DEFAULT '',approved_by TEXT DEFAULT '',commission TEXT DEFAULT '',reason TEXT DEFAULT '',conditions TEXT DEFAULT '',notes TEXT DEFAULT '',revision INTEGER DEFAULT 1)''',
    '''CREATE TABLE IF NOT EXISTS defect_lines(id INTEGER PRIMARY KEY,act_id INTEGER NOT NULL REFERENCES defect_acts(id) ON DELETE CASCADE,defect TEXT NOT NULL,work TEXT NOT NULL,unit TEXT NOT NULL,quantity TEXT NOT NULL,profile_id INTEGER REFERENCES norm_profiles(id),notes TEXT DEFAULT '')''',
    '''CREATE TABLE IF NOT EXISTS stock_acts(id INTEGER PRIMARY KEY,number TEXT NOT NULL,act_date TEXT NOT NULL,object_name TEXT NOT NULL,owner_type TEXT,owner_id INTEGER,defect_id INTEGER REFERENCES defect_acts(id),organization TEXT DEFAULT '',approved_by TEXT DEFAULT '',commission TEXT DEFAULT '',basis TEXT DEFAULT '',notes TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','posted','reversed')),revision INTEGER DEFAULT 1,calculation TEXT DEFAULT '[]')''',
    '''CREATE TABLE IF NOT EXISTS stock_act_lines(id INTEGER PRIMARY KEY,act_id INTEGER NOT NULL REFERENCES stock_acts(id) ON DELETE CASCADE,material_id INTEGER NOT NULL REFERENCES stock_materials(id),material_name TEXT NOT NULL,category TEXT NOT NULL,unit TEXT NOT NULL,norm_qty INTEGER,actual_qty INTEGER NOT NULL CHECK(actual_qty>=0),note TEXT DEFAULT '',UNIQUE(act_id,material_id))''',
    '''CREATE TABLE IF NOT EXISTS stock_moves(id INTEGER PRIMARY KEY,material_id INTEGER NOT NULL REFERENCES stock_materials(id),move_date TEXT NOT NULL,qty INTEGER NOT NULL,kind TEXT NOT NULL,act_id INTEGER REFERENCES stock_acts(id),note TEXT DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP)''',
    'CREATE INDEX IF NOT EXISTS idx_stock_moves_material ON stock_moves(material_id,move_date)',
    'CREATE INDEX IF NOT EXISTS idx_stock_acts_date ON stock_acts(act_date,status)',
    'CREATE INDEX IF NOT EXISTS idx_defect_date ON defect_acts(act_date)',
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_defect_active_writeoff ON stock_acts(defect_id) WHERE defect_id IS NOT NULL AND status<>'reversed'",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_post_once ON stock_moves(act_id,material_id,kind) WHERE act_id IS NOT NULL",
    ]
    for sql in statements:db.execute(sql)
    for key in ('object_text','welder_text'):
        if key not in [r[1] for r in db.fetchall('PRAGMA table_info(welding_jobs)')]:db.execute(f"ALTER TABLE welding_jobs ADD COLUMN {key} TEXT DEFAULT ''")
    # Expand old multi-day jobs into independently editable journal entries, retaining first ID.
    if db.get_setting('stock_schema')!='1':
        from .gsv_domain import owner_label
        for jid,owner,rid in db.fetchall("SELECT id,owner_type,owner_id FROM welding_jobs WHERE coalesce(object_text,'')='' AND owner_type IS NOT NULL"):
            db.execute('UPDATE welding_jobs SET object_text=? WHERE id=?',(owner_label(db,owner,rid),jid))
        for rid in [r[0] for r in db.fetchall('SELECT id FROM welding_jobs')]:
            days=db.fetchall('SELECT work_date FROM welding_days WHERE job_id=? ORDER BY work_date',(rid,))
            for (day,) in days[1:]:
                cur=db.execute('''INSERT INTO welding_jobs(title,owner_type,owner_id,estimate_item_id,welder_id,notes,object_text,welder_text)
                  SELECT title,owner_type,owner_id,estimate_item_id,welder_id,notes,object_text,welder_text FROM welding_jobs WHERE id=?''',(rid,))
                db.execute('UPDATE welding_days SET job_id=? WHERE job_id=? AND work_date=?',(cur.lastrowid,rid,day))
        defaults=[('Ацетилен','Ацетилен','м³'),('Кислород','Кислород','м³'),('Сварочная проволока','Сварочная проволока','кг'),('Краска','Краска','кг'),('Отрезные круги','Отрезные круги','шт')]
        ids=[]
        for row in defaults:ids.append(db.execute('INSERT INTO stock_materials(name,category,unit) VALUES(?,?,?)',row).lastrowid)
        for dia,thick in [('15','2.8'),('20','2.8'),('25','3.2'),('32','3.2')]:
            pid=db.execute('INSERT INTO norm_profiles(name,diameter,thickness,basis) VALUES(?,?,?,?)',(f'Газовая сварка Ду {dia} × {thick}',dia,thick,'стык')).lastrowid
            for mid in ids:db.execute('INSERT INTO norm_items(profile_id,material_id,rate) VALUES(?,?,NULL)',(pid,mid))
        db.set_setting('stock_schema','1')

def material(db,mid):
    row=db.fetchone('SELECT name,category,unit FROM stock_materials WHERE id=?',(mid,))
    if not row:raise ValueError('Материал удалён или не выбран')
    return row

def save_material(db,name,category,unit,notes='',mid=None):
    if not name.strip() or not unit.strip():raise ValueError('Укажите название и единицу измерения')
    with db.transaction():
        if mid:
            old=material(db,mid)
            if old[2]!=unit.strip() and (db.fetchone('SELECT 1 FROM stock_moves WHERE material_id=?',(mid,)) or db.fetchone('SELECT 1 FROM norm_items WHERE material_id=?',(mid,)) or db.fetchone('SELECT 1 FROM stock_act_lines WHERE material_id=?',(mid,))):raise ValueError('Единица уже используется. Создайте отдельный материал с другой единицей.')
            db.execute('UPDATE stock_materials SET name=?,category=?,unit=?,notes=? WHERE id=?',(name.strip(),category.strip(),unit.strip(),notes,mid));return mid
        return db.execute('INSERT INTO stock_materials(name,category,unit,notes) VALUES(?,?,?,?)',(name.strip(),category.strip(),unit.strip(),notes)).lastrowid

def balance(db,mid):return db.fetchone('SELECT coalesce(sum(qty),0) FROM stock_moves WHERE material_id=?',(mid,))[0]

def check_timeline(db,mid):
    running=0
    for day,qty in db.fetchall('SELECT move_date,sum(qty) FROM stock_moves WHERE material_id=? GROUP BY move_date ORDER BY move_date',(mid,)):
        running+=qty
        if running<0:raise ValueError(f'{material(db,mid)[0]}: недостаточно {fmt(-running)} {material(db,mid)[2]} на {day}. Проверьте дату поступления.')

def receive(db,mid,quantity,day,note='',correction=False):
    date.fromisoformat(day);d=decimal(quantity)
    if not d or (d<0 and not correction):raise ValueError('Введите положительное поступление')
    n=units(abs(d),True)*(1 if d>0 else -1)
    with db.transaction():
        material(db,mid)
        db.execute('INSERT INTO stock_moves(material_id,move_date,qty,kind,note) VALUES(?,?,?,?,?)',(mid,day,n,'correction' if correction else 'receipt',note))
        check_timeline(db,mid)

def save_profile(db,values,items,pid=None):
    if not values['name'].strip() or values['basis'] not in BASES:raise ValueError('Укажите название и базу нормы')
    with db.transaction():
        args=tuple(values.get(k,'') for k in ('name','diameter','thickness','basis','notes'))
        if pid:db.execute('UPDATE norm_profiles SET name=?,diameter=?,thickness=?,basis=?,notes=? WHERE id=?',(*args,pid));db.execute('DELETE FROM norm_items WHERE profile_id=?',(pid,))
        else:pid=db.execute('INSERT INTO norm_profiles(name,diameter,thickness,basis,notes) VALUES(?,?,?,?,?)',args).lastrowid
        for mid,rate in items:
            material(db,mid)
            if rate not in (None,''):
                if decimal(rate)<0:raise ValueError('Норма не может быть отрицательной')
                rate=str(decimal(rate))
            else:rate=None
            db.execute('INSERT INTO norm_items(profile_id,material_id,rate) VALUES(?,?,?)',(pid,mid,rate))
    return pid

def calculate(db,volumes):
    totals={};snapshots=[]
    for pid,amount in volumes:
        count=decimal(amount)
        if count<=0:raise ValueError('Объём работ должен быть больше нуля')
        profile=db.fetchone('SELECT name,basis FROM norm_profiles WHERE id=?',(pid,))
        if not profile:raise ValueError('Выберите профиль нормы')
        if profile[1]=='стык' and count!=count.to_integral_value():raise ValueError('Количество стыков должно быть целым')
        rows=db.fetchall('SELECT material_id,rate FROM norm_items WHERE profile_id=? ORDER BY id',(pid,))
        if not rows:raise ValueError(f'{profile[0]}: добавьте материалы и нормы')
        details=[]
        for mid,rate in rows:
            name,cat,unit=material(db,mid)
            if rate is None:raise ValueError(f'{profile[0]}: не задана норма «{name}». Введите норму или явный 0, если материал не расходуется.')
            value=decimal(rate)*count
            totals[mid]=totals.get(mid,Decimal(0))+value
            details.append(dict(material_id=mid,name=name,unit=unit,rate=rate,quantity=str(value)))
        snapshots.append(dict(profile_id=pid,name=profile[0],basis=profile[1],volume=str(count),items=details))
    lines=[dict(material_id=mid,norm_qty=units(value),actual_qty=units(value),note='') for mid,value in totals.items() if value>0]
    return lines,snapshots

def validate_object(db,data):
    if not str(data.get('object_name','')).strip():raise ValueError('Введите объект списания')
    if data.get('owner_type'):
        from .gsv_domain import require_owner
        require_owner(db,data['owner_type'],data.get('owner_id'))
    date.fromisoformat(data['act_date'])
    if not data.get('number','').strip():raise ValueError('Укажите номер документа')

def save_act(db,data,lines,aid=None,revision=None):
    validate_object(db,data)
    fields=('number','act_date','object_name','owner_type','owner_id','defect_id','organization','approved_by','commission','basis','notes','calculation')
    values=[data.get(k) if k in ('owner_type','owner_id','defect_id') else data.get(k,'[]' if k=='calculation' else '') for k in fields]
    with db.transaction():
        if aid:
            row=db.fetchone('SELECT status,revision FROM stock_acts WHERE id=?',(aid,))
            if not row or row[0]!='draft':raise ValueError('Изменяется только черновик. Для проведённого акта сначала отмените проведение.')
            if revision is not None and row[1]!=revision:raise ValueError('Документ изменён в другом окне. Откройте его заново.')
            db.execute('UPDATE stock_acts SET '+','.join(k+'=?' for k in fields)+',revision=revision+1 WHERE id=?',(*values,aid));db.execute('DELETE FROM stock_act_lines WHERE act_id=?',(aid,))
        else:aid=db.execute('INSERT INTO stock_acts('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',values).lastrowid
        if data.get('defect_id'):
            d=db.fetchone('SELECT object_name,owner_type,owner_id FROM defect_acts WHERE id=?',(data['defect_id'],))
            if d!=tuple(data.get(k) for k in ('object_name','owner_type','owner_id')):raise ValueError('Объект должен совпадать с дефектным актом')
        seen=set()
        for line in lines:
            mid=line['material_id'];name,category,unit=material(db,mid)
            if mid in seen:raise ValueError('Материал повторяется: объедините количество в одну строку')
            seen.add(mid);actual=int(line['actual_qty']);norm=line.get('norm_qty')
            if actual<0 or (norm is not None and int(norm)<0):raise ValueError('Количество не может быть отрицательным')
            db.execute('INSERT INTO stock_act_lines(act_id,material_id,material_name,category,unit,norm_qty,actual_qty,note) VALUES(?,?,?,?,?,?,?,?)',(aid,mid,name,category,unit,norm,actual,line.get('note','')))
    return aid

def post_act(db,aid):
    with db.transaction():
        row=db.fetchone('SELECT status,act_date FROM stock_acts WHERE id=?',(aid,))
        if not row:raise ValueError('Акт не найден')
        if row[0]=='posted':return
        if row[0]!='draft':raise ValueError('Отменённый акт нельзя провести повторно; создайте исправленный черновик')
        lines=db.fetchall('SELECT material_id,actual_qty,material_name,unit FROM stock_act_lines WHERE act_id=?',(aid,))
        if not lines or not any(r[1]>0 for r in lines):raise ValueError('Добавьте материалы с положительным расходом')
        missing=[f'{name}: нужно {fmt(qty)}, доступно {fmt(balance(db,mid))} {unit}' for mid,qty,name,unit in lines if qty>balance(db,mid)]
        if missing:raise ValueError('Списание невозможно. Недостаточно материалов:\n'+'\n'.join(missing))
        for mid,qty,_,_ in lines:
            if qty:db.execute('INSERT INTO stock_moves(material_id,move_date,qty,kind,act_id) VALUES(?,?,?,?,?)',(mid,row[1],-qty,'writeoff',aid));check_timeline(db,mid)
        db.execute("UPDATE stock_acts SET status='posted',revision=revision+1 WHERE id=?",(aid,))

def reverse_act(db,aid):
    with db.transaction():
        row=db.fetchone('SELECT status,act_date FROM stock_acts WHERE id=?',(aid,))
        if not row or row[0]=='reversed':return
        if row[0]!='posted':raise ValueError('Акт ещё не проведён')
        for mid,qty in db.fetchall("SELECT material_id,qty FROM stock_moves WHERE act_id=? AND kind='writeoff'",(aid,)):
            db.execute('INSERT INTO stock_moves(material_id,move_date,qty,kind,act_id,note) VALUES(?,?,?,?,?,?)',(mid,row[1],-qty,'reversal',aid,'Отмена проведения'))
        db.execute("UPDATE stock_acts SET status='reversed',revision=revision+1 WHERE id=?",(aid,))

def copy_act(db,aid):
    with db.transaction():
        cur=db.execute('SELECT * FROM stock_acts WHERE id=?',(aid,));data=dict(zip([c[0] for c in cur.description],cur.fetchone()));data['number']+='-испр'
        lines=[dict(material_id=r[0],norm_qty=r[1],actual_qty=r[2],note=r[3]) for r in db.fetchall('SELECT material_id,norm_qty,actual_qty,note FROM stock_act_lines WHERE act_id=?',(aid,))]
        return save_act(db,data,lines)

def save_defect(db,data,lines,did=None,revision=None):
    validate_object(db,data)
    keys=('number','act_date','object_name','owner_type','owner_id','organization','approved_by','commission','reason','conditions','notes')
    with db.transaction():
        if did:
            if db.fetchone("SELECT 1 FROM stock_acts WHERE defect_id=? AND status<>'reversed'",(did,)):raise ValueError('По акту уже создано списание. Сначала удалите его черновик или отмените проведение.')
            old=db.fetchone('SELECT revision FROM defect_acts WHERE id=?',(did,))
            if not old or (revision is not None and old[0]!=revision):raise ValueError('Дефектный акт изменён; откройте его заново')
            db.execute('UPDATE defect_acts SET '+','.join(k+'=?' for k in keys)+',revision=revision+1 WHERE id=?',(*(data.get(k) for k in keys),did));db.execute('DELETE FROM defect_lines WHERE act_id=?',(did,))
        else:did=db.execute('INSERT INTO defect_acts('+','.join(keys)+') VALUES('+','.join('?' for _ in keys)+')',tuple(data.get(k) for k in keys)).lastrowid
        for l in lines:
            if not l['work'].strip() or not l['unit'].strip() or decimal(l['quantity'])<=0:raise ValueError('Укажите работу, единицу и положительный объём')
            if l.get('profile_id'):
                basis=db.fetchone('SELECT basis FROM norm_profiles WHERE id=?',(l['profile_id'],))
                if not basis or basis[0]!=l['unit']:raise ValueError('Единица работы должна совпадать с базой выбранной нормы')
            db.execute('INSERT INTO defect_lines(act_id,defect,work,unit,quantity,profile_id,notes) VALUES(?,?,?,?,?,?,?)',(did,l.get('defect',''),l['work'],l['unit'],str(decimal(l['quantity'])),l.get('profile_id'),l.get('notes','')))
    return did

def from_defect(db,did):
    with db.transaction():
        existing=db.fetchone("SELECT id FROM stock_acts WHERE defect_id=? AND status<>'reversed'",(did,))
        if existing:return existing[0]
        cur=db.execute('SELECT * FROM defect_acts WHERE id=?',(did,));row=cur.fetchone()
        if not row:raise ValueError('Дефектный акт не найден')
        data=dict(zip([c[0] for c in cur.description],row));data.update(defect_id=did,basis='Дефектный акт №'+data['number'],number='СП-'+data['number'])
        rows=db.fetchall('SELECT profile_id,quantity,work FROM defect_lines WHERE act_id=?',(did,))
        if not rows:raise ValueError('Дефектный акт не содержит работ')
        # Unlinked work is preserved as basis; its materials must be entered manually.
        volumes=[(pid,qty) for pid,qty,_ in rows if pid]
        lines,snapshots=calculate(db,volumes)
        manual=[work for pid,qty,work in rows if not pid]
        data['notes']='Материалы вне норм заполнить вручную: '+ '; '.join(manual) if manual else ''
        data['calculation']=json.dumps(snapshots,ensure_ascii=False)
        return save_act(db,data,lines)
