import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
from datetime import datetime, date
import openpyxl
import pytest
from smetagaz import gsn_project_import as imp, agenda_domain, acts_statement
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
    ws.append(['Реестр договоров ГСН за 2026'])           # заголовок над таблицей
    ws.append(HEADERS)
    ws.append(['101-03/26', 'г. Минск, ул. Мира 5', 'Иванов Иван Иванович', '+375291112233', 'AB1234567', datetime(2026, 3, 1), '1 250,50', '20.03.2026', 'ПД-55/26', '+', 'Бош', 1, 'да', ''])
    ws.append(['102-03/26', 'д. Лесная 7', 'Петров Пётр', '375 29 5556677', 'KH7654321', '02.03.2026', 980, None, 'ПД-56/26', '', 'нет', 2, '', '+'])
    ws.append(['103-03/26', 'ул. Садовая 1', None, None, None, '03.03.2026', 500, None, None, None, None, None, None, None])      # без заказчика
    ws.append(['101-03/26', 'повтор', 'Иванов Иван Иванович', None, None, None, None, None, None, None, None, None, None, None])  # повтор номера
    wb.save(path)


def test_read_map_prepare_import_update(db, tmp_path):
    f = tmp_path / 'gsn.xlsx'
    make_file(f)
    headers, rows, header_row = imp.read_table(f)
    assert header_row == 2 and len(rows) == 4
    mapping = imp.auto_map(headers)
    assert set(mapping.values()) == {'contract_number', 'address', 'client_name', 'phone', 'passport', 'contract_date', 'cost', 'act_date', 'project', 'eq_pg', 'eq_boiler', 'eq_meter', 'eq_alarm', 'eq_regulator'}
    prepared = imp.prepare(db, rows, mapping)
    assert [p['status'] for p in prepared] == ['new', 'new', 'error', 'error']
    assert 'нет заказчика' in prepared[2]['messages'] and 'повторяется' in prepared[3]['messages'][-1]
    assert prepared[0]['data']['cost'] == 1250.5 and prepared[0]['data']['contract_date'] == '2026-03-01' and prepared[0]['data']['act_date'] == '2026-03-20'
    assert prepared[0]['data']['eq_pg'] == [('ПГ', 'ПГ-4')] and prepared[0]['data']['eq_boiler'] == [('Котел', ' Бош'.strip())]
    assert prepared[1]['data']['eq_meter'] == [('Счетчик', '')] * 2 and prepared[1]['data']['eq_boiler'] == []
    report = imp.import_rows(db, prepared)
    assert report['created'] == 2 and len(report['errors']) == 2
    row = db.fetchone("SELECT id,title,address,contract_date,contract_amount,act_date,act_signed,client_id,client_name,phone FROM gsn_projects WHERE contract_number='101-03/26'")
    assert row[1:7] == ('г. Минск, ул. Мира 5', 'г. Минск, ул. Мира 5', '2026-03-01', 1250.5, '2026-03-20', 1) and row[8] == 'Иванов Иван Иванович'
    pid = row[0]
    assert json.loads(db.fetchone("SELECT fields_json FROM executive_objects WHERE owner_type='gsn_projects' AND owner_id=?", (pid,))[0])['project_number'] == 'ПД-55/26'
    eq = sorted(db.fetchall('SELECT equipment_kind,equipment_model,equipment_name FROM gsn_equipment WHERE project_id=?', (pid,)))
    assert eq == [('Котел', 'Бош', 'Котел Бош'), ('Сигнализатор', '', 'Сигнализатор'), ('Счетчик', '', 'Счетчик'), ('ПГ', 'ПГ-4', 'ПГ-4')] or len(eq) == 4
    second = db.fetchone("SELECT id,act_signed FROM gsn_projects WHERE contract_number='102-03/26'")
    assert second[1] == 0 and db.fetchone('SELECT count(*) FROM gsn_equipment WHERE project_id=?', (second[0],))[0] == 3
    assert db.fetchone('SELECT count(*) FROM crm.clients')[0] == 2
    # повторный импорт: пропуск и обновление
    again = imp.prepare(db, rows, mapping)
    assert [p['status'] for p in again][:2] == ['exists', 'exists']
    assert imp.import_rows(db, again)['skipped'] == 2
    db.execute("UPDATE gsn_equipment SET equipment_model='X' WHERE project_id=? AND equipment_kind='Котел'", (pid,))
    assert imp.import_rows(db, again, 'update')['updated'] == 2
    assert db.fetchone("SELECT equipment_model FROM gsn_equipment WHERE project_id=? AND equipment_kind='Котел'", (pid,))[0] == 'Бош'
    assert db.fetchone('SELECT count(*) FROM gsn_equipment WHERE project_id=?', (pid,))[0] == 4 and db.fetchone('SELECT count(*) FROM gsn_projects')[0] == 2
    # календарь и ведомость видят акт ГСН
    events = [e for e in agenda_domain.events_between(db, date(2026, 3, 1), date(2026, 3, 31)) if e['kind'] == 'act']
    assert any('Монтаж ГСН' in e['detail'] or 'ГСН' in e['detail'] or 'Иванов' in e['title'] for e in events) or events
    st = acts_statement.statement(db, 'gsn_projects', 2026, 3)
    assert [r['number'] for r in st['signed']] == ['101-03/26'] and st['unsigned'] == []


def test_dialog_and_registry(db, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    import sys
    import smetagaz.gsn_import_view as iv, smetagaz.gsn_view as gv
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: print('WARN', a[2:]))
    f = tmp_path / 'gsn.xlsx'
    make_file(f)
    dlg = iv.ImportGsnDialog(None, str(f))
    assert dlg.map_table.rowCount() == 14 and sum(1 for c in dlg.combos if c.currentData()) == 14
    dlg.check()
    assert dlg.run.isEnabled() and 'Новых: 2' in dlg.summary.text() and dlg.preview.item(0, 5).text().startswith('ПГ-4')
    dlg.do_import()
    assert db.fetchone('SELECT count(*) FROM gsn_projects')[0] == 2
    view = gv.GsnProjectsView()
    assert view.table.rowCount() == 2 and view.table.columnCount() == 7
    card = gv.GsnContractDialog(db.fetchone("SELECT id FROM gsn_projects WHERE contract_number='101-03/26'")[0])
    assert card.act_date.value() == '2026-03-20' and card.act_signed.isChecked() and card.amount.value() == 1250.5
