"""Окно справки (F1) и проверка обновлений."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton, QLineEdit, QLabel, QMessageBox

from .database import db
from . import help_texts, updater


class HelpDialog(QDialog):
    def __init__(self, tab_id='', parent=None):
        super().__init__(parent)
        self.setWindowTitle('Справка')
        self.resize(720, 640)
        layout = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setHtml(help_texts.html(tab_id))
        layout.addWidget(self.view, 1)
        bar = QHBoxLayout()
        update = QPushButton('Проверить обновления…')
        update.clicked.connect(lambda: UpdateDialog(self).exec())
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        bar.addWidget(update)
        bar.addStretch()
        bar.addWidget(close)
        layout.addLayout(bar)


class UpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Проверка обновлений')
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Установленная версия: {updater.__version__}'))
        layout.addWidget(QLabel('Адрес файла версий (https://…, JSON {"version": "3.5.0", "url": "…", "notes": "…"} или текст с номером):'))
        self.url = QLineEdit(db.get_setting('update_url', ''))
        layout.addWidget(self.url)
        self.result = QTextBrowser()
        self.result.setPlainText(updater.HOW_TO)
        layout.addWidget(self.result, 1)
        bar = QHBoxLayout()
        check = QPushButton('Проверить сейчас')
        check.setProperty('type', 'primary')
        check.clicked.connect(self.run)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        bar.addWidget(check)
        bar.addStretch()
        bar.addWidget(close)
        layout.addLayout(bar)

    def run(self):
        db.set_setting('update_url', self.url.text().strip())
        try:
            newer, info, message = updater.check(db, force=True)
        except Exception as e:
            QMessageBox.warning(self, 'Обновления', f'Не удалось проверить: {e}')
            return
        text = message
        if newer:
            if info.get('notes'):
                text += '\n\nЧто нового:\n' + info['notes']
            if info.get('url'):
                text += '\n\nСкачать: ' + info['url']
            text += '\n\n' + updater.HOW_TO
        self.result.setPlainText(text)
