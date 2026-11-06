"""Запуск ПТО вместе с Windows: запись в реестре текущего пользователя (без прав администратора), программа стартует свёрнутой в значок у часов (ключ --background)."""
import sys
from pathlib import Path

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
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


def _registry():
    import winreg
    return winreg


def is_enabled():
    if not supported():
        return False
    reg = _registry()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            value, _kind = reg.QueryValueEx(key, VALUE_NAME)
        return bool(value)
    except OSError:
        return False


def enable():
    """Включает автозапуск (если запись уже есть — обновляет команду, например после переезда папки программы)."""
    if not supported():
        raise OSError('Автозапуск поддерживается только в Windows')
    reg = _registry()
    with reg.CreateKey(reg.HKEY_CURRENT_USER, RUN_KEY) as key:
        reg.SetValueEx(key, VALUE_NAME, 0, reg.REG_SZ, command())


def disable():
    if not supported():
        return
    reg = _registry()
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
            reg.DeleteValue(key, VALUE_NAME)
    except OSError:
        pass
