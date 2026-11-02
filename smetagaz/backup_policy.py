"""Политика автоматических копий: частые копии — только базы данных (малый размер), полная копия с вложениями — раз в сутки, общий лимит места.

Раньше каждый час делалась полная копия со всеми вложениями и папками договоров и хранились последние 24 — при гигабайтах документов это десятки гигабайт."""
import shutil
import tempfile
from pathlib import Path

HOURLY_KEEP = 24          # db_*.zip — только базы, каждый час
FULL_KEEP = 3             # full_*.zip — полная копия с файлами, раз в сутки
LEGACY_KEEP = 2           # auto_*.zip — полные почасовые копии прежних версий
DEFAULT_CAP_GB = 10
PATTERNS = (('db_', 'db_*.zip'), ('full_', 'full_*.zip'), ('auto_', 'auto_*.zip'))


def cap_bytes(db):
    try:
        gb = float(str(db.get_setting('backup_max_gb', str(DEFAULT_CAP_GB)) or DEFAULT_CAP_GB).replace(',', '.'))
    except ValueError:
        gb = DEFAULT_CAP_GB
    return int(max(1.0, gb) * 1024 ** 3)


def _files(folder, pattern):
    return sorted((p for p in Path(folder).glob(pattern) if p.is_file() and not p.is_symlink()), key=lambda p: p.name)


def summary(folder):
    """{'total': байт, 'count': файлов, 'db': (файлов, байт), 'full': (...), 'legacy': (...)} по автоматическим копиям."""
    out, total, count = {}, 0, 0
    for key, (_prefix, pattern) in zip(('db', 'full', 'legacy'), PATTERNS):
        files = _files(folder, pattern)
        size = sum(p.stat().st_size for p in files)
        out[key] = (len(files), size)
        total += size
        count += len(files)
    out['total'], out['count'] = total, count
    return out


def prune(folder, cap=None, hourly=HOURLY_KEEP, full=FULL_KEEP, legacy=LEGACY_KEEP):
    """Удаляет старые автоматические копии сверх лимитов по количеству, затем — пока общий размер больше cap — самые старые (последняя копия баз остаётся всегда).
    Возвращает список удалённых файлов."""
    removed = []

    def drop(path):
        try:
            size = path.stat().st_size
            path.unlink()
            removed.append((path.name, size))
        except OSError:
            pass
    for (_prefix, pattern), keep in zip(PATTERNS, (hourly, full, legacy)):
        for old in _files(folder, pattern)[:-keep] if keep else _files(folder, pattern):
            drop(old)
    if cap:
        def total():
            return sum(p.stat().st_size for _k, pat in PATTERNS for p in _files(folder, pat))
        for pattern, keep_last in ((PATTERNS[2][1], 0), (PATTERNS[1][1], 1), (PATTERNS[0][1], 1)):
            files = _files(folder, pattern)
            while total() > cap and len(files) > keep_last:
                drop(files.pop(0))
    return removed


def estimate_files_size(db):
    """Сколько места займут вложения и папки договоров в полной копии (без сжатия) — по снимку баз."""
    from .asset_registry import fields, MANAGED_FOLDERS
    from .sqlite_util import connect
    data_root = Path(db.db_name).parent.resolve()
    seen, total = set(), 0

    def add(path):
        nonlocal total
        try:
            path = path.resolve()
        except OSError:
            return
        if path in seen:
            return
        seen.add(path)
        if path.is_file():
            total += path.stat().st_size
        elif path.is_dir():
            for f in path.rglob('*'):
                try:
                    if f.is_file() and not f.is_symlink() and f.resolve() not in seen:
                        seen.add(f.resolve())
                        total += f.stat().st_size
                except OSError:
                    continue
    for name in MANAGED_FOLDERS:
        add(data_root / name)
    with tempfile.TemporaryDirectory() as tmp:
        db.snapshot_databases(Path(tmp))
        with connect(Path(tmp) / 'smetagaz.db') as snap:
            for table, column in fields(snap):
                q = '"' + table.replace('"', '""') + '"', '"' + column.replace('"', '""') + '"'
                for (value,) in snap.execute(f'SELECT {q[1]} FROM {q[0]} WHERE {q[1]} IS NOT NULL AND {q[1]}<>\'\'').fetchall():
                    src = Path(value).expanduser()
                    if not src.is_absolute():
                        src = data_root / src
                    if src.exists():
                        add(src)
    return total


def full_backup_allowed(db, folder):
    """(можно ли делать полную копию, причина отказа): размер вложений не больше лимита и на диске хватает места с запасом."""
    cap = cap_bytes(db)
    size = estimate_files_size(db)
    if size > cap:
        return False, f'вложения занимают {size / 1024 ** 3:.1f} ГБ — больше лимита копий {cap / 1024 ** 3:.0f} ГБ'
    free = shutil.disk_usage(folder).free
    if free < size * 1.5 + 200 * 1024 ** 2:
        return False, f'на диске свободно {free / 1024 ** 3:.1f} ГБ — для копии нужно примерно {size * 1.5 / 1024 ** 3:.1f} ГБ'
    return True, ''
