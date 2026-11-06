"""Сортировка договоров с юрлицами: по номеру, дате заключения или статусу, по возрастанию/убыванию; выбор запоминается; та же сортировка в веб-клиенте."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys

import pytest
from PyQt6.QtCore import Qt

from smetagaz import contracts_core as cc
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


def make_all(db, mod='smr'):
    lid = cc.save_legal(db, dict(name='ООО Ромашка', unp='123456789'))
    base = dict(party_type='legal', legal_id=lid, amount=10)
    rows = {
        'A': dict(contract_number='02-05/26', contract_date='2026-03-01', status='Действует', end_date='2099-01-01'),
        'B': dict(contract_number='10-05/26', contract_date='2026-01-15', status='Завершён'),
        'C': dict(contract_number='01-05/27', contract_date='', status='Предварительно'),
        'D': dict(contract_number='05-05/26', contract_date='2026-02-10', status='Действует', end_date='2020-01-01'),         # просрочен
        'E': dict(contract_number='07-05/26', contract_date='2026-05-05', status='Расторгнут'),
    }
    ids = {k: cc.save_contract(db, mod, dict(base, **v)) for k, v in rows.items()}
    return {v: k for k, v in ids.items()}


def listing(db, field, direction, mod='smr'):
    order, params = cc.order_sql(mod, field, direction)
    table = cc.cfg(mod)['contracts']
    return [r[0] for r in db.fetchall(f'SELECT c.id FROM {table} c ORDER BY {order}', params)]


def test_order_by_number_is_numeric_by_year_then_sequence(db):
    names = make_all(db)
    asc = [names[i] for i in listing(db, 'number', 'asc')]
    assert asc == ['A', 'D', 'E', 'B', 'C'] and [names[i] for i in listing(db, 'number', 'desc')] == asc[::-1]                 # 02, 05, 07, 10 (2026), затем 01/27; «10» не раньше «02»


def test_order_by_date_puts_missing_dates_last_in_both_directions(db):
    names = make_all(db)
    assert [names[i] for i in listing(db, 'date', 'asc')] == ['B', 'D', 'A', 'E', 'C']
    assert [names[i] for i in listing(db, 'date', 'desc')] == ['E', 'A', 'D', 'B', 'C']              # без даты — всегда в конце


def test_order_by_status_uses_visual_status_then_number(db):
    names = make_all(db)
    # предварительно, в работе, просрочен, годовой, завершён, расторгнут
    assert [names[i] for i in listing(db, 'status', 'asc')] == ['C', 'A', 'D', 'B', 'E']
    assert [names[i] for i in listing(db, 'status', 'desc')] == ['E', 'B', 'D', 'A', 'C']
    cc.set_visual_status(db, 'smr', next(i for i, n in names.items() if n == 'A'), 'done')          # статус, проставленный вручную, учитывается
    assert [names[i] for i in listing(db, 'status', 'asc')] == ['C', 'D', 'A', 'B', 'E']


def test_parse_sort_and_defaults():
    assert cc.parse_sort('date:desc') == ('date', 'desc') and cc.parse_sort('') == cc.DEFAULT_SORT and cc.parse_sort('мусор:asc') == cc.DEFAULT_SORT and cc.parse_sort('date:up') == cc.DEFAULT_SORT
    assert cc.order_sql('smr', 'неизвестно', 'asc')[0].startswith('coalesce(c.year_num')               # неизвестное поле — по номеру


def test_registry_sort_controls_header_clicks_and_memory(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    from smetagaz import counterparty_ui as cu
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    QApplication.instance() or QApplication([])
    names = make_all(db)
    view = cu.ContractsRegistry('smr')
    numbers = lambda: [view.table.item(r, 0).text() for r in range(view.table.rowCount())]
    assert numbers() == ['02-05/26', '05-05/26', '07-05/26', '10-05/26', '01-05/27'] and view.btn_sort_dir.text() == '▲ по возрастанию'          # по умолчанию — по номеру
    view.cmb_sort.setCurrentIndex(view.cmb_sort.findData('date'))
    assert view.sort_field == 'date' and numbers() == ['10-05/26', '05-05/26', '02-05/26', '07-05/26', '01-05/27']
    view.toggle_sort_direction()
    assert view.btn_sort_dir.text() == '▼ по убыванию' and numbers() == ['07-05/26', '02-05/26', '05-05/26', '10-05/26', '01-05/27']
    assert db.get_setting('sort_contracts_smr') == 'date:desc'                                           # выбор запомнен для раздела
    view.header_clicked(8)                                                                              # щелчок по заголовку «Статус»
    assert view.sort_field == 'status' and view.sort_dir == 'asc' and numbers()[0] == '01-05/27'
    view.header_clicked(8)
    assert view.sort_dir == 'desc' and numbers()[0] == '07-05/26'
    view.header_clicked(3)                                                                              # колонка без сортировки — ничего не меняется
    assert view.sort_field == 'status'
    assert view.table.horizontalHeader().sortIndicatorSection() == 8
    again = cu.ContractsRegistry('smr')                                                                 # после перезапуска сортировка та же
    assert again.sort_field == 'status' and again.sort_dir == 'desc' and again.cmb_sort.currentData() == 'status'
    other = cu.ContractsRegistry('to')                                                                  # у других разделов — своя (по умолчанию по номеру)
    assert other.sort_field == 'number'
    assert not cu.ContractsRegistry('ip').cmb_sort.isVisibleTo(cu.ContractsRegistry('ip')) or cu.ContractsRegistry('ip').sortable is False    # СМР (ИП) без сортировки
    page = view.pager.size
    assert page == 100


def test_web_list_sorting(db):
    from test_web_gateway import Client
    from smetagaz import web_gateway as wg
    names = make_all(db)
    wg.add_user(db, 'vw', 'viewerpass1', 'viewer')
    g = wg.WebGateway(db, '127.0.0.1', 0)
    g.start()
    try:
        c = Client(g)
        c.login('vw', 'viewerpass1')

        def order(url):
            page = c.request('GET', url)[1]
            import re
            return re.findall(r'<td><a class="c" href="/m/smr/\d+">([^<]+)</a></td>', page)
        default = order('/m/smr')
        assert default[0] == '01-05/27' and default[-1] == '02-05/26'                                   # без настроек — новые сверху (как раньше)
        assert order('/m/smr?sort=number:asc')[:2] == ['02-05/26', '05-05/26']
        assert order('/m/smr?sort=date:asc')[:2] == ['10-05/26', '05-05/26'] and order('/m/smr?sort=date:desc')[-1] == '01-05/27'
        assert order('/m/smr?sort=status:asc')[0] == '01-05/27'
        page = c.request('GET', '/m/smr?sort=date:asc')[1]
        assert 'Сортировка:' in page and 'sort=date:desc' in page and 'sort=status:asc' in page and 'sort=number:asc' in page          # активная сортировка переключает направление
        assert 'Сортировка:' not in c.request('GET', '/m/ip')[1] and 'Сортировка:' not in c.request('GET', '/m/clients')[1]
        db.set_setting('sort_contracts_smr', 'number:asc')                                              # сохранённая в программе сортировка — по умолчанию и в вебе
        assert order('/m/smr')[:2] == ['02-05/26', '05-05/26']
        assert order('/m/smr?sort=junk')[:2] == ['02-05/26', '05-05/26']
    finally:
        g.stop()
