import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from decimal import Decimal
import pytest
from smetagaz.database import DatabaseManager
from smetagaz.work_pricing import compute_work_price, has_breakdown
from smetagaz import report_templates as reports


@pytest.fixture
def database(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_compute_work_price_formula():
    b = compute_work_price(labor_hours=2, hourly_rate=50, overhead_pct=15, profit_pct=10, other_costs=5)
    assert b['wage'] == Decimal('100')
    assert b['overhead'] == Decimal('15.0')
    assert b['profit'] == Decimal('10.0')
    assert b['social'] == Decimal('34.60')
    assert b['other'] == Decimal('5')
    assert b['subtotal'] == Decimal('164.60')
    assert b['tax'] == Decimal('32.9200')
    assert b['total'] == Decimal('197.5200')


def test_compute_work_price_all_zero_is_zero():
    b = compute_work_price(0, 0, 0, 0, 0)
    assert b['total'] == 0


def test_has_breakdown():
    assert not has_breakdown(0, 0, 0, 0, 0)
    assert has_breakdown(2, 0, 0, 0, 0)
    assert has_breakdown(0, 0, 0, 0, 5)


def test_work_item_price_snapshot_and_breakdown_report(database):
    db = database
    with_data = db.execute(
        "INSERT INTO materials(name,unit,price,item_type,labor_hours,hourly_rate,overhead_pct,profit_pct,other_costs) "
        "VALUES('Монтаж стыка','стык',197.52,'Работа',2,50,15,10,5)"
    ).lastrowid
    no_data = db.execute(
        "INSERT INTO materials(name,unit,price,item_type) VALUES('Прочистка дымохода','шт',80,'Работа')"
    ).lastrowid
    material = db.execute(
        "INSERT INTO materials(name,unit,price,item_type) VALUES('Труба 25','м',12.5,'Материал')"
    ).lastrowid

    est = db.execute("INSERT INTO estimates(title) VALUES('Тест')").lastrowid
    db.execute(
        "INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,labor_hours,hourly_rate,overhead_pct,profit_pct,other_costs) "
        "VALUES(?, 'Работа','Монтаж стыка','стык',3,197.52,592.56,2,50,15,10,5)", (est,)
    )
    db.execute(
        "INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum) "
        "VALUES(?, 'Работа','Прочистка дымохода','шт',1,80,80)", (est,)
    )
    db.execute(
        "INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,purchase_price,sum) "
        "VALUES(?, 'Материал','Труба 25','м',4,12.5,8.0,50)", (est,)
    )

    ctx, tables = reports.context(db, 'estimate_breakdown', est)
    works = {r['name']: r for r in tables['works']}
    assert works['Монтаж стыка']['has_breakdown'] == 'Да'
    assert works['Монтаж стыка']['wage_sum'] == Decimal('300')  # 100 * qty 3
    assert works['Прочистка дымохода']['has_breakdown'] == 'Нет данных'
    assert works['Прочистка дымохода']['wage_sum'] == 'нет данных'
    assert ctx['work_wage_total'] == Decimal('300')
    assert ctx['works_total'] == Decimal('672.56')
    assert ctx['materials_total'] == Decimal('50')
    assert ctx['grand_total'] == Decimal('722.56')
    assert len(tables['materials']) == 1 and tables['materials'][0]['name'] == 'Труба 25'
    assert tables['materials'][0]['margin_unit'] == Decimal('4.5')
    assert tables['materials'][0]['margin_sum'] == Decimal('18.0')
    assert ctx['materials_margin_total'] == Decimal('18.0')
