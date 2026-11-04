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

from . import web_modules, web_pages as wp
from .web_pages import esc

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


# --- СЕРВЕР --------------------------------------------------------------------------------------------

class WebGateway:
    def __init__(self, db, host='0.0.0.0', port=8765, cert=None, key=None):
        self.db, self.host, self.port, self.cert, self.key = db, host, int(port), cert, key
        self.sessions = {}
        self.modules = web_modules.all_modules()
        self.fails = {}
        self.lock = threading.Lock()
        self.httpd = None
        self.thread = None
        self.installer = None

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
        if self.installer:
            self.installer.stop()
            self.installer = None
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
                self._send(h, 500, wp.layout(self.db, 'Ошибка', '<div class="panel"><h1>Ошибка сервера</h1><p>Подробности — в журнале программы (app.log).</p></div>', None, app_name=self.app_name()), nonce)
            except Exception:
                pass

    def app_name(self):
        return self.db.get_setting('app_name', 'ПТО') or 'ПТО'

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

    def _notice(self, h, code, text, session, nonce):
        self._send(h, code, wp.layout(self.db, 'Ошибка', f'<div class="panel"><h1>{esc(text)}</h1></div>', session, modules=self.modules, nonce=nonce, app_name=self.app_name()), nonce)

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
        name = self.app_name()
        if route == '/health':
            return self._send(h, 200, 'ok', nonce, ctype='text/plain; charset=utf-8')
        token = self._cookie(h)
        session = self.session(token)
        cookie_flags = 'HttpOnly; SameSite=Strict; Path=/' + ('; Secure' if self.https else '')
        if route == '/login':
            if method == 'GET':
                return self._send(h, 200, wp.login_page(self.db, app_name=name), nonce)
            form = self._form(h)
            if form is None:
                return self._send(h, 413, wp.login_page(self.db, ('err', 'Слишком большой запрос'), name), nonce)
            if self.locked_out(ip):
                return self._send(h, 429, wp.login_page(self.db, ('err', 'Слишком много неудачных попыток. Подождите минуту.'), name), nonce)
            found = verify(self.db, form.get('login'), form.get('password'))
            if not found:
                self.failed(ip)
                time.sleep(0.4)
                return self._send(h, 401, wp.login_page(self.db, ('err', 'Неверный логин или пароль'), name), nonce)
            self.fails.pop(ip, None)
            self.drop(token)
            return self._redirect(h, '/m/contracts', nonce, (('Set-Cookie', f'pto_session={self.new_session(found[0], form.get("login").strip(), found[1])}; {cookie_flags}'),))
        if not session:
            return self._redirect(h, '/login', nonce)
        if route == '/logout' and method == 'POST':
            form = self._form(h) or {}
            if hmac.compare_digest(form.get('csrf', ''), session['csrf']):
                self.drop(token)
            return self._redirect(h, '/login', nonce, (('Set-Cookie', f'pto_session=; Max-Age=0; {cookie_flags}'),))
        if route in ('/', '/contracts'):
            return self._redirect(h, '/m/contracts', nonce)
        m = re.fullmatch(r'/contracts/(\d+)', route)
        if m:
            return self._redirect(h, f'/m/contracts/{m.group(1)}', nonce)
        m = re.fullmatch(r'/m/([a-z_]+)(?:/(new|\d+))?', route)
        module = self.modules.get(m.group(1)) if m else None
        if not module:
            return self._notice(h, 404, 'Страница не найдена', session, nonce)
        if not m.group(2):
            if method != 'GET':
                return self._notice(h, 405, 'Метод не поддерживается', session, nonce)
            q = (query.get('q') or [''])[0]
            return self._send(h, 200, wp.list_page(self.db, module, module.search(self.db, q), q, session, self.modules, app_name=name, can_create=module.can_create and session['role'] == 'editor'), nonce)
        if m.group(2) == 'new':
            if not module.can_create:
                return self._notice(h, 404, 'В этом разделе новые записи создаются в программе', session, nonce)
            return self._card(h, method, module, None, session, nonce)
        return self._card(h, method, module, int(m.group(2)), session, nonce)

    def _lock_holder(self, module, cid):
        if not module.lock or not cid:
            return None
        key = f'{module.lock}:{cid}'
        from . import edit_locks
        for k, user, host, _since in edit_locks.holders(self.db):
            if k == key:
                return f'{user or "пользователь"} ({host})'
        return None

    @staticmethod
    def _parse_form(module, form):
        values = {}
        for f in module.fields:
            raw = form.get(f'f_{f.name}')
            values[f.name] = bool(raw) if f.kind == 'check' else (raw if raw is not None else '')
        children = {}
        for ch in module.children:
            rows = []
            try:
                count = min(int(form.get(f'c_{ch.key}_count') or 0), 80)
            except ValueError:
                count = 0
            for i in range(count):
                row = dict(id=form.get(f'c_{ch.key}_id_{i}') or None, delete=bool(form.get(f'c_{ch.key}_del_{i}')))
                for f in ch.fields:
                    raw = form.get(f'c_{ch.key}_{f.name}_{i}')
                    row[f.name] = bool(raw) if f.kind == 'check' else (raw or '')
                rows.append(row)
            children[ch.key] = rows
        return values, children

    def _card(self, h, method, module, cid, session, nonce):
        message = ''
        values = children = None
        if method == 'POST':
            form = self._form(h)
            if form is None:
                return self._notice(h, 413, 'Слишком большой запрос', session, nonce)
            if not hmac.compare_digest(form.get('csrf', ''), session['csrf']):
                return self._notice(h, 403, 'Запрос отклонён (устарела страница). Откройте карточку заново.', session, nonce)
            if session['role'] != 'editor':
                return self._notice(h, 403, 'У вашей учётной записи нет права правки.', session, nonce)
            if cid and module.load(self.db, cid) is None:
                return self._notice(h, 404, 'Запись не найдена', session, nonce)
            locked = self._lock_holder(module, cid)
            values, children = self._parse_form(module, form)
            if locked:
                message = ('err', f'Не сохранено: карточку сейчас правит {locked}.')
            else:
                rows = {ch.key: children[ch.key] for ch in module.children}
                try:
                    saved = module.save(self.db, cid, values, rows.get(module.children[0].key, []) if module.children else [])
                    logging.info('web: %s сохранил %s %s', session['login'], module.key, saved)
                    if not cid:
                        return self._redirect(h, f'/m/{module.key}/{saved}', nonce)
                    values = children = None
                    message = ('ok', 'Сохранено.')
                except ValueError as e:
                    message = ('err', f'Не сохранено: {e}')
        if cid:
            loaded = module.load(self.db, cid)
            if loaded is None:
                return self._notice(h, 404, 'Запись не найдена', session, nonce)
            if values is None:
                values = loaded
            else:
                for k in ('_title', '_legal', '_party', '_statuses', '_chip_keys'):
                    if k in loaded:
                        values[k] = loaded[k]
            if children is None:
                children = {ch.key: ch.rows(self.db, cid) for ch in module.children}
        else:
            if values is None:
                values = module.blank(self.db) if module.blank else {}
            if children is None:
                children = {ch.key: [] for ch in module.children}
        copy = module.copy(self.db, cid) if (module.copy and cid) else ''
        return self._send(h, 200, wp.card_page(self.db, module, cid, values, children, session, self.modules, nonce, message, self._lock_holder(module, cid), copy, self.app_name()), nonce)


def lan_addresses():
    from . import web_tls
    return web_tls.lan_addresses()


def start_from_settings(db, data_dir):
    """Запускает шлюз по настройкам программы (web_port, web_https). Возвращает WebGateway.
    HTTPS: сертификат подписан собственным центром сертификации ПТО (один раз ставится на устройство — тогда «подключение не защищено» пропадает);
    на соседнем порту (порт + 1) работает страница установки этого сертификата."""
    from pathlib import Path
    from . import web_tls
    port = int(db.get_setting('web_port', '8765') or 8765)
    cert = key = None
    folder = Path(data_dir) / 'web_cert'
    ips = lan_addresses()
    if db.get_setting('web_https', '1') == '1':
        cert, key = web_tls.ensure_server_cert(folder, ips, [socket.gethostname()])
    gateway = WebGateway(db, '0.0.0.0', port, cert, key)
    gateway.start()
    if cert:
        try:
            gateway.installer = web_tls.InstallServer(folder, 'https://{host}:' + str(gateway.port), '0.0.0.0', gateway.port + 1 if port else 0)
            gateway.installer.start()
        except Exception as e:                                           # порт+1 занят — основной сервер всё равно работает
            logging.warning('web: страница установки сертификата не запущена: %s', e)
            gateway.installer = None
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


def install_urls():
    """Адреса страницы установки сертификата (обычный http, порт + 1) — их открывают на телефоне один раз."""
    if not RUNNING or not RUNNING.installer:
        return []
    return [f'http://{ip}:{RUNNING.installer.port}' for ip in lan_addresses()]
