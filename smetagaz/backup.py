"""Consistent database snapshots, streamed archives and verified isolated restore."""
import hashlib
import json
import os
import shutil
import sqlite3
from .sqlite_util import connect
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from .asset_registry import fields, quote, rebase, MANAGED_FOLDERS


def flush_to_disk(path):
    """Сбрасывает файл на диск. В Windows fsync допустим только для файла, открытого на запись («r+b»); на чтение он даёт [Errno 9].
    Сбой сброса не должен ломать копию — файл уже записан и закрыт."""
    try:
        with open(path,'r+b') as f:os.fsync(f.fileno())
    except OSError:
        pass


def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def create_backup(db, destination, progress=None):
    """progress(сделано, всего, текст) — необязательный обратный вызов; он же может прервать копирование исключением (до этого момента итоговый файл не тронут)."""
    step = progress or (lambda *a, **k: None)
    step(0, 0, 'Снимок баз данных')
    destination=Path(destination).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        stage=Path(tmp)
        missing=[]
        external_references=[]
        directory_mappings={}
        db.snapshot_databases(stage)
        data_root=Path(db.db_name).parent.resolve()
        # Include generated and not-yet-linked managed documents as well.
        for dirname in MANAGED_FOLDERS:
            source=data_root/dirname
            if source.is_symlink():raise ValueError('Символическая ссылка в папке данных: '+str(source))
            if source.is_dir():
                for item in source.rglob('*'):
                    step(0, 0, 'Копирование файлов: ' + item.name)
                    if item.is_symlink():raise ValueError('Символическая ссылка в папке данных: '+str(item))
                    if item.is_file() and not item.name.endswith('.part'):
                        target=stage/item.relative_to(data_root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,target)
        with connect(stage/'smetagaz.db') as snapshot:
            # пароль внешних копий и их автозапуск не должны попадать в обычный архив; после восстановления их настраивают заново
            snapshot.execute("UPDATE settings SET value='' WHERE key='offsite_password'")
            snapshot.execute("UPDATE settings SET value='0' WHERE key='offsite_enabled'")
            if snapshot.execute("SELECT 1 FROM sqlite_master WHERE name='welding_documents'").fetchone():
                external_references=[dict(id=r[0],title=r[1],path=r[2]) for r in snapshot.execute('SELECT id,title,file_path FROM welding_documents')]
            for table,column in fields(snapshot):
                for rid,value in snapshot.execute(f'SELECT rowid,{quote(column)} FROM {quote(table)} WHERE {quote(column)} IS NOT NULL AND {quote(column)}<>\'\'').fetchall():
                    src=Path(value).expanduser()
                    if not src.is_absolute(): src=Path(db.db_name).parent/src
                    if not src.exists():
                        missing.append({'table':table,'id':rid,'field':column,'path':value});continue
                    if src.is_symlink() or (src.is_dir() and any(f.is_symlink() for f in src.rglob('*'))):raise ValueError('Ссылки во вложениях не поддерживаются')
                    resolved=src.resolve()
                    if src.is_dir() and (destination.is_relative_to(resolved) or stage.resolve().is_relative_to(resolved)):
                        raise ValueError("Резервную копию нельзя сохранять внутри папки документов договора: "+str(resolved))
                    mapped=next(((base,rel) for base,rel in sorted(directory_mappings.items(),key=lambda item:len(item[0].parts),reverse=True) if resolved.is_relative_to(base)),None)
                    if mapped:relative=mapped[1]/resolved.relative_to(mapped[0])
                    else:relative=resolved.relative_to(data_root) if resolved.is_relative_to(data_root) and bool(resolved.relative_to(data_root).parts) and resolved.relative_to(data_root).parts[0] in MANAGED_FOLDERS else Path('files')/table/str(rid)/column/src.name
                    if src.is_dir():directory_mappings[resolved]=relative
                    target=stage/relative
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if not target.exists():
                        if src.is_dir(): shutil.copytree(src,target,symlinks=False)
                        else: shutil.copy2(src,target)
                    snapshot.execute(f'UPDATE {quote(table)} SET {quote(column)}=? WHERE rowid=?',(relative.as_posix(),rid))
            # Export templates stored in settings must travel with the backup.
            for key,value in snapshot.execute("SELECT key,value FROM settings WHERE key LIKE '%template%'").fetchall():
                src=Path(value or '')
                if value and not src.is_absolute():src=data_root/src
                if value and src.is_file():
                    dest=Path('templates')/(hashlib.sha256(key.encode()).hexdigest()[:16]+'_'+src.name);(stage/dest).parent.mkdir(exist_ok=True)
                    shutil.copy2(src,stage/dest);snapshot.execute('UPDATE settings SET value=? WHERE key=?',(dest.as_posix(),key))
        staged = [f for f in stage.rglob('*') if f.is_file()]
        files = {}
        for n, f in enumerate(staged, 1):
            step(n, len(staged), 'Контрольные суммы: ' + f.name)
            files[f.relative_to(stage).as_posix()] = digest(f)
        manifest={'version':1,'created':datetime.now(timezone.utc).isoformat(),'files':files,'missing':missing,'external_welding_references':external_references}
        (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        temp_archive=stage/'archive.tmp'
        with zipfile.ZipFile(temp_archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
            names = [*files, 'manifest.json']
            for n, name in enumerate(names, 1):
                step(n, len(names), 'Архивирование: ' + name)
                z.write(stage/name, name)
        flush_to_disk(temp_archive)
        os.replace(temp_archive,destination)
        try:destination.chmod(0o600)
        except OSError:pass
    return manifest


def restore_backup(archive, destination):
    """Restore to a NEW folder only. Never overwrite a running or existing database."""
    destination=Path(destination).resolve()
    if destination.exists(): raise ValueError('Выберите новую, ещё не существующую папку')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        stage=Path(tmp)/'restored';stage.mkdir()
        with zipfile.ZipFile(archive) as z:
            infos=z.infolist()
            if len({i.filename for i in infos})!=len(infos):raise ValueError('Повторяющиеся файлы в архиве')
            if sum(i.file_size for i in infos)>shutil.disk_usage(stage).free:raise ValueError('Недостаточно места')
            for item in infos:
                path=Path(item.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in item.filename or ':' in item.filename:raise ValueError('Небезопасный путь в архиве')
                if (item.external_attr>>16)&0o170000==0o120000:raise ValueError('Ссылки в архиве запрещены')
            z.extractall(stage)
        manifest=json.loads((stage/'manifest.json').read_text(encoding='utf-8'))
        actual={f.relative_to(stage).as_posix() for f in stage.rglob('*') if f.is_file()}
        manifest['files']={name.replace('\\','/'):value for name,value in manifest.get('files',{}).items()}      # старые манифесты Windows
        if actual!=set(manifest['files'])|{'manifest.json'}:raise ValueError('Состав архива не совпадает с описанием')
        if manifest.get('version')!=1:raise ValueError('Неизвестный формат копии')
        if not {'smetagaz.db','clients.db'}<=set(manifest['files']):raise ValueError('Нет обязательных баз')
        for name,expected in manifest['files'].items():
            target=(stage/name).resolve()
            if not target.is_relative_to(stage.resolve()) or digest(target)!=expected:raise ValueError('Контрольная сумма не совпадает')
        for name in ['smetagaz.db','clients.db']:
            with connect(stage/name) as c:
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Повреждена база '+name)
        with connect(stage/'smetagaz.db') as c:
            rebase(c, stage, destination)
        os.replace(stage,destination)
        destination.chmod(0o700)
    return manifest
