"""Ensure an estimate without an explicit signature tag has a signature line."""
from zipfile import ZipFile
from lxml import etree as ET
from .template_engine import transform,W,S

def ensure_signature(source,output,author):
    if 'prepared_by' in transform(source):return
    with ZipFile(output) as z:infos=z.infolist();parts={n:z.read(n) for n in z.namelist()}
    text='Составил: '+str(author)+'    Подпись: __________________'
    parser=ET.XMLParser(resolve_entities=False,no_network=True)
    if 'word/document.xml' in parts:
        root=ET.fromstring(parts['word/document.xml'],parser);body=root.find('{'+W+'}body');p=ET.Element('{'+W+'}p');run=ET.SubElement(p,'{'+W+'}r');ET.SubElement(run,'{'+W+'}t').text=text;section=body.find('{'+W+'}sectPr');body.insert(body.index(section) if section is not None else len(body),p);parts['word/document.xml']=ET.tostring(root,encoding='UTF-8',xml_declaration=True)
    else:
        sheet=next(n for n in parts if n.startswith('xl/worksheets/sheet') and n.endswith('.xml'));root=ET.fromstring(parts[sheet],parser);data=root.find('{'+S+'}sheetData');n=max([int(r.get('r')) for r in data]+[0])+2;row=ET.SubElement(data,'{'+S+'}row',r=str(n));cell=ET.SubElement(row,'{'+S+'}c',r='A'+str(n),t='inlineStr');ET.SubElement(ET.SubElement(cell,'{'+S+'}is'),'{'+S+'}t').text=text
        dimension=root.find('{'+S+'}dimension')
        if dimension is not None:
            import re
            ref=dimension.get('ref','A1');last=ref.split(':')[-1];col=re.sub(r'\d','',last);dimension.set('ref',ref.split(':')[0]+':'+col+str(n))
        parts[sheet]=ET.tostring(root,encoding='UTF-8',xml_declaration=True)
        # A fixed print area would hide the automatically added signature.
        wb=ET.fromstring(parts['xl/workbook.xml'],parser)
        for node in list(wb.iter('{'+S+'}definedName')):
            if node.get('name')=='_xlnm.Print_Area' and node.get('localSheetId')=='0':node.getparent().remove(node)
        parts['xl/workbook.xml']=ET.tostring(wb,encoding='UTF-8',xml_declaration=True)
    with ZipFile(output,'w') as z:
        for info in infos:z.writestr(info,parts[info.filename])
