"""Справочник ГСН: позиции (трубопроводы, арматура, материалы) и собственный реестр сертификатов ГСН.

Полностью независим от справочника ГСВ: свои таблицы (gsn_*), свои сертификаты, никаких общих записей и предзаполненных правил.
Всё, что нужно, добавляется вручную. Состав полей справочника уточняется — при необходимости будет расширен."""
import os
from datetime import date

from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QTextEdit, QComboBox, QPushButton, QCheckBox, QTabWidget,
                              QTableWidget, QTableWidgetItem, QAbstractItemView, QListWidget, QListWidgetItem, QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt

from .database import db
from .agenda_domain import norm_date


# --- данные ----------------------------------------------------------------------------------

def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS gsn_certificates(id INTEGER PRIMARY KEY, name TEXT NOT NULL, number TEXT DEFAULT '', issued_by TEXT DEFAULT '',
        valid_from TEXT DEFAULT '', valid_to TEXT DEFAULT '', file_path TEXT DEFAULT '', note TEXT DEFAULT '', always INTEGER NOT NULL DEFAULT 0)""")
    db.execute("""CREATE TABLE IF NOT EXISTS gsn_items(id INTEGER PRIMARY KEY, category TEXT DEFAULT '', name TEXT NOT NULL, unit TEXT DEFAULT '',
        note TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1)""")
    db.execute("""CREATE TABLE IF NOT EXISTS gsn_item_certs(item_id INTEGER NOT NULL REFERENCES gsn_items(id) ON DELETE CASCADE,
        cert_id INTEGER NOT NULL REFERENCES gsn_certificates(id) ON DELETE CASCADE, PRIMARY KEY(item_id,cert_id))""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_gsn_item_certs_cert ON gsn_item_certs(cert_id)')
    # версия 3.0 создала заготовки по образцу ГСВ — они убраны; записи, если их успели ввести, переносятся в «Позиции»
    if db.fetchone("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gsn_pipelines'"):
        for name, unit, notes, active in db.fetchall('SELECT name,unit,notes,active FROM gsn_pipelines'):
            if not db.fetchone('SELECT 1 FROM gsn_items WHERE name=? AND category=?', (name, 'Трубопроводы')):
                db.execute('INSERT INTO gsn_items(category,name,unit,note,active) VALUES(?,?,?,?,?)', ('Трубопроводы', name, unit or '', notes or '', active))
        db.execute('DROP TABLE gsn_pipelines')
    for table in ('gsn_cert_rules', 'gsn_default_certs'):
        db.execute(f'DROP TABLE IF EXISTS {table}')


def categories(db):
    return [r[0] for r in db.fetchall("SELECT DISTINCT category FROM gsn_items WHERE coalesce(category,'')<>'' ORDER BY category")]


def save_cert(db, values, cert_id=None):
    name = str(values.get('name') or '').strip()
    if not name:
        raise ValueError('Введите название сертификата')
    for key in ('valid_from', 'valid_to'):
        if values.get(key):
            date.fromisoformat(values[key])
    if values.get('valid_from') and values.get('valid_to') and values['valid_from'] > values['valid_to']:
        raise ValueError('Срок действия «с» позже срока «по»')
    data = [name, str(values.get('number') or '').strip(), str(values.get('issued_by') or '').strip(), values.get('valid_from') or '', values.get('valid_to') or '',
            str(values.get('file_path') or '').strip(), str(values.get('note') or '').strip(), int(bool(values.get('always')))]
    if cert_id:
        db.execute('UPDATE gsn_certificates SET name=?,number=?,issued_by=?,valid_from=?,valid_to=?,file_path=?,note=?,always=? WHERE id=?', (*data, cert_id))
        return cert_id
    return db.execute('INSERT INTO gsn_certificates(name,number,issued_by,valid_from,valid_to,file_path,note,always) VALUES(?,?,?,?,?,?,?,?)', data).lastrowid


def save_item(db, values, item_id=None, cert_ids=()):
    name = str(values.get('name') or '').strip()
    if not name:
        raise ValueError('Введите наименование')
    data = [str(values.get('category') or '').strip(), name, str(values.get('unit') or '').strip(), str(values.get('note') or '').strip(), int(bool(values.get('active', True)))]
    with db.transaction():
        if item_id:
            db.execute('UPDATE gsn_items SET category=?,name=?,unit=?,note=?,active=? WHERE id=?', (*data, item_id))
        else:
            item_id = db.execute('INSERT INTO gsn_items(category,name,unit,note,active) VALUES(?,?,?,?,?)', data).lastrowid
        db.execute('DELETE FROM gsn_item_certs WHERE item_id=?', (item_id,))
        for cid in set(cert_ids):
            if not db.fetchone('SELECT 1 FROM gsn_certificates WHERE id=?', (cid,)):
                raise ValueError('Сертификат не найден')
            db.execute('INSERT INTO gsn_item_certs(item_id,cert_id) VALUES(?,?)', (item_id, cid))
    return item_id


def cert_state(valid_to, today=None):
    """('none'|'ok'|'soon'|'expired', текст) по сроку действия."""
    day = norm_date(valid_to)
    if not day:
        return 'none', ''
    left = (date.fromisoformat(day) - (today or date.today())).days
    if left < 0:
        return 'expired', f'просрочен на {-left} дн.'
    return ('soon', f'осталось {left} дн.') if left <= 30 else ('ok', f'до {date.fromisoformat(day).strftime("%d.%m.%Y")}')


def required_certificates(db, item_ids=()):
    """Сертификаты объекта ГСН: привязанные к выбранным позициям и отмеченные «всегда». [{'id','name','number','path','reason'}], без повторов."""
    found, seen = [], set()

    def add(row, reason):
        if row[0] not in seen:
            seen.add(row[0])
            found.append(dict(id=row[0], name=row[1], number=row[2] or '', path=row[3] or '', reason=reason))
    for item_id in item_ids:
        item = db.fetchone('SELECT name FROM gsn_items WHERE id=?', (item_id,))
        for row in db.fetchall('SELECT c.id,c.name,c.number,c.file_path FROM gsn_item_certs l JOIN gsn_certificates c ON c.id=l.cert_id WHERE l.item_id=? ORDER BY c.id', (item_id,)):
            add(row, f'позиция «{item[0]}»' if item else 'позиция')
    for row in db.fetchall('SELECT id,name,number,file_path FROM gsn_certificates WHERE always=1 ORDER BY id'):
        add(row, 'всегда')
    return found


# --- интерфейс -------------------------------------------------------------------------------

def _cell(text, data=None):
    it = QTableWidgetItem('' if text is None else str(text))
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
    return it


def _table(headers, widths=()):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.horizontalHeader().setStretchLastSection(True)
    for i, w in enumerate(widths):
        t.setColumnWidth(i, w)
    return t


def _selected(table):
    r = table.currentRow()
    return table.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 and table.item(r, 0) else None


class GsnCertDialog(QDialog):
    def __init__(self, cert_id=None, parent=None):
        super().__init__(parent)
        from .domain_widgets import OptionalDate
        self.cert_id = cert_id
        self.setWindowTitle('Сертификат ГСН')
        self.resize(560, 460)
        form = QFormLayout(self)
        self.name, self.number, self.issued_by, self.path = QLineEdit(), QLineEdit(), QLineEdit(), QLineEdit()
        self.valid_from, self.valid_to = OptionalDate(), OptionalDate()
        self.note = QTextEdit()
        self.note.setFixedHeight(70)
        self.always = QCheckBox('Подтягивать в каждый объект ГСН')
        pick = QPushButton('Выбрать файл…')
        pick.clicked.connect(self.pick_file)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(pick)
        for label, w in (('Название *', self.name), ('Номер', self.number), ('Кем выдан', self.issued_by), ('Действует с', self.valid_from), ('Действует по', self.valid_to)):
            form.addRow(label, w)
        form.addRow('Файл', row)
        form.addRow('Примечание', self.note)
        form.addRow('', self.always)
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        form.addRow(save)
        if cert_id:
            r = db.fetchone('SELECT name,number,issued_by,valid_from,valid_to,file_path,note,always FROM gsn_certificates WHERE id=?', (cert_id,))
            if r:
                self.name.setText(r[0]); self.number.setText(r[1] or ''); self.issued_by.setText(r[2] or '')
                self.valid_from.set_value(r[3]); self.valid_to.set_value(r[4]); self.path.setText(r[5] or '')
                self.note.setPlainText(r[6] or ''); self.always.setChecked(bool(r[7]))

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Файл сертификата', '', 'Документы (*.pdf *.jpg *.jpeg *.png *.docx *.xlsx);;Все файлы (*)')
        if path:
            self.path.setText(path)

    def save(self):
        try:
            self.cert_id = save_cert(db, dict(name=self.name.text(), number=self.number.text(), issued_by=self.issued_by.text(), valid_from=self.valid_from.value(),
                                              valid_to=self.valid_to.value(), file_path=self.path.text(), note=self.note.toPlainText(), always=self.always.isChecked()), self.cert_id)
        except ValueError as e:
            QMessageBox.warning(self, 'Сертификат', str(e))
            return
        self.accept()


class GsnItemDialog(QDialog):
    def __init__(self, item_id=None, parent=None):
        super().__init__(parent)
        self.item_id = item_id
        self.setWindowTitle('Позиция справочника ГСН')
        self.resize(600, 560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.addItems(categories(db))
        self.category.setEditText('')
        self.name, self.unit, self.note = QLineEdit(), QLineEdit(), QLineEdit()
        self.active = QCheckBox('Доступна для выбора')
        self.active.setChecked(True)
        for label, w in (('Раздел справочника', self.category), ('Наименование *', self.name), ('Единица', self.unit), ('Примечание', self.note)):
            form.addRow(label, w)
        form.addRow('', self.active)
        layout.addWidget(QLabel('Сертификаты этой позиции (отметьте нужные):'))
        self.certs = QListWidget()
        layout.addWidget(self.certs, 1)
        new = QPushButton('＋ Новый сертификат ГСН…')
        new.clicked.connect(self.new_cert)
        layout.addWidget(new)
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        layout.addWidget(save)
        linked = {r[0] for r in db.fetchall('SELECT cert_id FROM gsn_item_certs WHERE item_id=?', (item_id,))} if item_id else set()
        self.fill_certs(linked)
        if item_id:
            r = db.fetchone('SELECT category,name,unit,note,active FROM gsn_items WHERE id=?', (item_id,))
            if r:
                self.category.setEditText(r[0] or ''); self.name.setText(r[1]); self.unit.setText(r[2] or ''); self.note.setText(r[3] or ''); self.active.setChecked(bool(r[4]))

    def fill_certs(self, checked):
        self.certs.clear()
        for cid, name, number in db.fetchall('SELECT id,name,number FROM gsn_certificates ORDER BY name'):
            it = QListWidgetItem(f'{name}' + (f' · № {number}' if number else ''))
            it.setData(Qt.ItemDataRole.UserRole, cid)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if cid in checked else Qt.CheckState.Unchecked)
            self.certs.addItem(it)

    def checked(self):
        return {self.certs.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.certs.count()) if self.certs.item(i).checkState() == Qt.CheckState.Checked}

    def new_cert(self):
        keep = self.checked()
        d = GsnCertDialog(parent=self)
        if d.exec():
            self.fill_certs(keep | {d.cert_id})

    def save(self):
        try:
            self.item_id = save_item(db, dict(category=self.category.currentText(), name=self.name.text(), unit=self.unit.text(), note=self.note.text(),
                                              active=self.active.isChecked()), self.item_id, self.checked())
        except ValueError as e:
            QMessageBox.warning(self, 'Позиция', str(e))
            return
        self.accept()


class ItemsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск по справочнику ГСН…')
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self.load_data)
        bar.addWidget(self.category)
        for text, fn, kind in (('Добавить', self.add, 'primary'), ('Изменить', self.edit, ''), ('Удалить', self.delete, 'danger')):
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        layout.addLayout(bar)
        self.table = _table(['Наименование', 'Раздел', 'Ед.', 'Сертификатов', 'Доступна', 'Примечание'], (320, 170, 70, 110, 90))
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table, 1)
        self.load_data()

    def reload_categories(self):
        keep = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem('Все разделы', None)
        for c in categories(db):
            self.category.addItem(c, c)
        self.category.setCurrentIndex(max(0, self.category.findData(keep)))
        self.category.blockSignals(False)

    def load_data(self, *_):
        if self.category.count() == 0:
            self.reload_categories()
        q = '%' + self.search.text().strip().casefold() + '%'
        cat = self.category.currentData()
        rows = db.fetchall("""SELECT i.id,i.name,i.category,i.unit,(SELECT count(*) FROM gsn_item_certs WHERE item_id=i.id),i.active,i.note FROM gsn_items i
            WHERE LOWER(i.name||' '||coalesce(i.category,'')||' '||coalesce(i.note,'')) LIKE ? AND (? IS NULL OR i.category=?) ORDER BY i.category,i.name""", (q, cat, cat))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            vals = [row[1], row[2], row[3], row[4], 'да' if row[5] else 'архив', row[6]]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, _cell(v, row[0] if c == 0 else None))

    def add(self):
        if GsnItemDialog(parent=self).exec():
            self.reload_categories()
            self.load_data()

    def edit(self, *_):
        item_id = _selected(self.table)
        if item_id and GsnItemDialog(item_id, self).exec():
            self.reload_categories()
            self.load_data()

    def delete(self):
        item_id = _selected(self.table)
        if item_id and QMessageBox.question(self, 'Удаление', 'Удалить позицию справочника ГСН?') == QMessageBox.StandardButton.Yes:
            db.execute('DELETE FROM gsn_items WHERE id=?', (item_id,))
            self.reload_categories()
            self.load_data()


class CertsTab(QWidget):
    COLORS = {'expired': '#DC2626', 'soon': '#D97706', 'ok': '#16A34A', 'none': '#65758b'}

    def __init__(self):
        super().__init__()
        from PyQt6.QtGui import QColor
        self._color = QColor
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Название, номер, кем выдан…')
        self.search.textChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        for text, fn, kind in (('Добавить', self.add, 'primary'), ('Изменить', self.edit, ''), ('Открыть файл', self.open_file, ''), ('Удалить', self.delete, 'danger')):
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        layout.addLayout(bar)
        self.table = _table(['Название', 'Номер', 'Кем выдан', 'Срок действия', 'Состояние', 'Всегда', 'Файл'], (280, 120, 170, 110, 160, 70))
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table, 1)
        self.load_data()

    def load_data(self, *_):
        q = '%' + self.search.text().strip().casefold() + '%'
        rows = db.fetchall("""SELECT id,name,number,issued_by,valid_to,always,file_path FROM gsn_certificates
            WHERE LOWER(name||' '||coalesce(number,'')||' '||coalesce(issued_by,'')) LIKE ? ORDER BY name""", (q,))
        self.table.setRowCount(len(rows))
        for r, (cid, name, number, issued, valid_to, always, path) in enumerate(rows):
            state, text = cert_state(valid_to)
            day = norm_date(valid_to)
            vals = [name, number, issued, date.fromisoformat(day).strftime('%d.%m.%Y') if day else '', text, 'да' if always else '', path]
            for c, v in enumerate(vals):
                it = _cell(v, cid if c == 0 else None)
                if c == 4:
                    it.setForeground(self._color(self.COLORS[state]))
                self.table.setItem(r, c, it)

    def add(self):
        if GsnCertDialog(parent=self).exec():
            self.load_data()

    def edit(self, *_):
        cid = _selected(self.table)
        if cid and GsnCertDialog(cid, self).exec():
            self.load_data()

    def open_file(self):
        cid = _selected(self.table)
        row = db.fetchone('SELECT file_path FROM gsn_certificates WHERE id=?', (cid,)) if cid else None
        if row and row[0] and os.path.isfile(row[0]):
            from .platform_utils import open_local
            open_local(row[0])
        elif cid:
            QMessageBox.warning(self, 'Сертификат', 'Файл не указан или не найден на диске.')

    def delete(self):
        cid = _selected(self.table)
        if cid and QMessageBox.question(self, 'Удаление', 'Удалить сертификат? Он будет убран из всех позиций справочника ГСН.') == QMessageBox.StandardButton.Yes:
            db.execute('DELETE FROM gsn_certificates WHERE id=?', (cid,))
            self.load_data()


class GsnCatalogView(QWidget):
    """Справочник ГСН: вкладки «Позиции» и «Сертификаты». Пустой — всё добавляется вручную."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Справочник ГСН независим от справочника ГСВ: свои позиции и свои сертификаты, ничего не подставляется автоматически.'))
        self.tabs = QTabWidget()
        self.items = ItemsTab()
        self.certs = CertsTab()
        self.tabs.addTab(self.items, 'Позиции')
        self.tabs.addTab(self.certs, 'Сертификаты')
        self.tabs.currentChanged.connect(self.on_tab)
        layout.addWidget(self.tabs)

    def on_tab(self, index):
        (self.items if index == 0 else self.certs).load_data()

    def load_data(self):
        self.items.reload_categories()
        self.on_tab(self.tabs.currentIndex())
