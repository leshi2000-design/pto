import sqlite3
import threading
import time

import pytest

from smetagaz import net_proto as proto, server_core as sc
from smetagaz.remote_db import RemoteDatabaseManager
from netutil import Cluster


@pytest.fixture
def net(tmp_path):
    c = Cluster(tmp_path)
    yield c
    c.stop()


def test_login_roles_and_pinning(net):
    r = net.client()
    assert r.user == 'Администратор' and r.role == 'admin' and r.get_setting('schema_version') == '8'
    with pytest.raises(proto.RemoteError) as e:
        net.client(password='wrong')
    assert e.value.code == 'bad_login'
    with pytest.raises(proto.RemoteError) as e:
        net.client(fingerprint='00' * 32)                 # чужой сертификат
    assert e.value.code == 'fingerprint'
    fp, hello = RemoteDatabaseManager.probe('127.0.0.1', net.port)
    assert fp == net.server.fingerprint and hello['service'] == 'PTO Server' and not hello['needs_setup']
    with pytest.raises(proto.RemoteError) as e:
        net.client(login='nobody')
    for _ in range(5):                                    # блокировка после серии ошибок
        with pytest.raises(proto.RemoteError):
            net.client(password='x')
    with pytest.raises(proto.RemoteError) as e:
        net.client()
    assert e.value.code == 'throttled'


def test_statements_roundtrip_and_errors(net):
    r = net.client()
    r.execute('CREATE TABLE IF NOT EXISTS t_dummy(x)') if False else None
    cur = r.execute("INSERT INTO estimates(title,date,total) VALUES(?,?,?)", ('Смета №1', '2026-01-01', 12.5))
    assert cur.lastrowid and cur.rowcount == 1
    row = r.fetchone('SELECT title,total FROM estimates WHERE id=?', (cur.lastrowid,))
    assert row == ('Смета №1', 12.5)
    cur = r.execute('SELECT id,title FROM estimates')
    assert [d[0] for d in cur.description] == ['id', 'title'] and cur.fetchall()
    r.executemany('INSERT INTO categories(name) VALUES(?)', [('А',), ('Б',)])
    assert r.fetchone('SELECT count(*) FROM categories')[0] == 2
    assert r.fetchone("SELECT LOWER('ЁЛКА'), digits('+375 (29) 1')")[:] == ('ёлка', '375291')          # функции регистрируются на сервере
    r.set_setting('k', 'значение')
    assert r.get_setting('k') == 'значение' and r.get_setting('none', 'def') == 'def'
    r.execute('INSERT INTO attachments(estimate_id,file_name,file_path) VALUES(?,?,?)', (1, 'f', 'p'))
    with pytest.raises(sqlite3.IntegrityError):
        r.execute('INSERT INTO settings(key,value) VALUES(?,?)', ('k', 'dup'))           # ошибки SQLite приходят теми же классами
    with pytest.raises(sqlite3.OperationalError):
        r.execute('SELECT * FROM no_such_table')
    for bad in ('DROP TABLE estimates', 'CREATE TABLE x(a)', "ATTACH DATABASE 'x' AS y", 'PRAGMA journal_mode=OFF', 'SELECT 1; DELETE FROM estimates', 'BEGIN'):
        with pytest.raises(proto.RemoteError) as e:
            r.execute(bad)
        assert e.value.code == 'forbidden'
    blob = bytes(range(10))
    r.execute('CREATE TEMP TABLE IF NOT EXISTS z(b)') if False else None
    assert r.fetchone('SELECT 1')[0] == 1 and r.conn.total_changes > 0


def test_transactions_commit_rollback_nested(net):
    r = net.client()
    with r.transaction() as cur:
        cur.execute('INSERT INTO categories(name) VALUES(?)', ('в транзакции',))
        new_id = cur.lastrowid
        with r.transaction():
            r.execute('INSERT INTO categories(name) VALUES(?)', ('вложенная',))
    assert r.fetchone('SELECT count(*) FROM categories')[0] == 2
    with pytest.raises(ValueError):
        with r.transaction():
            r.execute('INSERT INTO categories(name) VALUES(?)', ('откатится',))
            raise ValueError('сбой')
    assert r.fetchone('SELECT count(*) FROM categories')[0] == 2
    with r.transaction():
        try:
            with r.transaction():
                r.execute('INSERT INTO categories(name) VALUES(?)', ('вложенная откатится',))
                raise KeyError()
        except KeyError:
            pass
        r.execute('INSERT INTO categories(name) VALUES(?)', ('внешняя останется',))
    names = {x[0] for x in r.fetchall('SELECT name FROM categories')}
    assert 'внешняя останется' in names and 'вложенная откатится' not in names and 'откатится' not in names


def test_two_clients_isolation_and_audit_user(net):
    net.users.add('ivan', 'pass12', 'editor', 'Иванов Иван')
    a, b = net.client(), net.client('ivan', 'pass12')
    order = []

    def slow():
        with a.transaction():
            a.execute('INSERT INTO categories(name) VALUES(?)', ('от А',))
            order.append('a-in')
            time.sleep(0.6)
            order.append('a-out')
    t = threading.Thread(target=slow)
    t.start()
    time.sleep(0.2)
    b.execute('INSERT INTO categories(name) VALUES(?)', ('от Б',))          # ждёт окончания чужой транзакции
    order.append('b-done')
    t.join()
    assert order == ['a-in', 'a-out', 'b-done']
    # журнал изменений помнит, кто менял
    cid = b.execute("INSERT INTO estimates(title,date,total) VALUES('Аудит','2026-01-01',1)").lastrowid
    a.execute('UPDATE estimates SET title=? WHERE id=?', ('Аудит 2', cid))
    rows = net.db.fetchall("SELECT action,user FROM audit_log WHERE table_name='estimates' ORDER BY id")
    assert rows == [('I', 'Иванов Иван'), ('U', 'Администратор')]


def test_viewer_and_inactive_user(net):
    net.users.add('view', 'pass12', 'viewer')
    v = net.client('view', 'pass12')
    assert v.fetchone('SELECT count(*) FROM estimates')[0] == 0
    v.set_setting('ui', '1')                                  # настройки интерфейса смотрящему можно
    with pytest.raises(proto.RemoteError):
        v.execute("INSERT INTO estimates(title,date,total) VALUES('x','2026-01-01',1)")
    with pytest.raises(proto.RemoteError):
        with v.transaction():
            pass
    uid = [u[0] for u in net.users.listing() if u[1] == 'view'][0]
    net.users.update(uid, active=False)
    with pytest.raises(proto.RemoteError):
        net.client('view', 'pass12')


def test_last_admin_protected_and_password_rules(net):
    admin_id = net.users.listing()[0][0]
    with pytest.raises(ValueError):
        net.users.update(admin_id, role='editor')
    with pytest.raises(ValueError):
        net.users.delete(admin_id)
    with pytest.raises(ValueError):
        net.users.add('x', '123', 'editor')
    with pytest.raises(ValueError):
        net.users.add('admin', 'secret1', 'editor')


def test_version_mismatch_and_lost_connection(tmp_path):
    c = Cluster(tmp_path, version='9.9.0')
    try:
        with pytest.raises(proto.RemoteError) as e:
            c.client()
        assert e.value.code == 'version'
    finally:
        c.stop()
    c2 = Cluster(tmp_path / 'b' if (tmp_path / 'b').mkdir() is None else tmp_path)
    r = c2.client()
    c2.stop()
    with pytest.raises((proto.ConnectionLost, proto.RemoteError)):           # сервер остановлен: связи нет либо сеанс уже закрыт
        r.fetchone('SELECT 1')
    r2 = RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=c2.port, fingerprint=c2.server.fingerprint, login='admin'))
    with pytest.raises(proto.ConnectionLost):
        r2._call('hello')


def test_idle_transaction_is_rolled_back(net):
    net.server.gate.idle = 0.3
    a, b = net.client(), net.client()
    a._call('tx_begin')
    a._call('exec', sql='INSERT INTO categories(name) VALUES(?)', params=['зависшая'])
    time.sleep(0.5)
    b.execute('INSERT INTO categories(name) VALUES(?)', ('от Б',))              # сервер откатил чужую зависшую транзакцию
    assert [x[0] for x in b.fetchall('SELECT name FROM categories')] == ['от Б']
    with pytest.raises(proto.RemoteError) as e:
        a._call('exec', sql='INSERT INTO categories(name) VALUES(?)', params=['поздно'])
    assert e.value.code == 'tx_aborted'
    with pytest.raises(proto.RemoteError):
        a._call('tx_end', commit=True)
    a._call('exec', sql='SELECT 1', params=[])                                    # после завершения прерванной транзакции клиент снова работает


def test_server_console_process_end_to_end(tmp_path):
    """Настоящий процесс «python -m smetagaz.server_main --console» + клиент по сети."""
    import os
    import subprocess
    import sys
    from netutil import free_port
    port = free_port()
    env = dict(os.environ, SMETAGAZ_DATA_DIR=str(tmp_path / 'data'), QT_QPA_PLATFORM='offscreen')
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.Popen([sys.executable, '-m', 'smetagaz.server_main', '--console', '--port', str(port), '--create-admin', 'boss', 'secret99'], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        client = None
        deadline = time.time() + 40
        while time.time() < deadline and proc.poll() is None:
            try:
                fp, hello = RemoteDatabaseManager.probe('127.0.0.1', port)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise AssertionError('сервер не запустился: ' + (proc.stdout.read() if proc.poll() is not None else ''))
        client = RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=port, fingerprint=fp, login='boss'))
        client.connect('boss', 'secret99')
        assert client.role == 'admin' and client.get_setting('schema_version') == '8'
        with client.transaction():
            client.execute("INSERT INTO estimates(title,date,total) VALUES('Через процесс','2026-01-01',5)")
        assert client.fetchone('SELECT title FROM estimates')[0] == 'Через процесс'
        client.disconnect()
    finally:
        proc.terminate()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_windows_and_dialogs_offscreen(net, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QMessageBox
    import smetagaz.network_ui as nu
    import smetagaz.server_app as sa
    win = sa.ServerWindow.__new__(sa.ServerWindow)          # окно целиком создаёт почасовые службы; проверяем отдельные части
    users_dialog = sa.UsersDialog(net.users)
    assert users_dialog.table.rowCount() == 1
    r = net.client()
    monkeypatch.setattr(nu.net_config, 'PATH', tmp_path / 'network.json')
    dialog = nu.LoginDialog(r)
    dialog.host.setText('127.0.0.1')
    dialog.port.setValue(net.port)
    dialog.login.setText('admin')
    dialog.password.setText('secret1')
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    dialog.connect_now()
    assert dialog.result() == dialog.DialogCode.Accepted
    saved = nu.net_config.load()
    assert saved['mode'] == 'client' and saved['fingerprint'] == net.server.fingerprint and saved['login'] == 'admin'
    nd = nu.NetworkDialog(r)
    assert nd.windowTitle() == 'Сетевая работа'
    label = nu.attach_status(None, r)
    r.fetchone('SELECT 1')
    assert label.text().startswith('●')


def test_saved_login_and_silent_relogin(net):
    r = RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=net.port, fingerprint=net.server.fingerprint, login='admin'))
    info = r.connect('admin', 'secret1', remember=True)
    saved = info['remember_token']
    assert saved
    r2 = RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=net.port, fingerprint=net.server.fingerprint, login='admin'))
    r2.connect('admin', remember_token=saved)                        # пароль не нужен
    assert r2.role == 'admin' and r2.fetchone('SELECT 1')[0] == 1
    net.server.sessions.clear()                                      # сервер перезапущен: сеанс потерян
    assert r2.fetchone('SELECT 2')[0] == 2                           # клиент тихо вошёл заново
    r2.disconnect(forget=True)                                       # «Забыть вход» отзывает ключ на сервере
    r3 = RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=net.port, fingerprint=net.server.fingerprint, login='admin'))
    with pytest.raises(proto.RemoteError) as e:
        r3.connect('admin', remember_token=saved)
    assert e.value.code == 'bad_token'
    net.users.set_password(net.users.listing()[0][0], 'secret2')
    r4 = RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=net.port, fingerprint=net.server.fingerprint, login='admin'))
    with pytest.raises(proto.RemoteError):
        r4.connect('admin', remember_token=info['remember_token'])    # смена пароля тоже отзывает


def test_card_lock_between_two_clients(net, monkeypatch):
    from smetagaz import edit_locks as locks
    net.users.add('ivan', 'pass12', 'editor', 'Иванов Иван')
    a, b = net.client(), net.client('ivan', 'pass12')
    locks.migrate(net.db)
    locks._held.clear()
    monkeypatch.setattr(locks, 'SID', 'sid-a')
    assert locks.acquire(a, 'gsn:77') is None
    monkeypatch.setattr(locks, 'SID', 'sid-b')
    other = locks.acquire(b, 'gsn:77')
    assert other['user'] == 'Администратор' and other['host']
    monkeypatch.setattr(locks, 'SID', 'sid-a')
    locks.release(a, 'gsn:77')
    monkeypatch.setattr(locks, 'SID', 'sid-b')
    assert locks.acquire(b, 'gsn:77') is None
    viewer_id = net.users.add('view', 'pass12', 'viewer', 'Наблюдатель')
    v = net.client('view', 'pass12')
    assert locks.acquire(v, 'gsn:77') is None                       # наблюдателю карточки не блокируются и он их не блокирует


def test_local_mode_next_to_server_signs_its_changes(net):
    from smetagaz.database import DatabaseManager
    c = net.client()
    c.execute("INSERT INTO estimates(title,date,total) VALUES('Сетевая','2026-01-01',1)")
    local = DatabaseManager(net.path / 'smetagaz.db')
    local.init_db()
    local.side_by_side = True
    lid = local.execute("INSERT INTO estimates(title,date,total) VALUES('Локальная','2026-01-02',1)").lastrowid
    with local.transaction():
        local.execute("UPDATE estimates SET title='Локальная 2' WHERE id=?", (lid,))
    c.execute("INSERT INTO estimates(title,date,total) VALUES('Сетевая 2','2026-01-03',1)")
    rows = net.db.fetchall("SELECT action,user FROM audit_log WHERE table_name='estimates' ORDER BY id")
    users = [u for _, u in rows]
    assert users[0] == 'Администратор' and users[1].endswith('(локально)') and users[2].endswith('(локально)') and users[3] == 'Администратор'
    assert net.db.fetchone("SELECT title FROM estimates WHERE id=?", (lid,))[0] == 'Локальная 2'      # оба видят одну базу
    local.close()


def test_saved_login_flow_in_client(net, monkeypatch, tmp_path):
    from smetagaz import net_config, network_ui
    monkeypatch.setattr(net_config, 'PATH', tmp_path / 'network.json')
    mgr = RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=net.port, fingerprint=net.server.fingerprint, login='admin'))
    assert network_ui.try_saved_login(mgr) is None                    # ничего не сохранено — окно входа покажется как обычно
    info = mgr.connect('admin', 'secret1', remember=True)
    net_config.save(dict(mode='client', host='127.0.0.1', port=net.port, fingerprint=net.server.fingerprint, login='admin', token=info['remember_token']))
    assert (tmp_path / 'network.json').stat().st_mode & 0o077 == 0     # ключ входа читает только владелец
    fresh = RemoteDatabaseManager(dict(mode='client'))
    assert network_ui.try_saved_login(fresh) == '' and fresh.user == 'Администратор'
    net.users.revoke_all(net.users.listing()[0][0])
    again = RemoteDatabaseManager(dict(mode='client'))
    assert 'больше не действует' in network_ui.try_saved_login(again)
    assert net_config.load()['token'] == ''                            # недействительный ключ стёрт
    net_config.save(dict(net_config.load(), token='x', port=net.port + 1))
    lost = RemoteDatabaseManager(dict(mode='client'))
    assert 'Сохранённый вход не потерян' in network_ui.try_saved_login(lost)
    assert net_config.load()['token'] == 'x'                           # при недоступном сервере ключ остаётся
