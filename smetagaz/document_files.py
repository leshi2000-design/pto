"""Publish a batch to user-chosen folders, staging beside each destination.

Works across Windows volumes; rolls back replaced files if rendering, publishing
or recording document history fails. No UI is called from worker threads.
"""
import hashlib
import os
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path


def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def validate_destinations(jobs, destinations):
    """jobs: [{key,path,source}]; preserve exactly the confirmed file names."""
    jobs = [dict(job) for job in jobs]
    if destinations is not None and set(destinations) != {job['key'] for job in jobs}:
        raise ValueError('Выберите путь для каждого документа комплекта')
    sources = {Path(job['source']).resolve() for job in jobs}
    used = set()
    for job in jobs:
        path = Path(destinations[job['key']] if destinations is not None else job['path']).expanduser().absolute()
        if path.suffix.lower() != Path(job['source']).suffix.lower():
            raise ValueError('Формат результата должен совпадать с форматом исходного документа')
        key = str(path.resolve()).casefold()
        if key in used or path.resolve() in sources:
            raise ValueError('Пути документов совпадают друг с другом или с исходным файлом')
        used.add(key)
        job['path'] = path
    return jobs


def publish_files(jobs, record):
    """jobs: [(path, writer(staged_path))]. record({path: sha256}) runs last."""
    with ExitStack() as stack:
        staged, backups, published = [], [], []
        hashes = {}
        for path, writer in jobs:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='.pto-document-', dir=path.parent)))
            new = temp / ('new' + path.suffix)
            writer(new)
            with new.open('r+b') as output:
                os.fsync(output.fileno())
            hashes[str(path)] = digest(new)
            staged.append((path, new, temp))
        try:
            for path, new, temp in staged:
                if path.exists():
                    saved = temp / 'previous'
                    shutil.copy2(path, saved)
                    backups.append((path, saved))
                os.replace(new, path)
                published.append(path)
            record(hashes)
        except BaseException:
            for path in published:
                path.unlink(missing_ok=True)
            for path, saved in backups:
                os.replace(saved, path)
            raise
