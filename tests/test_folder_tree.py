"""Подразделы любой глубины (2, 3, 4, 5 уровней): справочник материалов, карточка материала, статистика, папки смет и сертификатов."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys

import pytest

from smetagaz import folder_tree as ft
from smetagaz.database import DatabaseManager


@pytest.fixture
def d(tmp_path):
    db = DatabaseManager(tmp_path / 'x.db')
    db.init_db()
    yield db
    db.close()


def chain(d, table, depth=5):
    ids, parent = [], None
    for i in range(depth):
        parent = ft.add_folder(d, table, f'Уровень {i + 1}', parent)
        ids.append(parent)
    return ids


@pytest.mark.parametrize('table', ['categories', 'estimate_folders', 'certificate_folders'])
def test_five_levels_flatten_descendants_and_delete(d, table):
    ids = chain(d, table)
    side = ft.add_folder(d, table, 'Соседний раздел')
    twig = ft.add_folder(d, table, 'Ветка 3 уровня', ids[1])
    assert [(n, depth) for _i, n, _p, depth in ft.flatten(d, table)] == [('Соседний раздел', 0), ('Уровень 1', 0), ('Уровень 2', 1), ('Ветка 3 уровня', 2), ('Уровень 3', 2), ('Уровень 4', 3), ('Уровень 5', 4)]
    assert set(ft.descendants(d, table, ids[1])) == {ids[1], ids[2], ids[3], ids[4], twig} and ft.descendants(d, table, side) == [side]
    owner, column = ft.TABLES[table]
    if owner == 'materials':
        mats = [d.execute(f'INSERT INTO materials(name,{column}) VALUES(?,?)', (f'M{i}', fid)).lastrowid for i, fid in enumerate(ids)]
    elif owner == 'estimates':
        mats = [d.execute(f"INSERT INTO estimates(title,date,total,{column}) VALUES(?,?,0,?)", (f'E{i}', '2026-01-01', fid)).lastrowid for i, fid in enumerate(ids)]
    else:
        mats = [d.execute(f'INSERT INTO certificates(name,{column}) VALUES(?,?)', (f'C{i}', fid)).lastrowid for i, fid in enumerate(ids)]
    assert ft.delete_branch(d, table, ids[1]) == 5                                              # Уровни 2–5 и ветка удалены, «Уровень 1» и соседний остались
    assert {r[1] for r in ft.flatten(d, table) for r in [r]} == {'Уровень 1', 'Соседний раздел'}
    left = d.fetchall(f'SELECT {column} FROM {owner} ORDER BY id')
    assert left[0][0] == ids[0] and all(r[0] is None for r in left[1:])                         # содержимое удалённых папок не удалено, оно «без папки»
    with pytest.raises(ValueError):
        ft.add_folder(d, table, '  ')
    with pytest.raises(ValueError):
        ft.add_folder(d, table, 'X', 99999)
    with pytest.raises(ValueError):
        ft.flatten(d, 'materials')


def test_orphans_and_cycles_do_not_break_the_tree(d):
    a = ft.add_folder(d, 'categories', 'A')
    b = ft.add_folder(d, 'categories', 'B', a)
    d.execute('UPDATE categories SET parent_id=? WHERE id=?', (b, a))                           # цикл A -> B -> A
    orphan = d.execute("INSERT INTO categories(name,parent_id) VALUES('Сирота',777)").lastrowid
    names = [n for _i, n, _p, _d in ft.flatten(d, 'categories')]
    assert 'Сирота' in names                                                                    # без зависания; сирота показывается как корневой
    assert set(ft.descendants(d, 'categories', a)) == {a, b} and orphan in {i for i, *_ in ft.flatten(d, 'categories')}


def env(d, monkeypatch):
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', d, raising=False)
    from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    return QInputDialog


def test_materials_view_creates_and_shows_all_levels(d, monkeypatch):
    QInputDialog = env(d, monkeypatch)
    from smetagaz import materials_view as mv
    view = mv.MaterialsView()
    names = iter(['Раздел', 'Подраздел 2', 'Подраздел 3', 'Подраздел 4', 'Подраздел 5'])
    monkeypatch.setattr(QInputDialog, 'getText', staticmethod(lambda *a, **k: (next(names), True)))
    view.add_root_category()
    parent = d.fetchone('SELECT id FROM categories')[0]
    for _ in range(4):                                                                          # подразделы 2, 3, 4 и 5 уровней
        view.add_sub_category(parent)
        parent = d.fetchone('SELECT max(id) FROM categories')[0]
    assert d.fetchone('SELECT count(*) FROM categories')[0] == 5
    # дерево показывает все 5 уровней
    depth, item = 0, view.tree.topLevelItem(1)
    while item.childCount():
        item = item.child(0)
        depth += 1
    assert depth == 4 and item.text(0) == '📂 Подраздел 5'
    # материал в самом глубоком подразделе виден при выборе любого уровня выше
    d.execute("INSERT INTO materials(name,category_id,item_type,price,unit) VALUES('Глубокий материал',?,'Материал',1,'шт')", (parent,))
    top = view.tree.topLevelItem(1)
    view.on_category_selected(top, 0)
    assert view.table.rowCount() == 1 and view.table.item(0, 0).text() == 'Глубокий материал'
    view.on_category_selected(top.child(0).child(0), 0)
    assert view.table.rowCount() == 1
    # переименование глубокого раздела и удаление ветки с третьего уровня
    deep = top.child(0).child(0)
    deep_id = deep.data(0, 0x100)
    monkeypatch.setattr(QInputDialog, 'getText', staticmethod(lambda *a, **k: ('Переименован', True)))
    view.rename_category(deep, deep_id)
    assert d.fetchone('SELECT name FROM categories WHERE id=?', (deep_id,))[0] == 'Переименован'
    view.delete_category(deep_id)
    assert d.fetchone('SELECT count(*) FROM categories')[0] == 2 and d.fetchone('SELECT category_id FROM materials')[0] is None


def test_card_combo_and_statistics_list_every_level(d, monkeypatch):
    env(d, monkeypatch)
    ids = chain(d, 'categories')
    from smetagaz import material_card as mc
    mid = d.execute("INSERT INTO materials(name,category_id,item_type) VALUES('М',?,'Материал')", (ids[4],)).lastrowid
    card = mc.MaterialCardDialog(mid)
    labels = [card.combo_category.itemText(i) for i in range(card.combo_category.count())]
    assert len(labels) == 6 and labels[-1].strip().endswith('Уровень 5') and card.combo_category.currentData() == ids[4]        # выбран пятый уровень
    from smetagaz import statistics_view as sv
    view = sv.StatisticsView()
    assert view.combo_cat.count() == 6


def test_estimate_and_certificate_folders_any_depth(d, monkeypatch):
    QInputDialog = env(d, monkeypatch)
    from smetagaz import estimates_registry as er
    ids = chain(d, 'estimate_folders')
    eid = d.execute("INSERT INTO estimates(title,date,total,folder_id) VALUES('Смета','2026-01-01',0,?)", (ids[4],)).lastrowid
    view = er.EstimatesView()
    if True:
        top = view.tree.topLevelItem(1)
        depth, item = 0, top
        while item.childCount():
            item, depth = item.child(0), depth + 1
        assert depth == 4
        view.on_folder_selected(top, 0)
        assert view.table.rowCount() == 1                                                       # папка 1 уровня показывает смету из 5-го
        view.delete_folder(ids[1])
        assert d.fetchone('SELECT folder_id FROM estimates WHERE id=?', (eid,))[0] is None and d.fetchone('SELECT count(*) FROM estimate_folders')[0] == 1
