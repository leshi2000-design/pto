"""Помощники сетевых тестов: настоящий ПТО Сервер на свободном порту и клиентская база к нему."""
import socket

from smetagaz import net_proto as proto, server_core as sc
from smetagaz.database import DatabaseManager
from smetagaz.remote_db import RemoteDatabaseManager


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Cluster:
    """Сервер с базой в папке path и пользователем admin/secret1."""
    def __init__(self, path, version=None):
        from smetagaz import __version__
        self.path = path
        self.db = DatabaseManager(path / 'smetagaz.db')
        self.db.init_db()
        self.users = sc.UserStore(path / 'users.db')
        if not self.users.count():
            self.users.add('admin', 'secret1', 'admin', 'Администратор')
        self.server = sc.PtoServer(self.db, self.users, path / 'tls', host='127.0.0.1', port=0, app_version=version or __version__)
        self.server.start()
        self.port = self.server.port

    def client(self, login='admin', password='secret1', fingerprint=None):
        cfg = dict(mode='client', host='127.0.0.1', port=self.port, fingerprint=fingerprint if fingerprint is not None else self.server.fingerprint, login=login)
        remote = RemoteDatabaseManager(cfg)
        remote.connect(login, password)
        return remote

    def stop(self):
        self.server.stop()
        self.db.close()
