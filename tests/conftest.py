import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest

if os.environ.get('PTO_TEST_REMOTE') == '1':
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    import remote_mode
    remote_mode.install()
    sys.excepthook = lambda *a: print('UNHANDLED', a[1], file=sys.stderr)       # без этого PyQt аварийно завершает процесс при исключении в слоте


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


SKIP_IN_REMOTE = {'test_close_hides_window_at_once_and_backs_up_in_background': 'в сетевом клиенте копии при закрытии не делаются',
                  'test_two_clients_isolation_and_audit_user': 'сервер внутри сервера: имя в журнале ставят оба и перебивают друг друга',
                  'test_local_mode_next_to_server_signs_its_changes': 'проверяет саму локальную базу рядом с сервером'}


def pytest_collection_modifyitems(config, items):
    if os.environ.get('PTO_TEST_REMOTE') == '1':
        for item in items:
            reason = SKIP_IN_REMOTE.get(item.name)
            if reason:
                item.add_marker(pytest.mark.skip(reason=reason))
