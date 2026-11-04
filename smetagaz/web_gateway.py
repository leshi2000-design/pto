"""Веб-доступ к базе (прототип): карточки договоров «Монтаж ГСВ» в браузере компьютера, планшета или телефона из той же сети.

Работает внутри программы (пока она открыта на компьютере с базой): отдельный поток с HTTPS-сервером (самоподписанный сертификат) на стандартной библиотеке.
Вход — по логину и паролю веб-пользователей (роль «Только просмотр» или «Сотрудник»); пароли хранятся только в виде PBKDF2-хэша, сессия — cookie HttpOnly + SameSite=Strict,
правка защищена CSRF-токеном и блокировкой карточки (если карточка открыта в программе, веб-правка отклоняется). Интернет не используется: сервер слушает только локальную сеть."""
import hashlib
import hmac
import html
import http.server
import logging
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.parse
from datetime import datetime

from . import web_cards as wc

SESSION_IDLE = 8 * 3600
LOGIN_FAILS, LOGIN_WINDOW, LOGIN_LOCK = 5, 300, 60
PBKDF2_ROUNDS = 200_000
MAX_BODY = 64 * 1024
ROLES = {'viewer': 'Только просмотр', 'editor': 'Сотрудник (может править)'}


# --- ПОЛЬЗОВАТЕЛИ ВЕБ-ДОСТУПА ------------------------------------------------------------------------

def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS web_users(id INTEGER PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE, role TEXT NOT NULL DEFAULT 'viewer',
        salt TEXT NOT NULL, hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created TEXT DEFAULT '', last_login TEXT DEFAULT '')""")


def _hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def add_user(db, login, password, role='viewer'):
    login = str(login or '').strip()
    if not re.fullmatch(r'[\w.\-]{2,40}', login):
        raise ValueError('Логин — 2–40 символов: буквы, цифры, точка, дефис, подчёркивание')
    if role not in ROLES:
        raise ValueError('Неизвестная роль')
    if len(password or '') < 8:
        raise ValueError('Пароль — не короче 8 символов')
    if db.fetchone('SELECT 1 FROM web_users WHERE login=?', (login,)):
        raise ValueError('Такой логин уже есть')
    salt = secrets.token_hex(16)
    return db.execute('INSERT INTO web_users(login,role,salt,hash,created) VALUES(?,?,?,?,?)', (login, role, salt, _hash(password, salt), datetime.now().isoformat(timespec='seconds'))).lastrowid


def set_password(db, uid, password):
    if len(password or '') < 8:
        raise ValueError('Пароль — не короче 8 символов')
    salt = secrets.token_hex(16)
    db.execute('UPDATE web_users SET salt=?,hash=? WHERE id=?', (salt, _hash(password, salt), uid))


def set_user(db, uid, role=None, active=None):
    if role is not None:
        if role not in ROLES:
            raise ValueError('Неизвестная роль')
        db.execute('UPDATE web_users SET role=? WHERE id=?', (role, uid))
    if active is not None:
        db.execute('UPDATE web_users SET active=? WHERE id=?', (int(bool(active)), uid))


def delete_user(db, uid):
    db.execute('DELETE FROM web_users WHERE id=?', (uid,))


def users(db):
    return db.fetchall('SELECT id,login,role,active,created,last_login FROM web_users ORDER BY login')


def verify(db, login, password):
    """-> (id, роль) или None. Время проверки не зависит от того, существует ли логин."""
    row = db.fetchone('SELECT id,role,salt,hash,active FROM web_users WHERE login=?', (str(login or '').strip(),))
    salt = row[2] if row else '00' * 16
    ok = hmac.compare_digest(_hash(str(password or ''), salt), row[3] if row else '0' * 64)
    if row and ok and row[4]:
        db.execute('UPDATE web_users SET last_login=? WHERE id=?', (datetime.now().isoformat(timespec='seconds'), row[0]))
        return row[0], row[1]
    return None


# --- ОФОРМЛЕНИЕ ----------------------------------------------------------------------------------------

CSS = """
:root{--bg:#f4f6f8;--panel:#fff;--text:#1f2933;--muted:#667085;--line:#d9dee5;--accent:#0f6b5f;--accent-text:#fff;--danger:#b42318;--ok:#15803d}
@media (prefers-color-scheme:dark){:root{--bg:#14181c;--panel:#1d2329;--text:#e6e9ec;--muted:#9aa4ae;--line:#2f3841;--accent:#3db2a3;--accent-text:#06201c;--danger:#f1707b;--ok:#4ade80}}
a{color:var(--accent)}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 system-ui,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0}
header b{font-size:18px}header .sp{flex:1}header a,header button{color:var(--accent);text-decoration:none;background:none;border:0;font:inherit;cursor:pointer}
main{max-width:900px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0 14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:12px}
.row a.item{display:block;color:inherit;text-decoration:none}.row .t{font-weight:600}.muted{color:var(--muted);font-size:14px}
.chip{display:inline-block;padding:1px 9px;border-radius:999px;border:1px solid var(--line);font-size:13px;margin:2px 4px 0 0}
label{display:block;font-weight:600;margin:12px 0 4px}input[type=text],input[type=password],input[type=date],input[type=search],textarea,select{width:100%;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--text);font:inherit}
textarea{min-height:84px}.btn{display:inline-block;padding:12px 18px;border-radius:10px;border:1px solid var(--accent);background:var(--accent);color:var(--accent-text);font:inherit;font-weight:600;cursor:pointer;text-decoration:none}
.btn.sec{background:transparent;color:var(--accent)}.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 14px}@media(max-width:640px){.grid{grid-template-columns:1fr}}
.eq{display:grid;grid-template-columns:1.1fr 1.4fr 1.2fr 1.2fr auto;gap:8px;margin-bottom:8px;align-items:center}@media(max-width:640px){.eq{grid-template-columns:1fr 1fr}.eq .x{grid-column:1/3}}
.msg{padding:10px 14px;border-radius:10px;margin-bottom:12px}.msg.err{background:#fee4e2;color:#7a271a}.msg.ok{background:#dcfae6;color:#085d3a}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;font:15px/1.5 ui-monospace,Consolas,monospace}
.checks label{display:inline-flex;gap:8px;align-items:center;margin-right:18px;font-weight:500}.checks input{width:20px;height:20px}
"""


def esc(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def layout(title, body, session=None, nonce='', message=''):
    nav = ''
    if session:
        nav = (f'<span class="muted">{esc(session["login"])} · {esc(ROLES.get(session["role"], session["role"]))}</span>'
               f'<form method="post" action="/logout" style="margin:0"><input type="hidden" name="csrf" value="{esc(session["csrf"])}"><button>Выйти</button></form>')
    box = f'<div class="msg {message[0]}">{esc(message[1])}</div>' if message else ''
    return (f'<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f'<title>{esc(title)} — ПТО</title><style>{CSS}</style></head><body><header><b>ПТО</b><a href="/contracts">Договоры</a><span class="sp"></span>{nav}</header>'
            f'<main>{box}{body}</main></body></html>')


def login_page(message=''):
    body = ('<div class="card"><h1>Вход в ПТО</h1><form method="post" action="/login" autocomplete="on"><label>Логин</label><input type="text" name="login" autocomplete="username" autofocus required>'
            '<label>Пароль</label><input type="password" name="password" autocomplete="current-password" required><p><button class="btn">Войти</button></p></form></div>')
    return layout('Вход', body, None, message=message)


def list_page(items, query, session, message=''):
    rows = ''
    for c in items:
        chips = ''.join(f'<span class="chip">{esc(s.strip())}</span>' for s in c['statuses'].split(',') if s.strip())
        flags = ('✔ договор ' if c['signed'] else '') + ('✔ акт' if c['act_signed'] else '')
        phone = f' · <a href="tel:{esc(re.sub(r"[^0-9+]", "", c["phone"].split(";")[0]))}">{esc(c["phone"].split(";")[0])}</a>' if c['phone'] else ''
        rows += (f'<div class="card row"><a class="item" href="/contracts/{c["id"]}"><div class="t">№ {esc(c["number"] or "б/н")} · {esc(c["client"] or "без клиента")}</div>'
                 f'<div class="muted">{esc(c["date"])} · {esc(c["object"])} {esc(c["address"])}</div></a><div class="muted">{flags}{phone}</div><div>{chips}</div></div>')
    body = (f'<h1>Монтаж ГСВ</h1><form method="get" action="/contracts" style="display:flex;gap:8px;margin-bottom:12px"><input type="search" name="q" value="{esc(query)}" placeholder="Номер, клиент, адрес, телефон…">'
            f'<button class="btn">Найти</button></form>{rows or "<p class=muted>Ничего не найдено.</p>"}<p class="muted">Показано: {len(items)}</p>')
    return layout('Договоры', body, session, message=message)


def card_page(card, session, copy, nonce, message='', locked=None):
    editable = session['role'] == 'editor' and not locked
    dis = '' if editable else ' disabled'
    cl = card['client']
    legal_note = f'<p class="muted">Заказчик — юрлицо «{esc(card["party_name"])}»: данные клиента правятся в программе.</p>' if card['legal'] else ''
    cdis = dis if not card['legal'] else ' disabled'
    chips = ''.join(f'<span class="chip" style="border-color:{esc(color)}">{esc(name)}</span>' for name, color in card['statuses'])
    lock_note = f'<div class="msg err">Карточку сейчас правит {esc(locked)}. Изменения запрещены, пока её не закроют.</div>' if locked else ''
    eq_rows = ''
    for i, e in enumerate(card['equipment']):
        opts = ''.join(f'<option value="{esc(k)}"{" selected" if k == e["kind"] else ""}>{esc(k)}</option>' for k in wc.EQUIPMENT_CHOICES + ([e['kind']] if e['kind'] not in wc.EQUIPMENT_CHOICES else []))
        eq_rows += (f'<div class="eq"><input type="hidden" name="eq_id_{i}" value="{e["id"]}"><select name="eq_kind_{i}"{dis}>{opts}</select><input type="text" name="eq_model_{i}" value="{esc(e["model"])}" placeholder="Модель"{dis}>'
                    f'<input type="text" name="eq_serial_{i}" value="{esc(e["serial"])}" placeholder="Серийный номер"{dis}><input type="text" name="eq_note_{i}" value="{esc(e["note"])}" placeholder="Примечание"{dis}>'
                    f'<label class="x"><input type="checkbox" name="eq_del_{i}" value="1"{dis}> удалить</label></div>')
    n = len(card['equipment'])
    for j in range(n, n + 2):
        opts = '<option value=""></option>' + ''.join(f'<option value="{esc(k)}">{esc(k)}</option>' for k in wc.EQUIPMENT_CHOICES)
        eq_rows += (f'<div class="eq"><input type="hidden" name="eq_id_{j}" value=""><select name="eq_kind_{j}"{dis}>{opts}</select><input type="text" name="eq_model_{j}" placeholder="Новое: модель"{dis}>'
                    f'<input type="text" name="eq_serial_{j}" placeholder="Серийный номер"{dis}><input type="text" name="eq_note_{j}" placeholder="Примечание"{dis}><span class="x"></span></div>')
    save = '<p><button class="btn">Сохранить</button></p>' if editable else '<p class="muted">Только просмотр.</p>'
    body = (f'<h1>Договор № {esc(card["number"] or "б/н")} от {esc(card["date"])}</h1><div>{chips}</div>{lock_note}{legal_note}'
            f'<form method="post" action="/contracts/{card["id"]}"><input type="hidden" name="csrf" value="{esc(session["csrf"])}"><input type="hidden" name="eq_count" value="{n + 2}">'
            f'<div class="card"><h1>Клиент</h1><label>ФИО</label><input type="text" name="client_name" value="{esc(cl["name"])}"{cdis}>'
            f'<label>Телефоны (по одному в строке; можно «номер (пояснение)»)</label><textarea name="phones"{cdis}>{esc(wc.phones_to_lines(cl["phone"]))}</textarea>'
            f'<label>Адрес клиента</label><input type="text" name="client_address" value="{esc(cl["address"])}"{cdis}>'
            f'<div class="grid"><div><label>Паспорт: серия, номер</label><input type="text" name="passport" value="{esc(cl["passport"])}"{cdis}></div>'
            f'<div><label>Дата выдачи</label><input type="date" name="passport_date" value="{esc(cl["passport_date"])}"{cdis}></div></div>'
            f'<label>Кем выдан</label><input type="text" name="passport_issuer" value="{esc(cl["passport_issuer"])}"{cdis}></div>'
            f'<div class="card"><h1>Объект</h1><label>Объект</label><input type="text" name="object" value="{esc(card["object"])}"{dis}>'
            f'<label>Адрес объекта</label><input type="text" name="object_address" value="{esc(card["object_address"])}"{dis}>'
            f'<label>Примечание</label><textarea name="notes"{dis}>{esc(card["notes"])}</textarea>'
            f'<p class="checks"><label><input type="checkbox" name="signed" value="1"{" checked" if card["signed"] else ""}{dis}> Договор подписан</label>'
            f'<label><input type="checkbox" name="act_signed" value="1"{" checked" if card["act_signed"] else ""}{dis}> Акт подписан</label></p></div>'
            f'<div class="card"><h1>Оборудование</h1>{eq_rows}</div>{save}</form>'
            f'<div class="card"><h1>Данные клиента для копирования</h1><pre id="copy">{esc(copy)}</pre><p><button class="btn sec" id="copybtn" type="button">Скопировать в буфер обмена</button> <span id="copied" class="muted"></span></p></div>'
            f'<script nonce="{nonce}">document.getElementById("copybtn").onclick=function(){{var t=document.getElementById("copy").innerText,m=document.getElementById("copied");'
            f'function ok(){{m.textContent="Скопировано"}}function fb(){{var a=document.createElement("textarea");a.value=t;document.body.appendChild(a);a.select();try{{document.execCommand("copy");ok()}}catch(e){{m.textContent="Выделите текст и скопируйте вручную"}}document.body.removeChild(a)}}'
            f'if(navigator.clipboard&&window.isSecureContext){{navigator.clipboard.writeText(t).then(ok,fb)}}else{{fb()}}}}</script>')
    return layout('Договор ' + (card['number'] or ''), body, session, message=message)


# --- СЕРВЕР --------------------------------------------------------------------------------------------

class WebGateway:
    def __init__(self, db, host='0.0.0.0', port=8765, cert=None, key=None):
        self.db, self.host, self.port, self.cert, self.key = db, host, int(port), cert, key
        self.sessions = {}
        self.fails = {}
        self.lock = threading.Lock()
        self.httpd = None
        self.thread = None

    # сессии и защита от подбора пароля
    def new_session(self, uid, login, role):
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[token] = dict(uid=uid, login=login, role=role, csrf=secrets.token_urlsafe(16), seen=time.time())
        return token

    def session(self, token):
        with self.lock:
            s = self.sessions.get(token or '')
            if not s:
                return None
            if time.time() - s['seen'] > SESSION_IDLE:
                del self.sessions[token]
                return None
            s['seen'] = time.time()
            return s

    def drop(self, token):
        with self.lock:
            self.sessions.pop(token or '', None)

    def locked_out(self, ip):
        with self.lock:
            recent = [t for t in self.fails.get(ip, []) if time.time() - t < LOGIN_WINDOW]
            self.fails[ip] = recent
            return len(recent) >= LOGIN_FAILS and time.time() - recent[-1] < LOGIN_LOCK

    def failed(self, ip):
        with self.lock:
            self.fails.setdefault(ip, []).append(time.time())

    # запуск и остановка
    def start(self):
        gateway = self

        class Handler(http.server.BaseHTTPRequestHandler):
            server_version = 'PTO'
            sys_version = ''
            protocol_version = 'HTTP/1.1'

            def log_message(self, fmt, *args):
                logging.info('web %s %s', self.client_address[0], fmt % args)

            def do_GET(self):
                gateway.handle(self, 'GET')

            def do_POST(self):
                gateway.handle(self, 'POST')
        self.httpd = http.server.ThreadingHTTPServer((self.host, self.port), Handler)
        self.httpd.daemon_threads = True
        if self.cert and self.key:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(self.cert, self.key)
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={'poll_interval': 0.3}, daemon=True, name='web-gateway')
        self.thread.start()
        return self.port

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    @property
    def https(self):
        return bool(self.cert and self.key)

    # обработка запроса
    def handle(self, h, method):
        nonce = secrets.token_urlsafe(12)
        try:
            self._route(h, method, nonce)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass
        except Exception:
            logging.exception('web gateway error')
            try:
                self._send(h, 500, layout('Ошибка', '<div class="card"><h1>Ошибка сервера</h1><p>Подробности — в журнале программы (app.log).</p></div>'), nonce)
            except Exception:
                pass

    def _send(self, h, code, body, nonce, headers=(), ctype='text/html; charset=utf-8'):
        data = body.encode('utf-8') if isinstance(body, str) else body
        h.send_response(code)
        h.send_header('Content-Type', ctype)
        h.send_header('Content-Length', str(len(data)))
        h.send_header('Cache-Control', 'no-store')
        h.send_header('X-Frame-Options', 'DENY')
        h.send_header('X-Content-Type-Options', 'nosniff')
        h.send_header('Referrer-Policy', 'no-referrer')
        h.send_header('Content-Security-Policy', f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{nonce}'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        for k, v in headers:
            h.send_header(k, v)
        h.end_headers()
        if h.command != 'HEAD':
            h.wfile.write(data)

    def _redirect(self, h, location, nonce, headers=()):
        self._send(h, 303, '', nonce, headers=(('Location', location), *headers))

    def _cookie(self, h):
        for part in (h.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'pto_session':
                return v
        return ''

    def _form(self, h):
        try:
            length = int(h.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            return None
        raw = h.rfile.read(length).decode('utf-8', 'replace') if length else ''
        return {k: v[-1] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def _route(self, h, method, nonce):
        path = urllib.parse.urlsplit(h.path)
        route, query = path.path.rstrip('/') or '/', urllib.parse.parse_qs(path.query)
        ip = h.client_address[0]
        if route == '/health':
            return self._send(h, 200, 'ok', nonce, ctype='text/plain; charset=utf-8')
        token = self._cookie(h)
        session = self.session(token)
        cookie_flags = 'HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if self.https else '')
        if route == '/login':
            if method == 'GET':
                return self._send(h, 200, login_page(), nonce)
            form = self._form(h)
            if form is None:
                return self._send(h, 413, login_page(('err', 'Слишком большой запрос')), nonce)
            if self.locked_out(ip):
                return self._send(h, 429, login_page(('err', 'Слишком много неудачных попыток. Подождите минуту.')), nonce)
            found = verify(self.db, form.get('login'), form.get('password'))
            if not found:
                self.failed(ip)
                time.sleep(0.4)
                return self._send(h, 401, login_page(('err', 'Неверный логин или пароль')), nonce)
            self.fails.pop(ip, None)
            self.drop(token)
            return self._redirect(h, '/contracts', nonce, (('Set-Cookie', f'pto_session={self.new_session(found[0], form.get("login").strip(), found[1])}; {cookie_flags}'),))
        if not session:
            if method == 'GET' and route != '/':
                return self._redirect(h, '/login', nonce)
            return self._redirect(h, '/login', nonce)
        if route == '/logout' and method == 'POST':
            form = self._form(h) or {}
            if hmac.compare_digest(form.get('csrf', ''), session['csrf']):
                self.drop(token)
            return self._redirect(h, '/login', nonce, (('Set-Cookie', f'pto_session=; Max-Age=0; {cookie_flags}'),))
        if route == '/':
            return self._redirect(h, '/contracts', nonce)
        if route == '/contracts' and method == 'GET':
            q = (query.get('q') or [''])[0]
            return self._send(h, 200, list_page(wc.search(self.db, q), q, session), nonce)
        m = re.fullmatch(r'/contracts/(\d+)', route)
        if m:
            return self._card(h, method, int(m.group(1)), session, nonce)
        return self._send(h, 404, layout('Не найдено', '<div class="card"><h1>Страница не найдена</h1></div>', session), nonce)

    def _lock_holder(self, cid):
        key = f'{wc.LOCK_PREFIX}:{cid}'
        from . import edit_locks
        for k, user, host, _since in edit_locks.holders(self.db):
            if k == key:
                return f'{user or "пользователь"} ({host})'
        return None

    def _card(self, h, method, cid, session, nonce):
        message = ''
        if method == 'POST':
            form = self._form(h)
            if form is None:
                return self._send(h, 413, layout('Ошибка', '<div class="card"><h1>Слишком большой запрос</h1></div>', session), nonce)
            if not hmac.compare_digest(form.get('csrf', ''), session['csrf']):
                return self._send(h, 403, layout('Ошибка', '<div class="card"><h1>Запрос отклонён (устарела страница). Откройте карточку заново.</h1></div>', session), nonce)
            if session['role'] != 'editor':
                return self._send(h, 403, layout('Ошибка', '<div class="card"><h1>У вашей учётной записи нет права правки.</h1></div>', session), nonce)
            locked = self._lock_holder(cid)
            if locked:
                message = ('err', f'Не сохранено: карточку сейчас правит {locked}.')
            else:
                rows = []
                for i in range(min(int(form.get('eq_count') or 0), 60)):
                    rows.append(dict(id=form.get(f'eq_id_{i}') or None, kind=form.get(f'eq_kind_{i}'), model=form.get(f'eq_model_{i}'), serial=form.get(f'eq_serial_{i}'),
                                     note=form.get(f'eq_note_{i}'), delete=bool(form.get(f'eq_del_{i}'))))
                values = dict(client_name=form.get('client_name'), phones=form.get('phones'), client_address=form.get('client_address'), passport=form.get('passport'),
                              passport_issuer=form.get('passport_issuer'), passport_date=form.get('passport_date'), object=form.get('object'), object_address=form.get('object_address'),
                              notes=form.get('notes'), signed=form.get('signed'), act_signed=form.get('act_signed'))
                try:
                    wc.save_card(self.db, cid, values, rows)
                    logging.info('web: %s сохранил договор %s', session['login'], cid)
                    message = ('ok', 'Сохранено.')
                except ValueError as e:
                    message = ('err', f'Не сохранено: {e}')
        card = wc.get_card(self.db, cid)
        if not card:
            return self._send(h, 404, layout('Не найдено', '<div class="card"><h1>Договор не найден</h1></div>', session), nonce)
        return self._send(h, 200, card_page(card, session, wc.copy_text(self.db, cid), nonce, message, self._lock_holder(cid)), nonce)


def lan_addresses():
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.') and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def start_from_settings(db, data_dir):
    """Запускает шлюз по настройкам программы (web_port, web_https). Возвращает WebGateway."""
    from pathlib import Path
    port = int(db.get_setting('web_port', '8765') or 8765)
    cert = key = None
    if db.get_setting('web_https', '1') == '1':
        from .server_core import ensure_certificate
        cert, key, _fp = ensure_certificate(str(Path(data_dir) / 'web_cert'), lan_addresses())
    gateway = WebGateway(db, '0.0.0.0', port, cert, key)
    gateway.start()
    return gateway


RUNNING = None          # запущенный шлюз (один на программу)
LAST_ERROR = ''


def apply_settings(db, data_dir):
    """Приводит шлюз в соответствие с настройками: web_enabled=1 — запущен (при смене порта / HTTPS перезапускается), иначе остановлен. Возвращает (WebGateway|None, ошибка)."""
    global RUNNING, LAST_ERROR
    want = db.get_setting('web_enabled', '0') == '1' and not getattr(db, 'is_remote', False)
    if RUNNING and (not want or RUNNING.port != int(db.get_setting('web_port', '8765') or 8765) or RUNNING.https != (db.get_setting('web_https', '1') == '1')):
        RUNNING.stop()
        RUNNING = None
    LAST_ERROR = ''
    if want and not RUNNING:
        try:
            RUNNING = start_from_settings(db, data_dir)
        except Exception as e:                                           # порт занят, нет прав и т. п. — программа продолжает работать
            logging.exception('web gateway start failed')
            LAST_ERROR = str(e)
            RUNNING = None
    return RUNNING, LAST_ERROR


def urls():
    if not RUNNING:
        return []
    scheme = 'https' if RUNNING.https else 'http'
    return [f'{scheme}://{ip}:{RUNNING.port}' for ip in lan_addresses()] or [f'{scheme}://localhost:{RUNNING.port}']
