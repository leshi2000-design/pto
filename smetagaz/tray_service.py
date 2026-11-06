"""Работа в фоне: значок у часов, закрытие окна сворачивает программу (веб-доступ, автокопии и напоминания продолжают работать), повторный запуск ярлыка открывает уже работающую программу.

Настройки (в базе): background_mode = 1 — «закрытие окна сворачивает в значок»; запуск вместе с Windows — см. autostart. Выход — только через значок («Выход») или завершение Windows."""
import json
import logging
import secrets
import socket
import threading
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

SETTING = 'background_mode'
HINT_SETTING = 'background_hint_shown'


class SingleInstance(QObject):
    """Один экземпляр на папку данных: второй запуск просит первый показать окно и завершается.
    Связь — обычный локальный сокет (только 127.0.0.1) на стандартных модулях Python: PyQt6.QtNetwork в собранную программу не входит, а обновление из ZIP менять набор модулей не может.
    Порт и случайный ключ хранятся в файле в папке данных; чужой процесс без ключа окно показать не попросит."""
    requested = pyqtSignal()

    def __init__(self, path, on_show, parent=None):
        super().__init__(parent)
        self.path, self.on_show = Path(path), on_show
        self.sock = None
        self.token = ''
        self.requested.connect(lambda: self.on_show())          # сигнал из потока приёма попадает в основной поток

    def activate_running(self):
        """True — программа уже запущена, ей отправлена просьба показать окно (этот процесс можно завершать)."""
        try:
            info = json.loads(self.path.read_text(encoding='utf-8'))
            with socket.create_connection(('127.0.0.1', int(info['port'])), timeout=0.5) as conn:
                conn.sendall((str(info['token']) + ' show\n').encode('ascii'))
                conn.settimeout(0.5)
                return conn.recv(8) == b'ok\n'
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def listen(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.bind(('127.0.0.1', 0))
            self.sock.listen(4)
            self.token = secrets.token_hex(16)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(dict(port=self.sock.getsockname()[1], token=self.token)), encoding='utf-8')
        except OSError:
            logging.exception('Связь между экземплярами программы не запущена')
            return False
        threading.Thread(target=self._accept_loop, daemon=True, name='pto-single-instance').start()
        return True

    def _accept_loop(self):
        while self.sock is not None:
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            try:
                conn.settimeout(1.0)
                line = conn.recv(128).decode('ascii', 'ignore').strip()
                if secrets.compare_digest(line, self.token + ' show'):
                    conn.sendall(b'ok\n')
                    self.requested.emit()
            except (OSError, ValueError):
                pass
            finally:
                conn.close()

    def stop(self):
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        try:
            self.path.unlink()
        except OSError:
            pass


class BackgroundController(QObject):
    """Значок у часов и правила закрытия главного окна."""

    def __init__(self, app, window, db, authenticate=None, web_urls=None, parent=None):
        super().__init__(parent)
        self.app, self.window, self.db = app, window, db
        self.authenticate = authenticate or (lambda: True)           # запрос пароля входа перед показом окна (при тихом запуске в фоне)
        self.web_urls = web_urls or (lambda: [])
        self.quitting = False
        self.tray = None
        self.authenticated = True
        window.background = self
        app.commitDataRequest.connect(self._session_end)             # выключение / выход из Windows — закрываем по-настоящему
        self.apply()

    # --- настройка
    @staticmethod
    def available():
        return QSystemTrayIcon.isSystemTrayAvailable()

    def enabled(self):
        return self.db.get_setting(SETTING, '0') == '1' and self.available()

    def apply(self):
        """Приводит значок и правило «закрыть окно = свернуть» в соответствие с настройкой."""
        on = self.enabled()
        self.app.setQuitOnLastWindowClosed(not on)
        if on and self.tray is None:
            self._build_tray()
        if self.tray is not None:
            self.tray.setVisible(on)

    def _build_tray(self):
        icon = self.app.windowIcon()
        if icon.isNull():
            try:
                from .icons import logo_pixmap
                icon = QIcon(logo_pixmap('#1B6B62', 64))
            except Exception:
                pixmap = QPixmap(32, 32)
                pixmap.fill(Qt.GlobalColor.darkCyan)
                icon = QIcon(pixmap)
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        self.act_open = QAction('Открыть ПТО', menu)
        self.act_open.triggered.connect(self.show_window)
        self.act_web = QAction('Копировать адрес веб-доступа', menu)
        self.act_web.triggered.connect(self.copy_web_address)
        self.act_quit = QAction('Выход (веб-доступ остановится)', menu)
        self.act_quit.triggered.connect(self.quit_app)
        for act in (self.act_open, self.act_web):
            menu.addAction(act)
        menu.addSeparator()
        menu.addAction(self.act_quit)
        self.tray.setContextMenu(menu)
        self._menu = menu
        self.tray.activated.connect(lambda reason: self.show_window() if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.refresh_tooltip()

    def refresh_tooltip(self):
        if self.tray is None:
            return
        urls = self.web_urls()
        self.tray.setToolTip('ПТО работает в фоне' + (f'\nВеб-доступ: {urls[0]}' if urls else ''))

    # --- окно
    def hide_on_close(self):
        """True — закрытие окна крестиком нужно заменить сворачиванием в значок."""
        return self.enabled() and not self.quitting and self.tray is not None and self.tray.isVisible()

    def window_hidden(self):
        """Вызывается после сворачивания в значок: один раз подсказывает, что программа продолжает работать."""
        self.refresh_tooltip()
        if self.db.get_setting(HINT_SETTING, '0') != '1' and self.tray is not None:
            self.db.set_setting(HINT_SETTING, '1')
            urls = self.web_urls()
            self.tray.showMessage('ПТО продолжает работать в фоне', 'Веб-доступ' + (f' ({urls[0]})' if urls else '') + ' работает. Открыть программу — значок у часов; выход — правая кнопка → «Выход».',
                                  QSystemTrayIcon.MessageIcon.Information, 8000)

    def show_window(self):
        """Показывает главное окно (при тихом запуске в фоне сначала спрашивает пароль входа)."""
        if not self.authenticated:
            if not self.authenticate():
                return
            self.authenticated = True
        w = self.window
        if w.isMinimized():
            w.showNormal()
        w.show()
        w.raise_()
        w.activateWindow()

    def copy_web_address(self):
        urls = self.web_urls()
        if urls:
            QApplication.clipboard().setText(urls[0])

    def quit_app(self):
        self.quitting = True
        self.window.request_quit()

    def _session_end(self, manager=None):
        self.quitting = True
        self.window._force_quit = True
