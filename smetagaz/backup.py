"""Consistent database snapshots, streamed archives and verified isolated restore."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timezone


def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def create_backup(db, destination):
    destination=Path(destination).resolve()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        stage=Path(tmp)
        missing=[]
        external_references=[]
        directory_mappings={}
        with db._lock:
            # No application writes between these two snapshots or attachment enumeration.
            for schema,name in [('main','smetagaz.db'),('crm','clients.db')]:
                with sqlite3.connect(stage/name) as target: db.conn.backup(target,name=schema)
        data_root=Path(db.db_name).parent.resolve()
        # Include generated and not-yet-linked managed documents as well.
        for dirname in ['projects','templates','attachments','certificates_storage']:
            source=data_root/dirname
            if source.is_dir():
                for item in source.rglob('*'):
                    if item.is_symlink():raise ValueError('Символическая ссылка в папке данных: '+str(item))
                    if item.is_file() and not item.name.endswith('.part'):
                        target=stage/item.relative_to(data_root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,target)
        with sqlite3.connect(stage/'smetagaz.db') as snapshot:
            if snapshot.execute("SELECT 1 FROM sqlite_master WHERE name='welding_documents'").fetchone():
                external_references=[dict(id=r[0],title=r[1],path=r[2]) for r in snapshot.execute('SELECT id,title,file_path FROM welding_documents')]
            for table,column in [('attachments','file_path'),('certificates','file_path'),('gsv_projects','tu_path'),('gsv_projects','custom_contract_path'),('gsv_projects','project_folder'),('executive_objects','folder_path'),('executive_templates','file_path'),('executive_overrides','file_path'),('executive_generated','file_path'),('report_templates','file_path'),('dossiers','folder_path'),('dossier_files','file_path')]:
                if not snapshot.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():continue
                for rid,value in snapshot.execute(f'SELECT id,{column} FROM {table} WHERE {column} IS NOT NULL AND {column}<>""').fetchall():
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
                    else:relative=resolved.relative_to(data_root) if resolved.is_relative_to(data_root) and bool(resolved.relative_to(data_root).parts) and resolved.relative_to(data_root).parts[0] in ['projects','templates','attachments','certificates_storage'] else Path('files')/table/str(rid)/column/src.name
                    if src.is_dir():directory_mappings[resolved]=relative
                    target=stage/relative
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if not target.exists():
                        if src.is_dir(): shutil.copytree(src,target,symlinks=False)
                        else: shutil.copy2(src,target)
                    snapshot.execute(f'UPDATE {table} SET {column}=? WHERE id=?',(relative.as_posix(),rid))
            # Export templates stored in settings must travel with the backup.
            for key,value in snapshot.execute("SELECT key,value FROM settings WHERE key LIKE '%template%'").fetchall():
                src=Path(value or '')
                if value and src.is_file():
                    dest=Path('templates')/(key+'_'+src.name);(stage/dest).parent.mkdir(exist_ok=True)
                    shutil.copy2(src,stage/dest);snapshot.execute('UPDATE settings SET value=? WHERE key=?',(dest.as_posix(),key))
        files={str(f.relative_to(stage)):digest(f) for f in stage.rglob('*') if f.is_file()}
        manifest={'version':1,'created':datetime.now(timezone.utc).isoformat(),'files':files,'missing':missing,'external_welding_references':external_references}
        (stage/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        temp_archive=stage/'archive.tmp'
        with zipfile.ZipFile(temp_archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
            for name in [*files,'manifest.json']:z.write(stage/name,name)
        with open(temp_archive,'rb') as f:os.fsync(f.fileno())
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
        actual={str(f.relative_to(stage)) for f in stage.rglob('*') if f.is_file()}
        if actual!=set(manifest.get('files',{}))|{'manifest.json'}:raise ValueError('Состав архива не совпадает с описанием')
        if manifest.get('version')!=1:raise ValueError('Неизвестный формат копии')
        if not {'smetagaz.db','clients.db'}<=set(manifest['files']):raise ValueError('Нет обязательных баз')
        for name,expected in manifest['files'].items():
            target=(stage/name).resolve()
            if not target.is_relative_to(stage.resolve()) or digest(target)!=expected:raise ValueError('Контрольная сумма не совпадает')
        for name in ['smetagaz.db','clients.db']:
            with sqlite3.connect(stage/name) as c:
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Повреждена база '+name)
        os.replace(stage,destination)
        destination.chmod(0o700)
    return manifest
