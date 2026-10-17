"""Окно «ПТО Сервер»: состояние, адреса для подключения, отпечаток сертификата, подключённые пользователи, управление пользователями и копиями."""
import sys

from PyQt6.QtCore import QLockFile, QTimer, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
                              QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import __version__
from .config import DATA_DIR
from .server_core import RESTRICTABLE, ROLES, local_addresses, pretty_fingerprint


class UserDialog(QDialog):
    def __init__(self, users, uid=None, parent=None):
        super().__init__(parent)
        self.users, self.uid = users, uid
        self.setWindowTitle('Пользователь')
        f = QFormLayout(self)
        self.login = QLineEdit()
        self.name = QLineEdit()
        self.role = QComboBox()
        for key, text in ROLES.items():
            self.role.addItem(text, key)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText('не короче 6 символов' if not uid else 'оставьте пустым, чтобы не менять')
        for label, w in (('Логин', self.login), ('Имя (для журнала)', self.name), ('Роль', self.role), ('Пароль', self.password)):
            f.addRow(label, w)
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        from .permissions import assignable
        self.sections = QListWidget()
        self.sections.setMinimumHeight(220)
        hidden = users.raw_hidden(uid) if uid else frozenset()
        for key, title in assignable():
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked if key in hidden else Qt.CheckState.Checked)
            self.sections.addItem(item)
        self.sections_note = QLabel()
        self.sections_note.setWordWrap(True)
        f.addRow('Что видит пользователь', self.sections)
        f.addRow(self.sections_note)
        self.role.currentIndexChanged.connect(self.role_changed)
        self.role_changed()
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        if uid:
            row = next(r for r in users.listing() if r[0] == uid)
            self.login.setText(row[1])
            self.login.setEnabled(False)
            self.name.setText(row[2])
            self.role.setCurrentIndex(self.role.findData(row[3]))

    def role_changed(self):
        restrict = self.role.currentData() in RESTRICTABLE
        self.sections.setEnabled(restrict)
        self.sections_note.setText('Снимите галочки с разделов, которые нужно скрыть от этого сотрудника. «Налоги и доходы ИП» закрываются и на уровне базы; '
                                  '«Оплаты» — ввод и правка закрываются на сервере, просмотр остаётся (суммы входят в общие сводки). Остальные разделы скрываются в интерфейсе.'
                                  if restrict else 'Администратору и руководителю доступны все разделы.')

    def hidden(self):
        return [self.sections.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sections.count())
                if self.sections.item(i).checkState() == Qt.CheckState.Unchecked]

    def save(self):
        try:
            if self.uid:
                self.users.update(self.uid, role=self.role.currentData(), full_name=self.name.text().strip(), hidden=self.hidden(), actor='сервер')
                if self.password.text():
                    self.users.set_password(self.uid, self.password.text(), actor='сервер')
            else:
                self.users.add(self.login.text(), self.password.text(), self.role.currentData(), self.name.text(), hidden=self.hidden(), actor='сервер')
        except ValueError as e:
            QMessageBox.warning(self, 'Пользователь', str(e))
            return
        self.accept()


class UsersDialog(QDialog):
    def __init__(self, users, parent=None):
        super().__init__(parent)
        self.users = users
        self.setWindowTitle('Пользователи ПТО Сервера')
        self.resize(800, 460)
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        for text, fn in (('Добавить', self.add), ('Изменить / сменить пароль', self.edit), ('Отключить / включить', self.toggle), ('Удалить', self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Логин', 'Имя', 'Роль', 'Работает', 'Создан', 'Последний вход'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)
        layout.addWidget(QLabel('Роли: администратор — всё, включая пользователей; руководитель — все разделы и данные, видит «Кто в сети» и снимает зависшие блокировки; сотрудник — работа с данными (разделы можно скрыть); только просмотр — чтение без изменений.'))
        self.load()

    def load(self):
        rows = self.users.listing()
        self.table.setRowCount(len(rows))
        for r, (uid, login, name, role, active, created, last) in enumerate(rows):
            for c, v in enumerate((login, name, ROLES.get(role, role), 'да' if active else 'нет', created[:16].replace('T', ' '), last[:16].replace('T', ' '))):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, uid)
                self.table.setItem(r, c, item)

    def current(self):
        r = self.table.currentRow()
        item = self.table.item(r, 0) if r >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add(self):
        UserDialog(self.users, None, self).exec()
        self.load()

    def edit(self):
        uid = self.current()
        if uid:
            UserDialog(self.users, uid, self).exec()
            self.load()

    def toggle(self):
        uid = self.current()
        if not uid:
            return
        row = next(r for r in self.users.listing() if r[0] == uid)
        try:
            self.users.update(uid, active=not row[4], actor='сервер')
        except ValueError as e:
            QMessageBox.warning(self, 'Пользователь', str(e))
        self.load()

    def delete(self):
        uid = self.current()
        if uid and QMessageBox.question(self, 'Удалить пользователя', 'Удалить пользователя? Записи журнала с его именем останутся.') == QMessageBox.StandardButton.Yes:
            try:
                self.users.delete(uid, actor='сервер')
            except ValueError as e:
                QMessageBox.warning(self, 'Пользователь', str(e))
            self.load()


class ServerWindow(QMainWindow):
    def __init__(self, db, users, server):
        super().__init__()
        self.db, self.users, self.server = db, users, server
        self.setWindowTitle(f'ПТО Сервер {__version__}')
        self.resize(900, 720)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.health = QLabel()
        self.health.setTextFormat(Qt.TextFormat.RichText)
        self.health.setWordWrap(True)
        layout.addWidget(self.health)
        from .ops_ui import OnlineWidget
        self.online = OnlineWidget(lambda: ([list(x) for x in self.server.active_sessions()], self.server.locks()),
                                   lambda key: self.server.release_lock(key, 'сервер'))
        layout.addWidget(self.online, 1)
        bar = QHBoxLayout()
        for text, fn in (('Пользователи…', self.manage_users), ('Журнал входов…', self.show_journal), ('Копия сейчас', self.backup_now), ('Скопировать данные для подключения', self.copy_info), ('Изменить порт…', self.change_port)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.note = QLabel('Не закрывайте это окно, пока сотрудники работают: после закрытия сервер остановится. Её можно свернуть. '
                           'Если Windows спросит про брандмауэр, разрешите доступ для частных сетей.')
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color: #605E5C;')
        layout.addWidget(self.note)
        from .services import AutoBackupService
        self.backup_service = AutoBackupService()         # почасовые копии и выгрузки в Excel — на сервере
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        self.refresh()

    def addresses(self):
        return [f'{ip}:{self.server.port}' for ip in local_addresses()] or [f'(адрес компьютера):{self.server.port}']

    def refresh(self):
        self.status.setText(f'<h3 style="margin:0">Сервер работает</h3>Адреса для подключения: <b>{" · ".join(self.addresses())}</b><br>'
                            f'Отпечаток сертификата: <code>{pretty_fingerprint(self.server.fingerprint)}</code><br>'
                            f'<span style="color:#605E5C">Папка данных: {DATA_DIR}</span>')
        self.refresh_health()

    def refresh_health(self):
        from . import backup_health
        try:
            rows = backup_health.report(self.db)
        except Exception:
            return
        self.health.setText('<b>Резервные копии</b>' + backup_health.html(rows))
        self.setWindowTitle(f'ПТО Сервер {__version__}' + ('' if backup_health.worst(rows) == backup_health.OK else '  ·  ВНИМАНИЕ: копии'))

    def manage_users(self):
        UsersDialog(self.users, self).exec()

    def show_journal(self):
        from .ops_ui import JournalWidget
        dlg = QDialog(self)
        dlg.setWindowTitle('Журнал входов и действий администратора')
        dlg.resize(900, 520)
        lay = QVBoxLayout(dlg)
        lay.addWidget(JournalWidget(lambda event: self.users.journal(500, event)))
        close = QPushButton('Закрыть')
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

    def backup_now(self):
        try:
            from datetime import datetime
            from pathlib import Path
            from .backup import create_backup
            folder = Path(self.db.db_name).parent / 'backups'
            folder.mkdir(exist_ok=True)
            path = folder / f'manual_{datetime.now():%Y%m%d_%H%M%S}.zip'
            create_backup(self.db, path)
            self.db.set_setting('last_db_backup', datetime.now().isoformat())
            self.refresh_health()
            QMessageBox.information(self, 'Копия', f'Копия создана:\n{path}')
        except Exception as e:
            QMessageBox.warning(self, 'Копия не создана', str(e))

    def copy_info(self):
        text = f'Сервер: {self.addresses()[0]}\nОтпечаток: {pretty_fingerprint(self.server.fingerprint)}'
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, 'Скопировано', 'Данные скопированы. Их нужно ввести/сверить при первом подключении клиента:\n\n' + text)

    def change_port(self):
        port, ok = QInputDialog.getInt(self, 'Порт сервера', 'Новый порт (изменение вступит в силу после перезапуска сервера):', self.server.port, 1024, 65535)
        if ok:
            from .server_main import save_settings
            save_settings(port=port)
            QMessageBox.information(self, 'Порт', 'Порт сохранён. Перезапустите ПТО Сервер и сообщите новый порт сотрудникам.')

    def closeEvent(self, event):
        if self.server.active_sessions() and QMessageBox.question(self, 'Остановить сервер', f'Сейчас подключено пользователей: {len(self.server.active_sessions())}. Остановить сервер?') != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        self.timer.stop()
        self.backup_service.close()
        self.server.stop()
        event.accept()


def run_window(port=None):
    from .server_main import build, save_settings
    app = QApplication(sys.argv)
    from .theme import apply
    apply(app)
    lock = QLockFile(str(DATA_DIR / 'server.lock'))
    if not lock.tryLock(100):
        QMessageBox.warning(None, 'ПТО Сервер', 'ПТО Сервер для этой папки данных уже запущен.')
        return 1
    db, users, server = build(port)
    if not users.count():
        login, ok = QInputDialog.getText(None, 'Первый запуск', 'Создайте администратора.\nЛогин:')
        password = QInputDialog.getText(None, 'Первый запуск', 'Пароль (не короче 6 символов):', QLineEdit.EchoMode.Password)[0] if ok else ''
        try:
            users.add(login, password, 'admin', login)
        except ValueError as e:
            QMessageBox.critical(None, 'ПТО Сервер', str(e))
            return 1
    try:
        server.start()
    except OSError as e:
        QMessageBox.critical(None, 'ПТО Сервер', f'Не удалось занять порт {server.port}: {e}\nВозможно, сервер уже запущен или порт занят.')
        return 1
    save_settings(port=server.port)
    window = ServerWindow(db, users, server)
    window.show()
    return app.exec()
