import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from datetime import datetime
import openpyxl
import pytest
from smetagaz import gsvm_import as imp, acts_statement
from smetagaz.database import DatabaseManager

HEADERS = ['№ договора', 'Адрес', 'Заказчик', 'Телефон', 'Паспортные данные', 'Дата заключения', 'Стоимость', 'ДАТА АКТА', 'Проект', 'ПГ-4', 'Котел', 'Счетчик', 'Сигнализатор', 'Регулятор']


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def make_file(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Реестр договоров монтажа ГСВ'])
    ws.append(HEADERS)
    ws.append(['01-02/26', 'г. Минск, ул. Мира 5', 'Иванов Иван Иванович', '+375291112233', 'AB1234567', datetime(2026, 3, 1), '1 250,50', '20.03.2026', 'ПД-55/26', '+', 'Бош', 1, 'да', ''])
    ws.append(['', 'д. Лесная 7', 'Петров Пётр', '375 29 5556677', 'KH7654321', '02.03.2026', 980, None, 'ПД-56/26', '', 'нет', 2, '', '+'])
    ws.append(['03-02/26', 'ул. Садовая 1', None, None, None, '03.03.2026', 500, None, None, None, None, None, None, None])
    ws.append(['01-02/26', 'повтор', 'Иванов Иван Иванович'] + [None] * 11)
    wb.save(path)


def test_import_into_gsv_installation_contracts(db, tmp_path):
    f = tmp_path / 'gsvm.xlsx'
    make_file(f)
    headers, rows, header_row = imp.read_table(f)
    assert header_row == 2 and len(rows) == 4
    mapping = imp.auto_map(headers)
    assert len(set(mapping.values())) == 14
    prepared = imp.prepare(db, rows, mapping)
    assert [p['status'] for p in prepared] == ['new', 'new', 'error', 'error']
    report = imp.import_rows(db, prepared)
    assert report['created'] == 2 and len(report['errors']) == 2
    row = db.fetchone("SELECT id,object_address,contract_date,contract_amount,acceptance_act_date,act_signed,contract_signed,designer_code,client_name,seq_num,year_num "
                      "FROM contracts WHERE contract_number='01-02/26'")
    assert row[1:] == ('г. Минск, ул. Мира 5', '2026-03-01', 1250.5, '2026-03-20', 1, 1, 'ПД-55/26', 'Иванов Иван Иванович', 1, 26)
    eq = sorted(db.fetchall('SELECT kind,model FROM gsvm_equipment WHERE contract_id=?', (row[0],)))
    assert ('ПГ', 'ПГ-4') in eq and ('Котел', 'Бош') in eq and ('Сигнализатор', '') in eq and ('Счётчик газа', '') in eq and len(eq) == 4
    # пустой номер получил следующий по порядку
    second = db.fetchone("SELECT contract_number,act_signed FROM contracts WHERE client_name='Петров Пётр'")
    assert second == ('02-02/26', 0)
    assert db.fetchone('SELECT count(*) FROM crm.clients')[0] == 2
    # повторный импорт и обновление
    again = imp.prepare(db, rows, mapping)
    assert [p['status'] for p in again][:2] == ['exists', 'exists']
    assert imp.import_rows(db, again)['skipped'] == 2
    db.execute("UPDATE gsvm_equipment SET model='X' WHERE contract_id=? AND kind='Котел'", (row[0],))
    assert imp.import_rows(db, again, 'update')['updated'] == 2
    assert db.fetchone("SELECT model FROM gsvm_equipment WHERE contract_id=? AND kind='Котел'", (row[0],))[0] == 'Бош'
    assert db.fetchone('SELECT count(*) FROM contracts')[0] == 2
    st = acts_statement.statement(db, 'contracts', 2026, 3)
    assert [r['number'] for r in st['signed']] == ['01-02/26']


def test_dialog_and_registry(db, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    import sys
    import smetagaz.gsvm_import_view as iv
    import smetagaz.contracts_registry as cr
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    f = tmp_path / 'gsvm.xlsx'
    make_file(f)
    dlg = iv.ImportGsvmDialog(None, str(f))
    assert dlg.map_table.rowCount() == 14 and sum(1 for c in dlg.combos if c.currentData()) == 14
    dlg.check()
    from conftest import wait_job
    wait_job(dlg)
    assert dlg.run.isEnabled() and 'Новых: 2' in dlg.summary.text()
    dlg.do_import()
    wait_job(dlg)
    assert db.fetchone('SELECT count(*) FROM contracts')[0] == 2
    view = cr.ContractsRegistryView()
    view.load_data()
    assert view.table.rowCount() == 2
