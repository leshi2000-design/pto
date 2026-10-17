"""Группы товаров: вкладка в справочнике и окно «Добавить группу» в смете."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import estimates_domain as ed
from . import material_groups as mg
from .database import db


def money(value):
    return f'{float(value or 0):,.2f}'.replace(',', ' ')


def _number(text, default=0.0):
    try:
        return float(str(text).replace(' ', '').replace(',', '.'))
    except ValueError:
        return default


class PickItemsDialog(QDialog):
    """Выбор нескольких позиций справочника (материалов и работ) для добавления в группу."""
    def __init__(self, parent=None, exclude=()):
        super().__init__(parent)
        self.setWindowTitle('Позиции справочника для группы')
        self.resize(820, 560)
        self.exclude = set(exclude)
        self.selected_ids = []
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск по названию (Ctrl/Shift — выбрать несколько)')
        self.kind = QComboBox()
        self.kind.addItem('Материалы и работы', None)
        self.kind.addItem('Только материалы', 'Материал')
        self.kind.addItem('Только работы', 'Работа')
        bar.addWidget(self.search, 1)
        bar.addWidget(self.kind)
        layout.addLayout(bar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Наименование', 'Тип', 'Ед.', 'Цена'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 430)
        layout.addWidget(self.table, 1)
        self.note = QLabel()
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        ok, cancel = QPushButton('Добавить выбранные'), QPushButton('Отмена')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.accept_selected)
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)
        self.search.textChanged.connect(self.load)
        self.kind.currentIndexChanged.connect(self.load)
        self.table.doubleClicked.connect(self.accept_selected)
        self.load()

    def load(self, *_):
        sql, args = "SELECT id,name,coalesce(item_type,'Материал'),coalesce(unit,''),coalesce(price,0) FROM materials WHERE 1=1", []
        text = self.search.text().strip()
        if text:
            sql += ' AND LOWER(name) LIKE ?'
            args.append('%' + text.casefold() + '%')
        if self.kind.currentData():
            sql += " AND coalesce(item_type,'Материал')=?"
            args.append(self.kind.currentData())
        rows = [r for r in db.fetchall(sql + ' ORDER BY name LIMIT 600', tuple(args)) if r[0] not in self.exclude]
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate((row[1], row[2], row[3], money(row[4]))):
                item = QTableWidgetItem(str(value))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row[0])
                self.table.setItem(r, c, item)
        self.note.setText('Показано не больше 600 позиций — уточните поиск.' if len(rows) >= 600 else f'Найдено: {len(rows)}. Уже входящие в группу позиции скрыты.')

    def accept_selected(self, *_):
        rows = sorted({i.row() for i in self.table.selectedItems()})
        self.selected_ids = [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in rows]
        if self.selected_ids:
            self.accept()


class MaterialGroupsTab(QWidget):
    """Слева группы, справа их состав. Количество по умолчанию правится прямо в таблице (двойной щелчок)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Группа — набор позиций справочника, который добавляется в смету одним действием (например, «ГСВ»). '
                                'В смете останется указать количество, лишнее можно убрать.'))
        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split, 1)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 6, 0)
        self.list = QListWidget()
        lv.addWidget(self.list, 1)
        for text, fn in (('Создать группу', self.create_group), ('Переименовать', self.rename_group), ('Копировать', self.copy_group), ('Удалить группу', self.delete_group)):
            b = QPushButton(text)
            if text.startswith('Удалить'):
                b.setProperty('type', 'danger')
            b.clicked.connect(fn)
            lv.addWidget(b)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 0, 0, 0)
        self.title = QLabel()
        rv.addWidget(self.title)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Наименование', 'Тип', 'Ед.', 'Цена сейчас', 'Кол-во по умолчанию', 'Сумма'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 360)
        self.table.itemChanged.connect(self.quantity_changed)
        rv.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for text, fn in (('Добавить из справочника…', self.add_items), ('Убрать из группы', self.remove_items), ('Вверх', lambda: self.move(-1)), ('Вниз', lambda: self.move(1))):
            b = QPushButton(text)
            if text.startswith('Добавить'):
                b.setProperty('type', 'primary')
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.total = QLabel()
        bar.addWidget(self.total)
        rv.addLayout(bar)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        self.list.currentItemChanged.connect(lambda *_: self.load_items())
        self.load_data()

    # --- данные
    def current_group(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def load_data(self):
        keep = self.current_group()
        self.list.blockSignals(True)
        self.list.clear()
        for gid, name, _note, count in mg.groups(db):
            item = QListWidgetItem(f'{name}  ({count})')
            item.setData(Qt.ItemDataRole.UserRole, gid)
            self.list.addItem(item)
            if gid == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self.load_items()

    def load_items(self):
        gid = self.current_group()
        self.table.blockSignals(True)
        rows = mg.items(db, gid) if gid else []
        self.table.setRowCount(len(rows))
        total = 0.0
        for r, m in enumerate(rows):
            amount = m['quantity'] * m['price']
            total += amount
            for c, value in enumerate((m['name'], m['type'], m['unit'], money(m['price']), f"{m['quantity']:g}", money(amount))):
                item = QTableWidgetItem(str(value))
                if c != 4:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, m['id'])
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)
        name = self.list.currentItem().text() if self.list.currentItem() else ''
        self.title.setText(f'<b>{name}</b>' if gid else 'Создайте первую группу кнопкой «Создать группу».')
        self.total.setText(f'Ориентировочно при количествах по умолчанию: {money(total)} руб.' if rows else '')

    def quantity_changed(self, item):
        if item.column() != 4 or self.current_group() is None:
            return
        row = item.row()
        mid = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        mg.set_quantity(db, self.current_group(), mid, _number(item.text()))
        self.load_items()

    def selected_material_ids(self):
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in sorted({i.row() for i in self.table.selectedItems()})]

    # --- действия
    def create_group(self):
        name, ok = QInputDialog.getText(self, 'Новая группа', 'Название группы (например, ГСВ):')
        if not ok:
            return
        try:
            gid = mg.create(db, name)
        except ValueError as e:
            QMessageBox.warning(self, 'Группа', str(e))
            return
        self.select(gid)

    def select(self, gid):
        self.load_data()
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == gid:
                self.list.setCurrentRow(i)
                return

    def rename_group(self):
        gid = self.current_group()
        if gid is None:
            return
        old = db.fetchone('SELECT name FROM material_groups WHERE id=?', (gid,))[0]
        name, ok = QInputDialog.getText(self, 'Переименовать группу', 'Название:', text=old)
        if ok:
            try:
                mg.rename(db, gid, name)
            except ValueError as e:
                QMessageBox.warning(self, 'Группа', str(e))
                return
            self.select(gid)

    def copy_group(self):
        gid = self.current_group()
        if gid is not None:
            self.select(mg.duplicate(db, gid))

    def delete_group(self):
        gid = self.current_group()
        if gid is None:
            return
        if QMessageBox.question(self, 'Удалить группу', 'Удалить группу? Позиции справочника и уже созданные сметы не изменятся.') == QMessageBox.StandardButton.Yes:
            mg.delete(db, gid)
            self.load_data()

    def add_items(self):
        gid = self.current_group()
        if gid is None:
            QMessageBox.information(self, 'Группа', 'Сначала создайте или выберите группу.')
            return
        dlg = PickItemsDialog(self, exclude=[m['id'] for m in mg.items(db, gid)])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            mg.add_items(db, gid, dlg.selected_ids)
            self.load_data()

    def remove_items(self):
        gid = self.current_group()
        for mid in self.selected_material_ids():
            mg.remove_item(db, gid, mid)
        self.load_data()

    def move(self, direction):
        gid, ids = self.current_group(), self.selected_material_ids()
        if gid is None or len(ids) != 1:
            return
        mg.move(db, gid, ids[0], direction)
        self.load_items()
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == ids[0]:
                self.table.selectRow(r)


class GroupInsertDialog(QDialog):
    """Окно «Добавить группу товаров» в смете: все позиции группы подставлены, остаётся указать количество и при необходимости убрать лишнее."""
    def __init__(self, estimate_id, parent=None, group_id=None):
        super().__init__(parent)
        self.estimate_id = estimate_id
        self.entries, self.section = [], None
        self._items = []
        self.setWindowTitle('Добавить группу товаров в смету')
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.group = QComboBox()
        for gid, name, _note, count in mg.groups(db):
            self.group.addItem(f'{name}  ({count})', gid)
        self.section_box = QComboBox()
        top.addWidget(QLabel('Группа:'))
        top.addWidget(self.group, 1)
        top.addWidget(QLabel('Куда в смете:'))
        top.addWidget(self.section_box, 1)
        layout.addLayout(top)
        layout.addWidget(QLabel('Укажите количество у нужных позиций. Позиции с нулевым количеством и без галочки в смету не попадут; потом их можно править и удалять как обычные строки.'))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(['Добавить', 'Наименование', 'Тип', 'Ед.', 'Цена', 'Количество', 'Сумма'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 380)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        all_on, all_off = QPushButton('Отметить все'), QPushButton('Снять все')
        all_on.clicked.connect(lambda: self.set_all(True))
        all_off.clicked.connect(lambda: self.set_all(False))
        self.total = QLabel()
        ok, cancel = QPushButton('Добавить в смету'), QPushButton('Отмена')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.accept_group)
        cancel.clicked.connect(self.reject)
        bar.addWidget(all_on)
        bar.addWidget(all_off)
        bar.addStretch()
        bar.addWidget(self.total)
        bar.addWidget(cancel)
        bar.addWidget(ok)
        layout.addLayout(bar)
        self.group.currentIndexChanged.connect(self.group_changed)
        if group_id is not None and self.group.findData(group_id) >= 0:
            self.group.setCurrentIndex(self.group.findData(group_id))
        self.group_changed()

    def group_name(self):
        row = db.fetchone('SELECT name FROM material_groups WHERE id=?', (self.group.currentData(),))
        return row[0] if row else ''

    def group_changed(self, *_):
        gid = self.group.currentData()
        self._items = mg.items(db, gid) if gid else []
        name = self.group_name()
        self.section_box.clear()
        self.section_box.addItem('— в конец сметы, без раздела —', ('end', None))
        existing = None
        for sid, title in ed.sections(db, self.estimate_id):
            self.section_box.addItem(f'Раздел «{title}»', ('id', sid))
            if title.strip().casefold() == name.strip().casefold():
                existing = self.section_box.count() - 1
        self.section_box.addItem(f'＋ Новый раздел «{name}»', ('new', name))
        self.section_box.setCurrentIndex(existing if existing is not None else self.section_box.count() - 1)
        self.fill_table()

    def fill_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._items))
        for r, m in enumerate(self._items):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            check.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(r, 0, check)
            for c, value in ((1, m['name']), (2, m['type']), (3, m['unit']), (4, money(m['price']))):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)
            spin = QDoubleSpinBox()
            spin.setDecimals(3)
            spin.setRange(0, 1_000_000)
            spin.setValue(float(m['quantity']))
            spin.valueChanged.connect(self.recalc)
            self.table.setCellWidget(r, 5, spin)
            self.table.setItem(r, 6, QTableWidgetItem(''))
        self.table.blockSignals(False)
        self.table.itemChanged.connect(self.recalc) if not getattr(self, '_wired', False) else None
        self._wired = True
        self.recalc()

    def set_all(self, on):
        self.table.blockSignals(True)
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self.recalc()

    def chosen(self):
        out = []
        for r, m in enumerate(self._items):
            qty = self.table.cellWidget(r, 5).value()
            if self.table.item(r, 0).checkState() == Qt.CheckState.Checked and qty > 0:
                out.append((m, qty))
        return out

    def recalc(self, *_):
        total = 0.0
        for r, m in enumerate(self._items):
            qty = self.table.cellWidget(r, 5).value()
            on = self.table.item(r, 0).checkState() == Qt.CheckState.Checked
            self.table.blockSignals(True)
            self.table.item(r, 6).setText(money(qty * m['price']) if on else '—')
            self.table.blockSignals(False)
            if on:
                total += qty * m['price']
        self.total.setText(f'Позиций: {len(self.chosen())} · на сумму {money(total)} руб.')

    def accept_group(self):
        self.entries = self.chosen()
        if not self.entries:
            QMessageBox.information(self, 'Группа товаров', 'Нет позиций с количеством больше нуля. Укажите количество хотя бы у одной.')
            return
        kind, value = self.section_box.currentData()
        self.section = None if kind == 'end' else (('new', value) if kind == 'new' else value)
        self.accept()


def add_to_group_dialog(parent, material_ids):
    """Из справочника: «Добавить выделенные позиции в группу…» -> число добавленных (или None, если отменено)."""
    names = [g[1] for g in mg.groups(db)]
    options = names + ['＋ Новая группа…']
    choice, ok = QInputDialog.getItem(parent, 'Добавить в группу', 'Группа товаров:', options, 0, False)
    if not ok:
        return None
    try:
        if choice == options[-1]:
            name, ok = QInputDialog.getText(parent, 'Новая группа', 'Название группы:')
            if not ok:
                return None
            gid = mg.create(db, name)
        else:
            gid = mg.groups(db)[names.index(choice)][0]
    except ValueError as e:
        QMessageBox.warning(parent, 'Группа', str(e))
        return None
    return mg.add_items(db, gid, material_ids)
