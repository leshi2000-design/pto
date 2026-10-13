"""Хранение секретов (пароль внешних копий) не открытым текстом.
Windows: DPAPI — расшифровать может только тот же пользователь Windows на этом компьютере.
Иначе: AES-GCM с ключом из файла secret.key рядом с базой (права 0600); копия базы без этого файла пароль не раскрывает.
Секрет из другой учётной записи или с другого компьютера не расшифруется: его нужно ввести заново."""
import base64
import os
import sys
from pathlib import Path

PREFIXES = ('dpapi:', 'key:')


def is_protected(value):
    return str(value or '').startswith(PREFIXES)


def _dpapi(data, protect):
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    source = Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)), ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    function = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    ok = function(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    if not ok:
        raise OSError('DPAPI недоступен')
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)


def _key(folder):
    path = Path(folder) / 'secret.key'
    if not path.exists():
        path.write_bytes(os.urandom(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_bytes()


def protect(text, folder):
    text = str(text or '')
    if not text or is_protected(text):
        return text
    if sys.platform == 'win32':
        try:
            return 'dpapi:' + base64.b64encode(_dpapi(text.encode('utf-8'), True)).decode()
        except OSError:
            pass
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return 'key:' + base64.b64encode(nonce + AESGCM(_key(folder)).encrypt(nonce, text.encode('utf-8'), b'pto-secret')).decode()


def reveal(value, folder):
    """Открытый текст; для старых незащищённых значений возвращает их как есть; при невозможности расшифровать — пустую строку."""
    value = str(value or '')
    if not is_protected(value):
        return value
    try:
        raw = base64.b64decode(value.split(':', 1)[1])
        if value.startswith('dpapi:'):
            return _dpapi(raw, False).decode('utf-8')
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM(_key(folder)).decrypt(raw[:12], raw[12:], b'pto-secret').decode('utf-8')
    except Exception:
        return ''


def get_secret(db, key, default=''):
    return reveal(db.get_setting(key, default), Path(db.db_name).parent)


def set_secret(db, key, text):
    db.set_setting(key, protect(text, Path(db.db_name).parent))


def migrate(db):
    """Пароли, сохранённые открытым текстом (старые версии), переводятся в защищённый вид."""
    for key in ('offsite_password',):
        value = db.get_setting(key, '')
        if value and not is_protected(value):
            set_secret(db, key, value)
