"""Вкладка «Объёмы» карточки договора: что и сколько потрачено на объект строительства (без цен), и смета из этих объёмов."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QMessageBox, QComboBox
from PyQt6.QtCore import Qt

from .database import db
from . import volumes_domain as vd


class VolumesTab(QWidget):
    """dialog — карточка договора: contract_id, ensure_saved(); after_estimate() — обновить блок сметы карточки."""

    def __init__(self, owner, dialog, after_estimate=None, parent=None):
        super().__init__(parent)
        self.owner, self.dialog, self.after_estimate = owner, dialog, after_estimate
        self._loading = False
        layout = QVBoxLayout(self)
        hint = QLabel('Объёмы — количество работ и материалов, потраченных на объект; цены не указываются. Порядок: договор → работа → объёмы → «Сформировать смету» '
                      '(смета создаётся по ценам справочника и привязывается к договору). Если смета составлена заранее и привязана к договору — «Внести объёмы из сметы».')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Вид', 'Наименование', 'Ед.', 'Количество', 'Примечание'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 100), (2, 70), (3, 110), (4, 220)):
            self.table.setColumnWidth(col, width)
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

    def reload(self):
        self._loading = True
        self.table.setRowCount(0)
        if self.cid():
            for r in vd.items(db, self.owner, self.cid()):
                self.add_row(r['kind'], r['name'], r['unit'], r['quantity'], r['note'], r['catalog_id'])
            eid = vd.estimate_id(db, self.owner, self.cid())
            self.status.setText('Смета привязана' if eid else 'Смета не привязана')
        else:
            self.status.setText('Договор ещё не сохранён')
        self._loading = False

    def add_row(self, kind='Материал', name='', unit='', qty=1, note='', catalog_id=None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        box = QComboBox()
        box.addItems(vd.KINDS)
        box.setCurrentText(kind)
        self.table.setCellWidget(r, 0, box)
        first = QTableWidgetItem(name)
        first.setData(Qt.ItemDataRole.UserRole, catalog_id)
        self.table.setItem(r, 1, first)
        self.table.setItem(r, 2, QTableWidgetItem(unit))
        q = QTableWidgetItem(('%g' % float(qty)) if qty not in (None, '') else '')
        q.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(r, 3, q)
        self.table.setItem(r, 4, QTableWidgetItem(note))
        self.table.setCurrentCell(r, 3)

    def rows(self):
        out = []
        for r in range(self.table.rowCount()):
            cell = lambda c: (self.table.item(r, c).text() if self.table.item(r, c) else '').strip()
            out.append(dict(kind=self.table.cellWidget(r, 0).currentText(), name=cell(1), unit=cell(2), quantity=cell(3).replace(',', '.') or 0,
                            note=cell(4), catalog_id=self.table.item(r, 1).data(Qt.ItemDataRole.UserRole)))
        return out

    def add_catalog(self, kind):
        from .dialogs_common import WorkSelectionDialog, MaterialSelectionDialog
        dlg = (WorkSelectionDialog if kind == 'Работа' else MaterialSelectionDialog)(self)
        if dlg.exec() and dlg.selected:
            self.add_row(kind, dlg.selected['name'], dlg.selected['unit'], 1, '', dlg.selected.get('id'))

    def add_custom(self):
        self.add_row('Материал', '', '', 1)
        self.table.editItem(self.table.item(self.table.rowCount() - 1, 1))

    def remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
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
