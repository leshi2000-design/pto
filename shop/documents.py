"""All output uses templates, including the supplied editable HTML examples."""
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import html
import json
import re
import tempfile
from docx import Document
from openpyxl import load_workbook

TITLES = {'receipt': 'Поступление товаров', 'invoice': 'Счёт на оплату', 'shipment': 'Расходная накладная'}
TAG = re.compile(r'{{\s*([\w.]+)\s*}}')


def money(value):
    return f'{Decimal(value) / 100:.2f}'


def context(store, doc_id, require_posted=True):
    docs = store.rows('SELECT * FROM documents WHERE id=?', (doc_id,))
    if not docs:
        raise ValueError('Документ не найден')
    doc = docs[0]
    if require_posted and doc['status'] != 'posted':
        raise ValueError('Для выдачи документа сначала проведите его')
    items = []
    total = tax_total = 0
    for index, line in enumerate(store.rows('SELECT * FROM lines WHERE document_id=? ORDER BY id', (doc_id,)), 1):
        amount = int((Decimal(line['quantity']) * line['price'] / 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        tax = int((Decimal(amount) * line['tax_bp'] / 10000).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
        total += amount + tax
        tax_total += tax
        items.append({'index': str(index), 'sku': line['sku'], 'name': line['name'], 'unit': line['unit'],
                      'quantity': str(Decimal(line['quantity']) / 1000), 'price': money(line['price']),
                      'tax_rate': str(Decimal(line['tax_bp']) / 100), 'tax': money(tax),
                      'amount': money(amount), 'total': money(amount + tax)})
    settings = dict((r['key'], r['value']) for r in store.rows('SELECT * FROM settings'))
    values = {'title': TITLES[doc['kind']], 'number': doc['number'], 'date': doc['day'],
              'customer': doc['party_name'], 'customer_details': doc['party_details'],
              'seller': settings.get('seller', ''), 'seller_details': settings.get('seller_details', ''),
              'currency': doc['currency'], 'total': money(total), 'tax_total': money(tax_total),
              'subtotal': money(total - tax_total), 'reference': doc['reference']}
    return doc, values, items


def substitute(text, values, escape=False):
    def replace(match):
        key = match.group(1)
        if key not in values:
            raise ValueError('Неизвестный тег шаблона: ' + key)
        return html.escape(str(values[key])) if escape else str(values[key])
    return TAG.sub(replace, text)


def ensure_templates(store):
    sample = '''<!doctype html><html lang="ru"><meta charset="utf-8"><title>{{title}} {{number}}</title>
<style>body{font:14px Arial;margin:40px;color:#172536}table{border-collapse:collapse;width:100%}td,th{border:1px solid #aaa;padding:8px}pre{white-space:pre-wrap;font:inherit}.note{color:#666;font-size:12px}</style>
<h1>{{title}} № {{number}}</h1><p>Дата: {{date}} · Основание: {{reference}}</p>
<p>Организация: {{seller}}</p><pre>{{seller_details}}</pre>
<p>Контрагент: {{customer}}</p><pre>{{customer_details}}</pre>
<table><thead><tr><th>№</th><th>Артикул</th><th>Товар</th><th>Ед.</th><th>Количество</th><th>Цена без НДС</th><th>НДС %</th><th>Сумма с НДС</th></tr></thead><tbody>
{{#items}}<tr><td>{{item.index}}</td><td>{{item.sku}}</td><td>{{item.name}}</td><td>{{item.unit}}</td><td>{{item.quantity}}</td><td>{{item.price}}</td><td>{{item.tax_rate}}</td><td>{{item.total}}</td></tr>{{/items}}
</tbody></table><p>Без НДС: {{subtotal}} · НДС: {{tax_total}} · Итого: <b>{{total}} {{currency}}</b></p>
<p>Отпустил: ____________________ Получил: ____________________</p>
<p class="note">Редактируемый образец. Для официальной ТН/ТТН подключите свой согласованный шаблон.</p></html>'''
    for kind in TITLES:
        path = store.root / 'templates' / f'{kind}.html'
        if not path.exists():
            path.write_text(sample, encoding='utf-8')


def export(store, doc_id, template, destination):
    template, destination = Path(template), Path(destination)
    if template.resolve() == destination.resolve():
        raise ValueError('Нельзя перезаписать шаблон')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        staged = Path(tmp) / destination.name
        _render(store, doc_id, template, staged)
        staged.replace(destination)
    return destination


def _render(store, doc_id, template, destination):
    doc, values, items = context(store, doc_id)
    template, destination = Path(template), Path(destination)
    if template.resolve() == destination.resolve():
        raise ValueError('Нельзя перезаписать шаблон')
    suffix = template.suffix.lower()
    if suffix != destination.suffix.lower():
        raise ValueError('Расширение результата должно совпадать с шаблоном')
    if suffix == '.html':
        text = template.read_text(encoding='utf-8')
        pattern = re.compile(r'{{#items}}(.*?){{/items}}', re.S)
        if not pattern.search(text):
            raise ValueError('В HTML нужен блок {{#items}}…{{/items}}')
        text = pattern.sub(lambda m: ''.join(substitute(m.group(1), {**values, **{'item.' + k: v for k, v in item.items()}}, True)
                                             for item in items), text)
        destination.write_text(substitute(text, values, True), encoding='utf-8')
    elif suffix == '.docx':
        from copy import deepcopy
        document = Document(template)
        repeated = False
        for table in document.tables:
            for row in list(table.rows):
                if any('{{item.' in cell.text for cell in row.cells):
                    repeated = True
                    for item in items:
                        clone = deepcopy(row._tr)
                        row._tr.addprevious(clone)
                        from docx.table import _Row
                        new_row = _Row(clone, table)
                        for cell in new_row.cells:
                            for paragraph in cell.paragraphs:
                                _paragraph(paragraph, {**values, **{'item.' + k: v for k, v in item.items()}})
                    table._tbl.remove(row._tr)
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        _paragraph(paragraph, values)
        if not repeated:
            raise ValueError('Добавьте в таблицу шаблона строку с тегами {{item.name}}, {{item.quantity}} и т. д.')
        for paragraph in document.paragraphs:
            _paragraph(paragraph, values)
        for section in document.sections:
            for part in (section.header, section.footer):
                for paragraph in part.paragraphs:
                    _paragraph(paragraph, values)
        document.save(destination)
    elif suffix == '.xlsx':
        from copy import copy
        workbook = load_workbook(template)
        repeated = False
        for sheet in workbook:
            repeat_rows = [row[0].row for row in sheet if any(isinstance(c.value, str) and '{{item.' in c.value for c in row)]
            if len(repeat_rows) > 1:
                raise ValueError('В листе разрешена одна строка товаров')
            if repeat_rows:
                repeated = True
                index = repeat_rows[0]
                originals = [(c.value, copy(c._style)) for c in sheet[index]]
                if len(items) > 1:
                    sheet.insert_rows(index + 1, len(items) - 1)
                for offset, item in enumerate(items):
                    for column, (value, style) in enumerate(originals, 1):
                        cell = sheet.cell(index + offset, column)
                        cell._style = copy(style)
                        cell.value = substitute(value, {**values, **{'item.' + k: v for k, v in item.items()}}) if isinstance(value, str) else value
                        if isinstance(cell.value, str) and cell.value.startswith('=') and isinstance(value, str) and '{{' in value:
                            cell.data_type = 's'
            for row in sheet:
                for cell in row:
                    if isinstance(cell.value, str) and '{{' in cell.value:
                        cell.value = substitute(cell.value, values)
                        if cell.value.startswith('='):
                            cell.data_type = 's'
        if not repeated:
            raise ValueError('Добавьте строку товаров с тегами {{item.name}}, {{item.quantity}} и т. д.')
        workbook.save(destination)
    else:
        raise ValueError('Поддерживаются HTML, DOCX и XLSX')
    # Keep a manifest of which snapshot and template produced each document.
    return destination


def _paragraph(paragraph, values):
    text = paragraph.text
    if '{{' not in text:
        return
    # Replace from right to left across Word runs without losing their formatting.
    runs = paragraph.runs
    for match in reversed(list(TAG.finditer(text))):
        replacement = substitute(match.group(0), values)
        cursor = 0
        touched = []
        for run in runs:
            end = cursor + len(run.text)
            if cursor < match.end() and end > match.start():
                touched.append((run, max(0, match.start() - cursor), min(len(run.text), match.end() - cursor)))
            cursor = end
        for index, (run, start, end) in enumerate(touched):
            run.text = run.text[:start] + (replacement if index == 0 else '') + run.text[end:]
