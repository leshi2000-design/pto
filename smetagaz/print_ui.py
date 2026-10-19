"""Печать и сохранение в PDF одним нажатием: реестры (то, что сейчас видно в таблице) и карточки договоров. Документ собирается как HTML и выводится через Qt."""
import html
import os
import re
from datetime import datetime

from PyQt6.QtCore import QMarginsF, QSizeF, Qt
from PyQt6.QtGui import QPageLayout, QPageSize, QTextDocument
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QPushButton

from .dates import display_date

STYLE = ('body{font-family:"Segoe UI",Arial,sans-serif;font-size:10pt;color:#201F1E;}h1{font-size:15pt;margin:0 0 2px 0;}h2{font-size:11.5pt;margin:14px 0 4px 0;color:#1B5E57;}'
         'p.sub{color:#605E5C;margin:0 0 8px 0;}table{border-collapse:collapse;width:100%;}td,th{border:1px solid #B8B8B8;padding:3px 5px;vertical-align:top;}'
         'th{background:#E8F1EF;text-align:left;}td.k{width:34%;background:#F6F6F6;color:#444;}')


def esc(value):
    text = '' if value is None else str(value)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        text = display_date(text)
    return html.escape(text).replace('\n', '<br>')


def page(title, body, subtitle=''):
    stamp = datetime.now().strftime('%d.%m.%Y %H:%M')
    sub = f'<p class="sub">{esc(subtitle)}{" · " if subtitle else ""}сформировано {stamp}</p>'
    return f'<html><head><style>{STYLE}</style></head><body><h1>{esc(title)}</h1>{sub}{body}</body></html>'


def table_html(title, table, subtitle=''):
    """Видимые колонки и строки QTableWidget (с учётом поиска и скрытых колонок)."""
    cols = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
    head = ''.join(f'<th>{esc(table.horizontalHeaderItem(c).text() if table.horizontalHeaderItem(c) else "")}</th>' for c in cols)
    rows = []
    for r in range(table.rowCount()):
        if table.isRowHidden(r):
            continue
        rows.append('<tr>' + ''.join(f'<td>{esc(table.item(r, c).text() if table.item(r, c) else "")}</td>' for c in cols) + '</tr>')
    body = f'<table><tr>{head}</tr>{"".join(rows)}</table><p class="sub">Строк: {len(rows)}</p>'
    return page(title, body, subtitle), len(cols) > 6


def card_html(title, sections, subtitle=''):
    """sections: [(заголовок, [(название, значение), …])] или [(заголовок, ('table', шапка, строки))]."""
    out = []
    for heading, content in sections:
        out.append(f'<h2>{esc(heading)}</h2>')
        if isinstance(content, tuple) and content and content[0] == 'table':
            _t, header, rows = content
            out.append('<table><tr>' + ''.join(f'<th>{esc(h)}</th>' for h in header) + '</tr>' + ''.join('<tr>' + ''.join(f'<td>{esc(v)}</td>' for v in row) + '</tr>' for row in rows) + '</table>')
        else:
            pairs = [(k, v) for k, v in content if str(v if v is not None else '').strip() != '']
            out.append('<table>' + ''.join(f'<tr><td class="k">{esc(k)}</td><td>{esc(v)}</td></tr>' for k, v in pairs) + '</table>' if pairs else '<p class="sub">нет данных</p>')
    return page(title, ''.join(out), subtitle), False


def _document(markup, printer):
    doc = QTextDocument()
    doc.setHtml(markup)
    rect = printer.pageRect(QPrinter.Unit.Point)
    doc.setPageSize(QSizeF(rect.width(), rect.height()))
    return doc


def _printer(landscape, mode=QPrinter.PrinterMode.HighResolution):
    printer = QPrinter(mode)
    printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    printer.setPageOrientation(QPageLayout.Orientation.Landscape if landscape else QPageLayout.Orientation.Portrait)
    printer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
    return printer


def write_pdf(path, markup, landscape=False):
    printer = _printer(landscape)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(path)
    _document(markup, printer).print(printer)
    return path


def save_pdf(parent, markup, landscape, name):
    safe = re.sub(r'[\\/:*?"<>|]+', '_', name).strip() or 'документ'
    path, _ = QFileDialog.getSaveFileName(parent, 'Сохранить PDF', safe + '.pdf', 'PDF (*.pdf)')
    if not path:
        return ''
    try:
        write_pdf(path, markup, landscape)
    except Exception as e:
        QMessageBox.warning(parent, 'PDF не сохранён', str(e))
        return ''
    from .platform_utils import open_local
    try:
        open_local(path)
    except OSError:
        pass
    return path


def print_html(parent, markup, landscape):
    printer = _printer(landscape, QPrinter.PrinterMode.ScreenResolution)
    if QPrintDialog(printer, parent).exec():
        _document(markup, printer).print(printer)
        return True
    return False


def make_buttons(parent, builder, name, before=None):
    """Две кнопки «PDF» и «Печать». builder() возвращает (html, альбомная ориентация); name — имя файла PDF."""
    pdf, prn = QPushButton('PDF'), QPushButton('Печать')
    pdf.setToolTip('Сохранить в PDF и открыть')
    prn.setToolTip('Отправить на принтер')
    pdf.clicked.connect(lambda: (before is None or before()) and save_pdf(parent, *builder(), name() if callable(name) else name))
    prn.clicked.connect(lambda: (before is None or before()) and print_html(parent, *builder()))
    return pdf, prn


# --- ДАННЫЕ КАРТОЧЕК -------------------------------------------------------------------------

def _money(v):
    try:
        return f'{float(v or 0):,.2f}'.replace(',', ' ').replace('.', ',') + ' BYN'
    except (TypeError, ValueError):
        return ''


def _yes(v):
    return 'да' if v else 'нет'


def gsn_card(db, cid):
    from . import gsn_domain as gn
    c = gn.get(db, cid)
    try:
        from . import payments_domain
        paid = float(payments_domain.summary(db, 'gsn_projects', cid)['paid'])
    except Exception:
        paid = 0
    sections = [
        ('Объект', [('Номер договора', c['contract_number']), ('Дата заключения', c['contract_date']), ('Договор подписан', _yes(c.get('contract_signed'))), ('Объект', c['title']), ('Адрес объекта', c.get('address'))]),
        ('Клиент', [('ФИО', c['client_name']), ('Телефон', c['phone']), ('Адрес', c.get('client_address')), ('Паспорт', c['passport']), ('Выдан', c.get('passport_issuer')), ('Дата выдачи', c.get('passport_issue_date'))]),
        ('Проект', [('Шифр', c.get('designer_code')), ('Проектировщик', c.get('designer')), ('Дата проекта', c.get('project_month')), ('ТУ', c.get('tu_text'))]),
        ('Сроки и стоимость', [('Начало работ', c.get('work_start_date')), ('Окончание работ', c.get('work_end_date')), ('Дата акта', c.get('act_date')), ('Акт подписан', _yes(c.get('act_signed'))), ('Стоимость', _money(c.get('contract_amount'))), ('Оплачено', _money(paid))]),
        ('Трубопроводы', [('ПЭ 32, м', c.get('pe_length')), ('Сталь 25 подземная, м', c.get('steel_under_length') or (0 if c.get('steel_above_length') else c.get('steel_length'))), ('Сталь 25 надземная, м', c.get('steel_above_length')), ('Давление', gn.PRESSURE_TEXT.get(c.get('pressure_type'), '')), ('Врезка', gn.TIE_TEXT.get(c.get('tie_in'), '')), ('Муфт, шт', c.get('couplings'))]),
        ('Примечания', [('Примечания', c.get('notes'))]),
    ]
    mats = [(m['name'], f'{m["quantity"]:g}', m['unit']) for m in gn.materials(db, cid)]
    if mats:
        sections.append(('Материалы', ('table', ['Позиция', 'Количество', 'Ед.'], mats)))
    certs = [(x['name'], x['number'], x['valid_to'], 'по умолчанию' if x['kind'] == 'default' else 'зависимый') for x in gn.certificates(db, cid)]
    if certs:
        sections.append(('Сертификаты', ('table', ['Сертификат', 'Номер', 'Действует до', 'Тип'], certs)))
    att = [(a['title'], a['welder'], a['number'], a['date']) for a in gn.attestations(db, cid)]
    if att:
        sections.append(('Аттестаты сварщиков', ('table', ['Аттестат', 'Сварщик', 'Номер', 'Дата'], att)))
    return card_html(f'Договор {c["contract_number"] or cid} · монтаж ГСН', sections, c['client_name'] or '')


def _has(db, table, col):
    try:
        return any(r[1] == col for r in db.fetchall(f'PRAGMA table_info({table})'))
    except Exception:
        return False


def _row(db, table, rid):
    cur = db.execute(f'SELECT * FROM {table} WHERE id=?', (rid,))
    row = cur.fetchone()
    return dict(zip([x[0] for x in cur.description], row)) if row else {}


def gsvm_card(db, cid):
    c = _row(db, 'contracts', cid)
    sections = [
        ('Договор', [('Номер', c.get('contract_number')), ('Дата заключения', c.get('contract_date')), ('Объект', c.get('object_name')), ('Адрес объекта', c.get('object_address')), ('Договор подписан', _yes(c.get('contract_signed')))]),
        ('Заказчик', [('ФИО / организация', c.get('client_name') or c.get('party_name')), ('Телефон', c.get('client_phone')), ('Адрес', c.get('client_address')), ('Паспорт', c.get('passport_series_number')), ('Выдан', c.get('passport_issued_by')), ('Дата выдачи', c.get('passport_issue_date'))]),
        ('Проект', [('Шифр', c.get('designer_code')), ('Проектировщик', c.get('designer')), ('Дата проекта', c.get('project_month'))]),
        ('Сроки и стоимость', [('Начало работ', c.get('work_start_date')), ('Окончание работ', c.get('work_end_date')), ('Дата акта', c.get('acceptance_act_date')), ('Акт подписан', _yes(c.get('act_signed'))), ('Стоимость', _money(c.get('contract_amount')))]),
        ('Примечания', [('Примечания', c.get('notes'))]),
    ]
    equip = db.fetchall('SELECT kind,model,serial,note FROM gsvm_equipment WHERE contract_id=? ORDER BY id', (cid,))
    if equip:
        sections.append(('Оборудование', ('table', ['Вид', 'Модель', 'Серийный номер', 'Примечание'], equip)))
    return card_html(f'Договор {c.get("contract_number") or cid} · монтаж ГСВ', sections, c.get('client_name') or c.get('party_name') or '')


def gsv_project_card(db, pid):
    c = _row(db, 'gsv_projects', pid)
    sections = [
        ('Проект', [('Номер ПД', c.get('pd_number')), ('Номер договора', c.get('contract_number')), ('Объект', c.get('object_name')), ('Адрес', c.get('address')), ('ТУ', c.get('tu_text'))]),
        ('Заказчик', [('ФИО / организация', c.get('client_name') or c.get('party_name')), ('Телефон', c.get('phone')), ('Адрес заказчика', c.get('client_address')), ('Паспорт', c.get('passport'))]),
        ('Сроки и стоимость', [('Дата договора', c.get('contract_date')), ('Срок проекта', c.get('due_date')), ('Дата акта', c.get('act_date')), ('Акт подписан', _yes(c.get('act_signed'))), ('Стоимость', _money(c.get('cost')))]),
        ('Примечания', [('Примечания', c.get('notes'))]),
    ]
    return card_html(f'Проект {c.get("pd_number") or pid} · ГСВ', sections, c.get('client_name') or c.get('party_name') or '')
