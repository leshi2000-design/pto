from datetime import datetime, timedelta
import pytest
from smetagaz import offsite_backup as ob
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    (tmp_path / 'data').mkdir()
    d = DatabaseManager(tmp_path / 'data' / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def configure(db, tmp_path, **extra):
    folder = tmp_path / 'cloud'
    folder.mkdir(exist_ok=True)
    for k, v in dict(offsite_dir=str(folder), offsite_password='correct horse battery', offsite_enabled='1', **extra).items():
        db.set_setting(k, v)
    return folder


def test_copy_encrypt_verify_and_retention(db, tmp_path):
    folder = configure(db, tmp_path, offsite_keep='2')
    db.execute("INSERT INTO crm.clients(name) VALUES('Петров')")
    db.execute("INSERT INTO estimates(title,date,total) VALUES('Смета','2026-10-01',10)")
    now = datetime(2026, 10, 8, 9, 0)
    copies = [ob.make_copy(db, now + timedelta(hours=i)) for i in range(3)]
    left = ob.list_copies(folder)
    assert left == copies[1:] and not (folder / (copies[0].name + '.sha256')).exists() and not list(folder.glob('*.part'))
    assert b'SQLite' not in left[-1].read_bytes()[:200] and left[-1].read_bytes().startswith(b'SGBAK1')   # зашифрована
    res = ob.verify_copy(left[-1], 'correct horse battery', db)
    assert res['ok'] and res['tables']['estimates'] == 1 and res['tables']['clients'] == 1
    assert not ob.verify_copy(left[-1], 'wrong password!!', db)['ok']
    # повреждение файла ловится контрольной суммой
    data = bytearray(left[-1].read_bytes())
    data[100] ^= 0xFF
    left[-1].write_bytes(bytes(data))
    bad = ob.verify_copy(left[-1], 'correct horse battery', db)
    assert not bad['ok'] and 'контрольная сумма' in bad['error']


def test_schedule_and_status(db, tmp_path):
    configure(db, tmp_path)
    now = datetime(2026, 10, 8, 9, 0)
    assert ob.due(db, now) == (True, False)            # копий ещё нет — делаем копию, проверять нечего
    done = ob.run_scheduled(db, now)
    assert len(done) == 1 and 'копия создана' in ob.status_text(db)[0]
    assert ob.due(db, now + timedelta(minutes=1)) == (False, True)      # первая же копия проверяется восстановлением
    assert len(ob.run_scheduled(db, now + timedelta(minutes=1))) == 1 and db.get_setting('offsite_verify_ok') == '1'
    assert ob.due(db, now + timedelta(hours=1)) == (False, False)
    assert ob.due(db, now + timedelta(hours=25)) == (True, False)
    assert ob.due(db, now + timedelta(days=31))[1] is True      # раз в месяц — проверка восстановлением
    later = now + timedelta(days=31)
    done = ob.run_scheduled(db, later)
    assert len(done) == 2 and 'восстановление проверено' in ob.status_text(db)[1] and db.get_setting('offsite_verify_ok') == '1'
    assert ob.due(db, later + timedelta(hours=1)) == (False, False)
    # папка пропала: ошибка попадает в статус, повтор — через интервал, программа не падает
    for p in (tmp_path / 'cloud').iterdir():
        p.unlink()
    (tmp_path / 'cloud').rmdir()
    ob.run_scheduled(db, later + timedelta(days=2))
    assert 'ОШИБКА' in ob.status_text(db)[0]


def test_settings_checks(db, tmp_path):
    assert ob.configured(db) is False and ob.due(db) == (False, False)
    db.set_setting('offsite_dir', str(tmp_path / 'data'))
    db.set_setting('offsite_password', 'short')
    problems = ' '.join(ob.check_settings(db))
    assert 'минимум 10' in problems and 'том же диске' in problems
    db.set_setting('offsite_dir', str(tmp_path / 'nope'))
    assert 'недоступна' in ' '.join(ob.check_settings(db))
