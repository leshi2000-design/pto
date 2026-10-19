"""Запуск «ПТО Сервера»: окно (по умолчанию) или консоль (--console, для службы Windows)."""
import os

os.environ['PTO_MODE'] = 'local'          # сервер всегда работает с локальной базой своего компьютера
import argparse
import json
import logging
import sys
import threading
import time

from . import __version__, net_proto as proto
from .config import DATA_DIR

SETTINGS = DATA_DIR / 'server.json'


def load_settings():
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            data = json.load(f)
        return dict(port=int(data.get('port', proto.DEFAULT_PORT)))
    except (OSError, ValueError, TypeError):
        return dict(port=proto.DEFAULT_PORT)


def save_settings(**values):
    data = load_settings()
    data.update(values)
    with open(SETTINGS, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def build(port=None):
    """Открывает базу, обновляет схему и создаёт сервер (ещё не запущенный). -> (db, users, server)."""
    from .database import db
    from .server_core import PtoServer, UserStore
    db.init_db()
    users = UserStore(DATA_DIR / 'users.db')
    server = PtoServer(db, users, DATA_DIR / 'server_tls', host='0.0.0.0', port=port or load_settings()['port'], app_version=__version__)
    return db, users, server


def console(args):
    from .server_core import local_addresses, pretty_fingerprint
    db, users, server = build(args.port)
    if args.create_admin:
        login, password = args.create_admin
        users.add(login, password, 'admin', login)
        print(f'Создан администратор {login}')
    if not users.count():
        print('Нет ни одного пользователя. Создайте администратора: --create-admin ЛОГИН ПАРОЛЬ')
        return 2
    server.start()
    save_settings(port=server.port)
    print(f'ПТО Сервер {__version__} запущен. Порт {server.port}. Адреса: {", ".join(local_addresses()) or "—"}')
    print('Отпечаток сертификата (сверьте при первом подключении клиента):', pretty_fingerprint(server.fingerprint))
    last_backup = 0.0
    try:
        while True:
            time.sleep(5)
            if time.time() - last_backup > 3600:            # почасовая копия, как в обычной программе
                last_backup = time.time()
                try:
                    from datetime import datetime
                    from pathlib import Path
                    from .backup import create_backup
                    folder = Path(db.db_name).parent / 'backups'
                    folder.mkdir(exist_ok=True)
                    create_backup(db, folder / f'auto_{datetime.now():%Y%m%d_%H%M%S}.zip')
                    for old in sorted(folder.glob('auto_*.zip'))[:-24]:
                        old.unlink()
                except Exception:
                    logging.exception('Копия не создана')
    except KeyboardInterrupt:
        server.stop()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='ПТО Сервер')
    parser.add_argument('--console', action='store_true', help='без окна (для службы)')
    parser.add_argument('--port', type=int)
    parser.add_argument('--create-admin', nargs=2, metavar=('ЛОГИН', 'ПАРОЛЬ'))
    parser.add_argument('--selftest', action='store_true', help='проверка сборки: все нужные модули на месте (результат в selftest.txt рядом с программой)')
    args = parser.parse_args(argv)
    if args.selftest:
        from .selftest import run
        return run()
    if args.console:
        return console(args)
    from .server_app import run_window
    return run_window(args.port)


if __name__ == '__main__':
    sys.exit(main())
