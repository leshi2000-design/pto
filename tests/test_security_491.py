"""Regression coverage for the nine fixes in 4.9.1. Uses real TLS RPC where relevant."""
import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from netutil import Cluster
from smetagaz import audit_domain, backup, contracts_excel_export, net_proto, payments_domain
from smetagaz.database import DatabaseManager
from smetagaz.remote_db import RemoteDatabaseManager
from smetagaz.server_core import UserStore


@pytest.fixture
def net(tmp_path):
    cluster = Cluster(tmp_path)
    yield cluster
    cluster.stop()


def forbidden(call):
    with pytest.raises(net_proto.RemoteError) as exc:
        call()
    assert exc.value.code == 'forbidden'


def test_savepoints_require_owned_transaction(net):
    net.users.add('staff', 'pass12', 'editor')
    net.users.add('view', 'pass12', 'viewer')
    staff, viewer = net.client('staff', 'pass12'), net.client('view', 'pass12')
    for user in (staff, viewer):
        forbidden(lambda: user.execute('SAVEPOINT injected'))
    with staff.transaction():
        staff.execute("INSERT INTO estimates(title) VALUES('outer')")
        for command in ('SAVEPOINT injected', 'ROLLBACK TO injected', 'RELEASE injected'):
            forbidden(lambda: viewer.execute(command))
        try:
            with staff.transaction():
                staff.execute("INSERT INTO estimates(title) VALUES('inner')")
                raise ValueError('rollback nested')
        except ValueError:
            pass
    assert staff.fetchall('SELECT title FROM estimates') == [('outer',)]
    assert not net.db.conn.in_transaction and net.server.gate.owner is None


def test_foreign_editor_savepoint_does_not_wait_or_abort_owner(net):
    net.users.add('staff', 'pass12', 'editor')
    a, b = net.client(), net.client('staff', 'pass12')
    with a.transaction():
        a.execute("INSERT INTO estimates(title) VALUES('preserved')")
        start = time.monotonic()
        forbidden(lambda: b.execute('SAVEPOINT injected'))
        assert time.monotonic() - start < 2
    assert b.fetchone('SELECT count(*) FROM estimates') == (1,)


@pytest.mark.parametrize('operation', ['disable', 'role', 'password', 'hidden', 'delete'])
def test_security_changes_revoke_sessions_and_rollback(net, operation):
    uid = net.users.add('staff', 'pass12', 'editor')
    client = net.client('staff', 'pass12')
    client._call('tx_begin')
    client.execute("INSERT INTO estimates(title) VALUES('uncommitted')")
    if operation == 'disable':
        net.users.update(uid, active=False)
    elif operation == 'role':
        net.users.update(uid, role='viewer')
    elif operation == 'password':
        net.users.set_password(uid, 'new-pass12')
    elif operation == 'hidden':
        net.users.update(uid, hidden=['payments'])
    else:
        net.users.delete(uid)
    with pytest.raises(net_proto.RemoteError) as exc:
        client.execute("INSERT INTO estimates(title) VALUES('denied')")
    assert exc.value.code == 'no_session'
    assert net.server.gate.owner is None
    assert net.db.fetchone('SELECT count(*) FROM estimates') == (0,)


def test_security_change_via_another_userstore_is_detected(net):
    uid = net.users.add('staff', 'pass12', 'editor')
    client = net.client('staff', 'pass12')
    other = UserStore(net.path / 'users.db')
    other.set_password(uid, 'different-password')
    assert not client.ping()


@pytest.mark.parametrize('command', [
    'PRAGMA foreign_keys(OFF)', 'PRAGMA main.journal_mode(OFF)', 'PRAGMA user_version(123)',
    'PRAGMA query_only(ON)', 'PRAGMA writable_schema(ON)', 'PRAGMA foreign_keys=OFF',
])
def test_mutating_pragmas_are_rejected(net, command):
    net.users.add('view', 'pass12', 'viewer')
    viewer = net.client('view', 'pass12')
    for user in (viewer, net.client()):
        forbidden(lambda: user.execute(command))
    assert net.db.fetchone('PRAGMA foreign_keys') == (1,)
    assert net.db.fetchone('PRAGMA query_only') == (0,)
    assert viewer.fetchall('PRAGMA table_info(estimates)')
    assert viewer.fetchone('PRAGMA main.data_version')


def test_personal_preferences_are_separate_from_global_settings(net):
    net.users.add('view', 'pass12', 'viewer')
    net.users.add('staff', 'pass12', 'editor')
    admin, viewer, staff = net.client(), net.client('view', 'pass12'), net.client('staff', 'pass12')
    net.db.set_setting('is_dark', '0')
    net.db.set_setting('offsite_enabled', '1')
    viewer.set_setting('is_dark', '1')
    assert viewer.get_setting('is_dark') == '1'
    assert staff.get_setting('is_dark') == '0'
    assert net.db.get_setting('is_dark') == '0'
    for client in (viewer, staff):
        forbidden(lambda: client.set_setting('offsite_enabled', '0'))
        forbidden(lambda: client.execute("UPDATE settings SET value='0' WHERE key='offsite_enabled'"))
        forbidden(lambda: client.execute("DELETE FROM settings"))
    assert net.db.get_setting('offsite_enabled') == '1'
    admin.set_setting('offsite_keep', 15)
    assert net.db.get_setting('offsite_keep') == '15'


def test_audit_cannot_be_forged_or_deleted_and_restore_still_works(net):
    net.users.add('staff', 'pass12', 'editor')
    client = net.client('staff', 'pass12')
    eid = client.execute("INSERT INTO estimates(title) VALUES('for trash')").lastrowid
    client.execute('DELETE FROM estimates WHERE id=?', (eid,))
    entry = net.db.fetchone("SELECT id FROM audit_log WHERE table_name='estimates' AND action='D'")[0]
    for user in (client, net.client()):
        for query in ('DELETE FROM audit_log', "UPDATE audit_log SET user='fake'", "UPDATE audit_ctx SET user='fake'", "INSERT INTO audit_log(ts,table_name,action) VALUES('now','x','D')"):
            forbidden(lambda: user.execute(query))
    assert audit_domain.restore(client, entry) == 1
    assert client.fetchone('SELECT title FROM estimates WHERE id=?', (eid,)) == ('for trash',)
    assert net.db.fetchone('SELECT restored FROM audit_log WHERE id=?', (entry,)) == (1,)
    assert net.db.fetchone("SELECT user FROM audit_log WHERE table_name='estimates' AND action='I' ORDER BY id DESC LIMIT 1") == ('staff',)


def test_viewer_payment_reads_and_export_preserve_values(net, tmp_path):
    net.users.add('view', 'pass12', 'viewer')
    admin, viewer = net.client(), net.client('view', 'pass12')
    eid = admin.execute("INSERT INTO estimates(title,total) VALUES('paid',100)").lastrowid
    cid = admin.execute('INSERT INTO contracts(estimate_id,contract_amount) VALUES(?,100)', (eid,)).lastrowid
    payments_domain.add(admin, 'contracts', cid, '25.00', '2026-10-01')
    changes = net.db.conn.total_changes
    assert payments_domain.summary(viewer, 'contracts', cid)['paid'] == 25
    assert len(payments_domain.history(viewer, 'contracts', cid)) == 1
    assert net.db.conn.total_changes == changes
    target = tmp_path / 'viewer.xlsx'
    contracts_excel_export.export_registries(viewer, target)
    from openpyxl import load_workbook
    wb = load_workbook(target)
    assert wb['ГСВ'].cell(2, 16).value == 25
    wb.close()


def test_export_error_keeps_previous_file(net, tmp_path, monkeypatch):
    net.db.execute('INSERT INTO contracts(contract_amount) VALUES(100)')
    target = tmp_path / 'existing.xlsx'
    target.write_bytes(b'previous valid report')
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError('read failed')
    monkeypatch.setattr(payments_domain, 'summary', broken)
    with pytest.raises(sqlite3.OperationalError):
        contracts_excel_export.export_registries(net.db, target)
    assert target.read_bytes() == b'previous valid report'


def test_backups_fail_fast_during_transaction_then_succeed(net, tmp_path):
    client = net.client()
    client._call('tx_begin')
    client.execute("INSERT INTO estimates(title) VALUES('commit after backup attempt')")
    errors = []
    def copy():
        try:
            backup.create_backup(net.db, tmp_path / 'during.zip')
        except sqlite3.OperationalError as exc:
            errors.append(str(exc))
    thread = threading.Thread(target=copy, daemon=True)
    thread.start(); thread.join(2)
    assert not thread.is_alive() and errors
    assert not (tmp_path / 'during.zip').exists()
    with pytest.raises(sqlite3.OperationalError):
        client.safety_backup('manual')
    assert not list((tmp_path / 'backups').glob('before_manual_*'))
    client._call('tx_end', commit=True)
    backup.create_backup(net.db, tmp_path / 'after.zip')
    assert client.fetchone('SELECT count(*) FROM estimates') == (1,)


def test_busy_local_backup_has_bounded_lock_wait(tmp_path):
    db = DatabaseManager(tmp_path / 'smetagaz.db'); db.init_db()
    folder = tmp_path / 'snapshot'; folder.mkdir()
    ready, release = threading.Event(), threading.Event()
    def holder():
        with db._lock:
            ready.set(); release.wait(5)
    thread = threading.Thread(target=holder); thread.start(); assert ready.wait(2)
    try:
        with pytest.raises(sqlite3.OperationalError):
            db.snapshot_databases(folder, timeout=0.05)
    finally:
        release.set(); thread.join(); db.close()


def test_full_backup_restores_external_folders_and_composite_key_docs(tmp_path):
    data = tmp_path / 'live'; data.mkdir()
    db = DatabaseManager(data / 'smetagaz.db'); db.init_db()
    external = tmp_path / 'external'; external.mkdir()
    tables = ('contracts', 'le_contracts', 'smr_contracts', 'to_contracts', 'ip_contracts', 'fl_contracts')
    for table in tables:
        folder = external / table; folder.mkdir()
        (folder / 'document.txt').write_text(table)
        column = 'contract_folder' if table == 'contracts' else 'folder'
        db.execute(f'INSERT INTO {table}({column}) VALUES(?)', (str(folder),))
    linked = external / 'linked.docx'; linked.write_bytes(b'document content')
    db.execute("INSERT INTO gsvm_docs(contract_id,kind,file_path) VALUES(1,'contract',?)", (str(linked),))
    missing = external / 'missing.pdf'
    db.execute('INSERT INTO certificates(name,file_path) VALUES(?,?)', ('missing', str(missing)))
    db.set_setting('folder_root_contracts', str(external))
    archive = tmp_path / 'full.zip'; manifest = backup.create_backup(db, archive)
    assert any(m['table'] == 'certificates' for m in manifest['missing'])
    db.close(); shutil.rmtree(external); shutil.rmtree(data)
    destination = tmp_path / 'moved-restored'
    backup.restore_backup(archive, destination)
    restored = DatabaseManager(destination / 'smetagaz.db')
    for table in tables:
        column = 'contract_folder' if table == 'contracts' else 'folder'
        folder = Path(restored.fetchone(f'SELECT {column} FROM {table}')[0])
        assert folder.is_relative_to(destination)
        assert (folder / 'document.txt').read_text() == table
    path = Path(restored.fetchone('SELECT file_path FROM gsvm_docs')[0])
    assert path.is_relative_to(destination) and path.read_bytes() == b'document content'
    assert restored.get_setting('folder_root_contracts') == ''
    restored.close()


@pytest.mark.parametrize('reason', ['x/../../../escaped', '../escape', '..\\escape', '*', 'a?', 'a:b', '', 'a' * 41])
def test_backup_reason_validation(net, reason):
    with pytest.raises(ValueError):
        net.db.safety_backup(reason)
    assert not (net.path / 'backups').exists()


@pytest.mark.parametrize('keep', [0, -1, 101, True, '10'])
def test_backup_retention_validation(net, keep):
    with pytest.raises(ValueError):
        net.db.safety_backup('manual', keep)


def test_backup_path_rejected_over_rpc(net):
    net.users.add('staff', 'pass12', 'editor')
    with pytest.raises(net_proto.RemoteError):
        net.client('staff', 'pass12').safety_backup('x/../../../escaped')
    assert not (net.path / 'backups').exists()


def test_backup_root_symlink_is_rejected(tmp_path):
    data = tmp_path / 'data'; data.mkdir()
    external = tmp_path / 'outside'; external.mkdir()
    db = DatabaseManager(data / 'smetagaz.db'); db.init_db()
    try:
        (data / 'backups').symlink_to(external, target_is_directory=True)
    except OSError:
        db.close(); pytest.skip('symlinks unavailable')
    with pytest.raises(ValueError):
        db.safety_backup('manual')
    assert not list(external.iterdir())
    db.close()


@pytest.mark.parametrize('payload', [
    dict(m='exec', sql='INSERT INTO estimates(title) VALUES(?)', params=['once']),
    dict(m='execmany', sql='INSERT INTO estimates(title) VALUES(?)', params=[['once']]),
    dict(m='tx_end', commit=True), dict(m='set_setting', key='x', value='y'),
])
def test_lost_write_response_is_never_retried(payload):
    class Transport:
        def __init__(self): self.sent = 0
        def request(self, *a, **kw): self.sent += 1
        def getresponse(self): raise ConnectionResetError('reply lost after execution')
        def close(self): pass
    remote = RemoteDatabaseManager(dict(host='unused', port=1))
    transport = Transport()
    remote._connection = lambda: transport
    remote.on_lost = lambda: pytest.fail('must not offer blind write retry')
    with pytest.raises(net_proto.ConnectionLost, match='Сервер мог выполнить'):
        remote._post(payload)
    assert transport.sent == 1


def test_lost_insert_reply_does_not_duplicate_real_server_operation(net):
    admin = net.client()
    class Applied:
        def __init__(self): self.count = 0
        def request(self, method, path, body, headers):
            self.count += 1
            reply = net.server.handle(body, '127.0.0.1')
            assert 'error' not in reply
        def getresponse(self): raise ConnectionResetError('lost reply')
        def close(self): pass
    transport = Applied()
    remote = RemoteDatabaseManager(dict(host='unused', port=1)); remote.token = admin.token
    remote._connection = lambda: transport
    with pytest.raises(net_proto.ConnectionLost):
        remote.execute('INSERT INTO estimates(title) VALUES(?)', ['exactly once'])
    assert transport.count == 1
    assert admin.fetchone('SELECT count(*) FROM estimates') == (1,)


def test_read_retry_and_preconnect_write_retry_remain_available():
    class Reply:
        def read(self): return net_proto.dumps({'result': 42})
    class Transport:
        def __init__(self): self.sent = 0
        def request(self, *a, **kw): self.sent += 1
        def getresponse(self):
            if self.sent == 1: raise ConnectionResetError('read reply lost')
            return Reply()
        def close(self): pass
    remote = RemoteDatabaseManager(dict(host='unused', port=1))
    transport = Transport(); remote._connection = lambda: transport
    assert remote._post(dict(m='exec', sql='SELECT 42')) == {'result': 42}
    assert transport.sent == 2
    attempts = []
    def reconnect():
        attempts.append(1)
        if len(attempts) == 1: raise ConnectionRefusedError('not sent')
        return transport
    remote._connection = reconnect
    assert remote._post(dict(m='exec', sql='INSERT INTO x VALUES(1)')) == {'result': 42}
    assert len(attempts) == 2
