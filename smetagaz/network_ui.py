"""Клиентский режим: окно входа на ПТО Сервер, выбор режима работы, индикатор связи."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout

from . import net_config, net_proto as proto
from .remote_db import RemoteDatabaseManager
from .server_core import pretty_fingerprint

LOOPBACK = ('127.0.0.1', 'localhost', '::1')


def is_loopback(host):
    return str(host).strip().lower() in LOOPBACK


class LoginDialog(QDialog):
    """Подключение к серверу и вход. При первом подключении показывает отпечаток сертификата для сверки с окном ПТО Сервера."""
    def __init__(self, db, parent=None, message=''):
        super().__init__(parent)
        self.db = db
        self.cfg = net_config.load()
        self.setWindowTitle('ПТО · вход на сервер')
        self.resize(460, 280)
        layout = QVBoxLayout(self)
        if message:
            note = QLabel(message)
            note.setWordWrap(True)
            note.setStyleSheet('color: #B45309;')
            layout.addWidget(note)
        f = QFormLayout()
        self.host = QLineEdit(self.cfg['host'])
        self.host.setPlaceholderText('например 192.168.1.10')
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(self.cfg['port'])
        self.login = QLineEdit(self.cfg['login'])
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        f.addRow('Адрес сервера', self.host)
        f.addRow('Порт', self.port)
        f.addRow('Логин', self.login)
        f.addRow('Пароль', self.password)
        layout.addLayout(f)
        self.remember = QCheckBox('Запомнить вход на этом компьютере')
        self.remember.setToolTip('Пароль не сохраняется: компьютер получает отдельный ключ входа, который можно отозвать (смена пароля, отключение пользователя, «Забыть вход»).')
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        self.info = QLabel('')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        bar = QHBoxLayout()
        local = QPushButton('Работать локально…')
        local.setToolTip('Вернуться к обычной работе с локальной базой этого компьютера')
        local.clicked.connect(self.go_local)
        ok = QPushButton('Войти')
        ok.setProperty('type', 'primary')
        ok.setDefault(True)
        ok.clicked.connect(self.connect_now)
        cancel = QPushButton('Выход')
        cancel.clicked.connect(self.reject)
        bar.addWidget(local)
        bar.addStretch()
        bar.addWidget(cancel)
        bar.addWidget(ok)
        layout.addLayout(bar)
        (self.password if self.host.text() else self.host).setFocus()

    def go_local(self):
        if QMessageBox.question(self, 'Локальный режим', 'Программа будет работать с локальной базой этого компьютера (не с сервером). Продолжить? Потребуется перезапуск.') == QMessageBox.StandardButton.Yes:
            cfg = net_config.load()
            cfg['mode'] = 'local'
            net_config.save(cfg)
            QMessageBox.information(self, 'Режим изменён', 'Перезапустите программу.')
            self.reject()

    def connect_now(self):
        host, port = self.host.text().strip(), self.port.value()
        if not host:
            self.info.setText('Укажите адрес сервера.')
            return
        try:
            pinned = self.cfg['fingerprint'] if (host, port) == (self.cfg['host'], self.cfg['port']) else ''
            if not pinned:
                fingerprint, hello = RemoteDatabaseManager.probe(host, port)
                if hello.get('needs_setup'):
                    raise proto.RemoteError('На сервере ещё нет ни одного пользователя. Создайте администратора в окне ПТО Сервера.')
                text = (f'Первое подключение к серверу {host}:{port}.\n\nОтпечаток его сертификата:\n{pretty_fingerprint(fingerprint)}\n\n'
                        'Сверьте его с отпечатком в окне «ПТО Сервер». Если совпадает — доверять этому серверу?')
                if QMessageBox.question(self, 'Проверка сервера', text) != QMessageBox.StandardButton.Yes:
                    return
                pinned = fingerprint
            self.db.cfg = dict(self.cfg, host=host, port=port, fingerprint=pinned, mode='client')
            self.db._local.conn = None
            info = self.db.connect(self.login.text().strip(), self.password.text(), remember=self.remember.isChecked())
        except proto.RemoteError as e:
            self.info.setText(f'<span style="color:#DC2626">{e}</span>')
            return
        except proto.ConnectionLost as e:
            self.info.setText(f'<span style="color:#DC2626">Не удаётся подключиться к {host}:{port}. Проверьте адрес, что ПТО Сервер запущен и порт открыт в брандмауэре.<br>{e}</span>')
            return
        net_config.save(dict(mode='client', host=host, port=port, fingerprint=pinned, login=self.login.text().strip(),
                             token=info.get('remember_token', '') if self.remember.isChecked() else ''))
        self.accept()


def try_saved_login(db):
    """Тихий вход по сохранённому ключу. -> '' если вошли, иначе текст для окна входа (пустой ключ — просто нет сохранённого входа, None)."""
    cfg = net_config.load()
    if not (cfg['token'] and cfg['host'] and cfg['login'] and cfg['fingerprint']):
        return None
    db.cfg = dict(cfg, mode='client')
    db._local.conn = None
    try:
        db.connect(cfg['login'], remember_token=cfg['token'])
        return ''
    except proto.ConnectionLost as e:
        return f'Не удаётся подключиться к серверу {cfg["host"]}:{cfg["port"]}: проверьте, что ПТО Сервер запущен. Сохранённый вход не потерян.'
    except proto.RemoteError as e:
        if e.code in ('bad_token', 'bad_login', 'throttled'):
            if e.code == 'bad_token':
                forget_saved_login()
            return str(e)
        return str(e)


def forget_saved_login():
    cfg = net_config.load()
    cfg['token'] = ''
    net_config.save(cfg)


def connect_client(db, message=''):
    """Вход на сервер перед открытием главного окна. True — подключено. Если на этом компьютере есть сохранённый вход — окно не показывается."""
    if not message:
        saved = try_saved_login(db)
        if saved == '':
            return True
        message = saved or ''
    dlg = LoginDialog(db, None, message)
    return bool(dlg.exec())


class NetworkDialog(QDialog):
    """Переключение режима работы (из «Настроек»)."""
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle('Сетевая работа')
        self.resize(480, 280)
        layout = QVBoxLayout(self)
        cfg = net_config.load()
        remote = getattr(db, 'is_remote', False)
        if remote:
            text = (f'Режим: <b>клиент</b>. Сервер: <b>{cfg["host"]}:{cfg["port"]}</b>. Вы вошли как <b>{db.user}</b> ({db.role}). Версия сервера: {db.server_version}.<br><br>'
                    'Данные хранятся на сервере. Резервные копии и восстановление выполняются на компьютере с ПТО Сервером.')
        else:
            text = ('Режим: <b>локальная база</b> на этом компьютере.<br><br>Чтобы работать через ПТО Сервер офиса, нажмите «Подключиться к серверу» и после перезапуска '
                    'введите адрес сервера, логин и пароль. Данные локальной базы на сервер не переносятся — сначала перенесите их (см. руководство).')
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        bar = QHBoxLayout()
        client = QPushButton('Подключиться к серверу…')
        client.clicked.connect(lambda: self.switch('client'))
        local = QPushButton('Работать локально')
        local.clicked.connect(lambda: self.switch('local'))
        client.setEnabled(not remote)
        local.setEnabled(remote)
        bar.addWidget(client)
        bar.addWidget(local)
        layout.addLayout(bar)
        if remote and db.role in ('admin', 'manager'):
            who = QPushButton('Кто в сети и что открыто…' + (' · журнал входов' if db.role == 'admin' else ''))
            who.clicked.connect(self.show_ops)
            layout.addWidget(who)
        if remote:
            saved = bool(cfg.get('token'))
            forget = QPushButton('Забыть сохранённый вход' if saved else 'Вход не сохранён')
            forget.setEnabled(saved)
            forget.setToolTip('При следующем запуске программа снова спросит логин и пароль. Ключ входа отзывается на сервере.')
            forget.clicked.connect(lambda: self.forget(forget))
            layout.addWidget(forget)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)

    def show_ops(self):
        from .ops_ui import client_dialog
        client_dialog(self.db, self).exec()

    def forget(self, button):
        try:
            self.db.disconnect(forget=True)
        except Exception:
            pass
        forget_saved_login()
        button.setText('Вход не сохранён')
        button.setEnabled(False)
        QMessageBox.information(self, 'Вход забыт', 'При следующем запуске потребуются логин и пароль. Программа сейчас закроется.')
        from PyQt6.QtWidgets import QApplication
        QApplication.closeAllWindows()

    def switch(self, mode):
        if mode == 'client' and QMessageBox.question(self, 'Сетевой режим', 'После перезапуска программа запросит адрес сервера и вход. Локальная база не изменится. Включить сетевой режим?') != QMessageBox.StandardButton.Yes:
            return
        cfg = net_config.load()
        cfg['mode'] = mode
        net_config.save(cfg)
        QMessageBox.information(self, 'Режим изменён', 'Перезапустите программу.')
        self.accept()


def attach_status(window, db):
    """Индикатор связи в боковой панели: зелёный — на связи, красный — нет."""
    label = QLabel('')
    label.setWordWrap(True)
    label.setStyleSheet('padding: 4px 8px; font-size: 9pt;')

    def show(ok, text):
        label.setText(('● ' if ok else '○ ') + text)
        label.setStyleSheet(f'padding: 4px 8px; font-size: 9pt; color: {"#15803D" if ok else "#DC2626"};')
    db.on_status = show
    show(True, f'{db.user} · сервер {db.cfg["host"]}')
    return label


class LostConnectionDialog(QDialog):
    """«Нет связи с сервером»: программа сама повторяет подключение и продолжает прерванное действие, когда сервер снова доступен.
    Данные в открытых окнах не теряются; если отказаться ждать, действие завершится ошибкой, а окно с данными останется открытым."""
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db, self.ok, self.waited = db, False, 0
        self.setWindowTitle('Нет связи с сервером')
        self.setModal(True)
        self.resize(480, 190)
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        bar = QHBoxLayout()
        now = QPushButton('Повторить сейчас')
        now.clicked.connect(self.attempt)
        cancel = QPushButton('Отмена')
        cancel.setToolTip('Прервать действие. Данные в открытых окнах останутся — их можно будет сохранить позже.')
        cancel.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(now)
        bar.addWidget(cancel)
        layout.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.show_text()

    def show_text(self, extra=''):
        cfg = self.db.cfg
        self.label.setText(f'<b>Нет связи с сервером {cfg["host"]}:{cfg["port"]}.</b><br>Проверьте сеть и что «ПТО Сервер» запущен. Программа повторяет подключение сама '
                           f'(ждём уже {self.waited} с) и продолжит ваше действие, как только связь вернётся.<br>Всё, что вы ввели в открытых окнах, сохранено в них.{extra}')

    def tick(self):
        self.waited += 1
        self.show_text()
        if self.waited % 3 == 0:
            self.attempt()

    def attempt(self):
        try:
            self.db._connection(fresh=True)
        except proto.RemoteError as e:                 # другой сертификат — ждать бессмысленно
            self.timer.stop()
            self.show_text(f'<br><span style="color:#DC2626">{e}</span>')
            return
        except (OSError, proto.ConnectionLost):
            return
        self.ok = True
        self.accept()

    def done(self, result):
        self.timer.stop()
        super().done(result)


def wait_for_connection(db):
    """Для RemoteDatabaseManager.on_lost: -> True, если связь вернулась. Вне основного потока Qt не ждёт (там просто ошибка)."""
    import threading
    from PyQt6.QtWidgets import QApplication
    if threading.current_thread() is not threading.main_thread() or QApplication.instance() is None:
        return False
    if getattr(db, '_lost_dialog_open', False):
        return False
    db._lost_dialog_open = True
    try:
        dlg = LostConnectionDialog(db, QApplication.activeWindow())
        dlg.exec()
        return dlg.ok
    finally:
        db._lost_dialog_open = False
