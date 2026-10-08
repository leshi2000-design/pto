"""Authenticated LAN transport. SQLite is opened only on the server computer."""
from pathlib import Path
from urllib.parse import urlsplit
import base64
import json
import sqlite3
import os
import requests
from .core import Store

METHODS = {'product', 'party', 'catalog', 'stock', 'offer', 'document', 'post', 'cancel', 'shipment_from_invoice',
    'reserved', 'available', 'set_retail', 'retail', 'total', 'invoices', 'debts', 'payment', 'cancel_payment',
    'sales', 'statistics', 'calendar', 'save_organization', 'set_settings', 'reschedule_shipment', 'rows'}


def dispatch(store, method, args, kwargs):
    if method in METHODS:
        if method == 'rows':
            def authorize(action, arg1, arg2, database, trigger):
                if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE):
                    return sqlite3.SQLITE_OK
                if action == sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() != 'load_extension':
                    return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            store.conn.set_authorizer(authorize)
            try:
                return store.rows(*args, **kwargs)
            finally:
                store.conn.set_authorizer(None)
        return getattr(store, method)(*args, **kwargs)
    if method == 'apply_imported_prices':
        from .sources import apply_imported_prices
        return apply_imported_prices(store, *args, **kwargs)
    if method == 'apply_web_prices':
        from .sources import apply_web_prices
        return apply_web_prices(store, *args, **kwargs)
    if method == 'backup':
        from .backup import create
        return base64.b64encode(create(store).read_bytes()).decode('ascii')
    if method == 'upload':
        relative, encoded = args
        target = (store.root / relative).resolve()
        if (not target.is_relative_to(store.root) or '..' in Path(relative).parts
                or not target.relative_to(store.root).parts
                or target.relative_to(store.root).parts[0] not in ('templates', 'documents', 'sources')):
            raise ValueError('Недопустимый путь файла')
        content = base64.b64decode(encoded, validate=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return relative
    if method == 'templates':
        return {p.name: base64.b64encode(p.read_bytes()).decode('ascii') for p in (store.root / 'templates').iterdir() if p.is_file()}
    raise ValueError('Неизвестная операция сервера')


class Cursor:
    def __init__(self, rows):
        self.data = rows
    def fetchone(self):
        return tuple(self.data[0].values()) if self.data else None


class ReadConnection:
    def __init__(self, store):
        self.store = store
    def execute(self, sql, args=()):
        return Cursor(self.store.rows(sql, args))


class RemoteStore:
    remote = True
    def __init__(self, root, url, token):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username:
            raise ValueError('Адрес сервера: http://IP:8765 или HTTPS')
        self.url = url.rstrip('/')
        self.root = Path(root).resolve()
        for folder in ('templates', 'documents', 'sources', 'backups'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers['Authorization'] = 'Bearer ' + token
        self.session.trust_env = False  # LAN traffic must not inherit an Internet proxy.
        self.session.verify = os.environ.get('MAGAZIN_CA_BUNDLE') or True
        self.conn = ReadConnection(self)
        self._closed = False
        templates = self.call('templates')
        for name, encoded in templates.items():
            if Path(name).name != name:
                raise ValueError('Некорректное имя шаблона сервера')
            (self.root / 'templates' / name).write_bytes(base64.b64decode(encoded))

    def call(self, method, *args, **kwargs):
        if self._closed:
            raise ValueError('Соединение с сервером закрыто')
        try:
            response = self.session.post(self.url + '/api', json={'method': method, 'args': args, 'kwargs': kwargs}, timeout=(10, 90))
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ValueError('Не удалось связаться с сервером. Проверьте адрес и сеть. Последняя операция могла выполниться: обновите списки перед повторной записью.') from exc
        if not response.ok or 'error' in data:
            raise ValueError(data.get('error', f'Ошибка сервера {response.status_code}'))
        return data['result']

    def __getattr__(self, name):
        if name in METHODS or name in ('apply_imported_prices', 'apply_web_prices'):
            return lambda *args, **kwargs: self.call(name, *args, **kwargs)
        raise AttributeError(name)

    def create_backup(self, destination=None):
        from datetime import datetime
        path = Path(destination or self.root / 'backups' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.zip'))
        path.write_bytes(base64.b64decode(self.call('backup'), validate=True))
        return path

    def upload_file(self, path):
        path = Path(path).resolve()
        relative = path.relative_to(self.root).as_posix()
        self.call('upload', relative, base64.b64encode(path.read_bytes()).decode('ascii'))

    def close(self):
        if not self._closed:
            self.session.close()
            self._closed = True
