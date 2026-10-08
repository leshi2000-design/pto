"""Standalone Магазин entry point; separate database from СМЕТА-ГАЗ."""
import argparse
import os
from pathlib import Path
import sys
import traceback
from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox, QInputDialog, QLineEdit
from shop.ui import Window


def main():
    parser = argparse.ArgumentParser(description='Магазин')
    parser.add_argument('--data-dir', default=os.environ.get('MAGAZIN_DATA_DIR', str(Path.home() / '.magazin')))
    parser.add_argument('--server', help='Адрес центрального сервера: http://IP:8765')
    parser.add_argument('--connect', action='store_true', help='Спросить адрес сервера при запуске')
    args = parser.parse_args()
    root = Path(args.data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    if args.connect:
        address, ok = QInputDialog.getText(None, 'Магазин — подключение', 'Адрес сервера, например http://192.168.1.10:8765')
        if not ok:
            return 0
        args.server = address.strip()
        if not args.server:
            QMessageBox.warning(None, 'Магазин', 'Адрес сервера не указан')
            return 1
    lock = QLockFile(str(root / 'app.lock'))
    if not lock.tryLock(100):
        QMessageBox.warning(None, 'Магазин', 'Эта папка данных уже открыта другим экземпляром программы.')
        return 1
    def report_error(exc_type, value, tb):
        message = ''.join(traceback.format_exception(exc_type, value, tb))
        try:
            with (root / 'error.log').open('a', encoding='utf-8') as stream:
                stream.write(message + '\n')
        except OSError:
            pass
        QMessageBox.critical(None, 'Ошибка «Магазина»', f'{value}\n\nПодробности: {root / "error.log"}')
    sys.excepthook = report_error
    try:
        store = None
        if args.server:
            from shop.network import RemoteStore
            token = os.environ.get('MAGAZIN_SERVER_TOKEN')
            if not token:
                token, ok = QInputDialog.getText(None, 'Подключение к серверу', 'Ключ из server-key.txt на серверном компьютере:', QLineEdit.EchoMode.Password)
                if not ok:
                    lock.unlock()
                    return 0
            store = RemoteStore(root, args.server, token)
        window = Window(root, store)
    except Exception:
        report_error(*sys.exc_info())
        lock.unlock()
        return 1
    window.show()
    result = app.exec()
    lock.unlock()
    return result


if __name__ == '__main__':
    sys.exit(main())
