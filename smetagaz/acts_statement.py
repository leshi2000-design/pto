"""Ведомость подписанных актов за календарный месяц (для бухгалтерии) — проекты ГСВ и монтаж ГСВ. Без зависимости от Qt."""
import os
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

from .agenda_domain import norm_date
from . import gsv_project_domain as gd

MONTHS = ['', 'январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь']
SECTIONS = {'gsv_projects': 'Проекты ГСВ', 'contracts': 'Монтаж ГСВ', 'le_contracts': 'Юрлица', 'smr_contracts': 'СМР'}
COUNTERPARTY = {'le_contracts': 'le', 'smr_contracts': 'smr'}
SQL = {
    'gsv_projects': ("SELECT id,pd_number,contract_number,contract_date,act_date,coalesce(nullif(client_name,''),party_name),object_name,address,cost,coalesce(act_signed,0) "
                     "FROM gsv_projects WHERE coalesce(act_date,'')<>''"),
    'contracts': ("SELECT id,contract_number,contract_number,contract_date,acceptance_act_date,coalesce(nullif(client_name,''),party_name),object_name,object_address,contract_amount,coalesce(act_signed,0) "
                  "FROM contracts WHERE coalesce(acceptance_act_date,'')<>''"),
}


def default_period(today=None):
    """Ведомость сдаётся до 10-го числа за прошлый месяц: до 10-го — прошлый месяц, дальше — текущий."""
    today = today or date.today()
    if today.day <= 10:
        return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
    return today.year, today.month


def period_label(year, month):
    return f'{MONTHS[month]} {year}'


def _act_file(db, section, rid):
    if section == 'gsv_projects':
        row = db.fetchone("SELECT file_path FROM gsv_project_docs WHERE project_id=? AND kind='act'", (rid,))
    else:
        row = db.fetchone("SELECT file_path FROM gsvm_docs WHERE contract_id=? AND kind='act'", (rid,))
    return row[0] if row and row[0] and os.path.isfile(row[0]) else ''


def _paid(db, section, rid):
    from . import payments_domain
    try:
        return float(payments_domain.summary(db, section, rid)['paid'])
    except Exception:
        return 0.0


def statement(db, section, year, month):
    """{'signed': [...], 'unsigned': [...]} — акты, датированные выбранным месяцем; сначала по дате акта."""
    if section not in SQL and section not in COUNTERPARTY:
        raise ValueError('Неизвестный раздел для ведомости')
    prefix = f'{year:04d}-{month:02d}'
    result = {'signed': [], 'unsigned': []}
    if section in COUNTERPARTY:
        from . import contracts_core as cc
        mod = COUNTERPARTY[section]
        c = cc.cfg(mod)
        for aid, number, act_date, amount, signed, cid in db.fetchall(f"SELECT id,act_number,act_date,amount,coalesce(signed,0),contract_id FROM {c['acts']} WHERE coalesce(act_date,'')<>''"):
            act = norm_date(act_date)
            if not act.startswith(prefix):
                continue
            ct = cc.contract(db, mod, cid)
            paid = sum(a for _d, a, _n in cc.payments(db, mod, cid))
            path = cc.doc_path(db, mod, 'act', aid)
            amount = float(amount or 0)
            row = dict(id=aid, number=number or '', contract_number=ct['contract_number'] or '', contract_date=norm_date(ct['contract_date']), act_date=act,
                       client=cc.party_label(db, mod, ct), object=ct['object_name'] or '', address=ct['object_address'] or '', amount=amount, paid=paid, rest=float(ct['amount'] or 0) - paid,
                       file=path if path and os.path.isfile(path) else '')
            result['signed' if signed else 'unsigned'].append(row)
        for rows in result.values():
            rows.sort(key=lambda r: (r['act_date'], r['number']))
        return result
    for rid, number, contract_number, contract_date, act_date, client, obj, address, amount, signed in db.fetchall(SQL[section]):
        act = norm_date(act_date)
        if not act.startswith(prefix):
            continue
        paid = _paid(db, section, rid)
        amount = float(amount or 0)
        row = dict(id=rid, number=number or '', contract_number=contract_number or '', contract_date=norm_date(contract_date), act_date=act, client=client or '',
                   object=obj or '', address=address or '', amount=amount, paid=paid, rest=amount - paid, file=_act_file(db, section, rid))
        result['signed' if signed else 'unsigned'].append(row)
    for rows in result.values():
        rows.sort(key=lambda r: (r['act_date'], r['number']))
    return result


def _fmt(day):
    return datetime.strptime(day, '%Y-%m-%d').strftime('%d.%m.%Y') if day else ''


def export_statement(db, section, year, month, path):
    """Записывает Excel-ведомость: лист «Подписанные акты» с итогом и лист «Не подписаны»; возвращает данные ведомости."""
    import openpyxl
    from openpyxl.styles import Font, Alignment
    data = statement(db, section, year, month)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Подписанные акты'
    headers = ['№', 'Дата акта', '№ договора', 'Дата договора', 'Клиент', 'Объект', 'Адрес', 'Сумма, BYN', 'Оплачено, BYN', 'Остаток, BYN', 'Файл акта']

    def fill(sheet, rows, title):
        sheet['A1'] = title
        sheet['A1'].font = Font(bold=True, size=14)
        sheet['A2'] = f'Раздел: {SECTIONS[section]}. Сформировано {datetime.now():%d.%m.%Y %H:%M}'
        sheet.append([])
        sheet.append(headers)
        for c in sheet[4]:
            c.font = Font(bold=True)
            c.alignment = Alignment(wrap_text=True, vertical='center')
        for i, r in enumerate(rows, 1):
            sheet.append([i, _fmt(r['act_date']), r['contract_number'], _fmt(r['contract_date']), r['client'], r['object'], r['address'], r['amount'], r['paid'], r['rest'],
                          'есть' if r['file'] else 'нет'])
        last = sheet.max_row
        sheet.append(['', '', '', '', 'ИТОГО', f'актов: {len(rows)}', '', sum(r['amount'] for r in rows), sum(r['paid'] for r in rows), sum(r['rest'] for r in rows), ''])
        for c in sheet[last + 1]:
            c.font = Font(bold=True)
        for col, width in zip('ABCDEFGHIJK', (5, 12, 14, 14, 30, 34, 36, 14, 14, 14, 10)):
            sheet.column_dimensions[col].width = width
        for row in sheet.iter_rows(min_row=5):
            for c in row:
                if isinstance(c.value, str):
                    c.data_type = 's'
                if isinstance(c.value, float):
                    c.number_format = '#,##0.00'

    fill(ws, data['signed'], f'Ведомость подписанных актов за {period_label(year, month)}')
    fill(wb.create_sheet('Не подписаны'), data['unsigned'], f'Акты за {period_label(year, month)}, которые ещё не подписаны')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix='.xlsx', dir=path.parent)
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return data


def collect_acts(db, section, year, month, target_dir):
    """Создаёт папку «Акты … за месяц» с копиями файлов подписанных актов и ведомостью. Возвращает {'folder','copied','missing'}."""
    folder = Path(target_dir) / gd.safe_name(f'Акты {SECTIONS[section]} {year}-{month:02d}')
    folder.mkdir(parents=True, exist_ok=True)
    data = export_statement(db, section, year, month, folder / gd.safe_name(f'Ведомость актов {SECTIONS[section]} {year}-{month:02d}.xlsx'))
    copied, missing = [], []
    for r in data['signed']:
        if not r['file']:
            missing.append(r)
            continue
        name = gd.safe_name(f'{r["act_date"]} {r["number"]} {r["client"]}').replace(' ', '_') + Path(r['file']).suffix
        shutil.copy2(r['file'], folder / name)
        copied.append(name)
    return dict(folder=str(folder), copied=copied, missing=missing, total=len(data['signed']))
