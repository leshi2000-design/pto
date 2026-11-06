"""Окно «Обновить программу из ZIP-файла»: выбор архива, проверка, установка без замены файлов программы, откат к встроенной версии."""
import sys
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton, QTextBrowser, QVBoxLayout

import pto_overlay
from . import __version__
from .database import db


class StageWorker(QThread):
    """Проверка и подготовка обновления в фоне: окно программы не зависает."""
    finished_with = pyqtSignal(dict)

    def __init__(self, zip_path, parent=None):
        super().__init__(parent)
        self.zip_path = zip_path

    def run(self):
        result = dict(ok=False, report='', error='', warnings=[], dest=None, info=None)
        try:
            info, dest, warnings = pto_overlay.stage(self.zip_path)
            result.update(info=info, dest=dest, warnings=warnings)
            ok, report = pto_overlay.run_selftest(dest)
            result.update(ok=ok, report=report)
            if not ok:
                import shutil
                shutil.rmtree(dest, ignore_errors=True)
        except pto_overlay.UpdateError as e:
            result['error'] = str(e)
        except Exception as e:                                    # непредвиденная ошибка не должна оставить окно «зависшим»
            result['error'] = f'{type(e).__name__}: {e}'
        self.finished_with.emit(result)


def source_text():
    """Какая версия работает сейчас и откуда она."""
    active = pto_overlay.ACTIVE
    if active:
        return f'Работает версия {__version__} из обновления (встроенная в программу — {active["builtin"] or "?"}).'
    text = f'Работает встроенная версия {__version__}.'
    if pto_overlay.IGNORED:
        text += f' Обновление не подключено: {pto_overlay.IGNORED}.'
    return text


class ZipUpdateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Обновление программы из ZIP-файла')
        self.resize(720, 560)
        self.worker = None
        self.installed_version = ''
        layout = QVBoxLayout(self)
        self.state = QLabel(source_text())
        self.state.setWordWrap(True)
        self.state.setStyleSheet('font-weight:600;')
        layout.addWidget(self.state)
        hint = QLabel('Нажмите «Выбрать ZIP…» и укажите архив с новой версией (тот же ZIP, что присылается для установки). Программа сама проверит его, '
                      'сделает снимок баз данных и установит обновление в папку данных — файлы программы (PTO.exe) не заменяются. После установки закройте и снова откройте программу. '
                      'Если новая версия не запустится, программа сама вернётся к предыдущей.')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(QLabel('Установленные обновления:'))
        self.items = QListWidget()
        self.items.setMaximumHeight(110)
        layout.addWidget(self.items)
        self.log = QTextBrowser()
        layout.addWidget(self.log, 1)
        bar = QHBoxLayout()
        self.pick = QPushButton('Выбрать ZIP…')
        self.pick.setProperty('type', 'primary')
        self.pick.clicked.connect(self.choose)
        self.rollback = QPushButton('Вернуться к встроенной версии')
        self.rollback.clicked.connect(self.roll_back)
        self.quit_button = QPushButton('Закрыть программу сейчас')
        self.quit_button.clicked.connect(self.quit_program)
        self.quit_button.hide()
        close = QPushButton('Закрыть окно')
        close.clicked.connect(self.reject)
        for b in (self.pick, self.rollback, self.quit_button):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(close)
        layout.addLayout(bar)
        self.refresh()

    def refresh(self):
        self.items.clear()
        for i in pto_overlay.installed():
            when = datetime.fromisoformat(i['installed']).strftime('%d.%m.%Y %H:%M') if i['installed'] else ''
            self.items.addItem(f'{"● " if i["active"] else "   "}{i["version"]} · {when} · {i["source"]}' + ('  (включено)' if i['active'] else ''))
        self.rollback.setEnabled(bool(pto_overlay.current_name()))

    def say(self, text):
        self.log.append(text)

    # --- установка
    def choose(self, path=None):
        path = path or QFileDialog.getOpenFileName(self, 'Архив обновления', '', 'ZIP-архив (*.zip)')[0]
        if not path:
            return
        try:
            info = pto_overlay.inspect_zip(path)
        except pto_overlay.UpdateError as e:
            QMessageBox.warning(self, 'Обновление', str(e))
            return
        current = pto_overlay.parse_version(__version__)
        new = pto_overlay.parse_version(info['version'])
        if new == current:
            question = f'В архиве та же версия, что работает сейчас ({info["version"]}). Установить заново?'
        elif new < current:
            question = f'В архиве более СТАРАЯ версия ({info["version"]}), сейчас работает {__version__}. Базы данных уже могли быть обновлены под новую версию. Всё равно установить?'
        else:
            question = f'Установить обновление {__version__} → {info["version"]}?'
        if QMessageBox.question(self, 'Обновление', question) != QMessageBox.StandardButton.Yes:
            return
        self.pick.setEnabled(False)
        self.rollback.setEnabled(False)
        self.say(f'Проверяю архив {info["version"]}: распаковка, синтаксис, самопроверка в отдельном процессе (до минуты)…')
        self.worker = StageWorker(path, self)
        self.worker.finished_with.connect(self.staged)
        self.worker.start()

    def staged(self, result):
        self.pick.setEnabled(True)
        if result['error']:
            self.say('<b>Не установлено:</b> ' + result['error'])
            QMessageBox.warning(self, 'Обновление', result['error'])
            self.refresh()
            return
        if not result['ok']:
            self.say('<b>Самопроверка обновления не пройдена — оно не установлено, программа работает как раньше.</b><pre>' + result['report'][-3000:] + '</pre>')
            QMessageBox.warning(self, 'Обновление', 'Самопроверка нового архива не пройдена. Установка отменена, ваши данные и программа не изменены. Подробности — в окне.')
            self.refresh()
            return
        try:
            db.safety_backup('update')                              # снимок баз перед включением новой версии
        except Exception as e:
            self.say(f'Снимок баз перед обновлением не создан: {e}')
        pto_overlay.activate_folder(result['dest'])
        self.installed_version = result['info']['version']
        for w in result['warnings']:
            self.say('⚠ ' + w)
        self.say(f'<b>Обновление {self.installed_version} установлено и включено.</b> Закройте программу и откройте снова — запустится новая версия.')
        self.state.setText(source_text() + f' Установлено {self.installed_version}: вступит в силу после перезапуска.')
        self.quit_button.show()
        self.refresh()

    def roll_back(self):
        if QMessageBox.question(self, 'Обновление', 'Отключить установленное обновление и вернуться к версии, встроенной в программу? Изменения применятся после перезапуска.') != QMessageBox.StandardButton.Yes:
            return
        pto_overlay.deactivate('Отключено пользователем')
        self.say('Обновление отключено: после перезапуска запустится встроенная версия.')
        self.quit_button.show()
        self.refresh()

    def quit_program(self):
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMainWindow):
                self.reject()
                (w.request_quit if hasattr(w, 'request_quit') else w.close)()
                return
        QApplication.quit()
