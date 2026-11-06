"""Оформление веб-доступа: те же цвета, боковое меню и значки, что в окне программы (светлая/тёмная тема и акцентный цвет берутся из настроек)."""
import html
import re

from . import icons, status_icons

NAV = [('Услуги', ['gsv', 'contracts', 'gsn', 'ip', 'fl']), ('Клиенты', ['clients', 'contacts']), ('Юрлица', ['legal_entities', 'smr', 'to', 'le_other']), ('Оплаты и ведомости', ['payments', 'acts']), ('Сервис', ['setup'])]
EXTRA = {'payments': ('Журнал оплат', '/payments', 'estimates'), 'acts': ('Ведомость актов', '/acts', 'docs'), 'setup': ('Ярлык на рабочий стол', '/setup', 'workspace')}
ROLES_TITLE = {'viewer': 'Только просмотр', 'editor': 'Сотрудник'}


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def palette(db):
    from . import theme
    return theme.colors(db.get_setting('is_dark', '0') == '1', db.get_setting('accent_color', '') or ''), db.get_setting('is_dark', '0') == '1'


def css(db):
    c, dark = palette(db)
    return f"""
:root{{--bg:{c['bg']};--panel:{c['panel']};--side:{c['side']};--text:{c['text']};--text2:{c['text2']};--muted:{c['muted']};--line:{c['line']};--border:{c['border']};--hover:{c['hover']};--alt:{c['alt']};
--accent:{c['accent']};--accent-fg:{c['accent_fg']};--accent-hover:{c['accent_hover']};--sel:{c['sel']};--sel-text:{'#fff' if dark else c['accent_fg']};--disabled:{c['disabled']};--danger:{'#F1707B' if dark else '#A4262C'};--ok:{'#4ADE80' if dark else '#15803D'}}}
*{{box-sizing:border-box}}html{{color-scheme:{'dark' if dark else 'light'}}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 Inter,'Segoe UI Variable','Segoe UI','Noto Sans',Arial,sans-serif}}
a{{color:var(--accent-fg)}}
.app{{display:flex;min-height:100vh}}
#side{{width:236px;flex:none;background:var(--side);border-right:1px solid var(--line);padding:14px 10px;position:sticky;top:0;height:100vh;overflow:auto}}
.brand{{display:flex;align-items:center;gap:10px;padding:4px 8px 14px;font-size:17px;font-weight:700;color:var(--text)}}.brand svg{{width:26px;height:26px}}
.sect{{color:var(--muted);font-size:11px;font-weight:600;letter-spacing:1px;padding:12px 10px 3px;text-transform:uppercase}}
.nav{{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:8px;color:var(--text2);text-decoration:none}}.nav:hover{{background:var(--hover);color:var(--text)}}
.nav.on{{background:var(--sel);color:var(--sel-text);font-weight:600}}.nav svg{{width:18px;height:18px;flex:none}}
.who{{margin-top:16px;padding:10px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}}.who button{{margin-top:6px}}
#content{{flex:1;min-width:0}}.top{{display:none}}
main{{max-width:1100px;margin:0 auto;padding:22px 24px 40px}}h1{{font-size:21px;margin:2px 0 14px;font-weight:600}}h2{{font-size:15px;margin:0 0 6px;font-weight:600}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}}
.bar{{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}}.bar input[type=search]{{flex:1;min-width:180px}}
input[type=text],input[type=password],input[type=date],input[type=search],textarea,select{{width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--panel);color:var(--text);font:inherit}}
input:focus,textarea:focus,select:focus{{outline:2px solid var(--accent);outline-offset:-1px}}input:disabled,textarea:disabled,select:disabled{{background:var(--alt);color:var(--disabled)}}
textarea{{min-height:76px;resize:vertical}}label.l{{display:block;font-weight:600;margin:10px 0 4px;color:var(--text2)}}label.l i{{color:var(--danger);font-style:normal}}.hint{{color:var(--muted);font-size:12px;margin-top:3px}}
.btn{{display:inline-block;padding:8px 16px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer;text-decoration:none}}.btn:hover{{background:var(--accent-hover)}}
.btn.sec{{background:transparent;color:var(--accent-fg);border-color:var(--border)}}.btn.sec:hover{{background:var(--hover)}}.btn.sm{{padding:4px 10px;font-weight:500}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}}
th{{text-align:left;font-weight:600;color:var(--muted);font-size:12px;padding:9px 12px;background:var(--alt);border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:0;border-bottom:1px solid var(--line);vertical-align:top}}td a.c{{display:block;padding:9px 12px;color:var(--text);text-decoration:none}}tr:hover td{{background:var(--hover)}}tr:last-child td{{border-bottom:0}}
.chip{{display:inline-block;padding:1px 9px;border-radius:999px;border:1px solid var(--border);font-size:12px;margin:0 4px 2px 0;color:var(--text2)}}
.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:baseline}}
.muted{{color:var(--muted);font-size:13px}}.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:0 16px}}
.chk{{display:inline-flex;gap:8px;align-items:center;margin:10px 18px 2px 0;font-weight:500}}.chk input{{width:18px;height:18px;accent-color:var(--accent)}}
.tabs{{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}}.tabs a{{padding:7px 14px;border-radius:8px;text-decoration:none;color:var(--text2);border:1px solid var(--line);background:var(--panel)}}.tabs a.on{{background:var(--sel);color:var(--sel-text);font-weight:600;border-color:transparent}}
.plain td{{padding:8px 12px}}.plain td a{{color:var(--accent-fg)}}td.num,th.num{{text-align:right;white-space:nowrap}}.neg{{color:var(--danger)}}.pos{{color:var(--ok)}}
.sum{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}}.sum div{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 14px;min-width:130px}}.sum b{{display:block;font-size:17px}}.sum span{{color:var(--muted);font-size:12px}}
.inline{{display:flex;gap:8px;flex-wrap:wrap;align-items:end}}.inline>div{{flex:1;min-width:120px}}.inline label.l{{margin-top:0}}
.child{{display:grid;gap:8px;margin-bottom:8px;align-items:center;padding-bottom:8px;border-bottom:1px dashed var(--line)}}
.msg{{padding:9px 14px;border-radius:8px;margin-bottom:12px;border:1px solid var(--line)}}.msg.err{{background:{'#3B1F22' if dark else '#FDECEC'};color:var(--danger)}}.msg.ok{{background:{'#12301F' if dark else '#E8F5EC'};color:var(--ok)}}
pre{{white-space:pre-wrap;word-break:break-word;background:var(--alt);border:1px solid var(--line);border-radius:8px;padding:10px;font:13px/1.5 ui-monospace,Consolas,monospace}}
.actions{{position:sticky;bottom:0;background:var(--bg);padding:10px 0;border-top:1px solid var(--line);display:flex;gap:8px;align-items:center}}
.login{{max-width:380px;margin:12vh auto;padding:0 16px}}.login .brand{{justify-content:center;font-size:22px}}
#navtoggle{{display:none}}
@media(max-width:820px){{
 .app{{display:block}}#side{{display:none;position:static;width:auto;height:auto;border-right:0;border-bottom:1px solid var(--line)}}#navtoggle:checked~#side{{display:block}}
 .top{{display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--side);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}}.top label{{cursor:pointer;padding:4px 10px;border:1px solid var(--border);border-radius:8px}}
 main{{padding:14px 14px 30px}}.grid{{grid-template-columns:1fr}}
 table,tbody,tr,td{{display:block}}thead{{display:none}}table{{background:transparent;border:0}}tr{{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:10px;padding:4px 0}}
 td{{border:0}}td a.c{{padding:3px 14px}}td a.c[data-l]:before{{content:attr(data-l)': ';color:var(--muted);font-size:12px}}td:first-child a.c{{font-weight:600;padding-top:8px}}
 .child{{grid-template-columns:1fr 1fr!important}}.child .x{{grid-column:1/3}}
}}
"""


def icon_svg(name, color='currentColor'):
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'<path d="{esc(icons.PATHS.get(name, icons.PATHS["workspace"]))}"/></svg>')


def layout(db, title, body, session=None, active='', modules=None, message='', nonce='', app_name='ПТО'):
    c, _dark = palette(db)
    msg = f'<div class="msg {message[0]}">{esc(message[1])}</div>' if message else ''
    if not session:
        return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
                f'<title>{esc(title)} — {esc(app_name)}</title><style>{css(db)}</style></head><body><div class="login"><div class="brand">{logo(c["accent"])}{esc(app_name)}</div>{msg}{body}</div></body></html>')
    nav = ''
    for section, keys in NAV:
        items = ''.join(f'<a class="nav{" on" if k == active else ""}" href="/m/{esc(k)}">{icon_svg(k)}<span>{esc(modules[k].title)}</span></a>' for k in keys if k in modules)
        items += ''.join(f'<a class="nav{" on" if k == active else ""}" href="{esc(EXTRA[k][1])}">{icon_svg(EXTRA[k][2])}<span>{esc(EXTRA[k][0])}</span></a>' for k in keys if k in EXTRA)
        nav += f'<div class="sect">{esc(section)}</div>{items}'
    who = (f'<div class="who">{esc(session["login"])} · {esc(ROLES_TITLE.get(session["role"], session["role"]))}'
           f'<form method="post" action="/logout"><input type="hidden" name="csrf" value="{esc(session["csrf"])}"><button class="btn sec sm">Выйти</button></form></div>')
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>{esc(title)} — {esc(app_name)}</title><style>{css(db)}</style></head><body><div class="app"><div class="top"><label for="navtoggle">☰ Меню</label><b>{esc(app_name)}</b></div>'
            f'<input type="checkbox" id="navtoggle"><nav id="side"><div class="brand">{logo(c["accent"])}{esc(app_name)}</div>{nav}{who}</nav>'
            f'<div id="content"><main>{msg}{body}</main></div></div>'
            f'<script nonce="{nonce}">document.addEventListener("submit",function(e){{var m=e.target.getAttribute("data-confirm");if(m&&!confirm(m))e.preventDefault()}});</script></body></html>')


def logo(color):
    return (f'<svg viewBox="0 0 40 40" aria-hidden="true"><rect x="2" y="2" width="36" height="36" rx="9" fill="{esc(color)}"/>'
            '<path d="M11 28V12h8a5 5 0 0 1 0 10h-8" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def login_page(db, message='', app_name='ПТО'):
    body = ('<div class="panel"><h1>Вход</h1><form method="post" action="/login" autocomplete="on"><label class="l">Логин</label><input type="text" name="login" autocomplete="username" autofocus required>'
            '<label class="l">Пароль</label><input type="password" name="password" autocomplete="current-password" required>'
            '<label class="chk"><input type="checkbox" name="remember" value="1" checked> Запомнить меня на этом устройстве (30 дней)</label>'
            '<p><button class="btn">Войти</button></p><p class="muted">Чтобы браузер предложил сохранить пароль, согласитесь на его запрос после входа. Не отмечайте «запомнить» на чужих устройствах.</p></form></div>')
    return layout(db, 'Вход', body, None, message=message, app_name=app_name)


def status_chip(key):
    if key in status_icons.TITLES:
        return f'<span class="chip"><span class="dot" style="background:{esc(status_icons.COLORS.get(key, "#6B7280"))}"></span>{esc(status_icons.TITLES[key])}</span>'
    return f'<span class="chip">{esc(key)}</span>' if key else ''


def list_page(db, module, items, query, session, modules, message='', app_name='ПТО', can_create=False):
    head = ''.join(f'<th>{esc(c)}</th>' for c in module.columns) + '<th></th>'
    rows = ''
    for it in items:
        link = f'/m/{esc(module.key)}/{it["id"]}'
        cells = ''.join(f'<td><a class="c"{"" if i == 0 else f" data-l=\"{esc(module.columns[i])}\""} href="{link}">{esc(v)}</a></td>' for i, v in enumerate(it['cols']))
        chips = ''.join(status_chip(s.strip()) for s in it['statuses'] if s and s.strip())
        extra = f'{chips}<span class="muted">{esc(it["flags"])}</span>'
        phone = (it.get('phone') or '').split(';')[0].strip()
        if phone:
            extra += f' <a href="tel:{esc(re.sub(r"[^0-9+]", "", phone))}">{esc(phone)}</a>'
        rows += f'<tr>{cells}<td><a class="c" href="{link}">{extra}</a></td></tr>'
    new = f'<a class="btn" href="/m/{esc(module.key)}/new">+ Добавить</a>' if can_create else ''
    body = (f'<h1>{esc(module.title)}</h1><form class="bar" method="get" action="/m/{esc(module.key)}"><input type="search" name="q" value="{esc(query)}" placeholder="Поиск…"><button class="btn">Найти</button>{new}</form>'
            + (f'<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>' if items else '<p class="muted">Ничего не найдено.</p>') + f'<p class="muted">Показано: {len(items)}</p>')
    return layout(db, module.title, body, session, module.key, modules, message, app_name=app_name)


def _field(f, value, db, disabled):
    name = f'f_{f.name}'
    dis = ' disabled' if (disabled or f.readonly) else ''
    label = f'<label class="l" for="{name}">{esc(f.label)}{" <i>*</i>" if f.required else ""}</label>'
    hint = f'<div class="hint">{esc(f.hint)}</div>' if f.hint else ''
    if f.kind == 'check':
        return f'<label class="chk"><input type="checkbox" name="{name}" value="1"{" checked" if value else ""}{dis}> {esc(f.label)}</label>'
    if f.kind == 'multi':
        chosen = {str(x) for x in (value or [])}
        boxes = ''.join(f'<label class="chk"><input type="checkbox" name="{name}" value="{esc(k)}"{" checked" if str(k) in chosen else ""}{dis}> {esc(t)}</label>' for k, t in (f.choices(db) if callable(f.choices) else f.choices))
        return f'<div style="grid-column:1/-1">{label}<div>{boxes or "<span class=muted>Справочник пуст</span>"}</div></div>'
    if f.kind in ('textarea', 'phones'):
        return f'<div style="grid-column:1/-1">{label}<textarea id="{name}" name="{name}"{dis}>{esc(value)}</textarea>{hint}</div>'
    if f.kind == 'select':
        choices = list(f.choices(db)) if callable(f.choices) else list(f.choices or [])
        if str(value or '') not in {str(k) for k, _ in choices} and value not in ('', None):
            choices.append((value, str(value)))
        opts = ''.join(f'<option value="{esc(k)}"{" selected" if str(k) == str(value or "") else ""}>{esc(t)}</option>' for k, t in choices)
        return f'{label}<select id="{name}" name="{name}"{dis}>{opts}</select>{hint}'
    typ = 'date' if f.kind == 'date' else 'text'
    mode = ' inputmode="decimal"' if f.kind == 'number' else ''
    return f'{label}<input type="{typ}" id="{name}" name="{name}" value="{esc(value)}"{mode}{dis}>{hint}'


def _child_row(child, i, row, db, disabled, blank):
    cols = ' '.join('1fr' for _ in child.fields) + ' auto'
    cells = ''
    for f in child.fields:
        n = f'c_{child.key}_{f.name}_{i}'
        v = row.get(f.name, '')
        dis = ' disabled' if disabled else ''
        if f.kind == 'check':
            cells += f'<label class="chk" style="margin:0"><input type="checkbox" name="{n}" value="1"{" checked" if v else ""}{dis}> {esc(f.label)}</label>'
        elif f.kind == 'select':
            choices = list(f.choices(db)) if callable(f.choices) else list(f.choices or [])
            if v and str(v) not in {str(k) for k, _ in choices}:
                choices.append((v, str(v)))
            opts = ('<option value=""></option>' if blank else '') + ''.join(f'<option value="{esc(k)}"{" selected" if str(k) == str(v) else ""}>{esc(t)}</option>' for k, t in choices)
            cells += f'<select name="{n}" aria-label="{esc(f.label)}"{dis}>{opts}</select>'
        else:
            typ = 'date' if f.kind == 'date' else 'text'
            cells += f'<input type="{typ}" name="{n}" value="{esc(v)}" placeholder="{esc(f.label)}" aria-label="{esc(f.label)}"{dis}>'
    rid = row.get('id') or ''
    tail = (f'<label class="x muted"><input type="checkbox" name="c_{child.key}_del_{i}" value="1"{" disabled" if disabled else ""}> удалить</label>' if rid else '<span class="x"></span>')
    return f'<div class="child" style="grid-template-columns:{cols}"><input type="hidden" name="c_{child.key}_id_{i}" value="{esc(rid)}">{cells}{tail}</div>'


def card_page(db, module, cid, values, child_rows, session, modules, nonce, message='', locked=None, copy='', app_name='ПТО', extra=''):
    editable = session['role'] == 'editor' and not locked
    disabled = not editable
    new = not cid
    groups, order = {}, []
    for f in module.fields:
        if f.new_only and not new:
            continue
        if f.group not in groups:
            groups[f.group] = []
            order.append(f.group)
        groups[f.group].append(f)
    panels = ''
    for g in order:
        grid = ''
        for f in groups[g]:
            part = _field(f, values.get(f.name, ''), db, disabled or (f.name in ('client_name', 'phones', 'client_address', 'passport', 'passport_date', 'passport_issuer') and values.get('_legal')))
            grid += part if f.kind in ('check', 'textarea', 'phones', 'multi') else f'<div>{part}</div>'
        panels += f'<div class="panel"><h2>{esc(g)}</h2><div class="grid">{grid}</div></div>'
    for ch in module.children:
        rows = child_rows.get(ch.key, [])
        html_rows = ''.join(_child_row(ch, i, r, db, disabled, False) for i, r in enumerate(rows))
        n = len(rows)
        for j in range(n, n + ch.add_blank):
            html_rows += _child_row(ch, j, {}, db, disabled, True)
        panels += f'<div class="panel"><h2>{esc(ch.title)}</h2><input type="hidden" name="c_{ch.key}_count" value="{n + ch.add_blank}">{html_rows}</div>'
    notes = ''
    if locked:
        notes += f'<div class="msg err">Карточку сейчас правит {esc(locked)}. Изменения запрещены, пока её не закроют.</div>'
    if values.get('_legal') and module.key == 'contracts':
        notes += f'<p class="muted">Заказчик — юрлицо «{esc(values.get("_party"))}»: данные клиента правятся в программе.</p>'
    chips = ''.join(f'<span class="chip" style="border-color:{esc(color)}">{esc(name)}</span>' for name, color in values.get('_statuses', [])) + ''.join(status_chip(k) for k in values.get('_chip_keys', []))
    save = '<button class="btn">Сохранить</button>' if editable else '<span class="muted">Только просмотр.</span>'
    action = f'/m/{esc(module.key)}/{cid or "new"}'
    form = (f'<form method="post" action="{action}"><input type="hidden" name="csrf" value="{esc(session["csrf"])}">{panels}<div class="actions">{save}'
            f'<a class="btn sec" href="/m/{esc(module.key)}">К списку</a></div></form>')
    copy_block = ''
    script = ''
    if copy:
        copy_block = ('<div class="panel"><h2>Данные клиента для копирования</h2><pre id="copy">' + esc(copy) + '</pre><p><button class="btn sec" id="copybtn" type="button">Скопировать в буфер обмена</button> '
                      '<span id="copied" class="muted"></span></p></div>')
        script = (f'<script nonce="{nonce}">document.getElementById("copybtn").onclick=function(){{var t=document.getElementById("copy").innerText,m=document.getElementById("copied");'
                  f'function ok(){{m.textContent="Скопировано"}}function fb(){{var a=document.createElement("textarea");a.value=t;document.body.appendChild(a);a.select();try{{document.execCommand("copy");ok()}}catch(e){{m.textContent="Выделите текст и скопируйте вручную"}}document.body.removeChild(a)}}'
                  f'if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(t).then(ok,fb)}}else{{fb()}}}}</script>')
    title = values.get('_title') or (module.title + ' — новая запись')
    dossier = values.get('_dossier') or ((module.dossier, cid) if module.dossier and cid else None)
    dlink = f'<p><a class="btn" href="/dossier/{esc(dossier[0])}/{dossier[1]}">Досье клиента: договоры и оплаты</a></p>' if dossier and dossier[1] else ''
    body = f'<h1>{esc(title)}</h1>{dlink}<div>{chips}</div>{notes}{extra}{form}{copy_block}{script}'
    return layout(db, title, body, session, module.key, modules, message, nonce=nonce, app_name=app_name)
