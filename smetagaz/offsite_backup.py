"""Резервная копия вне компьютера: зашифрованная копия на втором диске или в облачной папке и ежемесячная проверка восстановлением. Без Qt.

Копия — это обычная полная копия программы (create_backup), зашифрованная AES-GCM паролем (формат .sgb, его же понимает «Восстановить из копии» в настройках).
Файл пишется во временный «.part» и переименовывается только после записи, поэтому облачная папка не получит недописанный файл.
Пароль хранится в настройках программы: он защищает копию от чтения в облаке и на чужом диске, но не от человека с доступом к самому компьютеру.
Запишите пароль отдельно: без него копию не восстановить."""
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .backup import create_backup, restore_backup, digest
from .security import encrypt_backup, decrypt_backup

SUFFIX = '.sgb'
PREFIX = 'smetagaz_'
DEFAULT_KEEP = 12
DEFAULT_INTERVAL_H = 24
VERIFY_DAYS = 30
KEY_TABLES = ('estimates', 'contracts', 'gsv_projects', 'le_contracts', 'smr_contracts', 'payments', 'notes', 'settings')


def settings(db):
    folder = db.get_setting('offsite_dir', '')
    return dict(folder=folder, password=db.get_setting('offsite_password', ''), keep=int(db.get_setting('offsite_keep', str(DEFAULT_KEEP)) or DEFAULT_KEEP),
                interval_h=int(db.get_setting('offsite_interval_h', str(DEFAULT_INTERVAL_H)) or DEFAULT_INTERVAL_H), enabled=db.get_setting('offsite_enabled', '0') == '1')


def configured(db):
    s = settings(db)
    return bool(s['enabled'] and s['folder'] and len(s['password']) >= 10)


def check_settings(db):
    """Список проблем настройки (пустой — всё в порядке)."""
    s = settings(db)
    problems = []
    if not s['folder']:
        problems.append('Не выбрана папка для копий.')
    elif not os.path.isdir(s['folder']):
        problems.append('Папка для копий недоступна: ' + s['folder'])
    else:
        try:
            if os.stat(s['folder']).st_dev == os.stat(Path(db.db_name).parent).st_dev:
                problems.append('Папка находится на том же диске, что и база: при поломке диска пропадут и база, и копия. Выберите другой диск или облачную папку.')
        except OSError:
            pass
    if len(s['password']) < 10:
        problems.append('Пароль копий — минимум 10 символов.')
    return problems


def list_copies(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.glob(PREFIX + '*' + SUFFIX) if p.is_file()), key=lambda p: p.name)


def make_copy(db, now=None):
    """Создаёт зашифрованную копию в папке, удаляет старые сверх лимита. Возвращает путь к новой копии."""
    s = settings(db)
    now = now or datetime.now()
    if not s['folder'] or not os.path.isdir(s['folder']):
        raise ValueError('Папка для копий недоступна: ' + (s['folder'] or '(не выбрана)'))
    if len(s['password']) < 10:
        raise ValueError('Пароль копий — минимум 10 символов')
    folder = Path(s['folder'])
    target = folder / f'{PREFIX}{now:%Y%m%d_%H%M%S}{SUFFIX}'
    with tempfile.TemporaryDirectory(prefix='smetagaz-offsite-') as tmp:
        archive = Path(tmp) / 'data.zip'
        create_backup(db, archive)
        part = folder / (target.name + '.part')
        try:
            encrypt_backup(archive, part, s['password'])
            if part.stat().st_size < 100:
                raise ValueError('Копия получилась пустой')
            os.replace(part, target)
        finally:
            part.unlink(missing_ok=True)
    (folder / (target.name + '.sha256')).write_text(digest(target), encoding='utf-8')
    for old in list_copies(folder)[:-max(1, s['keep'])]:
        old.unlink(missing_ok=True)
        (folder / (old.name + '.sha256')).unlink(missing_ok=True)
    db.set_setting('last_offsite_backup', now.isoformat(timespec='seconds'))
    db.set_setting('offsite_status', f'{now:%d.%m.%Y %H:%M}: копия создана — {target.name} ({target.stat().st_size / 1e6:.1f} МБ)')
    return target


def verify_copy(path, password, live_db=None):
    """Проверка восстановлением: расшифровка, распаковка в новую временную папку, контрольные суммы, целостность баз, число записей в основных таблицах.
    Возвращает {'ok': bool, 'tables': {...}, 'error': str}. Рабочие данные не затрагиваются."""
    path = Path(path)
    result = dict(ok=False, tables={}, error='')
    sha = path.with_name(path.name + '.sha256')
    try:
        if sha.exists() and sha.read_text(encoding='utf-8').strip() != digest(path):
            raise ValueError('Файл копии изменился или повреждён (не совпала контрольная сумма)')
        with tempfile.TemporaryDirectory(prefix='smetagaz-verify-') as tmp:
            archive = Path(tmp) / 'data.zip'
            decrypt_backup(path, archive, password)
            restored = Path(tmp) / 'restored'
            restore_backup(archive, restored)
            with sqlite3.connect(restored / 'smetagaz.db') as con:
                for table in KEY_TABLES:
                    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        result['tables'][table] = con.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            with sqlite3.connect(restored / 'clients.db') as con:
                result['tables']['clients'] = con.execute('SELECT count(*) FROM clients').fetchone()[0]
        if not result['tables'].get('settings'):
            raise ValueError('В восстановленной базе нет настроек — копия неполная')
        result['ok'] = True
    except Exception as e:
        result['error'] = str(e)
    return result


def verify_latest(db, now=None):
    """Проверяет самую свежую копию и записывает итог в настройки. Возвращает текст итога."""
    s = settings(db)
    now = now or datetime.now()
    copies = list_copies(s['folder']) if s['folder'] else []
    if not copies:
        message = f'{now:%d.%m.%Y %H:%M}: проверка невозможна — в папке нет копий'
        ok = False
    else:
        res = verify_copy(copies[-1], s['password'], db)
        ok = res['ok']
        if ok:
            tables = ', '.join(f'{k}: {v}' for k, v in res['tables'].items() if k in ('estimates', 'contracts', 'clients', 'payments'))
            message = f'{now:%d.%m.%Y %H:%M}: восстановление проверено — {copies[-1].name} ({tables})'
        else:
            message = f'{now:%d.%m.%Y %H:%M}: ОШИБКА проверки {copies[-1].name} — {res["error"]}'
    db.set_setting('offsite_verify_status', message)
    db.set_setting('offsite_verify_ok', '1' if ok else '0')
    db.set_setting('last_offsite_verify', now.isoformat(timespec='seconds'))
    return message


def _parse(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min


def due(db, now=None):
    """(пора ли делать копию, пора ли проверять восстановлением)."""
    if not configured(db):
        return False, False
    now = now or datetime.now()
    s = settings(db)
    backup_due = now - _parse(db.get_setting('last_offsite_backup', '')) >= timedelta(hours=s['interval_h'])
    verify_due = now - _parse(db.get_setting('last_offsite_verify', '')) >= timedelta(days=VERIFY_DAYS) and bool(list_copies(s['folder']))
    return backup_due, verify_due


def run_scheduled(db, now=None):
    """Вызывается службой раз в минуту: делает копию и/или проверку, если пора. Ошибки пишутся в статус, а не выбрасываются."""
    now = now or datetime.now()
    backup_due, verify_due = due(db, now)
    done = []
    if backup_due:
        try:
            done.append(str(make_copy(db, now)))
        except Exception as e:
            db.set_setting('last_offsite_backup', now.isoformat(timespec='seconds'))   # не долбить диск каждую минуту; повтор через интервал
            db.set_setting('offsite_status', f'{now:%d.%m.%Y %H:%M}: ОШИБКА копии вне компьютера — {e}')
    if verify_due:
        done.append(verify_latest(db, now))
    return done


def status_text(db):
    return db.get_setting('offsite_status', 'Копий вне компьютера пока нет'), db.get_setting('offsite_verify_status', 'Проверка восстановлением ещё не проводилась')
