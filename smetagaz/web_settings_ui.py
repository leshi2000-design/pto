"""Настройки веб-доступа (прототип): включение, порт, HTTPS, пользователи."""
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox,
                             QVBoxLayout, QWidget)

from . import web_gateway as wg
from .config import DATA_DIR
from .database import db


class WebUsersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Пользователи веб-доступа')
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        bar = QHBoxLayout()
        for text, fn in (('Добавить…', self.add), ('Сменить пароль…', self.password), ('Роль', self.role), ('Отключить / включить', self.toggle), ('Удалить', self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        lay.addLayout(bar)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        lay.addWidget(close)
        self.load()

    def load(self):
        self.list.clear()
        self.ids = []
        for uid, login, role, active, created, last in wg.users(db):
            self.list.addItem(f'{login} — {wg.ROLES.get(role, role)}{"" if active else " (отключён)"}' + (f' · последний вход {last[:16].replace("T", " ")}' if last else ''))
            self.ids.append(uid)

    def current(self):
        r = self.list.currentRow()
        return self.ids[r] if 0 <= r < len(self.ids) else None

    def add(self):
        login, ok = QInputDialog.getText(self, 'Новый пользователь', 'Логин:')
        if not ok or not login.strip():
            return
        password, ok = QInputDialog.getText(self, 'Новый пользователь', 'Пароль (не короче 8 символов):', QLineEdit.EchoMode.Password)
        if not ok:
            return
        role, ok = QInputDialog.getItem(self, 'Новый пользователь', 'Права:', list(wg.ROLES.values()), 0, False)
        if not ok:
            return
        try:
            wg.add_user(db, login, password, [k for k, v in wg.ROLES.items() if v == role][0])
        except ValueError as e:
            QMessageBox.warning(self, 'Пользователь', str(e))
        self.load()

    def password(self):
        uid = self.current()
        if not uid:
            return
        password, ok = QInputDialog.getText(self, 'Пароль', 'Новый пароль (не короче 8 символов):', QLineEdit.EchoMode.Password)
        if ok:
            try:
                wg.set_password(db, uid, password)
            except ValueError as e:
                QMessageBox.warning(self, 'Пароль', str(e))

    def role(self):
        uid = self.current()
        if uid:
            role, ok = QInputDialog.getItem(self, 'Права', 'Права:', list(wg.ROLES.values()), 0, False)
            if ok:
                wg.set_user(db, uid, role=[k for k, v in wg.ROLES.items() if v == role][0])
                self.load()

    def toggle(self):
        uid = self.current()
        if uid:
            row = db.fetchone('SELECT active FROM web_users WHERE id=?', (uid,))
            wg.set_user(db, uid, active=not row[0])
            self.load()

    def delete(self):
        uid = self.current()
        if uid and QMessageBox.question(self, 'Удаление', 'Удалить пользователя?') == QMessageBox.StandardButton.Yes:
            wg.delete_user(db, uid)
            self.load()


class WebAccessBox(QGroupBox):
    def __init__(self, parent=None):
        super().__init__('Веб-доступ (прототип): карточки договоров с других компьютеров и телефонов сети', parent)
        lay = QVBoxLayout(self)
        note = QLabel('Работает, пока программа открыта на этом компьютере. Доступ только из локальной сети, по логину и паролю. Адрес откройте в браузере другого устройства; '
                      'при первом входе браузер предупредит о самоподписанном сертификате — это ожидаемо: нажмите «Дополнительно → Перейти». В брандмауэре Windows разрешите доступ для частной сети.')
        note.setWordWrap(True)
        lay.addWidget(note)
        row = QHBoxLayout()
        self.enabled = QCheckBox('Включить веб-доступ')
        self.enabled.setChecked(db.get_setting('web_enabled', '0') == '1')
        self.https = QCheckBox('HTTPS (рекомендуется)')
        self.https.setChecked(db.get_setting('web_https', '1') == '1')
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(db.get_setting('web_port', '8765') or 8765))
        for w in (self.enabled, self.https, QLabel('Порт:'), self.port):
            row.addWidget(w)
        users = QPushButton('Пользователи…')
        users.clicked.connect(lambda: WebUsersDialog(self).exec())
        apply = QPushButton('Применить')
        apply.clicked.connect(self.apply)
        row.addWidget(users)
        row.addWidget(apply)
        row.addStretch()
        lay.addLayout(row)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(self.status.textInteractionFlags() | __import__('PyQt6.QtCore', fromlist=['Qt']).Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.status)
        self.refresh()

    def apply(self):
        db.set_setting('web_enabled', '1' if self.enabled.isChecked() else '0')
        db.set_setting('web_https', '1' if self.https.isChecked() else '0')
        db.set_setting('web_port', str(self.port.value()))
        if self.enabled.isChecked() and not wg.users(db):
            QMessageBox.information(self, 'Веб-доступ', 'Добавьте хотя бы одного пользователя (кнопка «Пользователи…»), иначе войти будет некому.')
        wg.apply_settings(db, DATA_DIR)
        self.refresh()

    def refresh(self):
        if wg.LAST_ERROR:
            self.status.setText('Не удалось запустить: ' + wg.LAST_ERROR + ' (возможно, порт занят — выберите другой).')
        elif wg.RUNNING:
            self.status.setText('Работает. Откройте в браузере: ' + '   '.join(wg.urls()))
        else:
            self.status.setText('Выключен.')
