import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtWidgets import QTableWidget, QLineEdit, QHBoxLayout, QWidget, QInputDialog
from smetagaz.database import DatabaseManager
from smetagaz.registry_tools import RegistryTools, search_clause


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_search_by_words_phone_and_address(db):
    db.execute("INSERT INTO contracts(contract_number,client_name,client_phone,object_address) VALUES('01-02/26','Иванов Иван','+375 (29) 111-22-33','г. Минск, ул. Мира 5')")
    db.execute("INSERT INTO contracts(contract_number,client_name,client_phone,object_address) VALUES('02-02/26','Петров','8 017 555 66 77','д. Лесная 7')")

    def found(text):
        clause, params = search_clause(text, ['c.contract_number', 'c.client_name', 'c.object_address'], ['c.client_phone'])
        return [r[0] for r in db.fetchall(f'SELECT c.contract_number FROM contracts c WHERE {clause} ORDER BY c.id', params)]

    assert found('иванов минск') == ['01-02/26']          # слова из разных полей
    assert found('29 111') == ['01-02/26'] and found('375291112233') == ['01-02/26']      # телефон без учёта пробелов, скобок и «+»
    assert found('5556677') == ['02-02/26'] and found('лесная') == ['02-02/26']
    assert found('') == ['01-02/26', '02-02/26'] and found('несуществующий') == []


def test_columns_and_saved_filters(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    host = QWidget()
    bar = QHBoxLayout(host)
    search = QLineEdit()
    bar.addWidget(search)
    table = QTableWidget(0, 4)
    table.setHorizontalHeaderLabels(['A', 'B', 'C', 'D'])
    tools = RegistryTools(db, 'demo', table, search, bar)
    tools.set_visible(1, False); tools.set_visible(2, False)
    assert table.isColumnHidden(1) and table.isColumnHidden(2) and not table.isColumnHidden(0)
    for col in (0, 3):
        tools.set_visible(col, False)
    assert sum(not table.isColumnHidden(c) for c in range(4)) >= 1          # скрыть все колонки нельзя
    table2 = QTableWidget(0, 4)                                              # настройка запоминается
    RegistryTools(db, 'demo', table2, QLineEdit())
    assert table2.isColumnHidden(1)
    tools.reset_columns()
    assert not any(table.isColumnHidden(c) for c in range(4))
    search.setText('иванов минск')
    monkeypatch.setattr(QInputDialog, 'getText', lambda *a, **k: ('Минск', True))
    tools.save_current()
    assert tools.filters() == {'Минск': {'text': 'иванов минск'}}
    search.setText('')
    tools.build_filters_menu()
    tools.filters_menu.actions()[0].trigger()
    assert search.text() == 'иванов минск'
    tools.delete('Минск')
    assert tools.filters() == {}
