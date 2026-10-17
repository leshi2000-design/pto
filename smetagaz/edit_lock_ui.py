"""Интерфейс блокировки карточек: сообщение «кто правит», режим «только просмотр», подтверждение блокировки по таймеру."""
from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox, QDialog, QLineEdit, QMessageBox, QPlainTextEdit,
                             QPushButton, QTextEdit)

from . import edit_locks as locks
from .database import db as default_db

VIEW_ONLY_KEEP = ('закрыть', 'отмена', 'печать', 'pdf', 'выход')


def freeze(dialog):
    """Режим «только просмотр»: поля нельзя менять, кнопки действий отключены."""
    for w in dialog.findChildren(QLineEdit):
        w.setReadOnly(True)
    for w in dialog.findChildren(QTextEdit) + dialog.findChildren(QPlainTextEdit):
        w.setReadOnly(True)
    for w in dialog.findChildren(QComboBox) + dialog.findChildren(QAbstractSpinBox):
        w.setEnabled(False)
    for w in dialog.findChildren(QAbstractItemView):
        w.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        w.setAcceptDrops(False)
    for w in dialog.findChildren(QAbstractButton):
        text = w.text().replace('&', '').strip().lower()
        if isinstance(w, QPushButton) and any(text.startswith(k) for k in VIEW_ONLY_KEEP):
            continue
        if w.isCheckable() or isinstance(w, QPushButton):
            w.setEnabled(False)
    dialog.setAcceptDrops(False)
    dialog.setWindowTitle(dialog.windowTitle() + '  ·  ТОЛЬКО ПРОСМОТР')
    dialog.view_only = True


class _Beater(QObject):
    """Таймер, подтверждающий блокировку, пока карточка открыта."""
    def __init__(self, dialog, db, key):
        super().__init__(dialog)
        self.dialog, self.db, self.key = dialog, db, key
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(locks.BEAT * 1000)

    def tick(self):
        other = locks.beat(self.db, self.key)
        if other:
            self.timer.stop()
            freeze(self.dialog)
            QMessageBox.warning(self.dialog, 'Карточка занята', f'Пока связь прерывалась, карточку открыл {other["user"]} ({other["host"]}, с {other["since"]}). '
                                'Ваши несохранённые правки в ней могли устареть, поэтому карточка переведена в режим просмотра. Закройте её и откройте заново.')


def describe(other):
    return f'{other["user"] or "другой пользователь"} ({other["host"]}) с {other["since"]}'


def guarded(prefix, key_of, label='Карточка'):
    """Декоратор класса-диалога. key_of(self) -> идентификатор записи или None (новая карточка не блокируется).
    Перехватывает exec(): занятую карточку предлагает открыть только для просмотра, свободную блокирует на время работы."""
    def wrap(cls):
        original = cls.exec

        def exec_(self, *args, **kwargs):
            ident = key_of(self)
            if ident in (None, '', 0):
                return original(self, *args, **kwargs)
            key = f'{prefix}:{ident}'
            other = locks.acquire(default_db, key)
            if other:
                box = QMessageBox(self.parent())
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle('Карточка занята')
                box.setText(f'{label} сейчас правит {describe(other)}.\n\nПока он её не закроет, изменения запрещены — иначе чужие правки затрутся.')
                view = box.addButton('Открыть для просмотра', QMessageBox.ButtonRole.AcceptRole)
                box.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton() is not view:
                    return QDialog.DialogCode.Rejected.value
                freeze(self)
                return original(self, *args, **kwargs)
            _Beater(self, default_db, key)
            try:
                return original(self, *args, **kwargs)
            finally:
                locks.release(default_db, key)

        cls.exec = exec_
        return cls
    return wrap
