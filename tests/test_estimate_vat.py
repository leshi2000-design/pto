"""НДС в сметах: 1) на всю смету (позиции без НДС, НДС на итог), 2) на каждую позицию (НДС в строке, итог = сумма позиций с НДС)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from decimal import Decimal

import pytest

from smetagaz import estimates_domain as ed
from smetagaz.database import DatabaseManager


@pytest.fixture
def d(tmp_path):
    db = DatabaseManager(tmp_path / 'x.db')
    db.init_db()
    yield db
    db.close()


def estimate(d):
    eid = d.execute("INSERT INTO estimates(title,date,total,paid) VALUES('С','2026-01-01',0,0)").lastrowid
    for i, (kind, name, qty, price) in enumerate((('Работа', 'Монтаж', 1, 100), ('Работа', 'Врезка', 3, 33.33), ('Материал', 'Труба', 2, 10.01))):
        d.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order) VALUES(?,?,?,?,?,?,?,?)", (eid, kind, name, 'шт', qty, price, round(qty * price, 2), i))
    return eid


def test_no_vat_by_default_and_total_unchanged(d):
    eid = estimate(d)
    t = ed.totals(d, eid)
    assert not t['vat_enabled'] and t['vat'] == 0 and t['total'] == t['total_no_vat'] == Decimal('220.01') and ed.vat_settings(d, eid) == (False, Decimal(20), 'total')


def test_vat_on_whole_estimate(d):
    eid = estimate(d)
    ed.set_vat(d, eid, True, 20, 'total')
    t = ed.totals(d, eid)
    assert t['total_no_vat'] == Decimal('220.01') and t['vat'] == Decimal('44.00') and t['total'] == Decimal('264.01')            # НДС 20 % от общей стоимости
    assert float(d.fetchone('SELECT total FROM estimates WHERE id=?', (eid,))[0]) == 264.01
    assert all(p['vat'] == 0 for p in ed.item_amounts(d, eid).values())                                                              # в строках НДС нет
    ed.set_vat(d, eid, False)
    assert ed.totals(d, eid)['total'] == Decimal('220.01') and float(d.fetchone('SELECT total FROM estimates WHERE id=?', (eid,))[0]) == 220.01


def test_vat_per_item_and_total_is_sum_of_items_with_vat(d):
    eid = estimate(d)
    ed.set_vat(d, eid, True, 20, 'items')
    parts = ed.item_amounts(d, eid)
    by_name = {d.fetchone('SELECT name FROM estimate_items WHERE id=?', (i,))[0]: p for i, p in parts.items()}
    assert by_name['Монтаж'] == dict(base=Decimal('100.00'), vat=Decimal('20.00'), with_vat=Decimal('120.00'), net=Decimal('100.00'))
    assert by_name['Врезка']['base'] == Decimal('99.99') and by_name['Врезка']['vat'] == Decimal('20.00') and by_name['Врезка']['with_vat'] == Decimal('119.99')
    assert by_name['Труба']['base'] == Decimal('20.02') and by_name['Труба']['vat'] == Decimal('4.00') and by_name['Труба']['with_vat'] == Decimal('24.02')
    t = ed.totals(d, eid)
    assert t['total'] == sum(p['with_vat'] for p in parts.values()) == Decimal('264.01') and t['vat'] == Decimal('44.00') and t['total_no_vat'] == Decimal('220.01')
    assert float(d.fetchone('SELECT total FROM estimates WHERE id=?', (eid,))[0]) == 264.01          # итог — сумма стоимостей позиций с НДС (с округлением по каждой строке)


def test_vat_with_adjustments_rate_validation_and_margin(d):
    eid = estimate(d)
    d.execute('UPDATE estimates SET work_adj_pct=10,total_adj_pct=-5 WHERE id=?', (eid,))
    ed.set_vat(d, eid, True, 20, 'items')
    t = ed.totals(d, eid)
    base = (Decimal('199.99') * Decimal('1.10') + Decimal('20.02')) * Decimal('0.95')
    assert abs(t['total_no_vat'] - base) < Decimal('0.02') and abs(t['total'] - base * Decimal('1.2')) < Decimal('0.05')
    for bad in (-1, 101):
        with pytest.raises(ValueError, match='0 до 100'):
            ed.set_vat(d, eid, True, bad, 'total')
    with pytest.raises(ValueError, match='способ'):
        ed.set_vat(d, eid, True, 20, 'x')
    assert ed.margin_summary(d, eid)['sale_total'] == t['total_no_vat']                          # маржа считается без НДС


def test_vat_tags_and_contract_marked_stale(d):
    eid = estimate(d)
    ed.set_vat(d, eid, True, 20, 'items')
    ctx = ed.extend_context(d, 'estimates', eid, dict(total=0, paid=0), {})
    assert ctx['vat_total'] == Decimal('44.00') and ctx['vat_rate'] == Decimal(20) and ctx['total_no_vat'] == Decimal('220.01') and 'каждую позицию' in ctx['vat_mode_text']
    assert ctx['ндс'] != '' and ctx['итого_без_ндс'] != ''
    tables = {}
    ed.extend_context(d, 'estimate_doc', eid, dict(total=0, paid=0), tables)
    assert [r['vat'] for r in tables['items']] == [Decimal('20.00'), Decimal('20.00'), Decimal('4.00')] and tables['items'][0]['amount_vat'] == Decimal('120.00')
    ed.set_vat(d, eid, True, 20, 'total')
    tables = {}
    ed.extend_context(d, 'estimate_doc', eid, dict(total=0, paid=0), tables)
    assert all(r['vat'] == '' for r in tables['items'])                                           # в режиме «на всю смету» колонки НДС в строках пустые
    n = d.fetchone('SELECT count(*) FROM estimate_changes WHERE estimate_id=? AND item_name=?', (eid, 'НДС'))[0]
    ed.set_vat(d, eid, True, 20, 'total')
    assert d.fetchone('SELECT count(*) FROM estimate_changes WHERE estimate_id=? AND item_name=?', (eid, 'НДС'))[0] == n       # без изменений запись не добавляется


def test_editor_checkbox_columns_totals_and_exports(d, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
    import smetagaz.estimate_editor as ee
    import sys
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', d, raising=False)
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    eid = estimate(d)
    editor = ee.EstimateEditorDialog(eid, 'Смета')
    assert not editor.chk_vat.isChecked() and editor.table.isColumnHidden(6) and '220.01' in editor.lbl_grand_total.text().replace(' ', '')
    editor.chk_vat.setChecked(True)                                        # режим 1: НДС на всю смету
    assert ed.vat_settings(d, eid) == (True, Decimal(20), 'total') and editor.table.isColumnHidden(6) and '264' in editor.lbl_grand_total.text() and 'с НДС' in editor.lbl_grand_total.text()
    assert 'НДС 20%' in editor.totals_lbl.text() and 'Итого без НДС' in editor.totals_lbl.text()
    editor.cmb_vat_mode.setCurrentIndex(editor.cmb_vat_mode.findData('items'))        # режим 2: НДС на каждую позицию
    assert not editor.table.isColumnHidden(6) and not editor.table.isColumnHidden(7) and '264' in editor.lbl_grand_total.text()
    assert [editor.table.item(r, 6).text().replace(' ', '') for r in range(3)] == ['20.00', '20.00', '4.00'] and editor.table.item(0, 7).text().replace(' ', '') == '120.00'
    editor.spin_vat.setValue(10)
    assert ed.vat_settings(d, eid)[1] == Decimal(10) and editor.table.item(0, 6).text().replace(' ', '') == '10.00'
    # PDF и Excel содержат НДС
    pdf, xlsx = str(tmp_path / 'e.pdf'), str(tmp_path / 'e.xlsx')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', staticmethod(lambda *a, **k: (pdf, '')))
    editor.export_estimate_pdf()
    assert os.path.getsize(pdf) > 1000
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', staticmethod(lambda *a, **k: (xlsx, '')))
    editor.export_excel()
    import openpyxl
    ws = openpyxl.load_workbook(xlsx).active
    cells = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert 'НДС (руб)' in cells and 'Сумма с НДС (руб)' in cells and any('НДС 10%' in c for c in cells) and 'ВСЕГО ПО СМЕТЕ (с НДС):' in cells
    editor.chk_vat.setChecked(False)
    assert editor.table.isColumnHidden(6) and '220.01' in editor.lbl_grand_total.text().replace(' ', '') and 'с НДС' not in editor.lbl_grand_total.text()


def test_per_item_rounding_differs_from_whole_estimate(d):
    eid = d.execute("INSERT INTO estimates(title,date,total,paid) VALUES('С','2026-01-01',0,0)").lastrowid
    for i in range(3):
        d.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order) VALUES(?,?,?,?,?,?,?,?)", (eid, 'Работа', f'Мелочь {i}', 'шт', 1, 0.03, 0.03, i))
    ed.set_vat(d, eid, True, 20, 'total')
    assert ed.totals(d, eid)['total'] == Decimal('0.11')                       # НДС на итог: 0,09 × 20 % = 0,02
    ed.set_vat(d, eid, True, 20, 'items')
    assert ed.totals(d, eid)['total'] == Decimal('0.12')                       # НДС по строкам: каждая 0,03 + 0,01


def test_extract_vat_from_item_amounts(d):
    """Режим «выделить НДС из суммы позиции»: сумма уже с НДС — итог не меняется, НДС показан «в том числе»."""
    eid = estimate(d)                                                              # 100,00 + 99,99 + 20,02 = 220,01
    ed.set_vat(d, eid, True, 20, 'extract_items')
    parts = ed.item_amounts(d, eid)
    by_name = {d.fetchone('SELECT name FROM estimate_items WHERE id=?', (i,))[0]: p for i, p in parts.items()}
    assert by_name['Монтаж'] == dict(base=Decimal('100.00'), vat=Decimal('16.67'), with_vat=Decimal('100.00'), net=Decimal('83.33'))        # 100 × 20 / 120
    assert by_name['Врезка']['vat'] == Decimal('16.67') and by_name['Врезка']['net'] == Decimal('83.32')
    assert by_name['Труба']['vat'] == Decimal('3.34') and by_name['Труба']['net'] == Decimal('16.68')
    t = ed.totals(d, eid)
    assert t['total'] == Decimal('220.01') and t['vat'] == Decimal('36.68') and t['total_no_vat'] == Decimal('183.33') and t['vat_mode'] == 'extract_items'
    assert float(d.fetchone('SELECT total FROM estimates WHERE id=?', (eid,))[0]) == 220.01            # итог сметы не изменился
    assert ed.margin_summary(d, eid)['sale_total'] == Decimal('183.33')                                # маржа — без НДС
    ctx = ed.extend_context(d, 'estimates', eid, dict(total=0, paid=0), {})
    assert ctx['vat_extracted'] == 'Да' and ctx['vat_total'] == Decimal('36.68')
    tables = {}
    ed.extend_context(d, 'estimate_doc', eid, dict(total=0, paid=0), tables)
    assert tables['items'][0]['vat'] == Decimal('16.67') and tables['items'][0]['amount_net'] == Decimal('83.33') and tables['items'][0]['amount_vat'] == Decimal('100.00')


def test_extract_vat_from_estimate_total_and_adjustments(d):
    eid = estimate(d)
    ed.set_vat(d, eid, True, 20, 'extract_total')
    t = ed.totals(d, eid)
    assert t['total'] == Decimal('220.01') and t['vat'] == Decimal('36.67') and t['total_no_vat'] == Decimal('183.34')                 # 220,01 × 20 / 120
    assert all(p['vat'] == 0 for p in ed.item_amounts(d, eid).values())                                                                # в строках НДС не показывается
    d.execute('UPDATE estimates SET total_adj_pct=10 WHERE id=?', (eid,))                                                              # наценка до выделения НДС
    t = ed.totals(d, eid)
    assert abs(t['total'] - Decimal('242.011')) < Decimal('0.001') and abs(t['vat'] - Decimal('40.34')) < Decimal('0.011')
    assert ed.extend_context(d, 'estimates', eid, dict(total=0, paid=0), {})['vat_extracted'] == 'Да'
    ed.set_vat(d, eid, True, 20, 'total')
    assert ed.extend_context(d, 'estimates', eid, dict(total=0, paid=0), {})['vat_extracted'] == 'Нет'


def test_editor_extract_vat_option_columns_and_exports(d, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
    import smetagaz.estimate_editor as ee
    import sys
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', d, raising=False)
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    eid = estimate(d)
    editor = ee.EstimateEditorDialog(eid, 'Смета')
    modes = [editor.cmb_vat_mode.itemData(i) for i in range(editor.cmb_vat_mode.count())]
    assert modes == ['total', 'items', 'extract_items', 'extract_total'] and 'Выделить НДС из суммы' in editor.cmb_vat_mode.itemText(2)        # пункт списка «выделить НДС»
    editor.chk_vat.setChecked(True)
    editor.cmb_vat_mode.setCurrentIndex(editor.cmb_vat_mode.findData('extract_items'))
    assert ed.vat_settings(d, eid)[2] == 'extract_items' and not editor.table.isColumnHidden(6)
    assert editor.table.horizontalHeaderItem(6).text() == 'в т.ч. НДС (руб)' and editor.table.horizontalHeaderItem(7).text() == 'Без НДС (руб)'
    assert [editor.table.item(r, 6).text().replace(' ', '') for r in range(3)] == ['16.67', '16.67', '3.34'] and editor.table.item(0, 7).text().replace(' ', '') == '83.33'
    assert '220.01' in editor.lbl_grand_total.text().replace(' ', '') and 'в том числе НДС 20%' in editor.totals_lbl.text()
    assert 'в том числе НДС' in editor.totals_lbl.text()
    pdf, xlsx = str(tmp_path / 'e.pdf'), str(tmp_path / 'e.xlsx')
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', staticmethod(lambda *a, **k: (pdf, '')))
    editor.export_estimate_pdf()
    assert os.path.getsize(pdf) > 1000
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', staticmethod(lambda *a, **k: (xlsx, '')))
    editor.export_excel()
    import openpyxl
    cells = [str(c.value) for row in openpyxl.load_workbook(xlsx).active.iter_rows() for c in row if c.value is not None]
    assert 'в т.ч. НДС (руб)' in cells and 'Без НДС (руб)' in cells and any('в том числе НДС 20%' in c for c in cells) and 'ВСЕГО ПО СМЕТЕ (с НДС):' in cells
    editor.cmb_vat_mode.setCurrentIndex(editor.cmb_vat_mode.findData('extract_total'))
    assert editor.table.isColumnHidden(6) and '220.01' in editor.lbl_grand_total.text().replace(' ', '')
