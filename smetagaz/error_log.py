"""Журнал ошибок: всё, что программа записала как ошибку (необработанные исключения, сбои фоновых операций, копирования, выгрузок),
плюс предупреждения, показанные пользователю окнами «не сохранено». Хранится в отдельном файле errors.db рядом с базой, чтобы сбой базы
не мешал записи. Одинаковые ошибки подряд складываются в одну строку со счётчиком."""
import logging
import re
import sys
import threading
import traceback
from datetime import datetime, timedelta

from .config import DATA_DIR
from .sqlite_util import connect

PATH = DATA_DIR / 'errors.db'
KEEP_DAYS = 90
KEEP_ROWS = 2000
_lock = threading.Lock()
_context = {'section': ''}
_guard = threading.local()


def _init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS errors(id INTEGER PRIMARY KEY, first_ts TEXT, last_ts TEXT, level TEXT, source TEXT, section TEXT,
                   message TEXT, trace TEXT, signature TEXT, count INTEGER DEFAULT 1, seen INTEGER DEFAULT 0)""")
    con.execute('CREATE INDEX IF NOT EXISTS idx_errors_sig ON errors(signature,last_ts)')


def set_section(name):
    """Раздел, в котором сейчас работает пользователь: попадёт в запись об ошибке."""
    _context['section'] = name or ''


def _signature(level, message, trace):
    last = ''
    lines = [l for l in (trace or '').strip().splitlines() if l.strip()]
    if lines:
        last = lines[-1]
    return re.sub(r'\d+', '#', f'{level}|{(message or "")[:120]}|{last[:160]}')


def record(level, source, message, trace='', section=None):
    """Записывает ошибку; никогда не бросает исключений (журнал не должен ломать программу)."""
    if getattr(_guard, 'busy', False):
        return
    _guard.busy = True
    try:
        now = datetime.now().isoformat(timespec='seconds')
        sig = _signature(level, message, trace)
        with _lock, connect(PATH, timeout=5) as con:
            _init(con)
            row = con.execute('SELECT id FROM errors WHERE signature=? AND last_ts>=? ORDER BY id DESC LIMIT 1',
                              (sig, (datetime.now() - timedelta(days=1)).isoformat(timespec='seconds'))).fetchone()
            if row:
                con.execute('UPDATE errors SET count=count+1,last_ts=?,seen=0 WHERE id=?', (now, row[0]))
            else:
                con.execute('INSERT INTO errors(first_ts,last_ts,level,source,section,message,trace,signature) VALUES(?,?,?,?,?,?,?,?)',
                            (now, now, level, source, _context['section'] if section is None else section, (message or '')[:2000], (trace or '')[:20000], sig))
    except Exception:
        pass
    finally:
        _guard.busy = False


class Handler(logging.Handler):
    """Передаёт в журнал записи logging уровня ERROR и выше (logging.exception, critical)."""
    def __init__(self):
        super().__init__(level=logging.ERROR)

    def emit(self, rec):
        try:
            trace = ''.join(traceback.format_exception(*rec.exc_info)) if rec.exc_info else ''
            level = 'Критическая' if rec.levelno >= logging.CRITICAL else 'Ошибка'
            record(level, rec.name if rec.name != 'root' else 'программа', rec.getMessage(), trace)
        except Exception:
            pass


def install():
    """Подключает журнал: logging, необработанные исключения в потоках и окна с предупреждениями. Безопасно вызывать повторно."""
    root = logging.getLogger()
    if not any(isinstance(h, Handler) for h in root.handlers):
        root.addHandler(Handler())
    if not getattr(threading, '_pto_errlog', False):
        threading._pto_errlog = True
        old = threading.excepthook

        def hook(args):
            record('Ошибка', 'фоновый поток', str(args.exc_value), ''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
            old(args)
        threading.excepthook = hook
    try:
        from PyQt6.QtWidgets import QMessageBox
        if not getattr(QMessageBox, '_pto_errlog', False):
            QMessageBox._pto_errlog = True
            for name, level in (('warning', 'Предупреждение'), ('critical', 'Ошибка')):
                original = getattr(QMessageBox, name)

                def wrapper(*args, _o=original, _l=level, **kwargs):
                    title = args[1] if len(args) > 1 else kwargs.get('title', '')
                    text = args[2] if len(args) > 2 else kwargs.get('text', '')
                    record(_l, 'окно сообщения', f'{title}: {text}')
                    return _o(*args, **kwargs)
                setattr(QMessageBox, name, staticmethod(wrapper))
    except Exception:
        pass


def entries(level='', search='', limit=500):
    where, args = [], []
    if level:
        where.append('level=?')
        args.append(level)
    if search:
        where.append("(message LIKE ? OR section LIKE ? OR source LIKE ? OR trace LIKE ?)")
        args += [f'%{search}%'] * 4
    sql = 'SELECT id,first_ts,last_ts,level,source,section,message,trace,count,seen FROM errors' + (' WHERE ' + ' AND '.join(where) if where else '') + ' ORDER BY last_ts DESC,id DESC LIMIT ?'
    try:
        with _lock, connect(PATH, timeout=5) as con:
            _init(con)
            return con.execute(sql, (*args, limit)).fetchall()
    except Exception:
        return []


def unseen_count():
    try:
        with _lock, connect(PATH, timeout=5) as con:
            _init(con)
            return con.execute('SELECT coalesce(sum(1),0) FROM errors WHERE seen=0').fetchone()[0]
    except Exception:
        return 0


def mark_seen():
    try:
        with _lock, connect(PATH, timeout=5) as con:
            _init(con)
            con.execute('UPDATE errors SET seen=1 WHERE seen=0')
    except Exception:
        pass


def clear():
    with _lock, connect(PATH, timeout=5) as con:
        _init(con)
        con.execute('DELETE FROM errors')


def purge():
    """Старше KEEP_DAYS дней и сверх KEEP_ROWS строк удаляется."""
    try:
        with _lock, connect(PATH, timeout=5) as con:
            _init(con)
            con.execute('DELETE FROM errors WHERE last_ts<?', ((datetime.now() - timedelta(days=KEEP_DAYS)).isoformat(timespec='seconds'),))
            con.execute('DELETE FROM errors WHERE id NOT IN (SELECT id FROM errors ORDER BY id DESC LIMIT ?)', (KEEP_ROWS,))
    except Exception:
        pass


def report_text(rows=None):
    """Текстовый отчёт для разработчика: версия, система и записи (без содержимого базы)."""
    from . import __version__
    import platform
    rows = entries(limit=200) if rows is None else rows
    out = [f'ПТО {__version__} · Python {sys.version.split()[0]} · {platform.platform()}', f'Записей: {len(rows)}', '']
    for r in rows:
        out.append(f'[{r[2]}] {r[3]} · {r[4]} · раздел: {r[5] or "—"} · повторов: {r[8]}\n{r[6]}')
        if r[7]:
            out.append(r[7].rstrip())
        out.append('-' * 60)
    return '\n'.join(out)
