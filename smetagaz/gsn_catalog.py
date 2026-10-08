"""Справочник ГСН: трубопроводы газоснабжения наружного (ГСН), их сертификаты, зависимые сертификаты и сертификаты по умолчанию.

Устроен так же, как справочник ГСВ, но данные у него свои (таблицы gsn_*) и с ГСВ не пересекаются. Общий только справочник сертификатов
(модуль «Исполнительная документация»)."""
from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QTabWidget, QMessageBox, QTableWidgetItem)
from PyQt6.QtCore import Qt

from .database import db
from .gsv_catalog import GsvCatalogView, PipelineDialog, CertificatePicker

RULE_TYPES = {
    'pipeline': 'Если в объекте есть трубопровод',
    'pipeline_text': 'Если в названии трубопровода есть текст (диаметр, материал, производитель)',
    'object_text': 'Если в объекте есть материал или оборудование с текстом в названии',
}


def migrate(db):
    db.execute("""CREATE TABLE IF NOT EXISTS gsn_pipelines(id INTEGER PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'м',
        certificate_id INTEGER REFERENCES certificates(id) ON DELETE SET NULL, notes TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1)""")
    db.execute("""CREATE TABLE IF NOT EXISTS gsn_cert_rules(id INTEGER PRIMARY KEY, cond_type TEXT NOT NULL, cond_value TEXT NOT NULL,
        certificate_id INTEGER NOT NULL REFERENCES certificates(id) ON DELETE CASCADE)""")
    db.execute('CREATE TABLE IF NOT EXISTS gsn_default_certs(certificate_id INTEGER PRIMARY KEY REFERENCES certificates(id) ON DELETE CASCADE)')


def cert_rules(db):
    return db.fetchall("""SELECT r.id,r.cond_type,r.cond_value,r.certificate_id,coalesce(c.name,''),coalesce(c.cert_number,'') FROM gsn_cert_rules r
        LEFT JOIN certificates c ON c.id=r.certificate_id ORDER BY r.id""")


def add_cert_rule(db, cond_type, cond_value, cert_id):
    if cond_type not in RULE_TYPES or not str(cond_value).strip() or not cert_id:
        raise ValueError('Укажите условие и сертификат')
    if db.fetchone('SELECT 1 FROM gsn_cert_rules WHERE cond_type=? AND cond_value=? AND certificate_id=?', (cond_type, str(cond_value).strip(), cert_id)):
        raise ValueError('Такое правило уже есть')
    return db.execute('INSERT INTO gsn_cert_rules(cond_type,cond_value,certificate_id) VALUES(?,?,?)', (cond_type, str(cond_value).strip(), cert_id)).lastrowid


def default_certs(db):
    return [r[0] for r in db.fetchall('SELECT certificate_id FROM gsn_default_certs ORDER BY rowid')]


def value_label(db, cond_type, value):
    if cond_type == 'pipeline' and str(value).isdigit():
        row = db.fetchone('SELECT name FROM gsn_pipelines WHERE id=?', (int(value),))
        return row[0] if row else value
    return value


def required_certificates(db, pipeline_ids=(), texts=()):
    """Сертификаты, которые нужны объекту ГСН: по правилам (зависимые) и по умолчанию. [{'id','name','number','path','reason'}], без повторов."""
    pipeline_ids = {int(p) for p in pipeline_ids}
    names = [r[0].casefold() for r in db.fetchall(f"SELECT name FROM gsn_pipelines WHERE id IN ({','.join('?' for _ in pipeline_ids) or 'NULL'})", tuple(pipeline_ids))]
    haystack = [str(t).casefold() for t in texts] + names
    found, seen = [], set()

    def add(cert_id, reason):
        row = db.fetchone("SELECT id,name,coalesce(cert_number,''),coalesce(file_path,'') FROM certificates WHERE id=?", (cert_id,))
        if row and cert_id not in seen:
            seen.add(cert_id)
            found.append(dict(id=row[0], name=row[1], number=row[2], path=row[3], reason=reason))
    for pid in sorted(pipeline_ids):
        row = db.fetchone('SELECT certificate_id,name FROM gsn_pipelines WHERE id=?', (pid,))
        if row and row[0]:
            add(row[0], f'трубопровод «{row[1]}»')
    for _rid, cond, value, cert_id, _n, _num in cert_rules(db):
        value_cf = str(value).casefold()
        hit = (cond == 'pipeline' and value.isdigit() and int(value) in pipeline_ids) or \
              (cond == 'pipeline_text' and any(value_cf in n for n in names)) or \
              (cond == 'object_text' and any(value_cf in t for t in haystack))
        if hit:
            add(cert_id, f'{RULE_TYPES[cond].split(" (")[0]} «{value_label(db, cond, value)}»')
    for cert_id in default_certs(db):
        add(cert_id, 'всегда')
    return found


class GsnPipelineDialog(PipelineDialog):
    TABLE = 'gsn_pipelines'

    def __init__(self, pipeline_id=None, parent=None):
        super().__init__(pipeline_id, parent)
        self.setWindowTitle('Трубопровод ГСН')


class GsnRulesDialog(QDialog):
    """Зависимые сертификаты и сертификаты по умолчанию для объектов ГСН."""
    def __init__(self, parent=None):
        super().__init__(parent)
        from .gsvm_tabs import make_table
        self.setWindowTitle('ГСН · зависимые сертификаты и сертификаты по умолчанию')
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Настройки действуют только для объектов ГСН и не влияют на ГСВ.'))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel('<b>Зависимые сертификаты</b>: «если в объекте … — добавить сертификат …»'))
        self.rules = make_table(['Условие', 'Значение', 'Сертификат', 'Номер'], (330, 220, 260))
        pl.addWidget(self.rules, 1)
        bar = QHBoxLayout()
        self.kind = QComboBox()
        for k, label in RULE_TYPES.items():
            self.kind.addItem(label, k)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.value = QComboBox()
        self.value.setEditable(True)
        self.value.setMinimumWidth(240)
        bar.addWidget(self.kind, 2)
        bar.addWidget(self.value, 2)
        add = QPushButton('Выбрать сертификат и добавить…')
        add.clicked.connect(self.add_rule)
        remove = QPushButton('Удалить правило')
        remove.clicked.connect(self.remove_rule)
        bar.addWidget(add)
        bar.addWidget(remove)
        pl.addLayout(bar)
        tabs.addTab(page, 'Зависимые')
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel('<b>Сертификаты по умолчанию</b> — подтягиваются во все объекты ГСН.'))
        self.defaults = make_table(['Сертификат', 'Номер', 'Файл'], (420, 160))
        pl.addWidget(self.defaults, 1)
        bar = QHBoxLayout()
        add = QPushButton('Добавить из справочника…')
        add.clicked.connect(self.add_default)
        remove = QPushButton('Убрать')
        remove.clicked.connect(self.remove_default)
        bar.addWidget(add)
        bar.addWidget(remove)
        bar.addStretch()
        pl.addLayout(bar)
        tabs.addTab(page, 'По умолчанию')
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.kind_changed()
        self.load()

    def kind_changed(self, *_):
        self.value.clear()
        if self.kind.currentData() == 'pipeline':
            for pid, name in db.fetchall('SELECT id,name FROM gsn_pipelines ORDER BY name'):
                self.value.addItem(name, str(pid))
            self.value.setEditable(False)
            return
        self.value.setEditable(True)
        self.value.setEditText('')
        self.value.lineEdit().setPlaceholderText('Например: 63, ПЭ100, кран, задвижка')

    def _item(self, text, data):
        item = QTableWidgetItem(str(text))
        item.setData(Qt.ItemDataRole.UserRole, data)
        return item

    def load(self):
        rows = cert_rules(db)
        self.rules.setRowCount(len(rows))
        for r, (rid, cond, value, _cid, name, number) in enumerate(rows):
            for c, v in enumerate((RULE_TYPES[cond], value_label(db, cond, value), name, number)):
                self.rules.setItem(r, c, self._item(v, rid))
        ids = default_certs(db)
        self.defaults.setRowCount(len(ids))
        for r, cid in enumerate(ids):
            row = db.fetchone("SELECT name,coalesce(cert_number,''),coalesce(file_path,'') FROM certificates WHERE id=?", (cid,))
            for c, v in enumerate(row or ('', '', '')):
                self.defaults.setItem(r, c, self._item(v, cid))

    def pick_certificate(self):
        d = CertificatePicker(self)
        return d.cert_id if d.exec() else None

    def add_rule(self):
        kind = self.kind.currentData()
        value = self.value.currentData() if kind == 'pipeline' else self.value.currentText().strip()
        if not value:
            QMessageBox.warning(self, 'Правило', 'Укажите значение условия.')
            return
        cert = self.pick_certificate()
        if cert:
            try:
                add_cert_rule(db, kind, value, cert)
            except ValueError as e:
                QMessageBox.warning(self, 'Правило', str(e))
            self.load()

    def remove_rule(self):
        r = self.rules.currentRow()
        if r >= 0:
            db.execute('DELETE FROM gsn_cert_rules WHERE id=?', (self.rules.item(r, 0).data(Qt.ItemDataRole.UserRole),))
            self.load()

    def add_default(self):
        cert = self.pick_certificate()
        if cert:
            db.execute('INSERT OR IGNORE INTO gsn_default_certs(certificate_id) VALUES(?)', (cert,))
            self.load()

    def remove_default(self):
        r = self.defaults.currentRow()
        if r >= 0:
            db.execute('DELETE FROM gsn_default_certs WHERE certificate_id=?', (self.defaults.item(r, 0).data(Qt.ItemDataRole.UserRole),))
            self.load()


class GsnCatalogView(GsvCatalogView):
    TABLE = 'gsn_pipelines'
    DIALOG = GsnPipelineDialog
    INTRO = 'Трубопроводы ГСН и их сертификаты. Справочник независим от ГСВ: свои трубопроводы, свои зависимые сертификаты и сертификаты по умолчанию.'

    def open_rules(self):
        GsnRulesDialog(self).exec()
