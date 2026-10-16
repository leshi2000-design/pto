import pytest
from smetagaz.database import DatabaseManager
from smetagaz import estimates_domain as ed


@pytest.fixture
def d(tmp_path):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


def add(d, eid, kind, name, qty=1, price=10, order=0):
    return d.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order) VALUES(?,?,?,?,?,?,?,?)", (eid, kind, name, 'шт', qty, price, qty * price, order)).lastrowid


def names(d, eid):
    return [r[2] for r in ed.ordered_items(d, eid)]


def test_sections_place_and_totals(d):
    eid = d.execute("INSERT INTO estimates(title,date,total,paid) VALUES('С','2026-01-01',0,0)").lastrowid
    gsv = add(d, eid, 'Раздел', 'ГСВ', order=1)
    a = add(d, eid, 'Материал', 'Труба', 2, 10, 2)
    gsn = add(d, eid, 'Раздел', 'ГСН', order=3)
    b = add(d, eid, 'Работа', 'Монтаж', 1, 100, 4)
    free = add(d, eid, 'Материал', 'Без раздела', 1, 5, 5)
    assert ed.sections(d, eid) == [(gsv, 'ГСВ'), (gsn, 'ГСН')]
    t = ed.section_totals(d, eid)
    assert t[gsv] == dict(materials=20.0, works=0.0, count=1) and t[gsn]['works'] == 100 and t[gsn]['materials'] == 5
    ed.place_item(d, eid, b, gsv)                    # работа отправлена в «ГСВ»: встала после его последней позиции
    assert names(d, eid) == ['ГСВ', 'Труба', 'Монтаж', 'ГСН', 'Без раздела']
    ed.place_item(d, eid, a, gsn)
    assert names(d, eid) == ['ГСВ', 'Монтаж', 'ГСН', 'Без раздела', 'Труба']
    ed.place_item(d, eid, free, None)               # без раздела — в конец сметы
    assert names(d, eid)[-1] == 'Без раздела'
    with pytest.raises(ValueError):
        ed.place_item(d, eid, a, a)                 # позиция не раздел
    assert 'ГСВ — внутреннее газоснабжение' in ed.SECTION_PRESETS and len(ed.SECTION_PRESETS) == 5


def test_editor_section_and_catalog_flow(d, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    import smetagaz.estimate_editor as ee, smetagaz.dialogs_common as dc
    monkeypatch.setattr(ee, 'db', d)
    monkeypatch.setattr(dc, 'db', d)
    cat = d.execute("INSERT INTO categories(name) VALUES('Трубы')").lastrowid
    sub = d.execute("INSERT INTO categories(name,parent_id) VALUES('ПЭ',?)", (cat,)).lastrowid
    d.execute("INSERT INTO materials(category_id,name,unit,price,item_type) VALUES(?,?,?,?,?)", (sub, 'Труба ПЭ 32', 'м', 5, 'Материал'))
    d.execute("INSERT INTO materials(category_id,name,unit,price,item_type) VALUES(NULL,?,?,?,?)", ('Монтаж', 'шт', 50, 'Работа'))
    m = dc.MaterialSelectionDialog()
    top = m.tree.topLevelItem(0)
    assert top.text(0) == 'Весь справочник (1)' and top.child(0).text(0) == 'Трубы (1)' and top.child(0).child(0).text(0) == 'ПЭ (1)'
    top.child(0).setSelected(True)
    m.tree.setCurrentItem(top.child(0))
    assert m.table.rowCount() == 1                 # папка «Трубы» показывает позиции вложенной «ПЭ»
    m.search_input.setText('несуществует')
    assert m.table.rowCount() == 0
    w = dc.WorkSelectionDialog()
    assert w.table.rowCount() == 1 and w.tree.topLevelItem(0).text(0) == 'Весь справочник (1)'
    eid = d.execute("INSERT INTO estimates(title,date,total,paid) VALUES('С','2026-01-01',0,0)").lastrowid
    editor = ee.EstimateEditorDialog(eid, 'С')
    monkeypatch.setattr(ee, 'ed', ed)
    for sid in ('ГСВ', 'СМР'):
        d.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order) VALUES(?,'Раздел',?,'',0,0,0,?)", (eid, sid, 1 if sid == 'ГСВ' else 2))
    editor.load_items()
    gsv_id = ed.sections(d, eid)[0][0]
    item = d.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order) VALUES(?,'Материал','Труба','м',3,10,30,3)", (eid,)).lastrowid
    editor.place(item, gsv_id)
    assert [editor.table.item(r, 0).text() for r in range(editor.table.rowCount())] == ['ГСВ', 'Труба', 'СМР']
    assert editor.table.item(0, 5).text() == '30,00'.replace(',', ',') or editor.table.item(0, 5).text().startswith('30')
    assert editor.table.item(0, 1).text() == 'Раздел'


def test_manual_client_and_payments_in_estimate(d, monkeypatch):
    import smetagaz.estimate_editor as ee, smetagaz.estimates_ui as eu, smetagaz.dialogs_common as dc
    from smetagaz import payments_domain
    monkeypatch.setattr(ee, 'db', d)
    monkeypatch.setattr(eu, 'db', d)
    dlg = eu.NewEstimateDialog()
    dlg.inp_manual.setText('Случайный Клиент')
    dlg.inp_manual_phone.setText('375291112233')
    title, client, contract, link = dlg.values()
    assert client == ('manual', 'Случайный Клиент', '375291112233') and dlg.rb_manual.isChecked()
    eid = ed.create_estimate(d, title, client=client)
    row = d.fetchone('SELECT client_name,client_phone,client_id FROM estimates WHERE id=?', (eid,))
    assert row[:2] == ('Случайный Клиент', '375291112233') and row[2]            # попал в «Клиенты»
    with pytest.raises(ValueError):
        ed.create_estimate(d, 'X', client=('manual', '  ', ''))
    d.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order) VALUES(?,'Работа','Монтаж','шт',1,500,500,1)", (eid,))
    editor = ee.EstimateEditorDialog(eid, 'С')
    editor.load_items()
    editor.pay_amount.setValue(200)
    editor.pay_note.setText('аванс')
    editor.add_payment_here()
    assert editor.pay_table.rowCount() == 1 and 'Остаток' in editor.pay_summary.text() and '300' in editor.pay_summary.text()
    editor.fill_rest()
    assert editor.pay_amount.value() == 300
    editor.add_payment_here()
    assert editor.pay_table.rowCount() == 2 and payments_domain.summary(d, 'estimates', eid)['debt'] == 0
    editor.pay_table.selectRow(0)
    monkeypatch.setattr(ee.QMessageBox, 'question', lambda *a, **k: ee.QMessageBox.StandardButton.Yes)
    editor.remove_payment_here()
    assert editor.pay_table.rowCount() == 1
    assert d.fetchone('SELECT paid FROM estimates WHERE id=?', (eid,))[0] in (200, 300, 200.0, 300.0)
