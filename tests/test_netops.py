"""Права по разделам, роль «руководитель», изменения для клиентов, журнал входов, потеря связи."""
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


def test_manager_role_and_hidden_sections(net):
    net.users.add('boss', 'pass12', 'manager', 'Руководитель')
    net.users.add('anna', 'pass12', 'editor', 'Анна', hidden=['stats', 'ip_tax', 'payments'])
    net.users.add('mgr2', 'pass12', 'manager', 'Рук2', hidden=['stats'])             # у руководителя скрытие не действует
    a = net.client('anna', 'pass12')
    assert a.hidden == {'stats', 'ip_tax', 'payments'}
    assert net.client('mgr2', 'pass12').hidden == frozenset()
    assert net.client('boss', 'pass12').role == 'manager'


def test_server_blocks_tax_tables_and_payment_writes(net):
    net.users.add('anna', 'pass12', 'editor', 'Анна', hidden=['ip_tax', 'payments'])
    a, admin = net.client('anna', 'pass12'), net.client()
    admin.fetchall('SELECT * FROM ip_manual')                                         # администратору можно
    # оплаты: читать можно, менять нельзя
    est = admin.execute("INSERT INTO estimates(title,date,total) VALUES('Смета','2026-01-01',100)").lastrowid
    assert a.fetchall('SELECT count(*) FROM payments')[0][0] == 0
    with pytest.raises(proto.RemoteError) as e:
        a.execute("INSERT INTO payments(estimate_id,amount,date,owner_type,owner_id) VALUES(?,10,'2026-01-02','estimates',?)", (est, est))
    assert e.value.code == 'forbidden'
    admin.execute("INSERT INTO payments(estimate_id,amount,date,owner_type,owner_id) VALUES(?,10,'2026-01-02','estimates',?)", (est, est))
    # обычная работа сотрудника не страдает (триггеры журнала не блокируются)
    a.execute("UPDATE estimates SET title='Новая' WHERE id=?", (est,))
    assert net.db.fetchone('SELECT title FROM estimates WHERE id=?', (est,))[0] == 'Новая'
    # и после запрещённого запроса защита снимается: сервер сам читает всё
    assert net.db.fetchall('SELECT * FROM ip_manual') == []


def test_changes_are_reported_to_other_clients_only(net):
    net.users.add('ivan', 'pass12', 'editor', 'Иван')
    a, b = net.client(), net.client('ivan', 'pass12')
    assert a.poll_changes() == set() and b.poll_changes() == set()                    # первое обращение лишь запоминает номер
    a.execute("INSERT INTO estimates(title,date,total) VALUES('X','2026-01-01',1)")
    assert a.poll_changes() == set()                                                  # свои изменения не возвращаются
    assert b.poll_changes() == {'estimates'}
    assert b.poll_changes() == set()
    with b.transaction():
        b.execute("UPDATE estimates SET total=2")
        b.execute("INSERT INTO categories(name) VALUES('k')")
    assert a.poll_changes() == {'estimates', 'categories'}


def test_online_release_lock_and_journal(net, monkeypatch):
    from smetagaz import edit_locks as locks
    net.users.add('ivan', 'pass12', 'editor', 'Иван')
    net.users.add('boss', 'pass12', 'manager', 'Руководитель')
    admin, ivan, boss = net.client(), net.client('ivan', 'pass12'), net.client('boss', 'pass12')
    locks.migrate(net.db)
    monkeypatch.setattr(locks, 'SID', 'sid-i')
    assert locks.acquire(ivan, 'gsn:5') is None
    online = boss.ops_online()
    assert {s[0] for s in online['sessions']} >= {'admin', 'ivan', 'boss'}
    assert online['locks'][0][0] == 'gsn:5' and online['locks'][0][1] == 'Иван'
    with pytest.raises(proto.RemoteError):
        ivan.ops_online()                                                              # сотруднику нельзя
    assert boss.ops_release_lock('gsn:5') == 1
    assert admin.ops_online()['locks'] == []
    with pytest.raises(proto.RemoteError):
        boss.ops_journal()                                                             # журнал входов — только администратору
    events = [r[1] for r in admin.ops_journal()]
    assert 'lock_release' in events and 'login' in events
    with pytest.raises(proto.RemoteError):
        RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=net.port, fingerprint=net.server.fingerprint)).connect('ivan', 'wrongpw')
    row = admin.ops_journal(5, 'login_fail')[0]
    assert row[2] == 'ivan' and 'неверный' in row[5]


def test_user_changes_are_journaled(net):
    uid = net.users.add('anna', 'pass12', 'editor', 'Анна', actor='сервер')
    net.users.update(uid, role='manager', actor='сервер')
    net.users.update(uid, hidden=['stats'], actor='сервер')
    net.users.set_password(uid, 'newpass1', actor='сервер')
    net.users.update(uid, active=0, actor='сервер')
    net.users.delete(uid, actor='сервер')
    text = ' | '.join(r[5] for r in net.users.journal(20))
    for part in ('создан anna', 'роль Сотрудник → Руководитель', 'скрыто stats', 'пароль пользователя anna изменён', 'отключён', 'удалён anna'):
        assert part in text


def test_connection_lost_waits_and_retries(tmp_path):
    from netutil import free_port
    c = Cluster(tmp_path)
    try:
        r = RemoteDatabaseManager(dict(mode='client', host='127.0.0.1', port=c.port, fingerprint=c.server.fingerprint, login='admin'))
        r.connect('admin', 'secret1', remember=True)
        port = c.port
        c.server.stop()
        r._local.conn.close()                                  # открытое соединение оборвано, как при падении сервера
        asked = []

        def lost():
            asked.append(1)
            c.server = sc.PtoServer(c.db, c.users, tmp_path / 'tls', host='127.0.0.1', port=port, app_version=c.server.app_version)
            c.server.start()                                  # «связь вернулась»: сервер снова работает (и сеансы потеряны)
            return True
        r.on_lost = lost
        assert r.fetchone('SELECT 41 + 1')[0] == 42           # запрос дождался сервера и прошёл
        assert len(asked) == 1
        r.execute("INSERT INTO categories(name) VALUES('после обрыва')")
        assert c.db.fetchone("SELECT count(*) FROM categories WHERE name='после обрыва'")[0] == 1
        # отказ ждать — обычная ошибка связи
        c.server.stop()
        r._local.conn.close()
        r.on_lost = lambda: False
        with pytest.raises(proto.ConnectionLost):
            r.fetchone('SELECT 1')
        # служебные запросы (индикатор связи, опрос) окно не вызывают
        r.on_lost = lambda: pytest.fail('не должно вызываться')
        assert r.ping() is False and r.poll_changes() == set()
    finally:
        c.server.stop()
        c.db.close()


# --- интерфейс -----------------------------------------------------------------------------------

def test_live_refresh_keeps_scroll_selection_and_skips_when_typing():
    from PyQt6.QtWidgets import QApplication, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
    from PyQt6.QtCore import Qt
    from smetagaz import live_refresh as lr

    class View(QWidget):
        def __init__(self):
            super().__init__()
            self.rows = list(range(60))
            self.table = QTableWidget(0, 1)
            self.edit = QLineEdit()
            lay = QVBoxLayout(self)
            lay.addWidget(self.edit)
            lay.addWidget(self.table)
            self.loads = 0

        def load_data(self):
            self.loads += 1
            self.table.setRowCount(len(self.rows))
            for i, r in enumerate(self.rows):
                item = QTableWidgetItem(f'запись {r}')
                item.setData(Qt.ItemDataRole.UserRole, r)
                self.table.setItem(i, 0, item)
    v = View()
    v.resize(300, 200)
    v.show()
    v.load_data()
    v.table.setCurrentCell(30, 0)
    v.table.verticalScrollBar().setValue(25)
    v.rows.insert(0, 999)                                  # коллега добавил запись в начало: строки сместились
    assert lr.refresh(v) is True
    assert v.table.item(v.table.currentRow(), 0).data(Qt.ItemDataRole.UserRole) == 30        # выбрана та же запись, а не та же строка
    assert v.table.verticalScrollBar().value() == 25
    assert lr.relevant({'edit_locks', 'audit_log'}) is False and lr.relevant({'estimates'}) is True
    assert lr.can_refresh(v) is True
    v.edit.setFocus()
    QApplication.processEvents()
    if QApplication.focusWidget() is v.edit:               # без экрана фокус может не выдаваться; если выдан — вводить текст нельзя прерывать
        assert lr.can_refresh(v) is False
    v.hide()
    assert lr.can_refresh(v) is False
    v.deleteLater()


def test_hidden_sections_in_menu_and_ip_tabs(tmp_path, monkeypatch):
    import sys
    from PyQt6.QtWidgets import QApplication
    from smetagaz.database import DatabaseManager
    import smetagaz.main_window as mw
    import smetagaz.ip_view as ipv
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not d:
            monkeypatch.setattr(mod, 'db', d)
    monkeypatch.setattr(mw.QApplication, 'quit', staticmethod(lambda: None))
    w = mw.MainWindow()
    assert 'СМР (ИП)' in [b.text() for b in w.tabs_buttons]
    w.hide()
    w.deleteLater()
    d.hidden = frozenset({'ip', 'stats', 'ip_tax'})
    w = mw.MainWindow()
    names = [b.text() for b in w.tabs_buttons]
    assert 'СМР (ИП)' not in names and 'Статистика' not in names and 'Реестр смет' in names
    w.hide()
    w.deleteLater()
    v = ipv.IpView()
    assert [t for _, t in v.pages if t in ('Налог', 'Оплаты', 'Ведомость по месяцам')] == []
    v.deleteLater()
    QApplication.processEvents()


def test_user_dialog_sections_and_roles(tmp_path, monkeypatch):
    from smetagaz import server_app
    from PyQt6.QtCore import Qt
    users = sc.UserStore(tmp_path / 'users.db')
    uid = users.add('anna', 'pass12', 'editor', 'Анна', hidden=['stats'])
    d = server_app.UserDialog(users, uid)
    assert d.sections.isEnabled() and d.hidden() == ['stats']
    d.role.setCurrentIndex(d.role.findData('manager'))
    assert not d.sections.isEnabled()
    d.role.setCurrentIndex(d.role.findData('editor'))
    first = d.sections.item(0)
    first.setCheckState(Qt.CheckState.Unchecked)
    d.save()
    assert users.raw_hidden(uid) == {'stats', first.data(Qt.ItemDataRole.UserRole)}
    assert 'доступ к разделам изменён' in users.journal(1)[0][5]
    d.deleteLater()
    new = server_app.UserDialog(users, None)
    new.login.setText('boris')
    new.password.setText('pass123')
    new.role.setCurrentIndex(new.role.findData('manager'))
    new.save()
    assert [r for r in users.listing() if r[1] == 'boris'][0][3] == 'manager'


def test_online_and_journal_widgets(net, monkeypatch):
    from smetagaz import ops_ui, edit_locks as locks
    locks.migrate(net.db)
    monkeypatch.setattr(locks, 'SID', 'zz')
    locks.acquire(net.client(), 'estimate:12')
    w = ops_ui.OnlineWidget(lambda: ([list(x) for x in net.server.active_sessions()], net.server.locks()), lambda key: net.server.release_lock(key, 'сервер'))
    assert w.locks.rowCount() == 1 and 'Смета № 12' in w.locks.item(0, 0).text()
    w.locks.selectRow(0)
    monkeypatch.setattr(ops_ui.QMessageBox, 'question', staticmethod(lambda *a, **k: ops_ui.QMessageBox.StandardButton.Yes))
    w.release_selected()
    assert w.locks.rowCount() == 0 and net.server.locks() == []
    j = ops_ui.JournalWidget(lambda event: net.users.journal(100, event))
    assert j.table.rowCount() >= 1
    j.filter.setCurrentIndex(j.filter.findData('lock_release'))
    assert j.table.rowCount() == 1 and 'Снята блокировка' in j.table.item(0, 1).text()
    w.timer.stop()
    w.deleteLater()
    j.deleteLater()


def test_lost_connection_dialog_returns_when_server_back(net):
    from smetagaz import network_ui
    r = net.client()
    d = network_ui.LostConnectionDialog(r)
    d.attempt()                                            # сервер работает — окно сразу принимает
    assert d.ok is True
    d2 = network_ui.LostConnectionDialog(r)
    bad = dict(r.cfg, port=net.port + 1)
    r.cfg = bad
    d2.attempt()
    assert d2.ok is False                                  # сервер недоступен — ждём дальше
    r.cfg = dict(bad, port=net.port)
    d2.timer.stop()
    d.deleteLater()
    d2.deleteLater()


def test_local_side_by_side_poll_changes(tmp_path):
    from smetagaz.database import DatabaseManager
    a = DatabaseManager(tmp_path / 'smetagaz.db')
    a.init_db()
    b = DatabaseManager(tmp_path / 'smetagaz.db')
    b.init_db()
    a.side_by_side = True
    assert a.poll_changes() == set()
    assert a.poll_changes() == set()
    b.execute("INSERT INTO categories(name) VALUES('чужая')")
    assert a.poll_changes() == {'*'}
    assert a.poll_changes() == set()
    a.execute("INSERT INTO categories(name) VALUES('своя')")
    assert a.poll_changes() == set()                       # свои правки не считаются
    a.close()
    b.close()


def test_main_window_live_refresh_and_read_only_payments(tmp_path, monkeypatch):
    import sys
    from PyQt6.QtWidgets import QApplication, QPushButton
    from smetagaz.database import DatabaseManager
    import smetagaz.main_window as mw
    import smetagaz.payments_view as pv
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not d:
            monkeypatch.setattr(mod, 'db', d)
    monkeypatch.setattr(mw.QApplication, 'quit', staticmethod(lambda: None))
    w = mw.MainWindow()
    w.show()
    QApplication.processEvents()
    view = w._current_view()
    calls = []
    view.load_data = lambda: calls.append(1)
    w._changes_pending = False
    answers = [set(), {'edit_locks'}, {'estimates'}]
    monkeypatch.setattr(d, 'poll_changes', lambda: answers.pop(0) if answers else set(), raising=False)
    w.live_refresh()
    w.live_refresh()
    assert calls == []                                    # ничего не изменилось / изменились служебные таблицы
    w.live_refresh()
    assert calls == [1]                                   # коллега изменил сметы — раздел перечитан
    w.live_refresh()
    assert calls == [1]
    w.hide()
    w.deleteLater()
    # оплаты: окно только для просмотра
    d.execute("INSERT INTO estimates(title,date,total) VALUES('С','2026-01-01',100)")
    eid = d.fetchone('SELECT id FROM estimates')[0]
    d.hidden = frozenset({'payments'})
    dlg = pv.PaymentsDialog('estimates', eid)
    assert 'только просмотр' in dlg.windowTitle()
    assert not any(b.isEnabled() for b in dlg.findChildren(QPushButton))
    dlg.deleteLater()
    d.hidden = frozenset()
    dlg = pv.PaymentsDialog('estimates', eid)
    assert any(b.isEnabled() for b in dlg.findChildren(QPushButton))
    dlg.deleteLater()
