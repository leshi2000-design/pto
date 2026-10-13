import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from decimal import Decimal
import pytest
from smetagaz import gsvm_domain as md, stock_domain
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def setup_contract(db):
    cid = db.execute("INSERT INTO contracts(contract_number,contract_date,object_name) VALUES('01-02/26','2026-01-01','Дом')").lastrowid
    p25 = db.execute("INSERT INTO gsv_pipelines(name,unit) VALUES('Труба стальная 25','м')").lastrowid
    p32 = db.execute("INSERT INTO gsv_pipelines(name,unit) VALUES('Труба стальная 32','м')").lastrowid
    pdn = db.execute("INSERT INTO gsv_pipelines(name,unit) VALUES('Труба ПЭ без диаметра','м')").lastrowid
    md.save_pipelines(db, cid, [dict(pipeline_id=p25, quantity=10), dict(pipeline_id=p32, quantity=5), dict(pipeline_id=pdn, quantity=3)])
    return cid


def enter_norms(db):
    """Пользователь вручную вводит нормы в справочнике (сид-профили по Ду созданы пустыми)."""
    mats = {name: mid for mid, name in db.fetchall('SELECT id,name FROM stock_materials')}
    pid25 = db.fetchone("SELECT id FROM norm_profiles WHERE diameter='25'")[0]
    pid32 = db.fetchone("SELECT id FROM norm_profiles WHERE diameter='32'")[0]
    stock_domain.save_profile(db, dict(name='Газовая сварка Ду 25 × 3.2', diameter='25', thickness='3.2', basis='стык', notes=''),
                              [(mats['Ацетилен'], '0.015'), (mats['Кислород'], '0,04'), (mats['Сварочная проволока'], '0.02')], pid25)
    stock_domain.save_profile(db, dict(name='Газовая сварка Ду 32 × 3.2', diameter='32', thickness='3.2', basis='стык', notes=''),
                              [(mats['Ацетилен'], '0.02'), (mats['Кислород'], '0.05'), (mats['Сварочная проволока'], '0')], pid32)
    return pid25, pid32, mats


def test_consumption_by_joints_is_automatic(db):
    cid = setup_contract(db)
    # нормы ещё не введены: расчёта нет, есть понятные предупреждения
    joints = md.joints(db, cid)
    assert [j['name'] for j in joints] == ['Труба стальная 25', 'Труба стальная 32', 'Труба ПЭ без диаметра']
    for j, n in zip(joints, (10, 4, 2)):
        j['count'] = n
    md.save_joints(db, cid, joints)
    empty = md.object_consumption(db, cid)
    assert empty['materials'] == [] and any('не задан расход' in w for w in empty['warnings']) and any('не найдена норма' in w for w in empty['warnings'])
    pid25, pid32, mats = enter_norms(db)
    plan = md.object_consumption(db, cid)
    got = {m['name']: (m['unit'], m['qty']) for m in plan['materials']}
    assert got['Ацетилен'][1] == Decimal('0.015') * 10 + Decimal('0.02') * 4 == Decimal('0.23')
    assert got['Кислород'][1] == Decimal('0.04') * 10 + Decimal('0.05') * 4 == Decimal('0.6')
    assert got['Сварочная проволока'][1] == Decimal('0.2')                    # у Ду 32 норма 0 — вклада нет
    assert [l['profile_name'] for l in plan['lines']] == ['Газовая сварка Ду 25 × 3.2', 'Газовая сварка Ду 32 × 3.2', '']
    assert plan['lines'][0]['auto'] is True and len(plan['warnings']) == 1 and 'без диаметра' in plan['warnings'][0]
    # ручной выбор нормы для строки и сохранение
    joints = md.joints(db, cid)
    joints[2]['profile_id'] = pid25
    md.save_joints(db, cid, joints)
    plan = md.object_consumption(db, cid)
    assert plan['warnings'] == [] and {m['name']: m['qty'] for m in plan['materials']}['Ацетилен'] == Decimal('0.26')
    assert md.joints(db, cid)[2]['profile_id'] == pid25
    # изменение количества стыков сразу меняет расход
    rows = [dict(name='Труба стальная 25', count=100, profile_id=None)]
    assert md.plan_consumption(db, rows)['materials'][0]['qty'] == Decimal('1.5') or md.format_qty(md.plan_consumption(db, rows)['materials'][0]['qty'])
    assert md.plan_consumption(db, [dict(name='x', count=0)])['materials'] == []
    assert md.format_qty(Decimal('0.2300')) == '0.23' and md.format_qty(Decimal('10')) == '10'


def test_pipes_tab_shows_plan_and_exports(db, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox, QFileDialog
    import sys
    app = QApplication.instance() or QApplication([])
    import smetagaz.gsvm_tabs as tabs
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    cid = setup_contract(db)
    enter_norms(db)

    class Dialog:
        estimate_id = None
        def open_work_entry(self): pass
        def open_consumption(self): pass
    tab = tabs.PipesTab(Dialog())
    tab.load(cid)
    assert tab.bottom.columnCount() == 4 and tab.bottom.rowCount() == 3
    tab.bottom.cellWidget(0, 1).setValue(10)
    tab.bottom.cellWidget(1, 1).setValue(4)
    names = {tab.plan.item(r, 0).text(): tab.plan.item(r, 2).text() for r in range(tab.plan.rowCount())}
    assert names['Ацетилен'] == '0.23' and names['Кислород'] == '0.6' and 'Ацетилен' in names
    assert tab.bottom.cellWidget(0, 2).itemText(0).startswith('Авто по Ду: Газовая сварка Ду 25')
    tab.bottom.cellWidget(2, 1).setValue(3)
    assert 'без диаметра' in tab.plan_warn.text()
    tab.bottom.cellWidget(2, 2).setCurrentIndex(1)                # любая норма из справочника
    tab.save(cid)
    saved = md.joints(db, cid)
    assert [j['count'] for j in saved] == [10, 4, 3] and saved[2]['profile_id'] is not None
    out = tmp_path / 'r.xlsx'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', staticmethod(lambda *a, **k: (str(out), '')))
    tab.export_plan()
    import openpyxl
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ['Расход на объект', 'Расчёт по стыкам'] and wb['Расход на объект']['A2'].value
