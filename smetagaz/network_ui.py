"""Клиентский режим: окно входа на ПТО Сервер, выбор режима работы, индикатор связи."""
from PyQt6.QtCore import Qt
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
            self.db.connect(self.login.text().strip(), self.password.text())
        except proto.RemoteError as e:
            self.info.setText(f'<span style="color:#DC2626">{e}</span>')
            return
        except proto.ConnectionLost as e:
            self.info.setText(f'<span style="color:#DC2626">Не удаётся подключиться к {host}:{port}. Проверьте адрес, что ПТО Сервер запущен и порт открыт в брандмауэре.<br>{e}</span>')
            return
        net_config.save(dict(mode='client', host=host, port=port, fingerprint=pinned, login=self.login.text().strip()))
        self.accept()


def connect_client(db, message=''):
    """Вход на сервер перед открытием главного окна. True — подключено."""
    while True:
        dlg = LoginDialog(db, None, message)
        if not dlg.exec():
            return False
        return True


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
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)

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
