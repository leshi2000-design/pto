from datetime import datetime, timedelta

import pytest

from smetagaz import backup_health as bh
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_never_backed_up_is_bad(db):
    rows = bh.report(db)
    assert rows[0][0] == bh.BAD and bh.worst(rows) == bh.BAD


def test_fresh_local_but_no_offsite_is_warning(db):
    now = datetime(2026, 10, 17, 12, 0)
    db.set_setting('last_db_backup', (now - timedelta(minutes=30)).isoformat())
    rows = bh.report(db, now)
    assert rows[0][0] == bh.OK and 'мин назад' in rows[0][1]
    assert any(l == bh.WARN and 'вне компьютера не настроена' in t for l, t in rows)
    assert bh.worst(rows) == bh.WARN


def test_stale_local_and_errors(db):
    now = datetime(2026, 10, 17, 12, 0)
    db.set_setting('last_db_backup', (now - timedelta(hours=30)).isoformat())
    rows = bh.report(db, now)
    assert rows[0][0] == bh.BAD and 'больше суток' in rows[0][1]
    db.set_setting('backup_status', '17.10.2026 11:00: ошибка резервного копирования — диск полон')
    assert any('диск полон' in t for l, t in bh.report(db, now))


def test_offsite_states(db, monkeypatch):
    from smetagaz import offsite_backup
    now = datetime(2026, 10, 17, 12, 0)
    db.set_setting('last_db_backup', now.isoformat())
    monkeypatch.setattr(offsite_backup, 'configured', lambda d: True)
    rows = bh.report(db, now)
    assert any('ещё не делалась' in t for l, t in rows)
    db.set_setting('last_offsite_backup', (now - timedelta(hours=60)).isoformat())
    assert any(l == bh.BAD and 'пора была раньше' in t for l, t in bh.report(db, now))
    db.set_setting('last_offsite_backup', (now - timedelta(hours=3)).isoformat())
    db.set_setting('offsite_verify_status', 'ОШИБКА проверки x.sgb — повреждён')
    rows = bh.report(db, now)
    assert any(l == bh.OK and 'вне компьютера' in t for l, t in rows) and any('повреждён' in t for l, t in rows)
    assert '✔' in bh.html(rows) and '✖' in bh.html(rows)
