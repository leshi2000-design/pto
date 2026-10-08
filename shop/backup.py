"""Verified SQLite snapshots and safe restore into a new directory."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def create(store, destination=None):
    destination = Path(destination or store.root / 'backups' / (datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f') + '.zip')).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        stage = Path(tmp)
        with sqlite3.connect(stage / 'shop.db') as target:
            store.conn.backup(target)
        for folder in ('templates', 'documents', 'sources'):
            source = store.root / folder
            for path in source.rglob('*'):
                if path.is_symlink():
                    raise ValueError('Ссылки в папке данных не поддерживаются')
                if path.is_file():
                    out = stage / path.relative_to(store.root)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, out)
        files = {p.relative_to(stage).as_posix(): digest(p) for p in stage.rglob('*') if p.is_file()}
        (stage / 'manifest.json').write_text(json.dumps({'version': 1, 'files': files}, ensure_ascii=False), encoding='utf-8')
        archive = stage / 'backup.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in (*files, 'manifest.json'):
                z.write(stage / name, name)
        archive.replace(destination)
    return destination


def restore(archive, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Выберите новую, ещё не существующую папку')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        stage = Path(tmp) / 'data'
        stage.mkdir()
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
            names = [entry.filename for entry in infos]
            if len(names) != len(set(names)) or sum(entry.file_size for entry in infos) > 2 * 1024**3:
                raise ValueError('Некорректный или слишком большой архив')
            manifest = json.loads(z.read('manifest.json'))
            if manifest.get('version') != 1 or set(names) != set(manifest['files']) | {'manifest.json'} or 'shop.db' not in manifest['files']:
                raise ValueError('Некорректный состав архива')
            for name, expected in manifest['files'].items():
                path = (stage / name).resolve()
                if not path.is_relative_to(stage) or '\\' in name or name.startswith('/'):
                    raise ValueError('Небезопасный путь в архиве')
                path.parent.mkdir(parents=True, exist_ok=True)
                with z.open(name) as source, path.open('wb') as target:
                    shutil.copyfileobj(source, target)
                if digest(path) != expected:
                    raise ValueError('Контрольная сумма не совпала: ' + name)
        with sqlite3.connect(stage / 'shop.db') as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('Повреждена база данных')
        stage.rename(destination)
    return destination
