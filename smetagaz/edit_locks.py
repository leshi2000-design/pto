"""Блокировка карточек от одновременной правки. Запись о том, кто открыл карточку, хранится в самой базе (таблица edit_locks),
поэтому работает одинаково в сети, в локальном режиме рядом с ПТО Сервером и между двумя окнами программы.
Запись «живёт» только пока карточка открыта: программа обновляет её каждые BEAT секунд, а брошенная (сбой, обрыв связи) устаревает через STALE секунд.
Время берётся с часов базы (сервера), поэтому расхождение часов компьютеров не мешает."""
import getpass
import logging
import socket
import uuid

from .database import db as default_db

STALE = 90          # секунд без обновления — запись считается брошенной
BEAT = 25           # как часто открытая карточка подтверждает, что она ещё открыта
SID = uuid.uuid4().hex          # отличает этот запуск программы от других (даже того же пользователя)
_held = {}                      # key -> сколько раз открыто в этом запуске (карточка может открываться из карточки)


def migrate(db):
    db.execute('CREATE TABLE IF NOT EXISTS edit_locks(key TEXT PRIMARY KEY, sid TEXT NOT NULL, user TEXT DEFAULT "", host TEXT DEFAULT "", since TEXT DEFAULT "", beat INTEGER NOT NULL DEFAULT 0)')


def who(db):
    name = str(getattr(db, 'user', '') or '').strip()
    if not name:
        try:
            name = getpass.getuser()
        except Exception:
            name = 'пользователь'
    return name, socket.gethostname()


def _now():
    return "CAST(strftime('%s','now') AS INTEGER)"


def _take(db, key):
    """Занимает карточку (или подтверждает, что она уже наша). -> None или сведения о том, кто её правит."""
    user, host = who(db)
    with db.transaction():
        db.execute(f'DELETE FROM edit_locks WHERE beat < {_now()} - ?', (STALE,))
        row = db.fetchone('SELECT sid,user,host,since FROM edit_locks WHERE key=?', (key,))
        if row and row[0] != SID:
            return dict(user=row[1], host=row[2], since=row[3])
        if row:
            db.execute(f'UPDATE edit_locks SET user=?,host=?,beat={_now()} WHERE key=?', (user, host, key))
        else:
            db.execute(f"INSERT INTO edit_locks(key,sid,user,host,since,beat) VALUES(?,?,?,?,strftime('%H:%M','now','localtime'),{_now()})", (key, SID, user, host))
    return None


def acquire(db, key):
    """-> None, если карточка теперь занята нами; иначе {'user','host','since'} того, кто её правит."""
    if getattr(db, 'role', '') == 'viewer':
        return None                                     # наблюдатель всё равно ничего не сохранит
    try:
        other = _take(db, key)
    except Exception:
        logging.exception('Не удалось проверить блокировку карточки %s', key)
        return None                                     # блокировка — помощник: при сбое карточку всё равно можно открыть
    if other is None:
        _held[key] = _held.get(key, 0) + 1
    return other


def beat(db, key):
    """Подтверждение. -> None, если карточка всё ещё наша; иначе сведения о новом владельце (запись устарела и её заняли другие)."""
    if getattr(db, 'role', '') == 'viewer':
        return None
    try:
        return _take(db, key)
    except Exception:
        logging.exception('Не удалось подтвердить блокировку карточки %s', key)
        return None


def release(db, key):
    if not _held.get(key):
        return
    _held[key] -= 1
    if _held[key] > 0:
        return
    _held.pop(key, None)
    try:
        db.execute('DELETE FROM edit_locks WHERE key=? AND sid=?', (key, SID))
    except Exception:
        logging.exception('Не удалось снять блокировку карточки %s', key)


def release_all(db=None):
    """При закрытии программы."""
    _held.clear()
    try:
        (db or default_db).execute('DELETE FROM edit_locks WHERE sid=?', (SID,))
    except Exception:
        pass


def holders(db):
    """Список занятых карточек (для окна сервера и проверок)."""
    return db.fetchall(f'SELECT key,user,host,since FROM edit_locks WHERE beat >= {_now()} - ? ORDER BY since', (STALE,))
