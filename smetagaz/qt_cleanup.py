"""Корректное завершение Qt: при выходе из Python окна и таймеры, пережившие QApplication, приводили к SIGSEGV («Segmentation fault» после успешной работы).
Перед выгрузкой модулей закрываем и удаляем все окна верхнего уровня и даём Qt обработать удаление."""
import atexit
import gc

_installed = False


def shutdown(app=None):
    try:
        from PyQt6.QtWidgets import QApplication
        app = app or QApplication.instance()
        if app is None:
            return
        for w in list(app.topLevelWidgets()):
            try:
                w.close()
                w.deleteLater()
            except RuntimeError:
                pass
        for _ in range(3):
            app.processEvents()
        gc.collect()
        app.processEvents()
    except Exception:
        pass


def install(app=None):
    global _installed
    if not _installed:
        _installed = True
        atexit.register(shutdown, app)
