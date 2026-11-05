"""Вкладка «Объёмы» карточки договора: что и сколько потрачено на объект строительства (без цен), и смета из этих объёмов."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QMessageBox, QComboBox
from PyQt6.QtCore import Qt

from .database import db
from . import volumes_domain as vd


COL_ACT, COL_KIND, COL_NAME, COL_UNIT, COL_QTY, COL_NOTE = range(6)
HEADER = 'volumes-header'


class VolumesTab(QWidget):
    """dialog — карточка договора: contract_id, ensure_saved(); after_estimate() — обновить блок сметы карточки.
    Для договоров с актами (СМР) объёмы делятся по актам выполненных работ: у каждой строки есть акт, таблица сгруппирована по актам, сверху — фильтр по акту."""

    def __init__(self, owner, dialog, after_estimate=None, parent=None):
        super().__init__(parent)
        self.owner, self.dialog, self.after_estimate = owner, dialog, after_estimate
        self.by_acts = vd.has_acts(owner)
        self._loading = False
        layout = QVBoxLayout(self)
        text = ('Объёмы — количество работ и материалов, потраченных на объект; цены не указываются. Порядок: договор → работа → объёмы → смета '
                '(смета создаётся по ценам справочника и привязывается к договору). Если смета составлена заранее и привязана к договору, кнопка «Внести объёмы из сметы» заполняет объёмы по её позициям.')
        if self.by_acts:
            text = ('Объёмы делятся по актам выполненных работ: у каждой строки выбирается акт, внизу таблицы строки группируются по актам. Здесь видны все объёмы договора; '
                    'фильтр «Показать» оставляет один акт. Смета договора формируется по сумме объёмов всех актов. ') + text
        hint = QLabel(text)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.filter = QComboBox()
        self.filter.currentIndexChanged.connect(self.apply_filter)
        top = QHBoxLayout()
        self.filter_label = QLabel('Показать:')
        top.addWidget(self.filter_label)
        top.addWidget(self.filter, 1)
        layout.addLayout(top)
        self.filter.setVisible(self.by_acts)
        self.filter_label.setVisible(self.by_acts)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Акт', 'Вид', 'Наименование', 'Ед.', 'Количество', 'Примечание'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col, width in ((COL_ACT, 190), (COL_KIND, 100), (COL_UNIT, 70), (COL_QTY, 110), (COL_NOTE, 200)):
            self.table.setColumnWidth(col, width)
        self.table.setColumnHidden(COL_ACT, not self.by_acts)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for text, fn in (('＋ Работа из справочника', lambda: self.add_catalog('Работа')), ('＋ Материал из справочника', lambda: self.add_catalog('Материал')),
                         ('＋ Произвольная строка', self.add_custom), ('Удалить строку', self.remove_row)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        bar = QHBoxLayout()
        self.save_btn = QPushButton('Сохранить объёмы')
        self.save_btn.clicked.connect(self.save)
        self.make_btn = QPushButton('Сформировать смету')
        self.make_btn.setProperty('type', 'primary')
        self.make_btn.clicked.connect(self.make_estimate)
        self.pull_btn = QPushButton('Внести объёмы из сметы')
        self.pull_btn.clicked.connect(self.pull_from_estimate)
        for b in (self.save_btn, self.make_btn, self.pull_btn):
            bar.addWidget(b)
        self.status = QLabel('')
        bar.addWidget(self.status, 1)
        layout.addLayout(bar)

    # --- таблица
    def showEvent(self, event):
        super().showEvent(event)
        self.reload()

    def cid(self):
        return getattr(self.dialog, 'contract_id', None)

    def act_choices(self):
        """[(id|None, подпись)] — акты договора и «без акта»."""
        return [(None, '— без акта —')] + (vd.acts(db, self.owner, self.cid()) if self.cid() else [])

    def reload(self):
        self._loading = True
        keep = self.filter.currentData() if self.by_acts and self.filter.count() else '__all__'
        self.table.setRowCount(0)
        if self.by_acts:
            self.filter.blockSignals(True)
            self.filter.clear()
            self.filter.addItem('Все акты (по группам)', '__all__')
            for aid, label in vd.acts(db, self.owner, self.cid()) if self.cid() else []:
                self.filter.addItem(label, aid)
            self.filter.addItem('Без акта', None)
            idx = self.filter.findData(keep)
            self.filter.setCurrentIndex(idx if idx >= 0 else 0)
            self.filter.blockSignals(False)
        if self.cid():
            groups = vd.grouped(db, self.owner, self.cid())
            for act_id, label, rows in groups:
                if self.by_acts:
                    self.add_header(act_id, label, len(rows))
                for r in rows:
                    self.add_row(r['kind'], r['name'], r['unit'], r['quantity'], r['note'], r['catalog_id'], r['act_id'])
            eid = vd.estimate_id(db, self.owner, self.cid())
            self.status.setText('Смета привязана' if eid else 'Смета не привязана')
        else:
            self.status.setText('Договор ещё не сохранён')
        self._loading = False
        self.apply_filter()

    def add_header(self, act_id, label, count, row=None):
        r = self.table.rowCount() if row is None else row
        self.table.insertRow(r)
        item = QTableWidgetItem(f'{label}  ·  позиций: {count}' if count else f'{label}  ·  объёмов пока нет')
        item.setData(Qt.ItemDataRole.UserRole, HEADER)
        item.setData(Qt.ItemDataRole.UserRole + 1, act_id)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        item.setBackground(self.palette().alternateBase())
        self.table.setItem(r, 0, item)
        self.table.setSpan(r, 0, 1, 6)
        return r

    def is_header(self, r):
        item = self.table.item(r, 0)
        return bool(item and item.data(Qt.ItemDataRole.UserRole) == HEADER)

    def row_act(self, r):
        """Акт строки: для заголовка — его акт, для строки объёмов — выбранный в ячейке."""
        if self.is_header(r):
            return self.table.item(r, 0).data(Qt.ItemDataRole.UserRole + 1)
        box = self.table.cellWidget(r, COL_ACT)
        return box.currentData() if box else None

    def apply_filter(self, *_):
        if self._loading and self.table.rowCount() == 0:
            return
        want = self.filter.currentData() if self.by_acts and self.filter.count() else '__all__'
        for r in range(self.table.rowCount()):
            self.table.setRowHidden(r, want != '__all__' and self.row_act(r) != want)

    def add_row(self, kind='Материал', name='', unit='', qty=None, note='', catalog_id=None, act_id=None, at=None):
        r = self.table.rowCount() if at is None else at
        self.table.insertRow(r)
        act_box = QComboBox()
        for aid, label in self.act_choices():
            act_box.addItem(label, aid)
        act_box.setCurrentIndex(max(0, act_box.findData(act_id)))
        self.table.setCellWidget(r, COL_ACT, act_box)
        box = QComboBox()
        box.addItems(vd.KINDS)
        box.setCurrentText(kind)
        self.table.setCellWidget(r, COL_KIND, box)
        first = QTableWidgetItem(name)
        first.setData(Qt.ItemDataRole.UserRole, catalog_id)
        self.table.setItem(r, COL_NAME, first)
        self.table.setItem(r, COL_UNIT, QTableWidgetItem(unit))
        q = QTableWidgetItem(('%g' % float(qty)) if qty not in (None, '') else '')
        q.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(r, COL_QTY, q)
        self.table.setItem(r, COL_NOTE, QTableWidgetItem(note))
        self.table.setCurrentCell(r, COL_QTY)
        return r

    def rows(self):
        out = []
        for r in range(self.table.rowCount()):
            if self.is_header(r):
                continue
            cell = lambda c: (self.table.item(r, c).text() if self.table.item(r, c) else '').strip()
            out.append(dict(kind=self.table.cellWidget(r, COL_KIND).currentText(), name=cell(COL_NAME), unit=cell(COL_UNIT), quantity=cell(COL_QTY).replace(',', '.') or 0,
                            note=cell(COL_NOTE), catalog_id=self.table.item(r, COL_NAME).data(Qt.ItemDataRole.UserRole), act_id=self.row_act(r) if self.by_acts else None))
        return out

    def target_act(self):
        """В какой акт попадает новая строка: выбранный в фильтре, иначе акт текущей строки, иначе «без акта»."""
        if not self.by_acts:
            return None
        want = self.filter.currentData()
        if want != '__all__':
            return want
        r = self.table.currentRow()
        return self.row_act(r) if r >= 0 else None

    def insert_position(self, act_id):
        """Строка таблицы, куда вставить новую строку акта: после последней строки этого акта; нет группы — создаётся заголовок в конце."""
        last = None
        for r in range(self.table.rowCount()):
            if self.row_act(r) == act_id:
                last = r
        if last is None:
            label = 'Без акта' if act_id is None else dict(vd.acts(db, self.owner, self.cid())).get(act_id, 'Акт')
            header = self.add_header(act_id, label, 0)
            return header + 1
        return last + 1

    def new_row(self, kind, name, unit, qty, catalog_id=None):
        act = self.target_act()
        at = self.insert_position(act) if self.by_acts else None
        return self.add_row(kind, name, unit, qty, '', catalog_id, act, at)

    def add_catalog(self, kind):
        from .dialogs_common import WorkSelectionDialog, MaterialSelectionDialog
        dlg = (WorkSelectionDialog if kind == 'Работа' else MaterialSelectionDialog)(self)
        if dlg.exec() and dlg.selected:
            self.new_row(kind, dlg.selected['name'], dlg.selected['unit'], None, dlg.selected.get('id'))      # количество не подставляется — его вводят сами

    def add_custom(self):
        r = self.new_row('Материал', '', '', None)
        self.table.editItem(self.table.item(r, COL_NAME))

    def remove_row(self):
        r = self.table.currentRow()
        if r >= 0 and not self.is_header(r):
            self.table.removeRow(r)

    # --- действия
    def save(self):
        if not self.dialog.ensure_saved():
            return False
        try:
            n = vd.save_items(db, self.owner, self.cid(), self.rows())
        except Exception as e:
            QMessageBox.warning(self, 'Объёмы', str(e))
            return False
        self.status.setText(f'Сохранено строк: {n}')
        self.reload()                                    # строки перегруппируются по актам
        return True

    def make_estimate(self):
        if not self.save():
            return
        replace = False
        eid = vd.estimate_id(db, self.owner, self.cid())
        if eid and db.fetchone("SELECT 1 FROM estimate_items WHERE estimate_id=? AND item_type<>'Раздел'", (eid,)):
            if QMessageBox.question(self, 'Сформировать смету', 'В смете договора уже есть позиции. Заменить их объёмами?') != QMessageBox.StandardButton.Yes:
                return
            replace = True
        try:
            eid, unpriced = vd.build_estimate(db, self.owner, self.cid(), replace)
        except Exception as e:
            QMessageBox.warning(self, 'Смета', str(e))
            return
        text = 'Смета сформирована и привязана к договору.'
        if unpriced:
            text += '\n\nНет цены в справочнике (откройте смету и укажите):\n' + '\n'.join('• ' + n for n in unpriced[:12]) + ('\n…' if len(unpriced) > 12 else '')
        QMessageBox.information(self, 'Смета', text)
        self.reload()
        if self.after_estimate:
            self.after_estimate()

    def pull_from_estimate(self):
        if not self.dialog.ensure_saved():
            return
        replace = False
        if vd.items(db, self.owner, self.cid()):
            self.save()
            if QMessageBox.question(self, 'Объёмы', 'Объёмы уже внесены. Заменить их данными сметы?') != QMessageBox.StandardButton.Yes:
                return
            replace = True
        try:
            n = vd.fill_from_estimate(db, self.owner, self.cid(), replace)
        except Exception as e:
            QMessageBox.warning(self, 'Объёмы', str(e))
            return
        self.reload()
        self.status.setText(f'Внесено строк из сметы: {n}')
