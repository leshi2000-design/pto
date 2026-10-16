import pytest
from datetime import date
from smetagaz.database import DatabaseManager
from smetagaz import ip_domain as ip, contracts_core as cc, payments_domain as pay


@pytest.fixture
def d(tmp_path):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


def person(d, name='Иванов Иван'):
    return d.execute('INSERT INTO crm.clients(name,phone) VALUES(?,?)', (name, '375291112233')).lastrowid


def test_month_tax_formula():
    p = dict(ip.DEFAULTS, children=1)
    r = ip.month_tax(1000, p)
    assert (r['expenses'], r['poverty'], r['children'], r['base'], r['tax']) == (200.0, 216.0, 120.0, 464.0, 92.8)
    r = ip.month_tax(5000, p)               # выше порога бедности вычета нет
    assert (r['poverty'], r['base'], r['tax']) == (0.0, 3880.0, 776.0)
    r = ip.month_tax(1308, dict(ip.DEFAULTS))    # ровно порог — вычет применяется
    assert r['poverty'] == 216.0 and r['base'] == pytest.approx(1308 - 261.6 - 216)
    r = ip.month_tax(100, dict(ip.DEFAULTS, children=3, dependents=2))
    assert r['base_raw'] < 0 and r['base'] == 0 and r['tax'] == 0
    assert ip.month_tax(0, p)['tax'] == 0
    r = ip.month_tax(5000, dict(ip.DEFAULTS, children=2, dependents=1))
    assert r['children'] == 240 and r['dependents'] == 63 and r['base'] == 5000 - 1000 - 240 - 63


def test_incomes_statement_and_quarter(d):
    pid = person(d)
    c = cc.save_contract(d, 'ip', dict(person_id=pid, contract_date='2026-01-10', amount=1000, signed=1))
    cc.save_act(d, 'ip', dict(contract_id=c, act_date='2026-01-25', amount=1000, signed=1))
    cc.save_act(d, 'ip', dict(contract_id=c, act_date='2026-01-26', amount=500, signed=0))          # не подписан — не считается выполненным
    pay.add(d, 'ip_contracts', c, 400, '2026-01-20')
    eid = ip.add_estimate(d, pid, 'Баня')
    d.execute("UPDATE estimates SET total=300, date='2026-01-15' WHERE id=?", (eid,))
    pay.add(d, 'estimates', eid, 300, '2026-02-03')
    ip.save_income(d, dict(client_id=pid, date='2026-02-10', amount=200, title='Ремонт крана'))
    ip.save_income(d, dict(client_name='Случайный', date='2026-03-05', amount=100))
    jan = ip.statement(d, 2026, 1)
    assert jan['works_total'] == 1300 and jan['paid_total'] == 400 and jan['balance'] == 900
    assert [w['counted'] for w in jan['works']] == [True, True, False] or sorted(w['counted'] for w in jan['works']) == [False, True, True]
    feb = ip.statement(d, 2026, 2)
    assert [(p_['kind'], p_['amount']) for p_ in feb['payments']] == [('По смете', 300.0), ('Без договора', 200.0)]
    assert [m[2] for m in ip.year_summary(d, 2026)][:4] == [400.0, 500.0, 100.0, 0.0]
    # чужой договор (ГСВ) в ведомость ИП не попадает
    gsv = d.execute("INSERT INTO contracts(contract_number,contract_amount) VALUES('99',100)").lastrowid
    pay.add(d, 'contracts', gsv, 77, '2026-01-12')
    assert ip.statement(d, 2026, 1)['paid_total'] == 400
    q = ip.quarter_report(d, 2026, 1, today=date(2026, 3, 31))
    assert q['revenue'] == 1000 and q['complete']
    assert [m['revenue'] for m in q['months']] == [400.0, 500.0, 100.0]
    expected = sum(ip.month_tax(r, q['params'])['tax'] for r in (400, 500, 100))
    assert q['tax'] == round(expected, 2)
    # на середину квартала считается то, что поступило к этой дате
    mid = ip.quarter_report(d, 2026, 1, today=date(2026, 2, 5))
    assert mid['revenue'] == 700 and not mid['complete']


def test_tax_params_per_year_and_copy(d):
    p = ip.params(d, 2026)
    assert p == ip.DEFAULTS
    ip.save_params(d, 2026, dict(p, children=2, dependents=1, poverty_deduction=230.0))
    nxt = ip.params(d, 2027)                       # новый год наследует прошлый, меняется вручную
    assert nxt['children'] == 2 and nxt['poverty_deduction'] == 230.0
    ip.save_params(d, 2027, dict(nxt, child_deduction=130.0))
    assert ip.params(d, 2026)['child_deduction'] == 120.0 and ip.params(d, 2027)['child_deduction'] == 130.0
    with pytest.raises(ValueError):
        ip.save_params(d, 2027, dict(nxt, tax_rate=150))
    with pytest.raises(ValueError):
        ip.save_params(d, 2027, dict(nxt, children=-1))


def test_quarter_mode_not_monthly(d):
    pid = person(d)
    ip.save_params(d, 2026, dict(ip.params(d, 2026), monthly=0, children=1))
    ip.save_income(d, dict(client_id=pid, date='2026-01-10', amount=100))
    ip.save_income(d, dict(client_id=pid, date='2026-02-10', amount=5000))
    q = ip.quarter_report(d, 2026, 1, today=date(2026, 3, 31))
    raw = sum(m['base_raw'] for m in q['months'])
    assert q['base'] == round(raw, 2) and q['tax'] == round(raw * 0.2, 2)


def test_estimates_listing_and_attach_rules(d):
    pid = person(d)
    eid = ip.add_estimate(d, pid, 'Забор')
    c = cc.save_contract(d, 'ip', dict(person_id=pid, contract_date='2026-02-01'))
    e2 = d.execute("INSERT INTO estimates(title,date,total,paid,client_name) VALUES('Под договор','2026-02-01',50,0,'Иванов')").lastrowid
    cc.link_estimate(d, c, e2, 'ip')
    rows = {r['id']: r for r in ip.estimates(d)}
    assert rows[eid]['without_contract'] and not rows[e2]['without_contract'] and rows[e2]['contract'].startswith('№')
    other = d.execute("INSERT INTO estimates(title,date,total,paid) VALUES('ГСВ-смета','2026-02-01',10,0)").lastrowid
    d.execute("UPDATE contracts SET estimate_id=? WHERE id=(SELECT min(id) FROM contracts)", (other,)) if d.fetchone('SELECT 1 FROM contracts') else d.execute("INSERT INTO contracts(contract_number,estimate_id) VALUES('1',?)", (other,))
    with pytest.raises(ValueError):
        ip.attach_estimate(d, other)
    free = d.execute("INSERT INTO estimates(title,date,total,paid) VALUES('Свободная','2026-02-02',10,0)").lastrowid
    ip.attach_estimate(d, free, pid)
    ip.detach_estimate(d, free)
    assert free not in {r['id'] for r in ip.estimates(d)}
    with pytest.raises(ValueError):
        ip.save_income(d, dict(client_id=pid, date='2026-02-02', amount=0))
    with pytest.raises(ValueError):
        ip.save_income(d, dict(date='2026-02-02', amount=5))


def test_export_statement(d, tmp_path):
    import openpyxl
    pid = person(d)
    ip.save_income(d, dict(client_id=pid, date='2026-02-10', amount=200, title='Ремонт'))
    path = ip.export_statement(d, 2026, 2, str(tmp_path / 'v.xlsx'))
    ws = openpyxl.load_workbook(path).active
    values = [c.value for row in ws.iter_rows() for c in row if c.value is not None]
    assert 'Итого получено' in values and 200 in values or 200.0 in values


def test_ip_view_tabs(d, monkeypatch, tmp_path):
    import sys
    from PyQt6.QtWidgets import QMessageBox
    from smetagaz.database import db as singleton
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is singleton:
            monkeypatch.setattr(mod, 'db', d)
    import smetagaz.ip_view as iv
    pid = person(d)
    ip.save_income(d, dict(client_id=pid, date=date.today().isoformat(), amount=1000, title='Работа'))
    ip.add_estimate(d, pid, 'Смета ИП')
    view = iv.IpView()
    for i in range(view.tabs.count()):
        view.tabs.setCurrentIndex(i)
        view.load_data()
    tax = view.pages[5][0]
    assert 'К уплате за' in tax.result.text()
    tax.fields['children'].setValue(1)
    tax.save_params()
    assert ip.params(d, date.today().year)['children'] == 1
    q = ip.quarter_report(d, date.today().year, (date.today().month - 1) // 3 + 1)
    assert f'{ip.money(q["tax"])}' in tax.result.text()
    st = view.pages[4][0]
    assert st.works.rowCount() >= 0 and 'Выполнено' in st.totals.text()
    est = view.pages[2][0]
    assert est.table.rowCount() == 1 and est.table.item(0, 6).text() == '— без договора —'
    inc = view.pages[3][0]
    assert inc.table.rowCount() == 1
    st.pdf = None
    out = tmp_path / 'ved.pdf'
    from smetagaz import print_ui
    assert open(print_ui.write_pdf(str(out), st.html()[0]), 'rb').read(5) == b'%PDF-'
