"""Передача данных из «Монтаж ГСВ» в программу «ТО физ.лиц.» по нажатию одной кнопки.

Обе программы работают на одном компьютере. ПТО кладёт небольшой файл .json в папку входящих «ТО физ.лиц.»
(%APPDATA%\\TO_fizlic\\inbox); «ТО физ.лиц.» подхватывает его сама (а если она закрыта — ПТО её запускает) и открывает
заполненную карточку нового договора. Сохраняет договор уже сотрудник — после проверки данных.

Формат файла (version 1) описан в «ТО физ.лиц.» (модуль handoff). Здесь — только отправка.
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

FORMAT = 'to-handoff'
VERSION = 1
SOURCE = 'ПТО'
ALIVE = '.alive'                   # «ТО физ.лиц.» запущена: файл обновляется каждые пару секунд
EXE_NAME = 'TO_fizlic.exe'


def base_dir():
    """Та же папка, что у «ТО физ.лиц.»: %APPDATA%\\TO_fizlic (на других системах ~/.to_fizlic)."""
    appdata = os.environ.get('APPDATA')
    return Path(appdata) / 'TO_fizlic' if appdata else Path.home() / '.to_fizlic'


def inbox_dir():
    folder = base_dir() / 'inbox'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _norm(text):
    return str(text or '').casefold().replace('ё', 'е')


def is_maintainable(kind):
    """Какое оборудование обслуживается по договору ТО: котёл, колонка, плита (ПГ). Счётчик, сигнализатор, регулятор — нет."""
    k = _norm(kind)
    return any(w in k for w in ('котел', 'котл', 'колонк', 'плит')) or k.strip() in ('пг', 'п/г')


def candidates(rows):
    """Строки оборудования, которые по умолчанию передаются в ТО."""
    return [r for r in rows if is_maintainable(r.get('kind')) and (str(r.get('model') or '').strip() or str(r.get('serial') or '').strip())]


def build_payload(client, equipment_rows, object_address='', contract_number='', version=''):
    """Словарь для файла передачи: клиент (ФИО, телефон, адрес, паспорт, кем выдан, дата выдачи), адрес объекта, оборудование."""
    client = client or {}
    return {
        'format': FORMAT, 'version': VERSION, 'source': (SOURCE + ' ' + version).strip(),
        'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'pto_contract': str(contract_number or '').strip(),
        'install_address': str(object_address or '').strip(),
        'client': {'name': str(client.get('name') or '').strip(), 'phone': str(client.get('phone') or '').strip(),
                   'address': str(client.get('address') or '').strip(), 'passport': str(client.get('passport') or '').strip(),
                   'issued_by': str(client.get('passport_issuer') or '').strip(), 'issue_date': str(client.get('passport_date') or '').strip()},
        'equipment': [{'kind': str(r.get('kind') or '').strip(), 'model': str(r.get('model') or '').strip(),
                       'serial': str(r.get('serial') or '').strip()} for r in equipment_rows],
    }


def write_payload(payload, inbox=None):
    """Пишет файл атомарно (сначала во временный, затем переименование): «ТО физ.лиц.» не увидит недописанный файл."""
    folder = Path(inbox) if inbox else inbox_dir()
    name = f'pto_{time.strftime("%Y%m%d_%H%M%S")}_{uuid.uuid4().hex[:8]}'
    tmp = folder / (name + '.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding='utf-8')
    final = folder / (name + '.json')
    os.replace(tmp, final)
    return final


def to_is_running(inbox=None, max_age=8.0):
    try:
        return time.time() - (Path(inbox) if inbox else inbox_dir()).joinpath(ALIVE).stat().st_mtime < max_age
    except OSError:
        return False


# --- поиск и запуск «ТО физ.лиц.» ---------------------------------------------------------

def _link_file():
    return base_dir() / 'pto_link.json'


def saved_exe():
    try:
        path = json.loads(_link_file().read_text(encoding='utf-8')).get('to_exe', '')
    except (OSError, ValueError):
        return ''
    return path if path and Path(path).is_file() else ''


def save_exe(path):
    try:
        _link_file().parent.mkdir(parents=True, exist_ok=True)
        _link_file().write_text(json.dumps({'to_exe': str(path)}, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def exe_candidates():
    """Обычные места, где лежит программа «ТО физ.лиц.» (рядом с ПТО, в Program Files, на диске C:)."""
    here = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve()
    places = [here.parent.parent / 'TO_fizlic' / EXE_NAME, here.parent.parent.parent / 'TO_fizlic' / EXE_NAME,
              here.parent / 'TO_fizlic' / EXE_NAME]
    for env in ('LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)'):
        if os.environ.get(env):
            places += [Path(os.environ[env]) / 'Programs' / 'TO_fizlic' / EXE_NAME, Path(os.environ[env]) / 'TO_fizlic' / EXE_NAME]
    places += [Path('C:/TO/TO_fizlic') / EXE_NAME, Path('C:/TO_fizlic') / EXE_NAME]
    return places


def find_exe():
    saved = saved_exe()
    if saved:
        return saved
    for p in exe_candidates():
        if p.is_file():
            return str(p)
    return ''


def launch(exe):
    """Запускает «ТО физ.лиц.» отдельным процессом (закрытие ПТО её не закрывает)."""
    kw = {}
    if sys.platform == 'win32':
        kw['creationflags'] = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw['start_new_session'] = True
    try:
        subprocess.Popen([str(exe)], cwd=str(Path(exe).parent), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **kw)
        return True
    except OSError:
        return False
