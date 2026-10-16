"""PTO_TEST_REMOTE=1: тесты работают с базой через настоящий ПТО Сервер (по сети, на localhost) — проверка совместимости сетевого слоя со всей программой."""
import smetagaz.database as dbm
from smetagaz import net_proto, server_core as sc
from smetagaz.remote_db import RemoteDatabaseManager

_RealDatabaseManager = dbm.DatabaseManager


class _Meta(type):
    def __instancecheck__(cls, obj):          # isinstance(db, DatabaseManager) в тестах должен узнавать и настоящую, и сетевую базу
        return isinstance(obj, (_RealDatabaseManager, RemoteDatabaseManager))


class RemoteForTests(RemoteDatabaseManager, metaclass=_Meta):
    def __init__(self, path, *args, **kwargs):
        import pathlib
        self._path = pathlib.Path(path)
        self._real = _RealDatabaseManager(path)
        folder = self._path.parent / ('_srv_' + self._path.stem)
        folder.mkdir(exist_ok=True)
        self._users = sc.UserStore(folder / 'users.db')
        if not self._users.count():
            self._users.add('admin', 'secret1', 'admin', 'Тест')
        from smetagaz import __version__
        self._server = sc.PtoServer(self._real, self._users, folder / 'tls', host='127.0.0.1', port=0, app_version=__version__)
        self._server.allow_unsafe = True            # тесты вызывают миграции и служебные команды с «клиента»
        self._server.start()
        super().__init__(dict(mode='client', host='127.0.0.1', port=self._server.port, fingerprint=self._server.fingerprint, login='admin'))
        self.db_name = str(self._path)
        self.conn = self._real.conn                  # служебные операции копирования выполняются на стороне сервера
        self.connect('admin', 'secret1')

    def __getattr__(self, name):
        if name.startswith('_real') or name == '__dict__':
            raise AttributeError(name)
        return getattr(self._real, name)

    def init_db(self):
        self._real.init_db()

    def close(self):
        try:
            self.disconnect()
        finally:
            self._server.stop()
            self._real.close()


def install():
    dbm.DatabaseManager = RemoteForTests
