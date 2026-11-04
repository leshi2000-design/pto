"""Веб-доступ: оплаты. Те же книги платежей и расчёты, что в окне программы (payments_domain, dossier_client): оплаты договора, досье клиента (договоры, сметы, чеки, оплаты, заметки, задачи), журнал оплат за период."""
import sqlite3
import urllib.parse
from datetime import date
from decimal import Decimal, InvalidOperation

from . import dossier_client as dc, payments_domain as pd
from .web_pages import esc, layout

OWNER_MODULE = {'contracts': 'contracts', 'gsv_projects': 'gsv', 'gsn_projects': 'gsn', 'smr_contracts': 'smr', 'to_contracts': 'to', 'ip_contracts': 'ip', 'fl_contracts': 'fl', 'le_contracts': 'le_other'}
TABS = (('contracts', 'Договоры'), ('estimates', 'Сметы'), ('sales', 'Чеки'), ('payments', 'Оплаты'), ('notes', 'Заметки'), ('tasks', 'Задачи'))


def money(x):
    try:
        return f'{Decimal(str(x or 0)):,.2f}'.replace(',', ' ')
    except InvalidOperation:
        return '0.00'


def parse_amount(text):
    try:
        value = Decimal(str(text or '').replace(' ', '').replace(' ', '').replace(',', '.'))
    except InvalidOperation:
        raise ValueError('Введите сумму числом') from None
    return value


def _cls(value):
    return 'neg' if Decimal(str(value or 0)) > 0 else 'pos'


def _confirm_form(action, fields, text, button, csrf, back):
    hidden = ''.join(f'<input type="hidden" name="{esc(k)}" value="{esc(v)}">' for k, v in dict(fields, action=action, back=back, csrf=csrf).items())
    return f'<form method="post" action="/pay" data-confirm="{esc(text)}" style="margin:0">{hidden}<button class="btn sec sm">{esc(button)}</button></form>'


def add_form(owner, rid, csrf, back, debt=None, label='Внести оплату', nonce=''):
    fid = f'amt_{owner}_{rid}'
    fill = (f'<button type="button" class="btn sec sm" data-fill="{fid}" data-value="{max(Decimal(0), Decimal(str(debt))):.2f}">Заполнить остаток</button>' if debt is not None else '')
    return (f'<form method="post" action="/pay" class="inline"><input type="hidden" name="csrf" value="{esc(csrf)}"><input type="hidden" name="action" value="add"><input type="hidden" name="owner" value="{esc(owner)}">'
            f'<input type="hidden" name="rid" value="{rid}"><input type="hidden" name="back" value="{esc(back)}">'
            f'<div><label class="l">Дата</label><input type="date" name="date" value="{date.today().isoformat()}" required></div>'
            f'<div><label class="l">Сумма</label><input type="text" id="{fid}" name="amount" inputmode="decimal" placeholder="0.00" required></div>'
            f'<div style="flex:2"><label class="l">Примечание</label><input type="text" name="note" placeholder="Примечание к платежу"></div>'
            f'<div style="flex:none"><button class="btn">{esc(label)}</button> {fill}</div></form>')


FILL_SCRIPT = ('document.addEventListener("click",function(e){var b=e.target.closest("[data-fill]");if(!b)return;var i=document.getElementById(b.getAttribute("data-fill"));if(i){i.value=b.getAttribute("data-value");i.focus()}});')


def payments_panel(db, owner, rid, back, session, nonce, editable=True):
    """Блок «Оплаты» в карточке договора: итоги, история, внесение и удаление платежа."""
    try:
        s = pd.summary(db, owner, rid)
        history = pd.history(db, owner, rid)
    except ValueError:
        return ''
    can = editable and session['role'] == 'editor'
    rows = ''
    for pid, day, amount, note in history:
        action = _confirm_form('delete', dict(pid=pid), 'Удалить ошибочно внесённый платёж?', 'Удалить', session['csrf'], back) if can else ''
        rows += f'<tr><td>{esc(day)}</td><td class="num">{money(amount)}</td><td>{esc(note or "")}</td><td>{action}</td></tr>'
    info = ('Общий учёт со сметой №' + str(s['estimate_id']) + '. ') if s['estimate_id'] else 'Самостоятельный договор. '
    if s['opening']:
        info += f'Включён ранее учтённый остаток оплаты: {money(s["opening"])}.'
    summary = (f'<div class="sum"><div><span>Сумма</span><b>{money(s["total"])}</b></div><div><span>Оплачено</span><b class="pos">{money(s["paid"])}</b></div>'
               f'<div><span>Остаток</span><b class="{_cls(s["debt"])}">{money(s["debt"])}</b></div></div>')
    table = (f'<table class="plain"><thead><tr><th>Дата</th><th class="num">Сумма</th><th>Примечание</th><th></th></tr></thead><tbody>{rows}</tbody></table>' if rows else '<p class="muted">Оплат пока нет.</p>')
    form = add_form(owner, rid, session['csrf'], back, s['debt'], nonce=nonce) if can else '<p class="muted">Только просмотр.</p>'
    return f'<div class="panel" id="pay"><h2>Оплаты</h2><p class="muted">{esc(info)}</p>{summary}{table}<div style="margin-top:12px">{form}</div></div><script nonce="{nonce}">{FILL_SCRIPT}</script>'


def client_back(kind, cid, tab):
    return f'/dossier/{kind}/{cid}?tab={tab}'


def dossier_page(db, kind, cid, tab, session, modules, nonce, message='', app_name='ПТО'):
    d = dc.client_dossier(db, kind, cid)
    t = d['totals']
    tab = tab if tab in dict(TABS) else 'contracts'
    back = client_back(kind, cid, tab)
    info = d['info']
    head = (f'<h1>Досье клиента: {esc(info["name"])}</h1><p class="muted">{" · ".join(esc(x) for x in info["lines"])}</p>'
            f'<div class="sum"><div><span>Договоров</span><b>{t["contracts"]}</b></div><div><span>Смет</span><b>{t["estimates"]}</b></div><div><span>На сумму</span><b>{money(t["amount"])}</b></div>'
            f'<div><span>Оплачено</span><b class="pos">{money(t["paid"])}</b></div><div><span>Долг</span><b class="{_cls(t["debt"])}">{money(t["debt"])}</b></div>'
            f'<div><span>Без подписи</span><b>{t["unsigned"]}</b></div></div>')
    counts = dict(contracts=t['contracts'], estimates=t['estimates'], sales=len(d['sales']), payments=len(d['payments']), notes=t['notes'], tasks=t['tasks'])
    tabs = '<div class="tabs">' + ''.join(f'<a class="{"on" if k == tab else ""}" href="{client_back(kind, cid, k)}">{esc(title)} ({counts[k]})</a>' for k, title in TABS) + '</div>'
    can = session['role'] == 'editor'
    if tab == 'contracts':
        rows = ''.join(f'<tr><td>{esc(c["section"])}</td><td><a href="/m/{OWNER_MODULE[c["table"]]}/{c["id"]}#pay">{esc(c["number"] or "б/н")}</a></td><td>{esc(c["date"])}</td><td>{esc(c["object"])}</td>'
                       f'<td class="num">{money(c["amount"])}</td><td class="num pos">{money(c["paid"])}</td><td class="num {_cls(c["debt"])}">{money(c["debt"])}</td><td>{"✔" if c["signed"] else ""}</td></tr>' for c in d['contracts'])
        body = (f'<table class="plain"><thead><tr><th>Раздел</th><th>№</th><th>Дата</th><th>Объект</th><th class="num">Сумма</th><th class="num">Оплачено</th><th class="num">Долг</th><th>Подписан</th></tr></thead><tbody>{rows}</tbody></table>'
                if rows else '<p class="muted">Договоров нет.</p>') + '<p class="muted">Нажмите номер договора — откроется карточка с оплатами.</p>'
    elif tab == 'estimates':
        rows = ''.join(f'<tr><td>{esc(e["title"])}</td><td>{esc(e["date"])}</td><td class="num">{money(e["total"])}</td><td class="num pos">{money(e["paid"])}</td><td class="num {_cls(e["debt"])}">{money(e["debt"])}</td><td>{esc(e["contract"] or "без договора")}</td></tr>' for e in d['estimates'])
        body = (f'<table class="plain"><thead><tr><th>Смета</th><th>Дата</th><th class="num">Итого</th><th class="num">Оплачено</th><th class="num">Долг</th><th>Договор</th></tr></thead><tbody>{rows}</tbody></table>'
                if rows else '<p class="muted">Смет нет.</p>') + '<p class="muted">Сметы в веб-версии только для просмотра; оплаты по смете без договора — на вкладке «Оплаты».</p>'
    elif tab == 'sales':
        rows = ''
        for s in d['sales']:
            ops = ''
            if can:
                ops = (add_form('client_sales', s['id'], session['csrf'], back, s['debt'], 'Оплата', nonce) + _confirm_form('sale_delete', dict(sid=s['id']), 'Удалить продажу по чеку?', 'Удалить продажу', session['csrf'], back))
            rows += (f'<tr><td>{esc(s["date"])}</td><td>{esc(s["title"])}<div class="muted">{esc(s["note"])}</div></td><td>{esc(s["receipt"])}</td><td class="num">{money(s["amount"])}</td>'
                     f'<td class="num pos">{money(s["paid"])}</td><td class="num {_cls(s["debt"])}">{money(s["debt"])}</td></tr>' + (f'<tr><td colspan="6">{ops}</td></tr>' if ops else ''))
        new = ''
        if can:
            new = (f'<div class="panel"><h2>Добавить продажу по чеку</h2><form method="post" action="/pay"><input type="hidden" name="csrf" value="{esc(session["csrf"])}"><input type="hidden" name="action" value="sale_add">'
                   f'<input type="hidden" name="kind" value="{esc(kind)}"><input type="hidden" name="cid" value="{cid}"><input type="hidden" name="back" value="{esc(back)}"><div class="grid">'
                   f'<div><label class="l">Что куплено</label><input type="text" name="title" required></div><div><label class="l">№ чека</label><input type="text" name="receipt"></div>'
                   f'<div><label class="l">Сумма</label><input type="text" name="amount" inputmode="decimal" required></div><div><label class="l">Дата</label><input type="date" name="date" value="{date.today().isoformat()}" required></div></div>'
                   f'<label class="l">Примечание</label><input type="text" name="note"><label class="chk"><input type="checkbox" name="paid_now" value="1"> Сразу оплачено полностью</label><p><button class="btn">Добавить</button></p></form></div>')
        body = (f'<table class="plain"><thead><tr><th>Дата</th><th>Что куплено</th><th>№ чека</th><th class="num">Сумма</th><th class="num">Оплачено</th><th class="num">Долг</th></tr></thead><tbody>{rows}</tbody></table>'
                if rows else '<p class="muted">Продаж по чеку нет.</p>') + new
    elif tab == 'payments':
        rows = ''.join(f'<tr><td>{esc(p["date"])}</td><td class="num">{money(p["amount"])}</td><td>{esc(p["section"])}</td><td>{esc(p["label"])}</td><td>{esc(p["note"])}</td>'
                       f'<td>{_confirm_form("delete", dict(pid=p["id"]), "Удалить ошибочно внесённый платёж?", "Удалить", session["csrf"], back) if can else ""}</td></tr>' for p in d['payments'])
        body = (f'<table class="plain"><thead><tr><th>Дата</th><th class="num">Сумма</th><th>Раздел</th><th>Договор / смета</th><th>Примечание</th><th></th></tr></thead><tbody>{rows}</tbody></table>'
                if rows else '<p class="muted">Оплат нет.</p>') + '<p class="muted">Новая оплата вносится в карточке договора (блок «Оплаты») или на вкладке «Чеки».</p>'
    elif tab == 'notes':
        rows = ''.join(f'<tr><td>{esc(n["date"])}</td><td>{esc(n["title"])}</td><td>{esc(n["link"])}</td></tr>' for n in d['notes'])
        body = f'<table class="plain"><thead><tr><th>Дата</th><th>Заметка</th><th>Привязка</th></tr></thead><tbody>{rows}</tbody></table>' if rows else '<p class="muted">Заметок нет.</p>'
    else:
        rows = ''.join(f'<tr><td>{esc(x["title"])}</td><td>{esc(x["status"])}</td><td>{esc(x["due"])}</td><td>{esc(x["link"])}</td></tr>' for x in d['tasks'] if not x['archived'])
        body = f'<table class="plain"><thead><tr><th>Задача</th><th>Статус</th><th>Срок</th><th>Привязка</th></tr></thead><tbody>{rows}</tbody></table>' if rows else '<p class="muted">Открытых задач нет.</p>'
    back_link = f'<p><a class="btn sec" href="/m/{"clients" if kind == "person" else "legal_entities"}/{cid}">← Карточка клиента</a></p>'
    page = head + tabs + body + back_link + f'<script nonce="{nonce}">{FILL_SCRIPT}</script>'
    return layout(db, 'Досье клиента', page, session, 'clients' if kind == 'person' else 'legal_entities', modules, message, nonce=nonce, app_name=app_name)


def report_page(db, start, end, section, session, modules, nonce, message='', app_name='ПТО'):
    rows, total = '', Decimal(0)
    try:
        data = pd.report(db, start, end, section)
    except ValueError as e:
        data, message = [], ('err', str(e))
    for r in data:
        total += Decimal(str(r['amount']))
        rows += (f'<tr><td>{esc(r["date"])}</td><td class="num">{money(r["amount"])}</td><td>{esc(r["section"])}</td><td>{esc(r["number"])}</td><td>{esc(r["client_name"])}</td><td>{esc(r["object_name"])}</td><td>{esc(r["note"])}</td></tr>')
    opts = '<option value="">Все разделы</option>' + ''.join(f'<option value="{esc(k)}"{" selected" if k == section else ""}>{esc(v[1])}</option>' for k, v in pd.OWNERS.items() if k != 'estimates') \
        + f'<option value="estimates"{" selected" if section == "estimates" else ""}>Сметы</option>'
    form = (f'<form class="bar" method="get" action="/payments"><input type="date" name="start" value="{esc(start)}"><input type="date" name="end" value="{esc(end)}"><select name="section" style="max-width:260px">{opts}</select>'
            f'<button class="btn">Показать</button></form>')
    body = (f'<h1>Журнал оплат</h1>{form}<div class="sum"><div><span>Платежей</span><b>{len(data)}</b></div><div><span>Сумма за период</span><b class="pos">{money(total)}</b></div></div>'
            + (f'<table class="plain"><thead><tr><th>Дата</th><th class="num">Сумма</th><th>Раздел</th><th>№</th><th>Клиент</th><th>Объект</th><th>Примечание</th></tr></thead><tbody>{rows}</tbody></table>' if rows else '<p class="muted">За период оплат нет.</p>'))
    return layout(db, 'Журнал оплат', body, session, 'payments', modules, message, nonce=nonce, app_name=app_name)


def handle_post(db, form):
    """Действия с оплатами и чеками. Возвращает текст успеха; ValueError — понятная ошибка."""
    action = form.get('action')
    try:
        if action == 'add':
            owner, rid = form.get('owner'), int(form.get('rid') or 0)
            if owner not in pd.OWNERS:
                raise ValueError('Неизвестный раздел оплаты')
            pd.add(db, owner, rid, parse_amount(form.get('amount')), form.get('date') or '', str(form.get('note') or '').strip())
            return 'Оплата внесена.'
        if action == 'delete':
            pid = int(form.get('pid') or 0)
            if not db.fetchone('SELECT 1 FROM payments WHERE id=?', (pid,)):
                raise ValueError('Платёж не найден')
            pd.remove(db, pid)
            return 'Платёж удалён.'
        if action == 'sale_add':
            kind = form.get('kind')
            if kind not in ('person', 'legal'):
                raise ValueError('Неизвестный тип клиента')
            dc.save_sale(db, kind, int(form.get('cid') or 0), dict(title=form.get('title'), amount=parse_amount(form.get('amount')), date=form.get('date'), receipt=form.get('receipt'), note=form.get('note')),
                         paid_now=bool(form.get('paid_now')))
            return 'Продажа добавлена.'
        if action == 'sale_delete':
            dc.delete_sale(db, int(form.get('sid') or 0))
            return 'Продажа удалена.'
    except (sqlite3.IntegrityError, sqlite3.OperationalError) as e:
        raise ValueError(str(e)) from None
    except (TypeError, OverflowError):
        raise ValueError('Проверьте введённые данные') from None
    raise ValueError('Неизвестное действие')


def back_url(back, kind, text):
    back = back if (back or '').startswith('/') and not (back or '').startswith('//') and '\\' not in back else '/m/contracts'
    sep = '&' if '?' in back else '?'
    anchor = ''
    if '#' in back:
        back, anchor = back.split('#', 1)
        anchor = '#' + anchor
    return f'{back}{sep}{kind}={urllib.parse.quote(text)}{anchor}'
