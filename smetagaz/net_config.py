"""Настройка сетевого режима. Файл network.json хранится в папке данных этого компьютера.
mode: 'local' — обычная работа с локальной базой (по умолчанию); 'client' — работа через ПТО Сервер."""
import json
import os

from .config import DATA_DIR

PATH = DATA_DIR / 'network.json'
DEFAULTS = {'mode': 'local', 'host': '', 'port': 8765, 'fingerprint': '', 'login': '', 'token': ''}


def load():
    data = dict(DEFAULTS)
    try:
        with open(PATH, encoding='utf-8') as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            data.update({k: raw[k] for k in DEFAULTS if k in raw})
    except (OSError, ValueError):
        pass
    if os.environ.get('PTO_MODE') in ('local', 'client'):
        data['mode'] = os.environ['PTO_MODE']
    try:
        data['port'] = int(data['port'])
    except (TypeError, ValueError):
        data['port'] = DEFAULTS['port']
    return data


def save(cfg):
    data = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    tmp = str(PATH) + '.part'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PATH)
    try:
        os.chmod(PATH, 0o600)               # в файле лежит ключ сохранённого входа
    except OSError:
        pass
    return data


def is_client():
    return load()['mode'] == 'client'
