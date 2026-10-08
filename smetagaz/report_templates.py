"""Reusable document templates and coherent data snapshots for reports."""
from datetime import date
from decimal import Decimal
from pathlib import Path
import tempfile
import os
from . import template_domain as domain
KINDS={'estimates':'Смета','estimate_breakdown':'Смета — расшифровка работ','contracts':'Договор на работы','gsv_projects':'Договор на проектирование ГСВ','gsn_projects':'Договор ГСН','crm.clients':'Карточка клиента','balances':'Остатки склада','statistics':'Статистический отчёт','payment_report':'Отчёт по оплатам','stock_acts':'Акт списания','defect_acts':'Дефектный акт'}
def migrate(db):
    if 'prepared_by' not in [r[1] for r in db.fetchall('PRAGMA table_info(estimates)')]:db.execute("ALTER TABLE estimates ADD COLUMN prepared_by TEXT DEFAULT ''")
    db.execute('CREATE TABLE IF NOT EXISTS report_templates(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,name TEXT NOT NULL,file_path TEXT NOT NULL)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_report_templates_kind ON report_templates(kind)')
    db.execute("CREATE TABLE IF NOT EXISTS report_preferences(record_key TEXT PRIMARY KEY,template_id INTEGER REFERENCES report_templates(id) ON DELETE SET NULL)")
def rows(db,sql,params=()):
    cur=db.execute(sql,params);return [dict(zip([c[0] for c in cur.description],row)) for row in cur.fetchall()]
def context(db,kind,rid=None,filters=None):
    if kind not in KINDS:raise ValueError('Шаблоны для этого раздела ещё не подключены')
    f=filters or {};tables={};ctx={'report_title':KINDS[kind],'report_date':date.today().strftime('%d.%m.%Y'),'company':db.get_setting('export_company_name','')}
    with db.transaction():
        if kind in domain.OWNERS:
            data,mats=domain.context(db,kind,rid);ctx.update(data);tables['materials']=mats
            ctx.update(domain.record(db,kind,rid))
            # Keep formatted contract dates and shared client values authoritative.
            ctx.update(data)
        elif kind=='estimates':
            from .exports import record_data
            data,_=record_data(db,kind,rid);ctx.update(data)
            items=rows(db,'SELECT name,item_type,unit,quantity,price,sum amount FROM estimate_items WHERE estimate_id=? ORDER BY sort_order,id',(rid,));tables['items']=items
            tables['payments']=rows(db,'SELECT date,amount FROM payments WHERE estimate_id=? ORDER BY date,id',(rid,))
            ctx['prepared_by']=data.get('prepared_by') or db.get_setting('estimate_prepared_by','')
            number=lambda k:Decimal(str(data.get(k) or 0))
            mats=sum((Decimal(str(r['amount'] or 0)) for r in items if r['item_type'] not in ('Работа','Раздел')),Decimal(0));works=sum((Decimal(str(r['amount'] or 0)) for r in items if r['item_type']=='Работа'),Decimal(0))
            ctx['materials_total']=mats*(1+number('mat_adj_pct')/100);ctx['works_total']=works*(1+number('work_adj_pct')/100)
            # начислений на работы в смете больше нет; прежние ключи остаются нулями, чтобы подключённые шаблоны не ломались
            for name in ('social_total','overhead_total','profit_total'):ctx[name]=Decimal(0)
            ctx['subtotal']=(ctx['materials_total']+ctx['works_total'])*(1+number('total_adj_pct')/100)
            ctx['vat_total']=Decimal(0);ctx['calculated_total']=ctx['subtotal'];ctx['debt']=number('total')-number('paid')
        elif kind=='estimate_breakdown':
            from .exports import record_data
            from . import estimates_domain as ed
            data,_=record_data(db,'estimates',rid);ctx.update(data)
            work_rows,materials,info=ed.breakdown(db,rid);tables['works']=work_rows;tables['materials']=materials;ctx.update(info)
        elif kind=='crm.clients':
            data=rows(db,'SELECT * FROM crm.clients WHERE id=?',(rid,))
            if not data:raise ValueError('Клиент не найден')
            ctx.update(data[0]);tables['contracts']=rows(db,"SELECT contract_number number,contract_date date,object_name,contract_amount amount FROM contracts WHERE client_id=? UNION ALL SELECT contract_number,contract_date,object_name,cost FROM gsv_projects WHERE client_id=? UNION ALL SELECT contract_number,contract_date,title,NULL FROM gsn_projects WHERE client_id=?",(rid,rid,rid))
        elif kind=='balances':
            sql=f.get('query');params=f.get('params',())
            if sql:
                # SQL is built exclusively by the registry, never supplied by a template.
                tables['items']=rows(db,sql,params)
            else:
                query='SELECT m.id,m.name,m.category,m.unit,coalesce(b.qty,0)/1000000.0 balance,m.notes FROM stock_materials m LEFT JOIN (SELECT material_id,sum(qty) qty FROM stock_moves GROUP BY material_id) b ON b.material_id=m.id WHERE (?="" OR m.category=?) AND LOWER(m.name) LIKE ? ORDER BY m.name'
                tables['items']=rows(db,query,(f.get('category',''),f.get('category',''),'%'+f.get('search','').casefold()+'%'))
            ctx['category']=f.get('category','') or 'Все категории';ctx['search']=f.get('search','');ctx['item_count']=len(tables['items'])
        elif kind=='payment_report':
            from .payments_domain import report
            start=f.get('start','1900-01-01');end=f.get('end',date.today().isoformat());tables['payments']=report(db,start,end,f.get('section',''));ctx.update(period_start=start,period_end=end,section=f.get('section') or 'Все разделы',payment_total=sum((Decimal(str(r['amount'])) for r in tables['payments']),Decimal(0)),payment_count=len(tables['payments']))
        elif kind=='statistics':
            start=f.get('start','1900-01-01');end=f.get('end',date.today().isoformat())
            if date.fromisoformat(start)>date.fromisoformat(end):raise ValueError('Начало периода позже окончания')
            ctx.update(period_start=start,period_end=end)
            ctx.update(rows(db,'SELECT count(*) estimate_count,coalesce(sum(total),0) total,coalesce(sum(paid),0) paid FROM estimates WHERE date BETWEEN ? AND ?',(start,end))[0]);ctx['debt']=ctx['total']-ctx['paid']
            tables['estimates']=rows(db,'SELECT title,date,client_name,total,paid FROM estimates WHERE date BETWEEN ? AND ? ORDER BY date,id',(start,end))
            tables['months']=rows(db,"SELECT substr(date,1,7) month,sum(total) total,sum(paid) paid FROM estimates WHERE date BETWEEN ? AND ? GROUP BY substr(date,1,7) ORDER BY month",(start,end))
            tables['items']=rows(db,'SELECT i.name,i.unit,i.item_type,sum(i.quantity) quantity,sum(i.sum) amount FROM estimate_items i JOIN estimates e ON e.id=i.estimate_id WHERE e.date BETWEEN ? AND ? GROUP BY i.name,i.unit,i.item_type ORDER BY amount DESC',(start,end))
            ctx['materials_total']=sum(r['amount'] or 0 for r in tables['items'] if r['item_type']!='Работа');ctx['works_total']=sum(r['amount'] or 0 for r in tables['items'] if r['item_type']=='Работа')
        else:
            from .stock_exports import document_data
            title,notice,data,sections=document_data(db,kind,rid,'act');ctx.update(data);ctx['report_title']=title
            for i,(title,columns,data_rows) in enumerate(sections,1):tables['section_'+str(i)]=[{'c'+str(j+1):value for j,value in enumerate(row)} for row in data_rows]
        if kind in ('estimates','estimate_breakdown'):
            from . import estimates_domain as ed
            ed.extend_context(db,kind,rid,ctx,tables)
        for name,items in tables.items():
            for i,row in enumerate(items,1):row['index']=i
            ctx[name+'_count']=len(items);ctx[name+'_text']='\n'.join(' | '.join(str(v if v is not None else '') for v in row.values()) for row in items)
    # Optional empty fields are printable; missing/misspelled keys remain an error.
    clean=lambda v:'—' if v is None or v=='' else v
    ctx={k:clean(v) for k,v in ctx.items()};tables={key:[{k:clean(v) for k,v in r.items()} for r in values] for key,values in tables.items()}
    return ctx,tables

def export(db,kind,rid,template_id,destination,filters=None):
    with db.transaction():
        row=db.fetchone('SELECT file_path FROM report_templates WHERE id=? AND kind=?',(template_id,kind))
        if not row:raise ValueError('Выберите шаблон этого вида документа')
        ctx,tables=context(db,kind,rid,filters)
    source=domain.path(db,row[0]);destination=Path(destination)
    if source.resolve()==destination.resolve():raise ValueError('Нельзя перезаписывать исходный шаблон')
    if source.suffix.lower()!=destination.suffix.lower():raise ValueError('Формат результата должен совпадать с шаблоном')
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(suffix=source.suffix,dir=destination.parent);os.close(fd)
    try:
        from .table_templates import render
        if kind=="estimates" and ctx.get("prepared_by") in (None,"","—"):raise ValueError("Укажите, кто составил смету")
        render(source,ctx,tables,tmp)
        if kind=="estimates":
            from .signature import ensure_signature
            ensure_signature(source,tmp,ctx["prepared_by"])
        os.replace(tmp,destination)
    except Exception:
        Path(tmp).unlink(missing_ok=True);raise
    return str(destination)
