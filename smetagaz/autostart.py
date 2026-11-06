"""Запуск ПТО вместе с Windows: запись в реестре текущего пользователя (без прав администратора), программа стартует свёрнутой в значок у часов (ключ --background).
Запись делается системной командой reg.exe, а не модулем winreg: так обновление из ZIP не зависит от набора модулей, вошедших в собранную программу."""
import subprocess
import sys
from pathlib import Path

RUN_KEY = r'HKCU\Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'PTO'


def supported():
    return sys.platform == 'win32'


def command():
    """Команда запуска: у собранной программы — PTO.exe, при запуске из исходников — pythonw run.py."""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" --background'
    python = Path(sys.executable)
    pythonw = python.with_name('pythonw.exe')
    run = Path(__file__).resolve().parent.parent / 'run.py'
    return f'"{pythonw if pythonw.exists() else python}" "{run}" --background'


def _reg(*args):
    """Запуск reg.exe без окна; возвращает (код возврата, вывод)."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    done = subprocess.run(['reg', *args], capture_output=True, text=True, timeout=15, creationflags=flags)
    return done.returncode, (done.stdout or '') + (done.stderr or '')


def is_enabled():
    if not supported():
        return False
    try:
        code, out = _reg('query', RUN_KEY, '/v', VALUE_NAME)
    except (OSError, subprocess.SubprocessError):
        return False
    return code == 0 and VALUE_NAME in out


def enable():
    """Включает автозапуск (если запись уже есть — обновляет команду, например после переезда папки программы)."""
    if not supported():
        raise OSError('Автозапуск поддерживается только в Windows')
    try:
        code, out = _reg('add', RUN_KEY, '/v', VALUE_NAME, '/t', 'REG_SZ', '/d', command(), '/f')
    except subprocess.SubprocessError as e:
        raise OSError(str(e)) from None
    if code != 0:
        raise OSError(out.strip() or 'reg.exe вернул ошибку')


def disable():
    if not supported():
        return
    try:
        _reg('delete', RUN_KEY, '/v', VALUE_NAME, '/f')
    except (OSError, subprocess.SubprocessError):
        pass
