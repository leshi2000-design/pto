"""Запуск программы с защитой от «тихого» падения: у собранного PTO.exe нет консоли, поэтому ошибку при старте иначе не видно вообще.
Любая ошибка записывается в startup_error.txt (рядом с программой и в папке данных) и показывается окном Windows."""
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path


def _folders():
    out = []
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
    out.append(base)
    out.append(Path(os.environ.get('SMETAGAZ_DATA_DIR', Path.home() / '.smetagaz')))
    return out


def report_startup_error(exc_text):
    """Пишет отчёт и показывает окно; возвращает список файлов, куда отчёт удалось записать."""
    version = ''
    try:
        from . import __version__
        version = __version__
    except Exception:
        pass
    head = f'ПТО {version} · {datetime.now():%d.%m.%Y %H:%M:%S}\nPython {sys.version.split()[0]} · {sys.platform}\nФайл программы: {sys.executable}\n\n'
    written = []
    for folder in _folders():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / 'startup_error.txt'
            path.write_text(head + exc_text, encoding='utf-8')
            written.append(str(path))
        except Exception:
            continue
    message = ('Программа не смогла запуститься.\n\nОтчёт об ошибке сохранён:\n' + '\n'.join(written) +
               '\n\nПришлите этот файл разработчику.\n\nПоследние строки ошибки:\n' + '\n'.join(exc_text.strip().splitlines()[-6:]))
    try:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, 'ПТО — ошибка запуска', 0x10)
        else:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication([])
            QMessageBox.critical(None, 'ПТО — ошибка запуска', message)
    except Exception:
        pass
    return written


def guarded(main):
    """Выполняет main(); при любой ошибке (в том числе при импорте модулей) оставляет отчёт вместо молчаливого закрытия."""
    try:
        return main()
    except SystemExit:
        raise
    except BaseException:
        report_startup_error(traceback.format_exc())
        raise SystemExit(1)
