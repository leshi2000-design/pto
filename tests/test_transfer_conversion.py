import pytest
from smetagaz import stock_view  # noqa: F401  (до подмены базы в тестах)
from smetagaz.database import DatabaseManager
from smetagaz import stock_domain as st, stock_registers as reg


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 't.db')
    d.init_db()
    yield d
    d.close()


def acetylene(db):
    mid = st.save_material(db, 'Ацетилен баллон', 'Газы', 'шт')
    st.receive(db, mid, '3', '2026-10-01', 'приход')
    db.execute("INSERT INTO materials(name,unit,price,purchase_price,item_type) VALUES('Ацетилен баллон','шт',150,120,'Материал')")
    return mid


def header(**kw):
    d = dict(number='АП-1', transfer_date='2026-10-05')
    d.update(kw)
    return d


def test_unit_prices_example():
    assert reg.unit_prices(120, 1, 5.05) == (120.0, 23.7624)


def test_save_post_and_reverse_conversion(db):
    mid = acetylene(db)
    line = dict(material_id=mid, material_name='Ацетилен баллон', unit='шт', quantity='1', new_unit='м³', new_quantity='5,05')
    tid = reg.save_transfer(db, header(), [line])                                    # стоимость взята из справочника: 120 × 1
    row = reg.transfer_conversions(db, tid)[0]
    assert row['cost'] == 120 and row['old_price'] == 120 and row['new_price'] == 23.7624
    assert not reg.is_posted(db, tid)
    assert reg.post_transfer(db, tid) == 1
    new_mid = db.fetchone("SELECT id FROM stock_materials WHERE name='Ацетилен баллон' AND unit='м³'")[0]
    assert st.balance(db, mid) == st.units('2') and st.balance(db, new_mid) == st.units('5,05')
    cat = db.fetchone("SELECT purchase_price,price FROM materials WHERE name='Ацетилен баллон' AND unit='м³'")
    assert cat[0] == 23.7624 and cat[1] == round(23.7624 * 150 / 120, 2)             # наценка прежней позиции сохранена
    assert db.fetchone("SELECT price FROM materials WHERE unit='шт'")[0] == 150          # прежняя позиция не тронута
    with pytest.raises(ValueError, match='проведён'):
        reg.save_transfer(db, header(), [line], tid)
    with pytest.raises(ValueError):
        reg.delete_transfer(db, tid)
    reg.reverse_transfer(db, tid)
    assert st.balance(db, mid) == st.units('3') and st.balance(db, new_mid) == 0
    assert db.fetchone("SELECT count(*) FROM materials WHERE unit='м³'")[0] == 0         # созданная актом позиция справочника удалена
    assert not reg.is_posted(db, tid)
    reg.post_transfer(db, tid)                                                         # повторное проведение
    assert st.balance(db, new_mid) == st.units('5,05')


def test_existing_catalog_item_is_updated_and_restored(db):
    mid = acetylene(db)
    db.execute("INSERT INTO materials(name,unit,price,purchase_price,item_type) VALUES('Ацетилен баллон','м³',30,25,'Материал')")
    tid = reg.save_transfer(db, header(), [dict(material_id=mid, material_name='Ацетилен баллон', unit='шт', quantity='1', new_unit='м³', new_quantity='5.05', cost='121,2')])
    reg.post_transfer(db, tid)
    assert db.fetchone("SELECT purchase_price FROM materials WHERE unit='м³'")[0] == 24.0
    reg.reverse_transfer(db, tid)
    assert db.fetchone("SELECT purchase_price,price FROM materials WHERE unit='м³'") == (25, 30)


def test_validation_and_insufficient_stock(db):
    mid = acetylene(db)
    base = dict(material_id=mid, material_name='Ацетилен баллон', unit='шт', quantity='1', new_unit='м³', new_quantity='5')
    with pytest.raises(ValueError, match='новое количество'):
        reg.save_transfer(db, header(), [dict(base, new_quantity='')])
    with pytest.raises(ValueError, match='совпадает'):
        reg.save_transfer(db, header(), [dict(base, new_unit='ШТ')])
    with pytest.raises(ValueError, match='стоимость'):
        reg.save_transfer(db, header(), [dict(base, material_name='Нет в справочнике')])
    tid = reg.save_transfer(db, header(), [dict(base, quantity='10')])                   # на складе только 3 шт
    with pytest.raises(ValueError, match='недостаточно'):
        reg.post_transfer(db, tid)
    assert not reg.is_posted(db, tid) and db.fetchone('SELECT count(*) FROM stock_moves WHERE transfer_id IS NOT NULL')[0] == 0     # проведение откатилось целиком
    plain = reg.save_transfer(db, header(number='АП-2'), [dict(material_name='Свой материал', quantity='2', unit='шт')])               # информационный акт (прежний вид)
    with pytest.raises(ValueError, match='нет строк перевода'):
        reg.post_transfer(db, plain)


def test_transfer_dialog_recalculates_and_posts(db, monkeypatch):
    import sys
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    from PyQt6.QtWidgets import QMessageBox
    from smetagaz import stock_view as sv
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    mid = acetylene(db)
    d = sv.TransferDialog()
    combo = d.lines.cellWidget(0, 0)
    combo.setCurrentIndex(next(i for i in range(combo.count()) if combo.itemData(i) and combo.itemData(i)[0] == mid))
    assert d.lines.item(0, 1).text() == 'шт'
    d.lines.item(0, 2).setText('1')
    assert d.lines.item(0, 5).text() == '120'                      # стоимость из справочника
    d.lines.item(0, 3).setText('м³')
    d.lines.item(0, 4).setText('5,05')
    assert d.lines.item(0, 6).text() == '120' and d.lines.item(0, 7).text() == '23.7624'
    d.post()
    assert d.tid and reg.is_posted(db, d.tid) and not d.post_btn.isEnabled() and d.reverse_btn.isEnabled()
    assert db.fetchone("SELECT purchase_price FROM materials WHERE unit='м³'")[0] == 23.7624
    reopened = sv.TransferDialog(d.tid)
    assert reopened.lines.item(0, 7).text() == '23.7624' and not reopened.save_btn.isEnabled()
    reopened.reverse()
    assert not reg.is_posted(db, d.tid)
    v = sv.RegisterView('transfers')
    assert v.table.rowCount() == 1 and 'Черновик' in [v.table.item(0, c).text() for c in range(v.table.columnCount())]
