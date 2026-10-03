"""Layout-preserving OOXML substitution; originals are never rewritten."""
from pathlib import Path
from zipfile import ZipFile
from lxml import etree as ET
import re
import json
import hashlib
import tempfile
import shutil
import os
import uuid
from . import template_domain as domain
TAG=re.compile(r'{{\s*([\w.]+)\s*}}',re.UNICODE)
W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'

def replace_nodes(nodes,values,found):
    text=''.join(n.text or '' for n in nodes)
    if ('{{' in TAG.sub('',text) or '}}' in TAG.sub('',text)):
        raise ValueError('Некорректный тег: '+text[:120])
    matches=list(TAG.finditer(text));found.update(m.group(1) for m in matches)
    if values is None:return
    for m in reversed(matches):
        key=m.group(1)
        if key not in values or values[key] in ('',None):raise ValueError('Не заполнен тег: '+key)
        starts=[];offset=0
        for n in nodes:starts.append(offset);offset+=len(n.text or '')
        a=next(i for i,n in enumerate(nodes) if starts[i]+len(n.text or '')>m.start())
        b=next(i for i,n in enumerate(nodes) if starts[i]+len(n.text or '')>=m.end())
        prefix=(nodes[a].text or '')[:m.start()-starts[a]];suffix=(nodes[b].text or '')[m.end()-starts[b]:]
        nodes[a].text=prefix+str(values[key])+(suffix if a==b else '')
        for i in range(a+1,b+1):nodes[i].text=suffix if i==b else ''
        nodes[a].set('{http://www.w3.org/XML/1998/namespace}space','preserve')

def numeric_value(text,values):
    match=TAG.fullmatch(text or '')
    if not match or values is None:return None
    key=match.group(1);canonical=domain.ALIASES.get(key,key)
    value=values.get(key)
    from decimal import Decimal
    if not canonical.endswith('_quantity') and not isinstance(value,(int,float,Decimal)):return None
    if value in ('',None):return None
    from decimal import Decimal
    n=Decimal(str(value).replace(',','.'))
    if not n.is_finite():raise ValueError('Некорректное количество: '+key)
    return format(n,'f')

def transform(source,values=None,destination=None):
    source=Path(source)
    if source.suffix.lower() not in ('.docx','.xlsx'):raise ValueError('Поддерживаются .docx и .xlsx')
    found=set();parts=[]
    with ZipFile(source) as z:
        required='word/document.xml' if source.suffix.lower()=='.docx' else 'xl/workbook.xml'
        if required not in z.namelist():raise ValueError('Файл не соответствует формату '+source.suffix)
        if sum(i.file_size for i in z.infolist())>256*1024*1024:raise ValueError('Слишком большой шаблон (распакованный размер >256 МБ)')
        if len(z.namelist())!=len(set(z.namelist())):raise ValueError('Повторяющиеся части в шаблоне')
        numeric_shared={}
        if values is not None and 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'),ET.XMLParser(resolve_entities=False,no_network=True))
            for i,si in enumerate(root.iter('{'+S+'}si')):
                value=numeric_value(''.join(n.text or '' for n in si.iter('{'+S+'}t')),values)
                if value is not None:numeric_shared[str(i)]=value
        for info in z.infolist():
            data=z.read(info)
            if info.filename.endswith('.xml') and info.filename.startswith(('word/','xl/')):
                root=ET.fromstring(data,ET.XMLParser(resolve_entities=False,no_network=True))
                if info.filename.startswith('word/'):
                    for p in root.iter('{'+W+'}p'):
                        nodes=[n for n in p.iter('{'+W+'}t') if next(n.iterancestors('{'+W+'}p'),None) is p]
                        replace_nodes(nodes,values,found)
                    if values is not None:
                        for n in list(root.iter('{'+W+'}t')):
                            if '\n' in (n.text or ''):
                                lines=n.text.split('\n');n.text=lines[0];parent=n.getparent();idx=parent.index(n)
                                for line in lines[1:]:
                                    idx+=1;parent.insert(idx,ET.Element('{'+W+'}br'));idx+=1;t=ET.Element('{'+W+'}t');t.text=line;t.set('{http://www.w3.org/XML/1998/namespace}space','preserve');parent.insert(idx,t)
                else:
                    if values is not None:
                        for cell in root.iter('{'+S+'}c'):
                            value=None
                            if cell.get('t')=='s':
                                v=cell.find('{'+S+'}v');value=numeric_shared.get(v.text) if v is not None else None
                            elif cell.get('t')=='inlineStr':value=numeric_value(''.join(n.text or '' for n in cell.iter('{'+S+'}t')),values)
                            if value is not None:
                                for child in list(cell):
                                    if child.tag in ('{'+S+'}is','{'+S+'}v'):cell.remove(child)
                                cell.set('t','n');ET.SubElement(cell,'{'+S+'}v').text=value
                    for name in ('oddHeader','evenHeader','firstHeader','oddFooter','evenFooter','firstFooter'):
                        for node in root.iter('{'+S+'}'+name):replace_nodes([node],values,found)
                    for f in root.iter('{'+S+'}f'):
                        if TAG.search(f.text or ''):raise ValueError('Теги внутри формул Excel не поддерживаются: поместите тег в отдельную ячейку')
                    for name in ('si','is'):
                        for block in root.iter('{'+S+'}'+name):replace_nodes(list(block.iter('{'+S+'}t')),values,found)
                if values is not None:data=ET.tostring(root,encoding='UTF-8',xml_declaration=True)
            parts.append((info,data))
    if destination:
        with ZipFile(destination,'w') as z:
            for info,data in parts:z.writestr(info,data)
    return found

def filename(text):
    text=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',text).strip(' .')[:150]
    if not text:raise ValueError('Пустое имя выходного файла')
    if text.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:text='_'+text
    return text

def generate(db,owner,rid,slots,copy_certificates=True):
    with db.transaction():
        ctx,mats=domain.context(db,owner,rid);folder,_=domain.load_details(db,owner,rid)
        selected=[t for t in domain.templates(db,owner,rid) if t['slot'] in slots]
    if not selected:raise ValueError('Выберите документы')
    if not folder:raise ValueError('Привяжите папку договора')
    target=domain.path(db,folder).resolve()
    if not target.is_dir():raise ValueError('Папка договора недоступна')
    token=uuid.uuid4().hex[:10];jobs=[]
    for t in selected:
        if not t['file_path']:raise ValueError('Подключите шаблон: '+t['label'])
        src=domain.path(db,t['file_path'])
        tags=transform(src);missing=sorted(k for k in tags if k not in ctx or ctx[k] in ('',None))
        missing=[k for k in missing if k not in ('реестр','document_register')]
        if missing:raise ValueError(t['label']+': не заполнены '+', '.join(missing))
        def sub(m):
            value=ctx.get(m.group(1))
            if value in ('',None):raise ValueError('Не заполнен тег имени файла: '+m.group(1))
            return str(value)
        name=filename(TAG.sub(sub,t['output_name'] or t['label']))
        if name.lower().endswith(src.suffix.lower()):name=name[:-len(src.suffix)]
        jobs.append((t,src,target/(name+'_'+token+src.suffix.lower())))
    ctx['document_register']='\n'.join(f'{i}. {t["label"]} — {out.name}' for i,(t,src,out) in enumerate(jobs,1));ctx['реестр']=ctx['document_register']
    certs={}
    if copy_certificates:
        for m in mats:
            if not m.get('certificate_id'):continue
            if not m.get('certificate_path'):raise ValueError('Нет файла сертификата: '+m['name'])
            src=domain.path(db,m['certificate_path'])
            if not src.is_file():raise ValueError('Недоступен сертификат: '+str(src))
            certs[m['certificate_id']]=src
    created=[]
    with tempfile.TemporaryDirectory(prefix='.smetagaz-',dir=target) as stage:
        staged=[]
        for i,(t,src,out) in enumerate(jobs):
            tmp=Path(stage)/str(i);transform(src,ctx,tmp);staged.append((tmp,out,t))
        for cid,src in certs.items():
            tmp=Path(stage)/('cert'+str(cid));shutil.copyfile(src,tmp);staged.append((tmp,target/('Сертификат_'+str(cid)+'_'+token+'_'+filename(src.name)),None))
        try:
            for tmp,out,t in staged:
                with out.open('xb') as dest:
                    created.append(out)
                    with tmp.open('rb') as source:shutil.copyfileobj(source,dest)
                    dest.flush();os.fsync(dest.fileno())
            with db.transaction():
                domain.require(db,owner,rid)
                for tmp,out,t in staged:
                    if t:db.execute('INSERT INTO executive_generated(owner_type,owner_id,slot,title,file_path,context_json,sha256) VALUES(?,?,?,?,?,?,?)',(owner,rid,t['slot'],t['label'],str(out),json.dumps(ctx,ensure_ascii=False),hashlib.sha256(out.read_bytes()).hexdigest()))
        except Exception:
            for out in created:out.unlink(missing_ok=True)
            raise
    return [str(p) for p in created]
