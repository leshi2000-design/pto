"""Настройки веб-доступа (прототип): включение, порт, HTTPS, пользователи."""
from PyQt6.QtWidgets import (QGridLayout, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox,
                             QVBoxLayout, QWidget)

from . import web_gateway as wg, web_tls
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
        note = QLabel('Работает, пока программа открыта на этом компьютере. Доступ только из локальной сети, по логину и паролю; интернет не используется. Страницы выглядят так же, как в программе '
                      '(тема и цвет берутся из настроек). Чтобы браузер не писал «подключение не защищено», один раз установите сертификат ПТО на каждое устройство: откройте на нём адрес «Страница сертификата» '
                      '(там пошаговая инструкция). Если телефон не заходит — нажмите «Разрешить в брандмауэре» и «Проверить доступ».')
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
        tools = QGridLayout()                                   # кнопки в сетке по три в ряд — окно не растягивается вширь
        buttons = (('Разрешить в брандмауэре', self.open_firewall), ('Проверить доступ', self.check), ('Сохранить сертификат ПТО…', self.save_certificate),
                   ('Скопировать адрес', self.copy_address), ('Ярлык на рабочий стол', self.desktop_shortcut), ('Сохранить скрипт установки…', self.save_setup_script))
        for i, (text, fn) in enumerate(buttons):
            b = QPushButton(text)
            b.clicked.connect(fn)
            tools.addWidget(b, i // 3, i % 3)
        lay.addLayout(tools)
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

    def ports(self):
        return [self.port.value(), self.port.value() + 1]

    def open_firewall(self):
        if not web_tls.open_firewall(self.ports()):
            QMessageBox.information(self, 'Брандмауэр', 'Это действие нужно только в Windows. Команда для ручного запуска от имени администратора:\n\n' + web_tls.firewall_command(self.ports()))
            return
        QMessageBox.information(self, 'Брандмауэр', 'Windows сейчас спросит разрешение администратора — нажмите «Да». Будет создано правило «PTO Web» (вход по TCP на порты '
                                f'{self.ports()[0]} и {self.ports()[1]}, только из вашей локальной сети). Потом нажмите «Проверить доступ».')

    def check(self):
        icons = {'ok': '✔', 'warn': '⚠', 'err': '✖'}
        lines = [f'{icons[level]} {text}' for level, text in web_tls.diagnose(wg.RUNNING, wg.RUNNING.installer.port if wg.RUNNING and wg.RUNNING.installer else None)]
        QMessageBox.information(self, 'Проверка веб-доступа', '\n\n'.join(lines))

    def save_certificate(self):
        if not wg.RUNNING or not wg.RUNNING.https:
            QMessageBox.information(self, 'Сертификат', 'Включите веб-доступ с HTTPS и нажмите «Применить».')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить сертификат ПТО', 'pto-ca.crt', 'Сертификат (*.crt *.cer)')
        if path:
            with open(path, 'wb') as f:
                f.write(web_tls.ca_der(DATA_DIR / 'web_cert'))
            QMessageBox.information(self, 'Сертификат', 'Сохранено. Установите файл как «центр сертификации» на устройстве (на телефоне проще открыть «Страницу сертификата» в браузере).\n'
                                    'Отпечаток SHA-256: ' + web_tls.ca_fingerprint(DATA_DIR / 'web_cert'))

    def portal_url(self):
        urls = wg.urls()
        return urls[0] + '/' if urls else ''

    def desktop_shortcut(self):
        url = self.portal_url()
        if not url:
            QMessageBox.information(self, 'Ярлык', 'Сначала включите веб-доступ и нажмите «Применить».')
            return
        try:
            path = web_tls.create_desktop_shortcut(url)
        except OSError as e:
            QMessageBox.warning(self, 'Ярлык', f'Не удалось создать ярлык: {e}')
            return
        QMessageBox.information(self, 'Ярлык', f'Ярлык создан: {path}\nОн открывает портал ПТО ({url}) в браузере.')

    def save_setup_script(self):
        url = self.portal_url()
        if not url or not wg.RUNNING or not wg.RUNNING.https:
            QMessageBox.information(self, 'Скрипт установки', 'Включите веб-доступ с HTTPS и нажмите «Применить».')
            return
        host = url.split('//', 1)[1].rsplit(':', 1)[0]
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить скрипт установки', 'pto-web-setup.bat', 'Сценарий Windows (*.bat)')
        if path:
            install_port = wg.RUNNING.installer.port if wg.RUNNING.installer else wg.RUNNING.port
            with open(path, 'w', encoding='ascii', newline='') as f:
                f.write(web_tls.setup_script(url, f'http://{host}:{install_port}'))
            QMessageBox.information(self, 'Скрипт установки', 'Сохранено. Запустите файл на другом компьютере сети (по флешке или почте): он установит сертификат ПТО и создаст ярлык на рабочем столе. '
                                    'Компьютер с ПТО при этом должен быть включён. Этот же файл можно скачать в самом портале: меню «Ярлык на рабочий стол».')

    def copy_address(self):
        urls = wg.urls()
        if urls:
            QApplication.clipboard().setText(urls[0])

    def refresh(self):
        if wg.LAST_ERROR:
            self.status.setText('Не удалось запустить: ' + wg.LAST_ERROR + ' (возможно, порт занят — выберите другой).')
        elif wg.RUNNING:
            text = 'Работает. Откройте в браузере: ' + '   '.join(wg.urls())
            if wg.install_urls():
                text += '\nСтраница сертификата (один раз на устройство, обычный http): ' + '   '.join(wg.install_urls())
            self.status.setText(text)
        else:
            self.status.setText('Выключен.')
