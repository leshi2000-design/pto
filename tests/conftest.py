import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest


@pytest.fixture(scope='session', autouse=True)
def qt_application():
    """Одно приложение Qt на весь прогон: пересоздание QApplication между тестами приводит к сбоям при сборке мусора."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def wait_job(owner, timeout=15):
    """Ждёт завершения фоновой операции окна (attribute .job) с обработкой событий Qt."""
    import time
    from PyQt6.QtWidgets import QApplication
    deadline = time.time() + timeout
    job = getattr(owner, 'job', None)
    from smetagaz import background
    while job is not None and job in background._ACTIVE and time.time() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)
