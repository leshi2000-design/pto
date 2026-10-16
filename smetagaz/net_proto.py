"""Общий формат обмена клиента и сервера: JSON поверх HTTPS. Двоичные значения кодируются как {"__b": base64}."""
import base64
import json
from datetime import date, datetime
from decimal import Decimal

PROTOCOL = 1
DEFAULT_PORT = 8765
MAX_BODY = 64 * 1024 * 1024


def _default(obj):
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return {'__b': base64.b64encode(bytes(obj)).decode('ascii')}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat(sep=' ') if isinstance(obj, datetime) else obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f'Нельзя передать по сети значение типа {type(obj).__name__}')


def _hook(obj):
    if len(obj) == 1 and '__b' in obj:
        return base64.b64decode(obj['__b'])
    return obj


def dumps(obj):
    return json.dumps(obj, default=_default, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def loads(data):
    return json.loads(data.decode('utf-8') if isinstance(data, (bytes, bytearray)) else data, object_hook=_hook)


class RemoteError(Exception):
    """Ошибка, пришедшая от сервера (не из SQLite): вход, права, версия, прерванная транзакция."""
    def __init__(self, message, code=''):
        super().__init__(message)
        self.code = code


class ConnectionLost(Exception):
    """Нет связи с сервером."""
