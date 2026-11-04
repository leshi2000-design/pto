import os
import time
import zipfile
import pytest
from smetagaz.database import DatabaseManager
from smetagaz import backup, backup_policy as bp


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def make(folder, name, size):
    p = folder / name
    p.write_bytes(b'x' * size)
    return p


def test_prune_counts_and_cap(tmp_path):
    f = tmp_path
    for i in range(30):
        make(f, f'db_2026010{i // 10}_{i:06d}.zip', 10)
    for i in range(5):
        make(f, f'full_20260101_{i:06d}.zip', 1000)
    for i in range(6):
        make(f, f'auto_20250101_{i:06d}.zip', 5000)
    keep_other = make(f, 'before_import_x.zip', 5)
    removed = bp.prune(f)
    s = bp.summary(f)
    assert s['db'][0] == 24 and s['full'][0] == 3 and s['legacy'][0] == 2 and keep_other.exists() and len(removed) == 6 + 2 + 4
    # лимит места: сначала уходят прежние, потом старые полные; последняя копия баз и последняя полная остаются
    bp.prune(f, cap=2500)
    s = bp.summary(f)
    assert s['legacy'][0] == 0 and s['full'][0] == 2 and s['db'][0] == 24 and s['total'] <= 2500 + 24 * 10
    bp.prune(f, cap=300)
    s = bp.summary(f)
    assert s['full'][0] == 1 and s['db'][0] >= 1


def test_database_only_backup_is_small_and_restorable(db, tmp_path):
    folder = tmp_path / 'docs'
    folder.mkdir()
    big = folder / 'scan.pdf'
    big.write_bytes(os.urandom(2_000_000))
    db.execute("INSERT INTO gsv_projects(object_name,contract_folder) VALUES('Объект',?)", (str(folder),)) if False else None
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(contracts)')}
    db.execute('INSERT INTO contracts(contract_number,contract_folder) VALUES(?,?)', ('01-02/26', str(folder)))
    small = tmp_path / 'db.zip'
    full = tmp_path / 'full.zip'
    m1 = backup.create_backup(db, small, include_files=False)
    m2 = backup.create_backup(db, full, include_files=True)
    assert m1['files_included'] is False and m2['files_included'] is True
    assert small.stat().st_size < 1_500_000 < full.stat().st_size                 # вложения в копию баз не попадают
    names = zipfile.ZipFile(small).namelist()
    assert 'smetagaz.db' in names and not any(n.endswith('scan.pdf') for n in names)
    assert any(n.endswith('scan.pdf') for n in zipfile.ZipFile(full).namelist())
    restored = tmp_path / 'restored'
    backup.restore_backup(small, restored)
    assert (restored / 'smetagaz.db').exists()


def test_estimate_and_guard(db, tmp_path, monkeypatch):
    folder = tmp_path / 'docs'
    folder.mkdir()
    (folder / 'a.bin').write_bytes(b'0' * 3000)
    db.execute('INSERT INTO contracts(contract_number,contract_folder) VALUES(?,?)', ('01-02/26', str(folder)))
    assert bp.estimate_files_size(db) >= 3000
    ok, reason = bp.full_backup_allowed(db, tmp_path)
    assert ok and reason == ''
    db.set_setting('backup_max_gb', '1')
    monkeypatch.setattr(bp, 'estimate_files_size', lambda d: 5 * 1024 ** 3)
    ok, reason = bp.full_backup_allowed(db, tmp_path)
    assert not ok and 'больше лимита' in reason


def test_service_backup_db_modes(db, tmp_path, monkeypatch):
    from smetagaz import services
    monkeypatch.setattr(services, 'db', db)
    svc = services.AutoBackupService()
    svc.timer.stop()
    svc._stopped = True                                   # периодические проверки не запускаются: проверяем backup_db напрямую
    from datetime import datetime
    folder = tmp_path / 'backups'
    folder.mkdir()
    for i in range(5):
        make(folder, f'auto_2025010{i}_000000_000001.zip', 100)                  # прежние полные почасовые копии
    svc.backup_db(datetime(2026, 11, 2, 10, 0, 0))
    svc.backup_db(datetime(2026, 11, 2, 11, 0, 0), full=True)
    s = bp.summary(folder)
    assert s['db'][0] == 1 and s['full'][0] == 1 and s['legacy'][0] == 2             # прежние ужаты до 2
    assert db.get_setting('last_db_backup') and db.get_setting('last_full_backup') and 'ГБ' in db.get_setting('backup_folder_status')
    monkeypatch.setattr(bp, 'full_backup_allowed', lambda d, f: (False, 'мало места'))
    svc.backup_db(datetime(2026, 11, 3, 11, 0, 0), full=True)
    assert bp.summary(folder)['full'][0] == 1 and 'пропущена' in db.get_setting('backup_full_status')
