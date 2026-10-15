import logging
import pytest
from smetagaz import error_log as el


@pytest.fixture(autouse=True)
def path(tmp_path, monkeypatch):
    monkeypatch.setattr(el, 'PATH', tmp_path / 'errors.db')


def test_record_dedup_and_counts():
    el.set_section('Монтаж ГСН')
    for _ in range(3):
        el.record('Ошибка', 'тест', 'Сбой 12', 'Traceback\nValueError: x')
    el.record('Предупреждение', 'окно', 'Договор не сохранён')
    rows = el.entries()
    assert len(rows) == 2
    err = [r for r in rows if r[3] == 'Ошибка'][0]
    assert err[8] == 3 and err[5] == 'Монтаж ГСН'
    assert el.unseen_count() == 2
    el.mark_seen()
    assert el.unseen_count() == 0
    assert len(el.entries('Предупреждение')) == 1 and len(el.entries(search='Сбой')) == 1
    assert 'ПТО' in el.report_text() and 'ValueError' in el.report_text()
    el.clear()
    assert el.entries() == []


def test_logging_handler_captures_exception(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'warning', QMessageBox.warning)
    monkeypatch.setattr(QMessageBox, 'critical', QMessageBox.critical)
    monkeypatch.setattr(QMessageBox, '_pto_errlog', False, raising=False)
    el.install()
    try:
        raise RuntimeError('boom')
    except RuntimeError:
        logging.exception('Фоновая операция упала')
    logging.getLogger().handlers[:] = [h for h in logging.getLogger().handlers if not isinstance(h, el.Handler)]
    rows = el.entries()
    assert rows and 'boom' in rows[0][7]


def test_view_loads(qapp=None):
    from smetagaz.error_view import ErrorLogView
    el.record('Ошибка', 'тест', 'Сообщение')
    v = ErrorLogView()
    v.load_data()
    assert v.table.rowCount() == 1
    v.table.selectRow(0)
    assert 'Сообщение' in v.details.toPlainText()
