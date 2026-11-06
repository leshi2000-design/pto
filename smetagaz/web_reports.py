"""Веб-доступ: ведомость актов за месяц по всем разделам (те же данные и расчёт, что в окне «Ведомость подписанных актов» программы)."""
import os
import re
import tempfile

from . import acts_statement as st
from .web_pages import esc, layout
from .web_payments import money

MODULE_OF = {'gsv_projects': 'gsv', 'contracts': 'contracts', 'gsn_projects': 'gsn', 'smr_contracts': 'smr', 'to_contracts': 'to', 'ip_contracts': 'ip', 'fl_contracts': 'fl', 'le_contracts': 'le_other'}


def parse_month(text, today=None):
    """'2026-10' -> (2026, 10); пусто или неверно — период по умолчанию (до 10-го числа — прошлый месяц)."""
    m = re.fullmatch(r'(\d{4})-(\d{1,2})', str(text or '').strip())
    if m and 1 <= int(m.group(2)) <= 12 and 2000 <= int(m.group(1)) <= 2100:
        return int(m.group(1)), int(m.group(2))
    return st.default_period(today)


def shift(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _table(rows, section, signed):
    body = ''
    for i, r in enumerate(rows, 1):
        link = f'/m/{MODULE_OF[section]}/{r["contract_id"]}'
        body += (f'<tr><td>{i}</td><td>{esc(r["act_date"][8:10] + "." + r["act_date"][5:7] + "." + r["act_date"][:4]) if r["act_date"] else ""}</td>'
                 f'<td><a href="{link}">{esc(r["contract_number"] or "б/н")}</a></td><td>{esc(r["client"])}</td><td>{esc(r["object"])}<div class="muted">{esc(r["address"])}</div></td>'
                 f'<td class="num">{money(r["amount"])}</td><td class="num pos">{money(r["paid"])}</td><td class="num {"neg" if r["rest"] > 0.005 else "pos"}">{money(r["rest"])}</td></tr>')
    return ('<table class="plain"><thead><tr><th>№</th><th>Дата акта</th><th>Договор</th><th>Клиент</th><th>Объект</th><th class="num">Сумма</th><th class="num">Оплачено</th><th class="num">Остаток</th></tr></thead>'
            f'<tbody>{body}</tbody></table>')


def acts_page(db, year, month, session, modules, nonce, app_name='ПТО', message=''):
    groups = st.statement_all(db, year, month)
    py, pm = shift(year, month, -1)
    ny, nm = shift(year, month, 1)
    month_value = f'{year:04d}-{month:02d}'
    nav = (f'<form class="bar" method="get" action="/acts"><a class="btn sec" href="/acts?month={py:04d}-{pm:02d}">← {esc(st.MONTHS[pm])}</a>'
           f'<input type="month" name="month" value="{month_value}" style="max-width:200px"><button class="btn">Показать</button>'
           f'<a class="btn sec" href="/acts?month={ny:04d}-{nm:02d}">{esc(st.MONTHS[nm])} →</a><a class="btn sec" href="/acts.xlsx?month={month_value}">Скачать Excel</a></form>')
    total_signed = sum(g['signed_sum'] for g in groups)
    total_unsigned = sum(g['unsigned_sum'] for g in groups)
    n_signed = sum(len(g['signed']) for g in groups)
    n_unsigned = sum(len(g['unsigned']) for g in groups)
    summary_rows = ''.join(f'<tr><td>{esc(g["title"])}</td><td class="num">{len(g["signed"])}</td><td class="num">{money(g["signed_sum"])}</td><td class="num">{len(g["unsigned"])}</td>'
                           f'<td class="num">{money(g["unsigned_sum"])}</td></tr>' for g in groups)
    summary = (f'<div class="sum"><div><span>Подписанных актов</span><b>{n_signed}</b></div><div><span>На сумму</span><b class="pos">{money(total_signed)}</b></div>'
               f'<div><span>Не подписано</span><b>{n_unsigned}</b></div><div><span>На сумму</span><b class="neg">{money(total_unsigned)}</b></div></div>'
               f'<table class="plain"><thead><tr><th>Раздел</th><th class="num">Подписано, шт</th><th class="num">Сумма</th><th class="num">Не подписано, шт</th><th class="num">Сумма</th></tr></thead>'
               f'<tbody>{summary_rows}<tr><td><b>Всего</b></td><td class="num"><b>{n_signed}</b></td><td class="num"><b>{money(total_signed)}</b></td><td class="num"><b>{n_unsigned}</b></td>'
               f'<td class="num"><b>{money(total_unsigned)}</b></td></tr></tbody></table>')
    sections = ''
    for g in groups:
        if not g['signed'] and not g['unsigned']:
            continue
        part = f'<h2 style="margin-top:18px">{esc(g["title"])}</h2>'
        if g['signed']:
            part += f'<p class="muted">Подписанные акты: {len(g["signed"])} на сумму {money(g["signed_sum"])}</p>' + _table(g['signed'], g['section'], True)
        if g['unsigned']:
            part += f'<p class="muted" style="margin-top:10px">Не подписаны: {len(g["unsigned"])} на сумму {money(g["unsigned_sum"])}</p>' + _table(g['unsigned'], g['section'], False)
        sections += part
    body = (f'<h1>Ведомость актов за {esc(st.period_label(year, month))}</h1>{nav}{summary}'
            + (sections or '<p class="muted" style="margin-top:14px">За этот месяц актов нет.</p>'))
    return layout(db, 'Ведомость актов', body, session, 'acts', modules, message, nonce=nonce, app_name=app_name)


def acts_xlsx(db, year, month):
    """Байты Excel-файла ведомости за месяц по всем разделам."""
    fd, path = tempfile.mkstemp(suffix='.xlsx')
    os.close(fd)
    try:
        st.export_all(db, year, month, path)
        with open(path, 'rb') as f:
            return f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
