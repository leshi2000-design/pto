"""Qt-помощники для деревьев папок любой глубины (см. folder_tree): дерево, выпадающий список, пункты меню «Отправить в…»."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTreeWidgetItem

from . import folder_tree as ft


def fill_tree(tree, db, table, all_label):
    """Заполняет QTreeWidget: «Все …», затем папки с любым числом уровней вложенности (данные элемента — id папки, у «Все» — None)."""
    tree.clear()
    all_item = QTreeWidgetItem([all_label])
    all_item.setData(0, Qt.ItemDataRole.UserRole, None)
    tree.addTopLevelItem(all_item)
    items = {}
    for fid, name, parent, depth in ft.flatten(db, table):
        item = QTreeWidgetItem([('📁 ' if depth == 0 else '📂 ') + name])
        item.setData(0, Qt.ItemDataRole.UserRole, fid)
        if depth > 0 and parent in items:
            items[parent].addChild(item)
        else:
            tree.addTopLevelItem(item)
        items[fid] = item
    tree.expandAll()
    tree.setCurrentItem(all_item)


def entries(db, table):
    """[(подпись с отступом по глубине, id)] — для выпадающих списков и меню."""
    return [('   ' * depth + ('📁 ' if depth == 0 else '📂 ') + name, fid) for fid, name, _parent, depth in ft.flatten(db, table)]


def fill_combo(combo, db, table):
    for label, fid in entries(db, table):
        combo.addItem(label, fid)


def fill_move_menu(menu, db, table, handler):
    """Пункты меню по всем папкам дерева; handler(id папки) вызывается при выборе."""
    from PyQt6.QtGui import QAction
    for label, fid in entries(db, table):
        act = QAction(label, menu)
        act.triggered.connect(lambda checked=False, f=fid: handler(f))
        menu.addAction(act)
