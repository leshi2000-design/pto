"""«ПТО Сервер»: единственный владелец базы в сети. Принимает запросы клиентов по HTTPS (самоподписанный сертификат с проверкой отпечатка),
проверяет вход и права, выполняет SQL по одному и транзакции — монопольно. Без Qt: можно запускать окном или из консоли."""
import hashlib
import hmac
import http.server
import ipaddress
import logging
import os
import re
import secrets
import socket
import sqlite3
import ssl
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta

from . import net_proto as proto

ROLES = {'admin': 'Администратор', 'manager': 'Руководитель', 'editor': 'Сотрудник', 'viewer': 'Только просмотр'}
RESTRICTABLE = ('editor', 'viewer')       # скрывать разделы можно только у сотрудников и наблюдателей; руководитель и администратор видят всё
JOURNAL_KEEP = 20000
SESSION_IDLE = 12 * 3600          # сессия без запросов закрывается через 12 часов
TX_IDLE = 30                      # транзакция без запросов откатывается через 30 секунд
LOGIN_FAILS, LOGIN_WINDOW, LOGIN_LOCK = 5, 300, 60
PBKDF2_ROUNDS = 200_000
TOKEN_DAYS = 180                  # сохранённый вход («запомнить меня») действует столько дней с последнего использования


# --- ПОЛЬЗОВАТЕЛИ ---------------------------------------------------------------------------------

class UserStore:
    """Пользователи сервера: отдельный файл users.db рядом с базой (не попадает в клиентские копии)."""
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE, full_name TEXT DEFAULT '', role TEXT NOT NULL DEFAULT 'editor',
                salt TEXT NOT NULL, hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created TEXT DEFAULT '', last_login TEXT DEFAULT '')""")
            if 'hidden' not in [r[1] for r in con.execute('PRAGMA table_info(users)')]:
                con.execute("ALTER TABLE users ADD COLUMN hidden TEXT DEFAULT ''")      # разделы, скрытые от пользователя (через запятую)
            con.execute("""CREATE TABLE IF NOT EXISTS access_log(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, event TEXT NOT NULL, login TEXT DEFAULT '', ip TEXT DEFAULT '',
                device TEXT DEFAULT '', details TEXT DEFAULT '')""")
            con.execute("""CREATE TABLE IF NOT EXISTS remember_tokens(id INTEGER PRIMARY KEY, uid INTEGER NOT NULL, hash TEXT NOT NULL UNIQUE, device TEXT DEFAULT '',
                created TEXT DEFAULT '', last_used TEXT DEFAULT '')""")

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _hash(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()

    @staticmethod
    def _hidden_set(role, text):
        return frozenset(x for x in str(text or '').split(',') if x) if role in RESTRICTABLE else frozenset()

    def log(self, event, login='', ip='', device='', details=''):
        """Журнал входов и действий администратора (таблица access_log в users.db)."""
        try:
            with self._lock, self._connect() as con:
                con.execute('INSERT INTO access_log(ts,event,login,ip,device,details) VALUES(?,?,?,?,?,?)',
                            (datetime.now().isoformat(timespec='seconds'), event, str(login or ''), str(ip or ''), str(device or '')[:60], str(details or '')[:300]))
                if con.execute('SELECT count(*) FROM access_log').fetchone()[0] > JOURNAL_KEEP + 500:
                    con.execute('DELETE FROM access_log WHERE id <= (SELECT max(id) FROM access_log) - ?', (JOURNAL_KEEP,))
        except sqlite3.Error:
            pass                                          # журнал не должен мешать работе

    def journal(self, limit=500, event=None):
        with self._connect() as con:
            if event:
                return con.execute('SELECT ts,event,login,ip,device,details FROM access_log WHERE event=? ORDER BY id DESC LIMIT ?', (event, int(limit))).fetchall()
            return con.execute('SELECT ts,event,login,ip,device,details FROM access_log ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()

    def hidden_of(self, uid):
        with self._connect() as con:
            row = con.execute('SELECT role,hidden FROM users WHERE id=?', (uid,)).fetchone()
        return self._hidden_set(row[0], row[1]) if row else frozenset()

    def add(self, login, password, role='editor', full_name='', hidden=(), actor=''):
        login = str(login or '').strip()
        if not re.fullmatch(r'[\w.\-]{2,40}', login):
            raise ValueError('Логин — 2–40 символов: буквы, цифры, точка, дефис, подчёркивание')
        if role not in ROLES:
            raise ValueError('Неизвестная роль')
        self._check_password(password)
        salt = secrets.token_hex(16)
        try:
            with self._lock, self._connect() as con:
                uid = con.execute('INSERT INTO users(login,full_name,role,salt,hash,created,hidden) VALUES(?,?,?,?,?,?,?)',
                                  (login, str(full_name or '').strip(), role, salt, self._hash(password, salt), datetime.now().isoformat(timespec='seconds'), ','.join(sorted(hidden or ())))).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('Пользователь с таким логином уже есть')
        self.log('user_add', actor, details=f'создан {login}, роль {ROLES[role]}')
        return uid

    @staticmethod
    def _check_password(password):
        if len(str(password or '')) < 6:
            raise ValueError('Пароль — не короче 6 символов')

    def set_password(self, uid, password, actor=''):
        self._check_password(password)
        salt = secrets.token_hex(16)
        with self._lock, self._connect() as con:
            con.execute('UPDATE users SET salt=?,hash=? WHERE id=?', (salt, self._hash(password, salt), uid))
            con.execute('DELETE FROM remember_tokens WHERE uid=?', (uid,))         # смена пароля отменяет все сохранённые входы
            row = con.execute('SELECT login FROM users WHERE id=?', (uid,)).fetchone()
        self.log('password', actor or (row[0] if row else ''), details=f'пароль пользователя {row[0] if row else uid} изменён, сохранённые входы отозваны')

    def update(self, uid, role=None, active=None, full_name=None, hidden=None, actor=''):
        with self._lock, self._connect() as con:
            row = con.execute('SELECT role,active,login,hidden FROM users WHERE id=?', (uid,)).fetchone()
            if not row:
                raise ValueError('Пользователь не найден')
            new_role = role if role is not None else row[0]
            new_active = int(active) if active is not None else row[1]
            new_hidden = ','.join(sorted(hidden)) if hidden is not None else row[3]
            if new_role not in ROLES:
                raise ValueError('Неизвестная роль')
            if row[0] == 'admin' and row[1] and (new_role != 'admin' or not new_active):
                if con.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (uid,)).fetchone()[0] == 0:
                    raise ValueError('Нельзя отключить или понизить последнего администратора')
            con.execute('UPDATE users SET role=?,active=?,full_name=coalesce(?,full_name),hidden=? WHERE id=?', (new_role, new_active, full_name, new_hidden, uid))
            if not new_active:
                con.execute('DELETE FROM remember_tokens WHERE uid=?', (uid,))
        changes = []
        if new_role != row[0]:
            changes.append(f'роль {ROLES[row[0]]} → {ROLES[new_role]}')
        if new_active != row[1]:
            changes.append('включён' if new_active else 'отключён')
        if new_hidden != (row[3] or ''):
            changes.append('доступ к разделам изменён: скрыто ' + (new_hidden.replace(',', ', ') or 'ничего'))
        if changes:
            self.log('user_update', actor, details=f'{row[2]}: ' + '; '.join(changes))

    def delete(self, uid, actor=''):
        with self._lock, self._connect() as con:
            row = con.execute('SELECT role,active,login FROM users WHERE id=?', (uid,)).fetchone()
            if row and row[0] == 'admin' and row[1] and con.execute("SELECT count(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (uid,)).fetchone()[0] == 0:
                raise ValueError('Нельзя удалить последнего администратора')
            con.execute('DELETE FROM users WHERE id=?', (uid,))
            con.execute('DELETE FROM remember_tokens WHERE uid=?', (uid,))
        if row:
            self.log('user_delete', actor, details=f'удалён {row[2]}')

    def raw_hidden(self, uid):
        with self._connect() as con:
            row = con.execute('SELECT hidden FROM users WHERE id=?', (uid,)).fetchone()
        return frozenset(x for x in str(row[0] if row else '').split(',') if x)

    def listing(self):
        with self._connect() as con:
            return con.execute('SELECT id,login,full_name,role,active,created,last_login FROM users ORDER BY login').fetchall()

    def count(self):
        with self._connect() as con:
            return con.execute('SELECT count(*) FROM users').fetchone()[0]

    def verify(self, login, password):
        """-> (id, login, full_name, role) или None. Время проверки не зависит от того, существует ли логин."""
        with self._connect() as con:
            row = con.execute('SELECT id,login,full_name,role,salt,hash,active,hidden FROM users WHERE login=?', (str(login or '').strip(),)).fetchone()
        salt = row[4] if row else '00' * 16
        calc = self._hash(str(password or ''), salt)
        if row and row[6] and hmac.compare_digest(calc, row[5]):
            with self._lock, self._connect() as con:
                con.execute('UPDATE users SET last_login=? WHERE id=?', (datetime.now().isoformat(timespec='seconds'), row[0]))
            return row[0], row[1], row[2], row[3], self._hidden_set(row[3], row[7])
        return None


    # --- сохранённый вход: вместо пароля компьютер хранит случайный ключ, который можно отозвать
    @staticmethod
    def _token_hash(raw):
        return hashlib.sha256(str(raw or '').encode('utf-8')).hexdigest()

    def make_token(self, uid, device=''):
        raw = secrets.token_urlsafe(32)
        now = datetime.now().isoformat(timespec='seconds')
        with self._lock, self._connect() as con:
            con.execute('INSERT INTO remember_tokens(uid,hash,device,created,last_used) VALUES(?,?,?,?,?)', (uid, self._token_hash(raw), str(device or '')[:60], now, now))
        return raw

    def verify_token(self, login, raw):
        """-> (id, login, full_name, role) или None. Ключ привязан к логину, не истёк и не отозван."""
        if not raw:
            return None
        with self._connect() as con:
            row = con.execute('SELECT u.id,u.login,u.full_name,u.role,u.active,t.id,t.last_used,u.hidden FROM remember_tokens t JOIN users u ON u.id=t.uid WHERE t.hash=?',
                              (self._token_hash(raw),)).fetchone()
        if not row or not row[4] or str(row[1]).lower() != str(login or '').strip().lower():
            return None
        try:
            if datetime.now() - datetime.fromisoformat(row[6]) > timedelta(days=TOKEN_DAYS):
                return None
        except ValueError:
            return None
        with self._lock, self._connect() as con:
            con.execute('UPDATE remember_tokens SET last_used=? WHERE id=?', (datetime.now().isoformat(timespec='seconds'), row[5]))
            con.execute('UPDATE users SET last_login=? WHERE id=?', (datetime.now().isoformat(timespec='seconds'), row[0]))
        return row[0], row[1], row[2], row[3], self._hidden_set(row[3], row[7])

    def revoke_token(self, raw):
        with self._lock, self._connect() as con:
            con.execute('DELETE FROM remember_tokens WHERE hash=?', (self._token_hash(raw),))

    def revoke_all(self, uid):
        with self._lock, self._connect() as con:
            con.execute('DELETE FROM remember_tokens WHERE uid=?', (uid,))


# --- СЕРТИФИКАТ -------------------------------------------------------------------------------------

def ensure_certificate(folder, hostnames=()):
    """Самоподписанный сертификат сервера (создаётся один раз). Возвращает (cert.pem, key.pem, отпечаток SHA-256)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    os.makedirs(folder, exist_ok=True)
    cert_path, key_path = os.path.join(folder, 'server.crt'), os.path.join(folder, 'server.key')
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'PTO Server')])
        names = [x509.DNSName('localhost'), x509.DNSName(socket.gethostname())] + [x509.DNSName(h) for h in hostnames if h]
        try:
            names.append(x509.IPAddress(ipaddress.ip_address('127.0.0.1')))
        except ValueError:
            pass
        now = datetime.utcnow()
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName(names), critical=False).sign(key, hashes.SHA256()))
        with open(key_path, 'wb') as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
        with open(cert_path, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
    return cert_path, key_path, fingerprint_of_file(cert_path)


def fingerprint_of_file(cert_path):
    with open(cert_path, 'rb') as f:
        der = ssl.PEM_cert_to_DER_cert(f.read().decode('ascii'))
    return hashlib.sha256(der).hexdigest()


def pretty_fingerprint(fp):
    fp = fp.upper()
    return ':'.join(fp[i:i + 2] for i in range(0, len(fp), 2))


# --- ПРАВА НА SQL -----------------------------------------------------------------------------------

_SETTINGS_WRITE = re.compile(r'^(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:main\.)?"?settings"?\b', re.I)
_STRIP = re.compile(r'(--[^\n]*|/\*.*?\*/)', re.S)


def classify(sql):
    """'read' | 'write' | 'settings' | 'savepoint' | 'denied' — вид SQL-команды для проверки прав."""
    text = _STRIP.sub(' ', str(sql or '')).strip().rstrip(';').strip()
    if not text or ';' in text:
        return 'denied'                           # только одна команда за запрос
    word = text.split(None, 1)[0].upper()
    if word in ('SELECT', 'EXPLAIN'):
        return 'read'
    if word == 'WITH':
        return 'write' if re.search(r'\b(INSERT|UPDATE|DELETE|REPLACE)\b', text, re.I) else 'read'
    if word == 'PRAGMA':
        return 'denied' if '=' in text else 'read'
    if word in ('INSERT', 'UPDATE', 'DELETE', 'REPLACE'):
        return 'settings' if _SETTINGS_WRITE.match(text) else 'write'
    if word == 'VACUUM':
        return 'write'
    if word in ('SAVEPOINT', 'RELEASE') or re.match(r'ROLLBACK\s+TO\b', text, re.I):
        return 'savepoint'
    return 'denied'                               # DDL, ATTACH, BEGIN/COMMIT (их выполняет сервер), load_extension…


def allowed(role, kind):
    if kind == 'denied':
        return False
    if role == 'viewer':
        return kind in ('read', 'settings', 'savepoint')
    return True


# --- ПРАВА ПО РАЗДЕЛАМ --------------------------------------------------------------------------
# Что сервер защищает на уровне самой базы (остальное — скрытие разделов в интерфейсе клиента):
FULL_DENY = {                        # ни читать, ни менять
    'ip': {'ip_income', 'ip_manual', 'ip_tax_params'},
    'ip_tax': {'ip_income', 'ip_manual', 'ip_tax_params'},
}
WRITE_DENY = {                       # читать можно (суммы входят в общие сводки), вводить и менять оплаты нельзя
    'payments': {'payments', 'client_sales'},
}


def denied_tables(hidden):
    full, write = set(), set()
    for key in hidden or ():
        full |= FULL_DENY.get(key, set())
        write |= WRITE_DENY.get(key, set())
    return full, write


def make_authorizer(full, write):
    DENY, OK = sqlite3.SQLITE_DENY, sqlite3.SQLITE_OK
    changing = (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE)

    def check(action, a1, a2, dbname, source):
        if source is not None:                       # действие триггера или представления (журнал изменений и т. п.)
            return OK
        table = str(a1 or '').lower()
        if action == sqlite3.SQLITE_READ and table in full:
            return DENY
        if action in changing and (table in full or table in write):
            return DENY
        return OK
    return check


_WRITE_TARGET = re.compile(r'^(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)\s+(?:\w+\.)?"?(\w+)"?', re.I)


def write_tables(sql):
    """Какую таблицу меняет команда ('*' — не удалось определить)."""
    m = _WRITE_TARGET.match(_STRIP.sub(' ', str(sql or '')).strip())
    return frozenset({m.group(1).lower()}) if m else frozenset({'*'})


# --- ДОСТУП К БАЗЕ И ТРАНЗАКЦИИ ------------------------------------------------------------------

class Gate:
    """Обычные команды выполняются параллельно (база сериализует их сама); транзакция клиента — монопольно: остальные ждут её завершения.
    Транзакция без запросов дольше TX_IDLE секунд откатывается, а клиент получает ошибку при следующей команде."""
    def __init__(self, db, idle=TX_IDLE):
        self.db, self.idle = db, idle
        self.cv = threading.Condition()
        self.owner, self.last, self.running = None, 0.0, 0
        self.aborted = set()

    def _expire(self):
        if self.owner is not None and time.monotonic() - self.last > self.idle:
            logging.warning('Транзакция клиента прервана по таймауту')
            try:
                with self.db._lock:
                    if self.db.conn.in_transaction:
                        self.db.conn.execute('ROLLBACK')
            except sqlite3.Error:
                logging.exception('Откат просроченной транзакции не удался')
            self.aborted.add(self.owner)
            self.owner = None
            self.cv.notify_all()

    @contextmanager
    def access(self, token):
        plain = False
        with self.cv:
            if token in self.aborted:
                raise proto.RemoteError('Транзакция была прервана сервером из-за долгого бездействия. Повторите действие.', 'tx_aborted')
            while True:
                self._expire()
                if self.owner == token:
                    break
                if self.owner is None:
                    self.running += 1
                    plain = True
                    break
                self.cv.wait(0.25)
        try:
            yield
        finally:
            with self.cv:
                if plain:
                    self.running -= 1
                    self.cv.notify_all()
                else:
                    self.last = time.monotonic()

    def begin(self, token):
        with self.cv:
            if token in self.aborted:
                self.aborted.discard(token)
            deadline = time.monotonic() + 60
            while self.owner is not None or self.running > 0:
                if self.owner == token:
                    raise proto.RemoteError('Транзакция уже открыта', 'tx_open')
                self._expire()
                if time.monotonic() > deadline:
                    raise proto.RemoteError('Сервер занят другим пользователем, повторите через несколько секунд', 'busy')
                self.cv.wait(0.25)
            with self.db._lock:
                self.db.conn.execute('BEGIN IMMEDIATE')
            self.owner, self.last = token, time.monotonic()

    def end(self, token, commit):
        with self.cv:
            if token in self.aborted:
                self.aborted.discard(token)
                if commit:
                    raise proto.RemoteError('Транзакция была прервана сервером из-за долгого бездействия: изменения не сохранены.', 'tx_aborted')
                return
            if self.owner != token:
                return
            try:
                with self.db._lock:
                    if self.db.conn.in_transaction:
                        self.db.conn.execute('COMMIT' if commit else 'ROLLBACK')
            finally:
                self.owner = None
                self.cv.notify_all()

    def forget(self, token):
        """Клиент вышел: открытая транзакция откатывается."""
        with self.cv:
            if self.owner == token:
                self.end_locked_rollback()
            self.aborted.discard(token)

    def end_locked_rollback(self):
        try:
            with self.db._lock:
                if self.db.conn.in_transaction:
                    self.db.conn.execute('ROLLBACK')
        finally:
            self.owner = None
            self.cv.notify_all()


# --- СЕРВЕР -------------------------------------------------------------------------------------------

class Session:
    def __init__(self, token, uid, login, name, role, ip, hidden=frozenset(), device=''):
        self.token, self.uid, self.login, self.name, self.role, self.ip = token, uid, login, name, role, ip
        self.hidden, self.device = frozenset(hidden), device
        full, write = denied_tables(self.hidden)
        self.auth = make_authorizer(full, write) if (full or write) else None
        self.created = self.last = time.time()
        self.requests = 0


class PtoServer:
    def __init__(self, db, users, tls_dir, host='0.0.0.0', port=proto.DEFAULT_PORT, app_version=''):
        self.db, self.users = db, users
        self.host, self.port = host, int(port)
        self.app_version = app_version
        self.allow_unsafe = False          # только для тестов: разрешает клиенту DDL и служебные команды
        self.gate = Gate(db)
        self.sessions = {}
        self.failures = {}
        self._lock = threading.Lock()
        self.cert_path, self.key_path, self.fingerprint = ensure_certificate(tls_dir)
        self.httpd = None
        self.thread = None
        self.rev = 0                                   # номер последнего изменения данных; клиенты по нему узнают, что список устарел
        self.changelog = deque(maxlen=3000)            # (номер, сеанс, таблицы)

    # --- жизненный цикл
    def start(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(self.cert_path, self.key_path)
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            timeout = 120

            def log_message(self, fmt, *args):
                logging.debug('http: ' + fmt, *args)

            def do_POST(self):
                if self.path != '/rpc':
                    return self.reply(404, {'error': {'type': 'RemoteError', 'message': 'Не найдено', 'code': 'not_found'}})
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                except ValueError:
                    length = -1
                if not 0 < length <= proto.MAX_BODY:
                    return self.reply(413, {'error': {'type': 'RemoteError', 'message': 'Неверный размер запроса', 'code': 'size'}})
                body = self.rfile.read(length)
                self.reply(200, server.handle(body, self.client_address[0]))

            def do_GET(self):
                self.reply(200, {'result': {'service': 'PTO Server'}})

            def reply(self, status, payload):
                data = proto.dumps(payload)
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        class Httpd(http.server.ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

            def finish_request(self, request, client_address):
                try:
                    request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)       # без задержек Нэйгла: иначе каждый запрос +40 мс
                    request = ctx.wrap_socket(request, server_side=True)
                except (ssl.SSLError, OSError):
                    return
                super().finish_request(request, client_address)

        self.httpd = Httpd((self.host, self.port), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, name='pto-server', daemon=True)
        self.thread.start()
        logging.info('ПТО Сервер запущен на %s:%s', self.host, self.port)

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        for token in list(self.sessions):
            self.gate.forget(token)
        self.sessions.clear()

    # --- вход
    def _throttled(self, ip, login):
        now = time.time()
        key = (ip, str(login).lower())
        fails = [t for t in self.failures.get(key, []) if now - t < LOGIN_WINDOW]
        self.failures[key] = fails
        return len(fails) >= LOGIN_FAILS and now - fails[-1] < LOGIN_LOCK

    def login(self, ip, login, password, remember_token='', remember=False, device=''):
        if self._throttled(ip, login):
            self.users.log('login_blocked', login, ip, device, 'слишком много неудачных попыток')
            raise proto.RemoteError('Слишком много неудачных попыток входа. Подождите минуту.', 'throttled')
        row = self.users.verify_token(login, remember_token) if remember_token else self.users.verify(login, password)
        if not row and remember_token:
            self.failures.setdefault((ip, str(login).lower()), []).append(time.time())
            self.users.log('login_fail', login, ip, device, 'сохранённый вход недействителен')
            raise proto.RemoteError('Сохранённый вход больше не действует. Введите логин и пароль.', 'bad_token')
        if not row:
            self.failures.setdefault((ip, str(login).lower()), []).append(time.time())
            self.users.log('login_fail', login, ip, device, 'неверный логин или пароль')
            raise proto.RemoteError('Неверный логин или пароль', 'bad_login')
        self.failures.pop((ip, str(login).lower()), None)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self.sessions[token] = Session(token, row[0], row[1], row[2] or row[1], row[3], ip, row[4], device)
        logging.info('Вход: %s (%s) с %s', row[1], row[3], ip)
        self.users.log('login_token' if remember_token else 'login', row[1], ip, device, ROLES.get(row[3], row[3]))
        info = dict(token=token, login=row[1], name=row[2] or row[1], role=row[3], hidden=sorted(row[4]))
        if remember and not remember_token:
            info['remember_token'] = self.users.make_token(row[0], device or ip)
        return info

    def session(self, token):
        with self._lock:
            s = self.sessions.get(token)
            if s and time.time() - s.last > SESSION_IDLE:
                self.sessions.pop(token, None)
                self.gate.forget(token)
                s = None
        if not s:
            raise proto.RemoteError('Сеанс завершён. Войдите заново.', 'no_session')
        s.last = time.time()
        s.requests += 1
        return s

    def active_sessions(self):
        with self._lock:
            return [(s.login, s.name, s.role, s.ip, datetime.fromtimestamp(s.created).strftime('%H:%M'), datetime.fromtimestamp(s.last).strftime('%H:%M:%S'), s.device) for s in self.sessions.values()]

    def locks(self):
        """Открытые сейчас карточки: [(ключ, кто, компьютер, с какого времени)]."""
        with self.db._lock:
            return [tuple(r) for r in self.db.conn.execute(
                "SELECT key,user,host,since FROM edit_locks WHERE beat >= CAST(strftime('%s','now') AS INTEGER) - 90 ORDER BY since").fetchall()]

    def release_lock(self, key, actor):
        with self.db._lock:
            n = self.db.conn.execute('DELETE FROM edit_locks WHERE key=?', (key,)).rowcount
        if n:
            self.users.log('lock_release', actor, details=f'снята блокировка карточки {key}')
        return n

    def changes_since(self, token, since):
        """-> (текущий номер, таблицы, изменённые другими с номера since). since=None — только запомнить текущий номер."""
        with self._lock:
            rev = self.rev
            if since is None or since >= rev:
                return rev, []
            oldest = self.changelog[0][0] if self.changelog else rev + 1
            if since < oldest - 1:
                return rev, ['*']
            tables = set()
            for r, owner, tb in self.changelog:
                if r > since and owner != token:
                    tables |= tb
            return rev, sorted(tables)

    def _note_change(self, token, sql):
        with self._lock:
            self.rev += 1
            self.changelog.append((self.rev, token, write_tables(sql)))

    # --- обработка запроса
    def handle(self, body, ip):
        try:
            req = proto.loads(body)
            method = req.get('m')
            return {'result': self.dispatch(method, req, ip)}
        except proto.RemoteError as e:
            return {'error': {'type': 'RemoteError', 'message': str(e), 'code': e.code}}
        except sqlite3.Error as e:
            return {'error': {'type': type(e).__name__, 'message': str(e)}}
        except Exception as e:                               # ошибка в самом сервере не должна ронять его
            logging.exception('Ошибка обработки запроса')
            return {'error': {'type': 'RemoteError', 'message': f'Ошибка сервера: {e}', 'code': 'server'}}

    def dispatch(self, method, req, ip):
        if method == 'hello':
            return dict(service='PTO Server', proto=proto.PROTOCOL, version=self.app_version, fingerprint=self.fingerprint, needs_setup=self.users.count() == 0)
        if method == 'login':
            return self.login(ip, req.get('login'), req.get('password'), req.get('remember_token') or '', bool(req.get('remember')), str(req.get('device') or ''))
        s = self.session(req.get('token'))
        if method == 'logout':
            self.users.log('logout', s.login, s.ip, s.device)
            if req.get('forget'):
                self.users.revoke_token(req.get('forget'))
            self.gate.forget(s.token)
            with self._lock:
                self.sessions.pop(s.token, None)
            return True
        if method == 'ping':
            return dict(user=s.login, role=s.role)
        if method == 'poll':
            rev, tables = self.changes_since(s.token, req.get('since'))
            return dict(rev=rev, tables=tables)
        if method == 'online':
            if s.role not in ('admin', 'manager'):
                raise proto.RemoteError('Недостаточно прав', 'forbidden')
            return dict(sessions=[list(x) for x in self.active_sessions()], locks=[list(x) for x in self.locks()])
        if method == 'release_lock':
            if s.role not in ('admin', 'manager'):
                raise proto.RemoteError('Недостаточно прав', 'forbidden')
            return self.release_lock(str(req.get('key') or ''), s.login)
        if method == 'access_log':
            if s.role != 'admin':
                raise proto.RemoteError('Журнал входов доступен администратору', 'forbidden')
            return [list(r) for r in self.users.journal(min(int(req.get('limit') or 500), 5000), req.get('event') or None)]
        if method == 'tx_begin':
            if s.role == 'viewer':
                raise proto.RemoteError('Недостаточно прав для изменения данных', 'forbidden')
            self.gate.begin(s.token)
            self._set_audit_user(s)
            return True
        if method == 'tx_end':
            self.gate.end(s.token, bool(req.get('commit')))
            return True
        if method in ('exec', 'execmany'):
            return self.run_sql(s, req.get('sql'), req.get('params') or [], many=method == 'execmany')
        if method == 'total_changes':
            with self.gate.access(s.token):
                return self.db.conn.total_changes
        if method == 'safety_backup':
            if s.role == 'viewer':
                raise proto.RemoteError('Недостаточно прав', 'forbidden')
            with self.gate.access(s.token):
                return self.db.safety_backup(str(req.get('reason') or 'client')[:40], keep=int(req.get('keep', 10)))
        raise proto.RemoteError('Неизвестная команда', 'bad_method')

    def _set_audit_user(self, s):
        """Имя пользователя для журнала изменений (таблица audit_ctx в каждой базе). Читается из базы, а не запоминается:
        на этом же компьютере параллельно может работать обычная программа в локальном режиме и менять то же имя."""
        for schema in ('main', 'crm'):
            try:
                row = self.db.conn.execute(f'SELECT user FROM {schema}.audit_ctx WHERE id=1').fetchone()
                if row is None or row[0] != s.name:
                    self.db.conn.execute(f'UPDATE {schema}.audit_ctx SET user=? WHERE id=1', (s.name,))
            except sqlite3.Error:
                pass

    def run_sql(self, s, sql, params, many=False):
        kind = classify(sql)
        if not self.allow_unsafe and not allowed(s.role, kind):
            raise proto.RemoteError('Команда запрещена: изменение структуры базы и опасные команды выполняет только сервер; режим «только просмотр» не позволяет менять данные', 'forbidden')
        with self.gate.access(s.token):
            with self.db._lock:                    # установка имени для журнала и сама команда — одним неразрывным действием
                if kind != 'read' and self.gate.owner != s.token:
                    self._set_audit_user(s)
                if s.auth:
                    self.db.conn.set_authorizer(s.auth)          # разделы, закрытые для этого пользователя, недоступны на уровне базы
                try:
                    if many:
                        cur = self.db.executemany(sql, [tuple(p) for p in params])
                    else:
                        cur = self.db.execute(sql, tuple(params))
                    desc = [d[0] for d in cur.description] if cur.description else None
                    rows = [list(r) for r in cur.fetchall()] if desc else []
                except sqlite3.DatabaseError as e:
                    if s.auth and ('not authorized' in str(e) or 'prohibited' in str(e)):
                        raise proto.RemoteError('Этот раздел закрыт для вашей учётной записи. Обратитесь к администратору.', 'forbidden')
                    raise
                finally:
                    if s.auth:
                        self.db.conn.set_authorizer(None)
                if kind in ('write', 'settings'):
                    self._note_change(s.token, sql)
                return dict(desc=desc, rows=rows, rowcount=cur.rowcount, lastrowid=cur.lastrowid)


def local_addresses():
    """Адреса этого компьютера в сети, которые надо сообщить клиентам."""
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith('127.') and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found
