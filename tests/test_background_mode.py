"""Работа в фоне: закрытие окна сворачивает программу в значок, веб-доступ продолжает работать; один экземпляр; автозапуск Windows; тихий старт."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys

import pytest
from PyQt6.QtCore import QEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon

from smetagaz import autostart, tray_service as ts
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class FakeWindow(QMainWindow):
    """Минимальное окно с тем же правилом закрытия, что у главного окна (MainWindow.closeEvent)."""
    quit_requested = False

    def closeEvent(self, event):
        ctl = getattr(self, 'background', None)
        if ctl is not None and not getattr(self, '_force_quit', False) and ctl.hide_on_close():
            event.ignore()
            self.hide()
            ctl.window_hidden()
            return
        event.accept()

    def request_quit(self):
        self._force_quit = True
        self.quit_requested = True
        self.close()


def test_close_hides_to_tray_and_quit_really_closes(db, app, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, 'isVisible', lambda self: True)
    shown = []
    monkeypatch.setattr(QSystemTrayIcon, 'showMessage', lambda self, *a, **k: shown.append(a[0]))
    w = FakeWindow()
    ctl = ts.BackgroundController(app, w, db, web_urls=lambda: ['https://192.168.0.5:8765'])
    assert not ctl.enabled() and app.quitOnLastWindowClosed()                               # по умолчанию выключено: крестик закрывает как раньше
    w.show()
    w.close()
    assert not w.isVisible() and not getattr(w, 'quit_requested', False)
    w.show()
    db.set_setting('background_mode', '1')
    ctl.apply()
    assert ctl.enabled() and not app.quitOnLastWindowClosed()
    w.show()
    w.close()                                                                               # режим «в фоне»: окно скрыто, но не закрыто
    assert w.isHidden() and shown == ['ПТО продолжает работать в фоне']
    assert 'Веб-доступ' in ctl.tray.toolTip() and '192.168.0.5:8765' in ctl.tray.toolTip()
    w.show()
    w.close()
    assert shown == ['ПТО продолжает работать в фоне']                                       # подсказка показывается один раз
    ctl.show_window()
    assert w.isVisible()
    ctl.quit_app()                                                                          # «Выход» из значка — настоящее закрытие
    assert w.quit_requested and ctl.quitting
    db.set_setting('background_mode', '0')
    ctl.apply()
    assert app.quitOnLastWindowClosed()


def test_no_tray_means_normal_close(db, app, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: False))
    db.set_setting('background_mode', '1')
    w = FakeWindow()
    ctl = ts.BackgroundController(app, w, db)
    assert not ctl.enabled() and not ctl.hide_on_close() and app.quitOnLastWindowClosed()        # без значка окно не «прячется» — потерять его было бы нельзя


def test_session_end_allows_real_close(db, app, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, 'isVisible', lambda self: True)
    db.set_setting('background_mode', '1')
    w = FakeWindow()
    ctl = ts.BackgroundController(app, w, db)
    assert ctl.hide_on_close()
    ctl._session_end()                                                                      # выключение Windows
    assert not ctl.hide_on_close() and w._force_quit


def test_silent_start_asks_password_only_when_window_is_opened(db, app, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: True))
    monkeypatch.setattr(QSystemTrayIcon, 'isVisible', lambda self: True)
    asked = []
    w = FakeWindow()
    answers = iter([False, True])
    ctl = ts.BackgroundController(app, w, db, authenticate=lambda: asked.append(1) or next(answers))
    ctl.authenticated = False                                                               # запуск вместе с Windows: пароль ещё не вводили
    ctl.show_window()
    assert not w.isVisible() and len(asked) == 1                                            # неверный пароль / отмена — окно не открывается
    ctl.show_window()
    assert w.isVisible() and ctl.authenticated
    ctl.show_window()
    assert len(asked) == 2                                                                  # после входа пароль больше не спрашивается


def test_second_launch_activates_running_program(app, tmp_path):
    path = tmp_path / 'instance.json'
    calls = []
    first = ts.SingleInstance(path, lambda: calls.append('show'))
    second = ts.SingleInstance(path, lambda: calls.append('second'))
    assert second.activate_running() is False                                              # первого экземпляра ещё нет (и файла нет)
    assert first.listen() and path.exists()
    assert second.activate_running() is True
    QTest.qWait(300)
    assert calls == ['show']                                                                # первый экземпляр получил просьбу показать окно
    # чужой процесс без ключа окно показать не может
    import json
    import socket
    info = json.loads(path.read_text(encoding='utf-8'))
    with socket.create_connection(('127.0.0.1', info['port']), timeout=2) as conn:
        conn.sendall(b'wrong show\n')
        conn.settimeout(1)
        assert conn.recv(8) == b''
    QTest.qWait(200)
    assert calls == ['show']
    first.stop()
    assert not path.exists() and second.activate_running() is False                         # после выхода первого экземпляра запускается обычный запуск


def test_only_bundled_qt_modules_are_imported():
    """Собранная программа содержит только QtCore, QtGui, QtWidgets, QtSvg, QtPrintSupport (см. smetagaz.spec), а обновление из ZIP набор модулей изменить не может:
    импорт любого другого модуля Qt в коде программы ломает обновление (самопроверка его не пропустит). Тесты (QtTest) под запретом не подпадают."""
    import re
    from pathlib import Path
    allowed = {'QtCore', 'QtGui', 'QtWidgets', 'QtSvg', 'QtPrintSupport', 'sip'}
    bad = []
    for path in Path(__file__).resolve().parent.parent.joinpath('smetagaz').glob('*.py'):
        for line in path.read_text(encoding='utf-8').splitlines():
            m = re.match(r'\s*(?:from PyQt6\.(\w+) import|import PyQt6\.(\w+)|from PyQt6 import (\w+))', line)
            if m and (m.group(1) or m.group(2) or m.group(3)) not in allowed:
                bad.append(f'{path.name}: {line.strip()}')
    assert not bad, bad
    for name in ('tray_service', 'autostart'):                               # и ни одного импорта QtNetwork / winreg в новых модулях
        text = (Path(__file__).resolve().parent.parent / 'smetagaz' / f'{name}.py').read_text(encoding='utf-8')
        assert not re.search(r'^\s*(from|import)\s+\S*(QtNetwork|winreg)', text, re.M)


def test_autostart_uses_reg_exe(monkeypatch):
    calls, store = [], {}

    def fake_reg(*args):
        calls.append(args)
        if args[0] == 'add':
            store['PTO'] = args[args.index('/d') + 1]
            return 0, ''
        if args[0] == 'query':
            return (0, '    PTO    REG_SZ    ' + store['PTO']) if 'PTO' in store else (1, 'ERROR')
        if args[0] == 'delete':
            return (0, '') if store.pop('PTO', None) else (1, 'ERROR')
    monkeypatch.setattr(autostart, 'supported', lambda: True)
    monkeypatch.setattr(autostart, '_reg', fake_reg)
    assert not autostart.is_enabled()
    autostart.enable()
    assert store['PTO'].endswith('--background') and autostart.is_enabled() and next(c for c in calls if c[0] == 'add')[:3] == ('add', autostart.RUN_KEY, '/v')
    autostart.disable()
    assert not autostart.is_enabled()
    autostart.disable()                                                                     # повторное отключение безвредно
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', r'C:\Program Files\PTO\PTO.exe')
    assert autostart.command() == r'"C:\Program Files\PTO\PTO.exe" --background'
    monkeypatch.setattr(autostart, '_reg', lambda *a: (1, 'Отказано в доступе'))
    with pytest.raises(OSError, match='Отказано'):
        autostart.enable()
    monkeypatch.setattr(autostart, 'supported', lambda: False)
    assert not autostart.is_enabled()
    with pytest.raises(OSError):
        autostart.enable()


def test_settings_checkboxes_for_background_mode(tmp_path, monkeypatch, app):
    import importlib
    d = DatabaseManager(tmp_path / 's.db')
    d.init_db()
    for name in ('notes_view', 'gsn_catalog', 'tasks_view', 'today_view', 'workspace_view', 'main_window', 'gsv_view', 'contract_card', 'payments_view', 'settings_view'):
        importlib.import_module('smetagaz.' + name)
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', d, raising=False)
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', staticmethod(lambda: True))
    stored = {}
    monkeypatch.setattr(autostart, 'supported', lambda: True)
    monkeypatch.setattr(autostart, 'is_enabled', lambda: bool(stored))
    monkeypatch.setattr(autostart, 'enable', lambda: stored.__setitem__('on', 1))
    monkeypatch.setattr(autostart, 'disable', lambda: stored.clear())
    from smetagaz import settings_view as sv
    view = sv.SettingsView(None)
    assert not view.chk_background.isChecked() and not view.chk_autostart.isChecked()
    view.chk_autostart.setChecked(True)                                                    # автозапуск включает и режим «в фоне»
    assert stored and view.chk_background.isChecked() and d.get_setting('background_mode') == '1'
    view.chk_background.setChecked(False)                                                  # выключили фон — автозапуск снят
    assert not stored and not view.chk_autostart.isChecked() and d.get_setting('background_mode') == '0'
    d.close()
