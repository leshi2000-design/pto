"""Блокировка карточек, сохранённый вход и локальный режим рядом с ПТО Сервером."""
import os
import sqlite3
import tempfile

import pytest

from smetagaz import edit_locks as locks
from smetagaz import net_proto as proto
from smetagaz.server_core import PtoServer, UserStore


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    from smetagaz import edit_lock_ui
    from smetagaz.database import DatabaseManager
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    locks.migrate(d)
    locks._held.clear()
    monkeypatch.setattr(edit_lock_ui, 'default_db', d)
    yield d
    d.close()


def test_free_card_is_taken_and_released(fresh):
    assert locks.acquire(fresh, 'gsn:1') is None
    assert fresh.fetchone("SELECT sid FROM edit_locks WHERE key='gsn:1'")[0] == locks.SID
    locks.release(fresh, 'gsn:1')
    assert fresh.fetchone("SELECT 1 FROM edit_locks WHERE key='gsn:1'") is None


def test_busy_card_reports_who(fresh):
    fresh.execute("INSERT INTO edit_locks(key,sid,user,host,since,beat) VALUES('gsn:2','other','Иванов','ПК-3','10:15',CAST(strftime('%s','now') AS INTEGER))")
    other = locks.acquire(fresh, 'gsn:2')
    assert other == dict(user='Иванов', host='ПК-3', since='10:15')
    assert not locks._held.get('gsn:2')


def test_stale_lock_is_taken_over(fresh):
    fresh.execute("INSERT INTO edit_locks(key,sid,user,host,since,beat) VALUES('gsn:3','other','Иванов','ПК-3','10:15',CAST(strftime('%s','now') AS INTEGER)-?)", (locks.STALE + 5,))
    assert locks.acquire(fresh, 'gsn:3') is None


def test_nested_open_in_same_process_is_allowed_and_released_once(fresh):
    assert locks.acquire(fresh, 'estimate:5') is None
    assert locks.acquire(fresh, 'estimate:5') is None
    locks.release(fresh, 'estimate:5')
    assert fresh.fetchone("SELECT 1 FROM edit_locks WHERE key='estimate:5'")
    locks.release(fresh, 'estimate:5')
    assert fresh.fetchone("SELECT 1 FROM edit_locks WHERE key='estimate:5'") is None


def test_beat_detects_lost_lock(fresh):
    assert locks.acquire(fresh, 'gsv:9') is None
    fresh.execute("UPDATE edit_locks SET sid='other', user='Пётр' WHERE key='gsv:9'")
    assert locks.beat(fresh, 'gsv:9')['user'] == 'Пётр'


def test_dialog_busy_opens_view_only(fresh, monkeypatch):
    from PyQt6.QtWidgets import QDialog, QLineEdit, QMessageBox, QPushButton, QVBoxLayout
    from smetagaz.edit_lock_ui import guarded

    seen = {}
    monkeypatch.setattr(QDialog, 'exec', lambda self: seen.setdefault('state', (self.edit.isReadOnly(), self.save.isEnabled(), self.close_btn.isEnabled())) and 0)

    @guarded('t', lambda d: 7, 'Тест')
    class D(QDialog):
        def __init__(self):
            super().__init__()
            l = QVBoxLayout(self)
            self.edit = QLineEdit('x')
            self.save = QPushButton('Сохранить')
            self.close_btn = QPushButton('Закрыть')
            for w in (self.edit, self.save, self.close_btn):
                l.addWidget(w)

    fresh.execute("INSERT INTO edit_locks(key,sid,user,host,since,beat) VALUES('t:7','other','Иванов','ПК-3','10:15',CAST(strftime('%s','now') AS INTEGER))")
    def fake_exec(box):
        seen['text'] = box.text()
        box._pick = [b for b in box.buttons() if b.text().startswith('Открыть')][0]
        box.clickedButton = lambda: box._pick
        return 0
    monkeypatch.setattr(QMessageBox, 'exec', fake_exec)
    d = D()
    d.exec()
    assert 'Иванов' in seen['text'] and 'ПК-3' in seen['text']
    assert seen['state'] == (True, False, True)


def test_dialog_free_holds_lock_while_open(fresh, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    from smetagaz.edit_lock_ui import guarded

    inside = {}
    monkeypatch.setattr(QDialog, 'exec', lambda self: inside.setdefault('held', fresh.fetchone("SELECT user FROM edit_locks WHERE key='t:8'") is not None) and 0)

    @guarded('t', lambda d: 8, 'Тест')
    class D(QDialog):
        pass

    D().exec()
    assert inside['held'] is True
    assert fresh.fetchone("SELECT 1 FROM edit_locks WHERE key='t:8'") is None


# --- сохранённый вход -----------------------------------------------------------------------------

@pytest.fixture
def users(tmp_path):
    u = UserStore(tmp_path / 'users.db')
    uid = u.add('anna', 'secret1', 'editor', 'Анна')
    return u, uid


def test_token_login_and_revocation(users):
    u, uid = users
    raw = u.make_token(uid, 'ПК-2')
    assert u.verify_token('anna', raw)[1] == 'anna'
    assert u.verify_token('boris', raw) is None                      # ключ привязан к логину
    assert u.verify_token('anna', raw + 'x') is None
    u.set_password(uid, 'newsecret')                                 # смена пароля отзывает все ключи
    assert u.verify_token('anna', raw) is None


def test_token_dies_when_user_disabled_or_old(users):
    u, uid = users
    raw = u.make_token(uid)
    u.update(uid, active=0) if u.count() > 1 else None
    other = u.add('admin1', 'secret2', 'admin')
    u.update(uid, active=0)
    assert u.verify_token('anna', raw) is None
    u.update(uid, active=1)
    raw2 = u.make_token(uid)
    with u._connect() as con:
        con.execute("UPDATE remember_tokens SET last_used='2000-01-01T00:00:00'")
    assert u.verify_token('anna', raw2) is None


def test_server_issues_and_accepts_remember_token(tmp_path):
    from smetagaz.database import DatabaseManager
    u = UserStore(tmp_path / 'users.db')
    u.add('anna', 'secret1', 'editor', 'Анна')
    srv = PtoServer(DatabaseManager(str(tmp_path / 'x.db')), u, tmp_path, host='127.0.0.1', port=0, app_version='1.0.0')
    first = srv.login('127.0.0.1', 'anna', 'secret1', remember=True, device='ПК-2')
    assert first['remember_token']
    second = srv.login('127.0.0.1', 'anna', '', remember_token=first['remember_token'])
    assert second['name'] == 'Анна' and 'remember_token' not in second
    with pytest.raises(proto.RemoteError) as e:
        srv.login('127.0.0.1', 'anna', '', remember_token='bad')
    assert e.value.code == 'bad_token'
    srv.dispatch('logout', dict(token=second['token'], forget=first['remember_token']), '127.0.0.1')
    with pytest.raises(proto.RemoteError):
        srv.login('127.0.0.1', 'anna', '', remember_token=first['remember_token'])
