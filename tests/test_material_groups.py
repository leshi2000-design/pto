import pytest

from smetagaz import estimates_domain as ed, material_groups as mg
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    d.execute("INSERT INTO materials(name,unit,price,item_type,purchase_price) VALUES('Труба ПЭ 32','м',100,'Материал',70)")
    d.execute("INSERT INTO materials(name,unit,price,item_type,purchase_price) VALUES('Муфта 32','шт',50,'Материал',30)")
    d.execute("INSERT INTO materials(name,unit,price,item_type,purchase_price,labor_hours,hourly_rate) VALUES('Сварка стыка','шт',500,'Работа',0,2,250)")
    yield d
    d.close()


def ids(db):
    return [r[0] for r in db.fetchall('SELECT id FROM materials ORDER BY id')]


def test_group_crud_and_unique_names(db):
    g = mg.create(db, 'ГСВ')
    with pytest.raises(ValueError):
        mg.create(db, ' гсв ')
    with pytest.raises(ValueError):
        mg.create(db, '')
    assert mg.groups(db) == [(g, 'ГСВ', '', 0)]
    mg.rename(db, g, 'ГСВ ввод')
    assert mg.add_items(db, g, ids(db), 2) == 3
    assert mg.add_items(db, g, ids(db)) == 0                      # повторно не добавляется
    assert mg.add_items(db, g, [9999]) == 0                       # несуществующая позиция
    assert mg.groups(db)[0][3] == 3
    copy = mg.duplicate(db, g)
    assert [i['name'] for i in mg.items(db, copy)] == [i['name'] for i in mg.items(db, g)]
    assert mg.groups(db)[1][1] == 'ГСВ ввод (копия)'
    mg.delete(db, g)
    assert db.fetchone('SELECT count(*) FROM material_group_items WHERE group_id=?', (g,))[0] == 0
    assert len(mg.items(db, copy)) == 3


def test_order_quantity_and_material_removal(db):
    g = mg.create(db, 'Врезка')
    a, b, c = ids(db)
    mg.add_items(db, g, [a, b, c])
    mg.move(db, g, c, -1)
    assert [i['id'] for i in mg.items(db, g)] == [a, c, b]
    mg.move(db, g, a, -1)                                         # выше некуда
    assert [i['id'] for i in mg.items(db, g)] == [a, c, b]
    mg.set_quantity(db, g, a, 12.5)
    mg.set_quantity(db, g, b, -3)
    q = {i['id']: i['quantity'] for i in mg.items(db, g)}
    assert q[a] == 12.5 and q[b] == 0
    assert mg.groups_of_material(db, a) == ['Врезка']
    db.execute('DELETE FROM materials WHERE id=?', (b,))          # удалили позицию из справочника — из группы исчезла
    assert [i['id'] for i in mg.items(db, g)] == [a, c]
    mg.remove_item(db, g, a)
    assert [i['id'] for i in mg.items(db, g)] == [c]


def test_insert_group_into_estimate_with_sections_and_works(db):
    eid = ed.create_estimate(db, 'Смета', ('manual', 'Иванов', ''), None, False, None, '') if False else db.execute("INSERT INTO estimates(title,date,total) VALUES('Смета','2026-01-01',0)").lastrowid
    old = db.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum,sort_order) VALUES(?, 'Материал','Старая','шт',1,10,10,1)", (eid,)).lastrowid
    g = mg.create(db, 'ГСВ')
    a, b, c = ids(db)
    mg.add_items(db, g, [a, b, c], 1)
    # цена в справочнике изменилась после создания группы — в смету идёт актуальная
    db.execute('UPDATE materials SET price=110 WHERE id=?', (a,))
    items = mg.items(db, g)
    created = mg.insert_into_estimate(db, eid, [(items[0], 10), (items[1], 0), (items[2], 3)], ('new', 'ГСВ'))
    assert len(created) == 2                                      # позиция с нулевым количеством пропущена
    order = ed.ordered_items(db, eid)
    assert [(t, n) for _i, t, n, _s in order] == [('Материал', 'Старая'), ('Раздел', 'ГСВ'), ('Материал', 'Труба ПЭ 32'), ('Работа', 'Сварка стыка')]
    pipe = db.fetchone("SELECT quantity,price,sum,purchase_price FROM estimate_items WHERE name='Труба ПЭ 32'")
    assert pipe == (10, 110, 1100, 70)
    weld = db.fetchone("SELECT quantity,sum,labor_hours,hourly_rate FROM estimate_items WHERE name='Сварка стыка'")
    assert weld == (3, 1500, 2, 250)                              # состав стоимости работы запомнен в строке
    # в существующий раздел
    again = mg.insert_into_estimate(db, eid, [(items[1], 4)], order[1][0])
    names = [n for _i, _t, n, _s in ed.ordered_items(db, eid)]
    assert names == ['Старая', 'ГСВ', 'Труба ПЭ 32', 'Сварка стыка', 'Муфта 32']
    # в конец сметы без раздела, редактируется и удаляется как обычные строки
    mg.insert_into_estimate(db, eid, [(items[1], 1)], None)
    assert ed.ordered_items(db, eid)[-1][2] == 'Муфта 32'
    db.execute('DELETE FROM estimate_items WHERE id=?', (again[0],))
    db.execute('UPDATE estimate_items SET quantity=20, sum=2200 WHERE id=?', (created[0],))
    assert db.fetchone('SELECT quantity FROM estimate_items WHERE id=?', (created[0],))[0] == 20


def test_ui_group_tab_catalog_menu_and_estimate_dialog(db, monkeypatch):
    import sys
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication, QDialog, QInputDialog
    import smetagaz.material_groups_ui as ui
    import smetagaz.materials_view as mv
    import smetagaz.estimate_editor as ee
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    # вкладка в справочнике
    view = mv.MaterialsView()
    assert [view.tabs.tabText(i) for i in range(view.tabs.count())] == ['Справочник', 'Группы товаров']
    tab = view.groups_tab
    monkeypatch.setattr(ui.QInputDialog, 'getText', staticmethod(lambda *a, **k: ('ГСВ', True)))
    tab.create_group()
    gid = tab.current_group()
    # добавление из справочника через ПКМ-функцию: «Новая группа…» не нужна, выбираем существующую
    monkeypatch.setattr(ui.QInputDialog, 'getItem', staticmethod(lambda *a, **k: ('ГСВ', True)))
    monkeypatch.setattr(mv.QMessageBox, 'information', staticmethod(lambda *a, **k: None))
    view.add_to_group(ids(db)[:2])
    tab.select(gid)
    assert tab.table.rowCount() == 2
    # количество по умолчанию правится в таблице
    tab.table.item(0, 4).setText('12,5')
    assert mg.items(db, gid)[0]['quantity'] == 12.5
    tab.table.selectRow(1)
    tab.remove_items()
    assert tab.table.rowCount() == 1
    mg.add_items(db, gid, ids(db)[2:])
    tab.select(gid)
    # окно «Добавить группу» в смете
    eid = db.execute("INSERT INTO estimates(title,date,total) VALUES('Смета','2026-01-01',0)").lastrowid
    dlg = ui.GroupInsertDialog(eid)
    assert dlg.table.rowCount() == 2 and dlg.section_box.currentData() == ('new', 'ГСВ')
    dlg.table.cellWidget(0, 5).setValue(10)
    dlg.table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert 'Позиций: 1' in dlg.total.text()
    dlg.accept_group()
    assert dlg.section == ('new', 'ГСВ') and len(dlg.entries) == 1
    mg.insert_into_estimate(db, eid, dlg.entries, dlg.section)
    # раздел с таким названием уже есть — предлагается он, а не новый
    again = ui.GroupInsertDialog(eid)
    assert again.section_box.currentData()[0] == 'id'
    # редактор сметы: кнопка и подстановка
    editor = ee.EstimateEditorDialog(eid, 'Смета')
    monkeypatch.setattr(ee, 'QMessageBox', ee.QMessageBox)

    class Fake:
        entries = [(mg.items(db, gid)[0], 2)]
        section = None

        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted
    monkeypatch.setattr('smetagaz.material_groups_ui.GroupInsertDialog', Fake)
    editor.add_group()
    assert [r[2] for r in ed.ordered_items(db, eid)][-1] == 'Труба ПЭ 32'
    editor.deleteLater()
    view.deleteLater()
    again.deleteLater()
    dlg.deleteLater()
