"""Клиентская «база»: тот же интерфейс, что у DatabaseManager (execute, fetchone, fetchall, transaction…), но команды выполняет ПТО Сервер.
Остальная программа не знает, что база удалённая."""
import hashlib
import http.client
import itertools
import socket
import sqlite3
import ssl
import threading
import uuid
from contextlib import contextmanager

from . import net_config, net_proto as proto
from .config import DATA_DIR


class RemoteCursor:
    """Результат команды: строки уже получены, поэтому fetchone/fetchall работают без обращения к серверу."""
    arraysize = 1

    def __init__(self, result=None):
        result = result or {}
        self.description = tuple((name, None, None, None, None, None, None) for name in result['desc']) if result.get('desc') else None
        self._rows = [tuple(r) for r in result.get('rows', [])]
        self._pos = 0
        self.rowcount = result.get('rowcount', -1)
        self.lastrowid = result.get('lastrowid')

    def fetchone(self):
        if self._pos < len(self._rows):
            self._pos += 1
            return self._rows[self._pos - 1]
        return None

    def fetchall(self):
        rows, self._pos = self._rows[self._pos:], len(self._rows)
        return rows

    def fetchmany(self, size=1):
        rows = self._rows[self._pos:self._pos + size]
        self._pos += len(rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        pass


class _TxCursor(RemoteCursor):
    """Курсор внутри transaction(): cur.execute(...) выполняется на сервере в этой же транзакции."""
    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def execute(self, sql, params=()):
        self._load(self._owner._call('exec', sql=sql, params=list(params)))
        return self

    def executemany(self, sql, seq):
        self._load(self._owner._call('execmany', sql=sql, params=[list(p) for p in seq]))
        return self

    def _load(self, result):
        fresh = RemoteCursor(result)
        self.description, self._rows, self._pos, self.rowcount, self.lastrowid = fresh.description, fresh._rows, 0, fresh.rowcount, fresh.lastrowid


class _ConnShim:
    """Минимум от sqlite3.Connection, который используется в программе."""
    def __init__(self, owner):
        self._owner = owner

    @property
    def total_changes(self):
        return self._owner._call('total_changes')

    @property
    def in_transaction(self):
        return self._owner._tx_depth > 0


class RemoteDatabaseManager:
    is_remote = True

    def __init__(self, cfg=None):
        self._lock = threading.RLock()
        self.cfg = cfg or net_config.load()
        self.db_name = str(DATA_DIR / 'smetagaz.db')         # только чтобы вычислять соседние локальные папки; файл на этом компьютере не создаётся
        self.conn = _ConnShim(self)
        self.token = None
        self.user = ''
        self.login_name = ''
        self.role = ''
        self.server_version = ''
        self._tx_depth = 0
        self._local = threading.local()
        self.on_status = None             # callback(bool connected, str text) для индикатора связи

    # --- соединение
    def _connection(self, fresh=False):
        conn = getattr(self._local, 'conn', None)
        if conn is not None and not fresh:
            return conn
        if conn is not None:
            try:
                conn.close()
            except OSError:
                pass
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE                       # подлинность проверяется отпечатком сертификата, сохранённым при первом подключении
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        conn = http.client.HTTPSConnection(self.cfg['host'], int(self.cfg['port']), context=ctx, timeout=60)
        conn.connect()
        conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        fp = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
        pinned = str(self.cfg.get('fingerprint') or '').lower()
        if pinned and fp != pinned:
            conn.close()
            raise proto.RemoteError('Сертификат сервера не совпадает с сохранённым. Возможно, подключение подменено или сервер переустановлен. '
                                    'Проверьте отпечаток в окне «ПТО Сервер» и подключитесь заново.', 'fingerprint')
        self._local.conn = conn
        self._local.fingerprint = fp
        return conn

    def _post(self, payload, retry=True):
        body = proto.dumps(payload)
        try:
            conn = self._connection()
            conn.request('POST', '/rpc', body=body, headers={'Content-Type': 'application/json', 'Content-Length': str(len(body))})
            response = conn.getresponse()
            data = response.read()
        except proto.RemoteError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            self._local.conn = None
            if retry and self._tx_depth == 0 and payload.get('m') not in ('execmany',):
                return self._post(payload, retry=False)
            self._status(False, 'нет связи с сервером')
            raise proto.ConnectionLost(f'Нет связи с сервером ({self.cfg["host"]}:{self.cfg["port"]}): {e}')
        self._status(True, f'{self.user} · сервер {self.cfg["host"]}')
        return proto.loads(data)

    def _call(self, method, **payload):
        reply = self._post(dict(payload, m=method, token=self.token))
        if 'error' in reply:
            err = reply['error']
            kind = err.get('type', 'RemoteError')
            if kind == 'RemoteError':
                raise proto.RemoteError(err.get('message', ''), err.get('code', ''))
            exc = getattr(sqlite3, kind, sqlite3.OperationalError)
            raise (exc if isinstance(exc, type) and issubclass(exc, Exception) else sqlite3.OperationalError)(err.get('message', ''))
        return reply.get('result')

    def _status(self, ok, text):
        callback = self.on_status
        if callback:
            try:
                callback(ok, text)
            except Exception:
                pass

    # --- вход
    @staticmethod
    def probe(host, port):
        """Первое знакомство с сервером: -> (отпечаток сертификата, сведения). Сертификат ещё не проверяется — его подтверждает пользователь."""
        cfg = dict(host=host, port=int(port), fingerprint='')
        tmp = RemoteDatabaseManager(cfg)
        reply = tmp._post(dict(m='hello'))
        if 'error' in reply:
            raise proto.RemoteError(reply['error'].get('message', 'Ошибка сервера'))
        return tmp._local.fingerprint, reply['result']

    def connect(self, login, password):
        """Вход на сервер. Проверяет версию протокола и программы."""
        hello = self._call('hello')
        if hello.get('service') != 'PTO Server' or hello.get('proto') != proto.PROTOCOL:
            raise proto.RemoteError('Версия сервера несовместима с этой программой. Обновите программу и сервер до одной версии.', 'proto')
        from . import __version__
        if tuple(str(hello.get('version', '')).split('.')[:2]) != tuple(__version__.split('.')[:2]):
            raise proto.RemoteError(f'Версия программы {__version__} не совпадает с версией сервера {hello.get("version")}. Обновите её (должны совпадать первые два числа).', 'version')
        result = self._post(dict(m='login', login=login, password=password))
        if 'error' in result:
            raise proto.RemoteError(result['error'].get('message', 'Вход не выполнен'), result['error'].get('code', ''))
        info = result['result']
        self.token, self.user, self.login_name, self.role = info['token'], info['name'], info['login'], info['role']
        self.server_version = hello.get('version', '')
        self._status(True, f'{self.user} · сервер {self.cfg["host"]}')
        return info

    @property
    def connected(self):
        return bool(self.token)

    def disconnect(self):
        if self.token:
            try:
                self._call('logout')
            except Exception:
                pass
        self.token = None
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def ping(self):
        try:
            self._call('ping')
            return True
        except Exception:
            return False

    # --- интерфейс DatabaseManager
    def execute(self, query, params=()):
        with self._lock:
            return RemoteCursor(self._call('exec', sql=query, params=list(params)))

    def executemany(self, query, seq_of_params):
        with self._lock:
            return RemoteCursor(self._call('execmany', sql=query, params=[list(p) for p in seq_of_params]))

    def fetchone(self, query, params=()):
        return self.execute(query, params).fetchone()

    def fetchall(self, query, params=()):
        return self.execute(query, params).fetchall()

    def get_setting(self, key, default=''):
        row = self.fetchone('SELECT value FROM settings WHERE key=?', (key,))
        if row and row[0] is not None:
            return str(row[0])
        return default

    def set_setting(self, key, value):
        self.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))

    @contextmanager
    def transaction(self):
        """Транзакция на сервере: пока она открыта, остальные пользователи ждут. Вложенные — через SAVEPOINT."""
        with self._lock:
            nested = self._tx_depth > 0
            name = 'sp_' + uuid.uuid4().hex
            if nested:
                self._call('exec', sql=f'SAVEPOINT {name}', params=[])
            else:
                self._call('tx_begin')
            self._tx_depth += 1
            try:
                yield _TxCursor(self)
            except BaseException:
                self._tx_depth -= 1
                try:
                    if nested:
                        self._call('exec', sql=f'ROLLBACK TO {name}', params=[])
                        self._call('exec', sql=f'RELEASE {name}', params=[])
                    else:
                        self._call('tx_end', commit=False)
                except Exception:
                    pass
                raise
            self._tx_depth -= 1
            try:
                if nested:
                    self._call('exec', sql=f'RELEASE {name}', params=[])
                else:
                    self._call('tx_end', commit=True)
            except BaseException:
                if not nested:
                    try:
                        self._call('tx_end', commit=False)
                    except Exception:
                        pass
                raise

    def safety_backup(self, reason, keep=10):
        """Снимок базы делает сервер (в своей папке backups)."""
        return self._call('safety_backup', reason=reason, keep=keep)

    def init_db(self):
        """Схему создаёт и обновляет сервер."""

    def close(self):
        self.disconnect()
