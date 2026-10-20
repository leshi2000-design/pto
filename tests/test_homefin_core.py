from datetime import date
from decimal import Decimal

import pytest

from homefin.core import Finance
from homefin.exchange import export_csv, export_xlsx, import_csv, report_text
from homefin.money import fmt, to_cents


@pytest.fixture
def fin():
    f = Finance(":memory:")
    yield f
    f.close()


def cash(f):
    return f.accounts()[0]["id"]


def test_money():
    assert to_cents("12,50") == 1250 and to_cents("1 000.1") == 100010 and to_cents(5) == 500
    assert fmt(123456) == "1 234,56" and fmt(-5) == "-0,05"
    with pytest.raises(ValueError):
        to_cents("abc")


def test_balance_and_transfer(fin):
    a = cash(fin)
    card = fin.add_account("Карта", initial="100")
    fin.add_transaction("01.10.2026", "income", "1000", a)
    fin.add_transaction("02.10.2026", "expense", "250,50", a, fin.category_id("Продукты"))
    fin.add_transaction("03.10.2026", "transfer", "300", a, to_account_id=card)
    assert fin.balance(a) == 44950 and fin.balance(card) == 40000
    assert fin.balance(a, "2026-10-01") == 100000
    assert fin.total_balance() == 84950
    with pytest.raises(ValueError):
        fin.add_transaction("03.10.2026", "transfer", "1", a, to_account_id=a)
    with pytest.raises(ValueError):
        fin.add_transaction("03.10.2026", "expense", "0", a)


def test_filters_and_reports(fin):
    a, food = cash(fin), fin.category_id("Продукты")
    fin.add_transaction("2026-10-05", "expense", "100", a, food, "хлеб")
    fin.add_transaction("2026-11-05", "expense", "40", a, fin.category_id("Транспорт"))
    fin.add_transaction("2026-10-07", "income", "500", a, fin.category_id("Зарплата", "income"))
    assert len(fin.transactions("2026-10-01", "2026-10-31")) == 2
    assert [t["note"] for t in fin.transactions(text="хлеб")] == ["хлеб"]
    assert fin.totals("2026-10-01", "2026-10-31") == (50000, 10000)
    assert fin.by_category("2026-10-01", "2026-11-30")[0] == ("Продукты", 10000)
    assert fin.monthly(2, date(2026, 11, 20))[0][0] == "2026-10"
    assert "Продукты" in report_text(fin, "2026-10-01", "2026-10-31")


def test_budget(fin):
    a, food = cash(fin), fin.category_id("Продукты")
    fin.set_budget(food, "200")
    fin.add_transaction("2026-10-05", "expense", "150", a, food)
    fin.add_transaction("2026-09-05", "expense", "999", a, food)
    assert fin.budget_status("2026-10") == [(food, "Продукты", 20000, 15000)]
    fin.set_budget(food, "")
    assert fin.budget_status("2026-10") == []


def test_recurring_catches_up_once(fin):
    a = cash(fin)
    fin.add_recurring("Интернет", "expense", "30", a, None, 31, "15.08.2026")
    n = fin.run_recurring(date(2026, 10, 20))
    assert n == 2  # 31.08 и 30.09; 31.10 ещё не наступило
    assert fin.run_recurring(date(2026, 10, 20)) == 0
    assert fin.run_recurring(date(2026, 11, 1)) == 1
    assert sorted(t["date"] for t in fin.transactions())[-1] == "2026-10-31"


def test_tariff_tier_and_bill_from_readings(fin):
    el = next(s["id"] for s in fin.services() if s["name"] == "Электроэнергия")
    fin.add_tariff(el, "01.01.2026", "0,30", tier_limit="100", tier_rate="0,50")
    fin.add_tariff(el, "01.10.2026", "0,40")
    assert fin.calc_amount(el, Decimal(150), "2026-09-30") == 5500  # 100*0.3 + 50*0.5
    assert fin.calc_amount(el, Decimal(150), "2026-10-31") == 6000  # новый тариф без порога
    fin.add_reading(el, "30.09.2026", "1000")
    fin.add_reading(el, "31.10.2026", "1150")
    with pytest.raises(ValueError):
        fin.add_reading(el, "30.11.2026", "1100")
    assert fin.readings(el)[0][3] == Decimal(150)
    bid = fin.create_bill(el, "2026-10", due_date="25.11.2026")
    b = fin.bills()[0]
    assert b["amount_cents"] == 6000 and Decimal(b["consumption"]) == 150
    with pytest.raises(Exception):
        fin.create_bill(el, "2026-10")  # дубликат периода
    assert fin.next_period_due(el, "2026-11") == "2026-12-25"
    assert bid


def test_pay_unpay_and_reminders(fin):
    a = cash(fin)
    fixed = fin.add_service("Домофон 2", metered=False, fixed="5")
    bid = fin.create_bill(fixed, "2026-10", due_date="2026-10-25")
    assert fin.bills()[0]["amount_cents"] == 500
    assert fin.reminders(date(2026, 10, 22))[0][1] == 3
    assert fin.reminders(date(2026, 10, 10)) == []
    assert fin.reminders(date(2026, 11, 1))[0][1] == -7
    fin.pay_bill(bid, a, "2026-10-24")
    assert fin.balance(a) == -500 and fin.reminders(date(2026, 11, 1)) == []
    with pytest.raises(ValueError):
        fin.pay_bill(bid, a)
    fin.unpay_bill(bid)
    assert fin.balance(a) == 0 and fin.bills("unpaid")
    fin.pay_bill(bid, a)
    fin.delete_transaction(fin.bills()[0]["transaction_id"])
    assert fin.bills("unpaid")  # удаление платежа возвращает счёт в неоплаченные
    assert fin.utility_stats(months=1, end=date(2026, 10, 5))[0][1] == 500


def test_bill_without_readings_needs_amount(fin):
    gas = next(s["id"] for s in fin.services() if s["name"] == "Газ")
    with pytest.raises(ValueError):
        fin.create_bill(gas, "2026-10")
    fin.create_bill(gas, "2026-10", amount="12,34")
    assert fin.bills()[0]["amount_cents"] == 1234


def test_csv_xlsx_roundtrip_and_backup(fin, tmp_path):
    a = cash(fin)
    card = fin.add_account("Карта")
    fin.add_transaction("01.10.2026", "income", "1000,5", a, fin.category_id("Зарплата", "income"), "аванс; часть")
    fin.add_transaction("02.10.2026", "transfer", "10", a, to_account_id=card)
    p = tmp_path / "t.csv"
    assert export_csv(fin, p) == 2
    other = Finance(":memory:")
    ok, errs = import_csv(other, p)
    assert (ok, errs) == (2, [])
    assert other.total_balance() == fin.total_balance() == 100050
    assert other.transactions(text="аванс; часть")
    p.write_text("Дата;Тип;Сумма;Счёт;Счёт назначения;Категория;Примечание\n01.01.2026;Чудо;5;X;;;\n", encoding="utf-8")
    assert import_csv(other, p)[0] == 0
    assert export_xlsx(fin, tmp_path / "t.xlsx") == 2
    assert fin.backup(tmp_path / "bk").exists()


def test_restore_file_db(tmp_path):
    f = Finance(tmp_path / "x.db")
    f.add_transaction("01.10.2026", "income", "5", cash(f))
    bk = f.backup(tmp_path / "bk")
    f.add_transaction("02.10.2026", "income", "7", cash(f))
    f.restore(bk)
    assert f.total_balance() == 500


def test_goal_deposit_withdraw_keeps_totals(fin):
    a = cash(fin)
    fin.add_transaction("01.10.2026", "income", "1000", a)
    g = fin.add_goal("Отпуск", "600", "31.12.2026")
    assert [x["name"] for x in fin.accounts()] == ["Наличные"]  # копилка не в обычных счетах
    fin.deposit_to_goal(g, a, "150", "05.10.2026")
    assert fin.balance(g) == 15000 and fin.balance(a) == 85000 and fin.total_balance() == 100000
    assert fin.totals("2026-10-01", "2026-10-31") == (100000, 0)  # перевод не расход
    pr = fin.goal_progress(fin.goals()[0], date(2026, 10, 20))
    assert pr["pct"] == 25 and pr["left"] == 45000 and pr["monthly"] == 22500 and not pr["done"]  # до 31.12 — 2 месяца: 450 / 2
    with pytest.raises(ValueError):
        fin.withdraw_from_goal(g, a, "200")
    fin.withdraw_from_goal(g, a, "50", "06.10.2026")
    assert fin.balance(g) == 10000
    fin.deposit_to_goal(g, a, "500")
    assert fin.goal_progress(fin.goals()[0])["done"]
    with pytest.raises(ValueError):
        fin.add_goal("X", "0")


def test_old_database_is_migrated(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'card',"
                " initial_cents INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0)")
    con.execute("INSERT INTO accounts(name) VALUES('Старый')")
    con.commit()
    con.close()
    f = Finance(p)
    assert f.goals() == [] and f.add_goal("Цель", "10")
    assert f.accounts()[0]["name"] == "Старый"


def test_password(fin):
    assert not fin.has_password() and fin.check_password("что угодно")
    with pytest.raises(ValueError):
        fin.set_password("abc")
    fin.set_password("секрет1")
    assert fin.has_password() and fin.check_password("секрет1") and not fin.check_password("секрет")
    assert "секрет1" not in str(fin.db.execute("SELECT * FROM settings").fetchall())  # пароль не хранится открыто
    with pytest.raises(ValueError):
        fin.set_password("новый-пароль", "не тот")
    fin.set_password("новый-пароль", "секрет1")
    assert fin.check_password("новый-пароль") and not fin.check_password("секрет1")
    with pytest.raises(ValueError):
        fin.remove_password("не тот")
    fin.remove_password("новый-пароль")
    assert not fin.has_password()


def test_calendar_events(fin):
    a = cash(fin)
    fin.add_transaction("2026-10-03", "income", "500", a, None, "Аванс")
    fin.add_transaction("2026-10-05", "expense", "20", a, fin.category_id("Продукты"))
    fin.add_transaction("2026-10-06", "transfer", "5", a, to_account_id=fin.add_account("Карта"))
    gas = next(s["id"] for s in fin.services() if s["name"] == "Газ")
    fin.create_bill(gas, "2026-09", amount="14", due_date="2026-10-25")
    paid = fin.create_bill(next(s["id"] for s in fin.services() if s["name"] == "Домофон"), "2026-09", amount="3",
                           due_date="2026-10-10")
    fin.pay_bill(paid, a, "2026-10-09")
    fin.add_recurring("Аренда", "expense", "300", a, None, 28, "2026-01-01")
    ev = fin.calendar_events("2026-10", date(2026, 10, 20))
    assert [e["type"] for e in ev["2026-10-03"]] == ["income"] and ev["2026-10-03"][0]["title"] == "Аванс"
    assert ev["2026-10-05"][0]["type"] == "expense" and "2026-10-06" not in ev  # переводы не показываем
    assert ev["2026-10-25"][0]["type"] == "bill" and ev["2026-10-25"][0]["bill_id"]
    assert "2026-10-10" not in ev  # оплаченный счёт не дублируется как «к оплате»
    assert ev["2026-10-09"][0]["type"] == "expense"
    assert ev["2026-10-28"][0]["type"] == "planned"
    assert "2026-10-28" not in fin.calendar_events("2026-10", date(2026, 10, 30))  # прошло — стало фактом/пропущено
