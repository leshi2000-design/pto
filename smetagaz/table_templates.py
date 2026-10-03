"""Repeat tagged table rows while retaining OOXML styles and package parts."""
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
from tempfile import TemporaryDirectory
import re
from lxml import etree as ET
from .template_engine import TAG,W,S,replace_nodes,transform,numeric_value

def dataset(text,tables):
    names={m.group(1).split('.')[0] for m in TAG.finditer(text) if '.' in m.group(1) and m.group(1).split('.')[0] in tables}
    if len(names)>1:raise ValueError('В одной строке шаблона используйте только одну таблицу данных')
    return next(iter(names),None)

def render(source,context,tables,destination):
    source=Path(source)
    transform(source) # package validation and malformed tag checks before editing
    parser=lambda:ET.XMLParser(resolve_entities=False,no_network=True)
    with ZipFile(source) as z:parts={n:z.read(n) for n in z.namelist()};infos=z.infolist()
    changed=False;sheet_shifts={}
    if source.suffix.lower()=='.docx':
        for name,content in list(parts.items()):
            if not name.startswith('word/') or not name.endswith('.xml'):continue
            root=ET.fromstring(content,parser());dirty=False
            for row in list(root.iter('{'+W+'}tr')):
                if row.getparent() is None:continue
                key=dataset(''.join(n.text or '' for n in row.iter('{'+W+'}t')),tables)
                if not key:continue
                if row.findall('.//{'+W+'}tbl'):raise ValueError('Повторяющаяся строка Word не должна содержать вложенную таблицу')
                parent=row.getparent();index=parent.index(row)
                for i,values in enumerate(tables[key]):
                    copy=deepcopy(row);local={**context,**{key+'.'+k:v for k,v in values.items()}}
                    for p in copy.iter('{'+W+'}p'):replace_nodes(list(p.iter('{'+W+'}t')),local,set())
                    parent.insert(index+i,copy)
                parent.remove(row);dirty=True
            if dirty:parts[name]=ET.tostring(root,encoding='UTF-8',xml_declaration=True);changed=True
    else:
        shared=[]
        if 'xl/sharedStrings.xml' in parts:
            ss=ET.fromstring(parts['xl/sharedStrings.xml'],parser());shared=list(ss.iter('{'+S+'}si'))
        for name,content in list(parts.items()):
            if not name.startswith('xl/worksheets/sheet') or not name.endswith('.xml'):continue
            root=ET.fromstring(content,parser());data=root.find('{'+S+'}sheetData')
            if data is None:continue
            def texts(cell):
                if cell.get('t')=='s':
                    v=cell.find('{'+S+'}v');return list(shared[int(v.text)].iter('{'+S+'}t')) if v is not None else []
                return list(cell.iter('{'+S+'}t'))
            repeating={}
            for row in data:
                key=dataset(' '.join(''.join(n.text or '' for n in texts(c)) for c in row),tables)
                if key:repeating[int(row.get('r'))]=key
            if not repeating:continue
            if root.find('{'+S+'}drawing') is not None or root.find('{'+S+'}tableParts') is not None:raise ValueError('Для повторяющихся строк Excel используйте обычный лист без диаграмм и структурированных таблиц')
            if any(b'<f' in value for key,value in parts.items() if key.startswith('xl/worksheets/') and key.endswith('.xml')):
                raise ValueError('В Excel-шаблоне с повторяющимися строками замените формулы тегами готовых итогов (total, vat_total и др.). Шаблоны без повторяющихся строк поддерживают формулы.')
            changes={r:len(tables[key])-1 for r,key in repeating.items()}
            def shifted(r,end=False):return max(1,r+sum(delta for at,delta in changes.items() if at<r or (end and at==r)))
            def cellref(ref,end=False):return re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)',lambda m:m.group(1)+str(shifted(int(m.group(2)),end)),ref)
            def range_ref(ref):
                return ' '.join(':'.join(cellref(part,i>0) for i,part in enumerate(pair.split(':'))) for pair in ref.split())
            original_rows=list(data)
            for row in original_rows:
                old=int(row.get('r'));key=repeating.get(old);parent=row.getparent();index=parent.index(row)
                values_list=tables[key] if key else [None]
                for i,values in enumerate(values_list):
                    copy=deepcopy(row);new=shifted(old)+i;copy.set('r',str(new))
                    for cell in copy:
                        cell.set('r',re.sub(r'\d+$',str(new),cell.get('r')))
                        if key:
                            local={**context,**{key+'.'+k:v for k,v in values.items()}}
                            original=''.join(n.text or '' for n in texts(cell));number=numeric_value(original,local)
                            if cell.get('t')=='s' and TAG.search(original):
                                si=deepcopy(shared[int(cell.find('{'+S+'}v').text)]);si.tag='{'+S+'}is';cell.remove(cell.find('{'+S+'}v'));cell.set('t','inlineStr');cell.append(si)
                            replace_nodes(list(cell.iter('{'+S+'}t')),local,set())
                            if number is not None:
                                for child in list(cell):
                                    if child.tag in ('{'+S+'}v','{'+S+'}is'):cell.remove(child)
                                cell.set('t','n');ET.SubElement(cell,'{'+S+'}v').text=number
                    parent.insert(index+i,copy)
                parent.remove(row)
            for merge in list(root.iter('{'+S+'}mergeCell')):
                ref=merge.get('ref');rr=[int(x) for x in re.findall(r'\d+',ref)]
                inside=[at for at in repeating if rr[0]<=at<=rr[-1]]
                if inside:
                    if rr[0]!=rr[-1]:raise ValueError('Объединение ячеек не должно пересекать повторяющуюся строку Excel по вертикали')
                    parent=merge.getparent();idx=parent.index(merge)
                    for i in range(len(tables[repeating[rr[0]]])):
                        copy=deepcopy(merge);copy.set('ref',re.sub(r'\d+',str(shifted(rr[0])+i),ref));parent.insert(idx+i,copy)
                    parent.remove(merge)
                else:merge.set('ref',range_ref(ref))
            for node in root.iter():
                if node.tag in ('{'+S+'}c','{'+S+'}row','{'+S+'}mergeCell'):continue
                for attr in ('ref','sqref'):
                    if node.get(attr):node.set(attr,range_ref(node.get(attr)))
                if node.tag=='{'+S+'}mergeCells':node.set('count',str(len(node)))
            # Defined print areas are shifted below using the workbook sheet mapping.
            sheet_shifts[name]=changes;parts[name]=ET.tostring(root,encoding='UTF-8',xml_declaration=True);changed=True
        if sheet_shifts:
            wb=ET.fromstring(parts['xl/workbook.xml'],parser());rels=ET.fromstring(parts['xl/_rels/workbook.xml.rels'],parser());targets={r.get('Id'):r.get('Target').lstrip('/') for r in rels};sheets=list(wb.iter('{'+S+'}sheet'))
            for node in wb.iter('{'+S+'}definedName'):
                idx=node.get('localSheetId')
                if idx is None:raise ValueError('Именованные диапазоны книги с повторяющимися строками не поддерживаются; используйте обычные ячейки с тегами')
                sheet=sheets[int(idx)];target=targets[sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')];target=target if target.startswith('xl/') else 'xl/'+target
                changes=sheet_shifts.get(target)
                if changes:
                    node.text=re.sub(r'(\$?[A-Z]{1,3}\$?)(\d+)',lambda m:m.group(1)+str(max(1,int(m.group(2))+sum(delta for at,delta in changes.items() if at<=int(m.group(2))))),node.text or '')
            parts['xl/workbook.xml']=ET.tostring(wb,encoding='UTF-8',xml_declaration=True)
            # Unreferenced shared strings can still contain row tags; remove their tag text.
            if 'xl/sharedStrings.xml' in parts:
                ss=ET.fromstring(parts['xl/sharedStrings.xml'],parser())
                for si in ss.iter('{'+S+'}si'):
                    if dataset(''.join(n.text or '' for n in si.iter('{'+S+'}t')),tables):
                        for n in si.iter('{'+S+'}t'):n.text=''
                parts['xl/sharedStrings.xml']=ET.tostring(ss,encoding='UTF-8',xml_declaration=True)
    if not changed:return transform(source,context,destination)
    with TemporaryDirectory() as tmp:
        expanded=Path(tmp)/source.name
        with ZipFile(expanded,'w') as z:
            for info in infos:z.writestr(info,parts[info.filename])
        transform(expanded,context,destination)
