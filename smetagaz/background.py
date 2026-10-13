"""Длительные операции в фоне: окно с прогрессом и кнопкой «Отмена», программа остаётся отзывчивой.
work(ctx) выполняется в отдельном потоке: ctx.progress(сделано, всего, текст) сообщает о ходе, ctx.check() прерывает операцию после нажатия «Отмена»
(исключение Cancelled). Интерфейс из рабочего потока не трогается — только данные; окно обновляет таймер в основном потоке."""
import logging
import threading
import time

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QProgressDialog, QApplication, QMessageBox
from PyQt6.QtCore import Qt


class Cancelled(Exception):
    """Операция прервана пользователем."""


class Context:
    def __init__(self):
        self._cancel = threading.Event()
        self.done = 0
        self.total = 0
        self.text = ''

    def progress(self, done=0, total=0, text=''):
        self.done, self.total = done, total
        if text:
            self.text = text
        self.check()

    def check(self):
        if self._cancel.is_set():
            raise Cancelled()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def cancel(self):
        self._cancel.set()


_ACTIVE = set()
SHOW_AFTER = 0.4          # быстрые операции обходятся без окна


class Job(QObject):
    def __init__(self, parent, title, work, done=None, error=None, cancelled=None, modal=False, cancellable=True):
        super().__init__(parent)
        self.parent_widget, self.title = parent, title
        self.on_done, self.on_error, self.on_cancelled = done, error, cancelled
        self.modal, self.cancellable = modal, cancellable
        self.ctx = Context()
        self.result = self.exception = None
        self.finished = False
        self.dialog = None
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._run, args=(work,), daemon=True, name='pto-job')
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        _ACTIVE.add(self)
        self.thread.start()
        self.timer.start(80)

    def _run(self, work):
        try:
            self.result = work(self.ctx)
        except Cancelled:
            self.exception = Cancelled()
        except BaseException as e:          # noqa: BLE001 — любая ошибка должна дойти до пользователя
            logging.exception('Фоновая операция «%s» завершилась ошибкой', self.title)
            self.exception = e
        finally:
            self.finished = True

    def show_dialog(self):
        self.dialog = QProgressDialog(self.title, 'Отмена' if self.cancellable else '', 0, 0, self.parent_widget)
        self.dialog.setWindowTitle(self.title)
        self.dialog.setMinimumWidth(420)
        self.dialog.setAutoClose(False)
        self.dialog.setAutoReset(False)
        self.dialog.setWindowModality(Qt.WindowModality.WindowModal if self.modal else Qt.WindowModality.NonModal)
        if self.cancellable:
            self.dialog.canceled.connect(self.request_cancel)
        else:
            self.dialog.setCancelButton(None)
        self.dialog.show()

    def request_cancel(self):
        self.ctx.cancel()
        if self.dialog:
            self.dialog.setLabelText('Отменяю… дождитесь безопасной остановки.')

    def poll(self):
        if not self.finished:
            if self.dialog is None and time.monotonic() - self.started > SHOW_AFTER:
                self.show_dialog()
            if self.dialog is not None and not self.ctx.cancelled:
                total = self.ctx.total
                self.dialog.setMaximum(total if total > 0 else 0)
                self.dialog.setValue(min(self.ctx.done, total) if total > 0 else 0)
                self.dialog.setLabelText(f'{self.title}\n{self.ctx.text}' if self.ctx.text else self.title)
            return
        self.timer.stop()
        if self.dialog is not None:
            self.dialog.canceled.disconnect() if self.cancellable else None
            self.dialog.close()
            self.dialog.deleteLater()
        _ACTIVE.discard(self)
        try:
            if isinstance(self.exception, Cancelled):
                if self.on_cancelled:
                    self.on_cancelled()
            elif self.exception is not None:
                if self.on_error:
                    self.on_error(self.exception)
                else:
                    QMessageBox.warning(self.parent_widget, self.title, f'Операция не выполнена:\n{self.exception}')
            elif self.on_done:
                self.on_done(self.result)
        finally:
            self.deleteLater()


def run(parent, title, work, done=None, error=None, cancelled=None, modal=False, cancellable=True):
    """Запускает work(ctx) в фоне. Возвращает Job."""
    return Job(parent, title, work, done, error, cancelled, modal, cancellable)
