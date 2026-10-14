"""Вкладки карточки договора «Монтаж ГСН»: трубопроводы и материалы, сертификаты и аттестаты, исполнительная документация, шаблоны и теги."""
import os

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QTableWidgetItem, QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit,
                              QMessageBox, QFileDialog, QHeaderView, QTabWidget, QApplication, QGroupBox, QRadioButton, QButtonGroup)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from .database import db
from . import gsn_domain as gn
from . import gsn_docs as dd
from .gsvm_tabs import STATE_TEXT, open_file, print_files, make_table, read_item


class DocsTab(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Документы формируются по тегам (вкладка «Шаблоны и теги») из данных всех вкладок и сохраняются в папке договора. '
                                'Можно привязать уже готовый файл вместо формирования.'))
        self.table = make_table(['Документ', 'Состояние', 'Файл'], (380, 260))
        self.table.cellDoubleClicked.connect(lambda *_: self.open_selected())
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.btn_make = QPushButton('Сформировать')
        self.btn_make.setProperty('type', 'primary')
        self.btn_make.clicked.connect(self.make)
        bar.addWidget(self.btn_make)
        for text, fn in (('Привязать готовый файл…', self.link), ('Открыть', self.open_selected), ('Печать', self.print_selected), ('Удалить', self.remove),
                         ('Сформировать все', self.make_all), ('Печать всех', self.print_all)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.table.itemSelectionChanged.connect(self.update_buttons)

    def load(self):
        cid = self.dialog.contract_id
        self.table.setRowCount(len(dd.ID_KINDS))
        for r, kind in enumerate(dd.ID_KINDS):
            state = dd.doc_state(db, cid, kind) if cid else 'none'
            text, color = STATE_TEXT[state]
            path = dd.doc_path(db, cid, kind) if cid else ''
            for c, v in enumerate((dd.DOC_KINDS[kind][0], text, path)):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, kind)
                if c == 1:
                    item.setForeground(QColor(color))
                self.table.setItem(r, c, item)
        self.update_buttons()

    def update_buttons(self):
        kind = self.current_kind()
        state = dd.doc_state(db, self.dialog.contract_id, kind) if kind and self.dialog.contract_id else 'none'
        self.btn_make.setText('⟳ Переформировать' if state in ('stale', 'fresh', 'linked') else 'Сформировать')

    def current_kind(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def make_kind(self, kind, check=True):
        if not self.dialog.ensure_saved():
            return None
        if check:
            from . import preflight_ui
            if not preflight_ui.confirm(self, f'«{dd.DOC_KINDS[kind][0]}»', dd.check(db, self.dialog.contract_id, kind)):
                return None
        if not self.dialog.ensure_folder():
            return None
        try:
            return dd.generate(db, self.dialog.contract_id, kind)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, 'Документ не создан', str(e))
            return None

    def make(self):
        kind = self.current_kind()
        if not kind:
            QMessageBox.information(self, 'Документы', 'Выберите документ в списке.')
            return
        if self.make_kind(kind):
            self.load()

    def make_all(self):
        done = 0
        if not self.dialog.ensure_saved():
            return
        from . import preflight_ui
        issues, seen = [], set()
        for kind in dd.ID_KINDS:              # сверка один раз для всего комплекта
            for i in dd.check(db, self.dialog.contract_id, kind):
                if i['text'] not in seen:
                    seen.add(i['text'])
                    issues.append(i)
        if not preflight_ui.confirm(self, 'Комплект исполнительной документации', issues):
            return
        for kind in dd.ID_KINDS:
            if self.make_kind(kind, check=False):
                done += 1
            else:
                break
        self.load()
        if done:
            self.dialog.status.setText(f'Сформировано документов: {done}')

    def link(self):
        kind = self.current_kind()
        if not kind or not self.dialog.ensure_saved():
            return
        ext = '*.xlsx' if dd.DOC_KINDS[kind][1] == 'xlsx' else '*.docx *.doc'
        path, _ = QFileDialog.getOpenFileName(self, 'Готовый документ', '', f'Документы ({ext});;Все файлы (*)')
        if path:
            try:
                dd.link_doc(db, self.dialog.contract_id, kind, path)
            except ValueError as e:
                QMessageBox.warning(self, 'Документ', str(e))
            self.load()

    def open_selected(self):
        kind = self.current_kind()
        if kind:
            open_file(self, dd.doc_path(db, self.dialog.contract_id, kind))

    def print_selected(self):
        kind = self.current_kind()
        if kind:
            print_files(self, [dd.doc_path(db, self.dialog.contract_id, kind)])

    def print_all(self):
        print_files(self, [dd.doc_path(db, self.dialog.contract_id, k) for k in dd.ID_KINDS if dd.doc_path(db, self.dialog.contract_id, k)])

    def remove(self):
        kind = self.current_kind()
        if not kind or not dd.doc_row(db, self.dialog.contract_id, kind):
            return
        box = QMessageBox(self)
        box.setWindowTitle('Удаление документа')
        box.setText(f'«{dd.DOC_KINDS[kind][0]}»: убрать из списка или удалить файл с компьютера?')
        unlink = box.addButton('Только убрать из списка', QMessageBox.ButtonRole.AcceptRole)
        delete = box.addButton('Удалить файл', QMessageBox.ButtonRole.DestructiveRole)
        box.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() in (unlink, delete):
            dd.remove_doc(db, self.dialog.contract_id, kind, delete_file=box.clickedButton() is delete)
            self.load()


class TemplatesTab(QWidget):
    """Шаблоны всех документов раздела и редактор тегов: имя, источник данных, формат, текст «если пусто»."""
    def __init__(self, dialog=None):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Шаблоны и теги действуют только в разделе «Монтаж ГСН». Теги записываются в документе в фигурных скобках, например {НОМЕР_ДОГОВОРА}.'))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        # шаблоны
        page = QWidget()
        pl = QVBoxLayout(page)
        self.tpl = make_table(['Документ', 'Файл шаблона (пусто — стандартный)'], (360,))
        self.tpl.setRowCount(len(dd.DOC_KINDS))
        for r, kind in enumerate(dd.DOC_KINDS):
            name = QTableWidgetItem(dd.DOC_KINDS[kind][0] + (' (вкладка «Договор и клиент»)' if dd.DOC_KINDS[kind][2] == 'main' else ' (исполнительная документация)'))
            name.setData(Qt.ItemDataRole.UserRole, kind)
            self.tpl.setItem(r, 0, name)
            self.tpl.setItem(r, 1, QTableWidgetItem(db.get_setting(dd.template_setting(kind), '')))
            for it in (self.tpl.item(r, 0), self.tpl.item(r, 1)):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        pl.addWidget(self.tpl, 1)
        pl.addWidget(QLabel('Шаблон сметы и её теги настраиваются в модуле «Реестр смет».'))
        bar = QHBoxLayout()
        for text, fn in (('Выбрать шаблон…', self.choose_template), ('Открыть шаблон', self.open_template), ('Стандартный', self.reset_template)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        pl.addLayout(bar)
        tabs.addTab(page, 'Шаблоны документов')
        # теги
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel('Для каждого тега задаётся источник данных (поле карточки, оборудование, трубопровод), формат и текст, который подставится, если данных нет. '
                            'Материалы объекта (труба, соединение, заглушка, муфта) получают теги автоматически.'))
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск тега…')
        self.search.textChanged.connect(self.filter_rows)
        top.addWidget(self.search, 1)
        pl.addLayout(top)
        self.tags = make_table(['Тег', 'Источник данных', 'Формат', 'Если данных нет', 'Вкл.'], (270, 400, 270, 200, 60))
        self.tags.horizontalHeader().setStretchLastSection(False)
        self.tags.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        pl.addWidget(self.tags, 1)
        bar = QHBoxLayout()
        for text, fn in (('＋ Новый тег', self.new_tag), ('Удалить / отключить', self.delete_tag), ('Копировать тег', self.copy_tag), ('Сохранить теги', self.save_tags)):
            b = QPushButton(text)
            if text == 'Сохранить теги':
                b.setProperty('type', 'primary')
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.status = QLabel('')
        bar.addWidget(self.status, 1)
        pl.addLayout(bar)
        tabs.addTab(page, 'Редактор тегов')
        self.sources = []
        self._tags_loaded = False      # таблица тегов тяжёлая — строится при первом показе вкладки

    # шаблоны
    def current_kind(self):
        r = self.tpl.currentRow()
        return self.tpl.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def choose_template(self):
        kind = self.current_kind()
        if not kind:
            return
        ext = '*.xlsx' if dd.DOC_KINDS[kind][1] == 'xlsx' else '*.docx'
        path, _ = QFileDialog.getOpenFileName(self, 'Шаблон документа', '', f'Шаблоны ({ext})')
        if path:
            db.set_setting(dd.template_setting(kind), path)
            self.tpl.item(self.tpl.currentRow(), 1).setText(path)

    def open_template(self):
        kind = self.current_kind()
        if kind:
            open_file(self, dd.template_path(db, kind))

    def reset_template(self):
        kind = self.current_kind()
        if kind:
            db.set_setting(dd.template_setting(kind), '')
            self.tpl.item(self.tpl.currentRow(), 1).setText('')

    # теги
    def showEvent(self, event):
        super().showEvent(event)
        if not self._tags_loaded:
            self.load_tags()

    def load_tags(self):
        self._tags_loaded = True
        self.sources = dd.available_sources(db)
        rows = dd.list_tags(db)
        self.tags.setRowCount(0)
        for row in rows:
            self.add_row(*row)
        self.filter_rows()

    def add_row(self, tag_id, name, source, fmt, empty_text, auto_key='', enabled=1, note=''):
        r = self.tags.rowCount()
        self.tags.insertRow(r)
        item = QTableWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, tag_id)
        item.setToolTip(note)
        if auto_key:
            item.setForeground(QColor('#2563EB'))
        self.tags.setItem(r, 0, item)
        src = QComboBox()
        for key, label in self.sources:
            src.addItem(label, key)
        if src.findData(source) < 0:
            src.addItem(source, source)
        src.setCurrentIndex(src.findData(source))
        self.tags.setCellWidget(r, 1, src)
        fm = QComboBox()
        for key, label in dd.FORMATS.items():
            fm.addItem(label, key)
        fm.setCurrentIndex(max(0, fm.findData(fmt)))
        self.tags.setCellWidget(r, 2, fm)
        self.tags.setItem(r, 3, QTableWidgetItem(empty_text or ''))
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        chk.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.tags.setItem(r, 4, chk)

    def filter_rows(self, *_):
        q = self.search.text().casefold()
        for r in range(self.tags.rowCount()):
            self.tags.setRowHidden(r, bool(q) and q not in (read_item(self.tags, r, 0) + self.tags.cellWidget(r, 1).currentText()).casefold())

    def new_tag(self):
        self.add_row(None, 'НОВЫЙ_ТЕГ', 'client.name', 'text', '', '', 1, '')
        self.tags.setCurrentCell(self.tags.rowCount() - 1, 0)
        self.tags.editItem(self.tags.item(self.tags.rowCount() - 1, 0))

    def delete_tag(self):
        r = self.tags.currentRow()
        if r < 0:
            return
        tag_id = self.tags.item(r, 0).data(Qt.ItemDataRole.UserRole)
        if tag_id:
            result = dd.delete_tag(db, tag_id)
            self.status.setText('Тег удалён.' if result == 'deleted' else 'Стандартный тег отключён (его можно включить галочкой).')
            self.load_tags()
        else:
            self.tags.removeRow(r)

    def copy_tag(self):
        r = self.tags.currentRow()
        if r >= 0:
            QApplication.clipboard().setText('{' + read_item(self.tags, r, 0) + '}')
            self.status.setText('Скопировано: {' + read_item(self.tags, r, 0) + '}')

    def save_tags(self):
        errors = []
        with db.transaction():
            for r in range(self.tags.rowCount()):
                tag_id = self.tags.item(r, 0).data(Qt.ItemDataRole.UserRole)
                try:
                    new_id = dd.save_tag(db, tag_id, read_item(self.tags, r, 0), self.tags.cellWidget(r, 1).currentData(), self.tags.cellWidget(r, 2).currentData(),
                                         read_item(self.tags, r, 3), self.tags.item(r, 4).checkState() == Qt.CheckState.Checked)
                    self.tags.item(r, 0).setData(Qt.ItemDataRole.UserRole, new_id)
                except ValueError as e:
                    errors.append(f'Строка {r + 1}: {e}')
        if errors:
            QMessageBox.warning(self, 'Теги', '\n'.join(errors))
        else:
            self.status.setText('Теги сохранены. Документы с изменившимися значениями получат пометку «переформируйте».')
            self.load_tags()


# --- ТРУБОПРОВОДЫ И ОБОРУДОВАНИЕ -------------------------------------------------------------

class GsnPipelineTab(QWidget):
    """Протяжённость ПЭ и стали, тип газопровода и врезки, муфты; материалы объекта, сертификаты (по умолчанию и зависимые) и аттестаты сварщиков."""
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.loading = False
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Трубопроводы всегда одного диаметра: ПЭ 32 и сталь 25. Материалы, сертификаты и аттестаты подбираются автоматически по типу врезки.'))
        box = QGroupBox('Трубопровод и врезка')
        form = QFormLayout(box)
        self.pe = QDoubleSpinBox()
        self.steel = QDoubleSpinBox()
        for w in (self.pe, self.steel):
            w.setRange(0, 1e6)
            w.setDecimals(2)
            w.setSuffix(' м')
            w.valueChanged.connect(self.refresh)
        self.pressure = QComboBox()
        self.pressure.addItem('— выберите —', '')
        for key, label in gn.PRESSURES.items():
            self.pressure.addItem(label, key)
        self.tie_in = QComboBox()
        self.tie_in.addItem('— выберите —', '')
        for key, label in gn.TIE_INS.items():
            self.tie_in.addItem(label, key)
        self.couplings = QSpinBox()
        self.couplings.setRange(0, 1000)
        self.couplings.setSuffix(' шт')
        self.hint = QLabel('')
        self.hint.setWordWrap(True)
        form.addRow(f'Протяжённость ПЭ трубопровода ({gn.PE_DIAMETER})', self.pe)
        form.addRow(f'Протяжённость стального трубопровода ({gn.STEEL_DIAMETER})', self.steel)
        form.addRow('Тип газопровода', self.pressure)
        form.addRow('Тип врезки', self.tie_in)
        form.addRow('Количество муфт', self.couplings)
        form.addRow(self.hint)
        for w in (self.tie_in, self.pressure):
            w.currentIndexChanged.connect(self.refresh)
        self.couplings.valueChanged.connect(self.refresh)
        layout.addWidget(box)
        self.lock_widgets = [box]
        layout.addWidget(QLabel('Материалы объекта (позицию с нужной ролью выбирают в Справочнике ГСН; если таких позиций несколько — выберите здесь):'))
        self.mat_table = make_table(['Материал', 'Позиция справочника ГСН', 'Количество', 'Ед.'], (200, 420, 110))
        self.mat_table.setMaximumHeight(210)
        layout.addWidget(self.mat_table)
        layout.addWidget(QLabel('Сертификаты: по умолчанию (для всех объектов ГСН) и зависимые (привязаны к материалам этого договора):'))
        self.cert_table = make_table(['Сертификат', 'Номер', 'Вид', 'Основание', 'Срок', 'Файл'], (300, 120, 110, 260, 130))
        self.cert_table.cellDoubleClicked.connect(lambda *_: self.open_cert())
        layout.addWidget(self.cert_table, 1)
        layout.addWidget(QLabel('Аттестаты сварщиков (по умолчанию для всех объектов и зависимые от типа врезки; правила — «Справочник ГСН → Аттестаты сварщиков»):'))
        self.att_table = make_table(['Документ', 'Сварщик', 'Номер', 'Дата', 'Когда', 'Файл'], (300, 180, 110, 100, 200))
        self.att_table.cellDoubleClicked.connect(lambda *_: self.open_att())
        layout.addWidget(self.att_table, 1)
        bar = QHBoxLayout()
        for text, fn in (('Открыть сертификат', self.open_cert), ('Открыть аттестат', self.open_att), ('Печать сертификатов', self.print_certs), ('Печать аттестатов', self.print_atts)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.certs, self.atts = [], []
        self.role_combos = {}

    # значения формы
    def values(self):
        return dict(pe_length=self.pe.value(), steel_length=self.steel.value(), pressure_type=self.pressure.currentData() or '', tie_in=self.tie_in.currentData() or '',
                    couplings=self.couplings.value())

    def items(self):
        return {role: combo.currentData() for role, combo in self.role_combos.items() if combo.currentData()}

    def fill(self, c, chosen=None):
        self.loading = True
        self.pe.setValue(float(c.get('pe_length') or 0))
        self.steel.setValue(float(c.get('steel_length') or 0))
        self.pressure.setCurrentIndex(max(0, self.pressure.findData(c.get('pressure_type') or '')))
        self.tie_in.setCurrentIndex(max(0, self.tie_in.findData(c.get('tie_in') or '')))
        self.couplings.setValue(int(c.get('couplings') or 0))
        self.loading = False
        self.chosen = chosen or {}
        self.refresh()

    def current(self):
        c = dict(id=self.dialog.contract_id)
        c.update(self.values())
        return c

    def refresh(self, *_):
        if self.loading:
            return
        tie = self.tie_in.currentData() or ''
        self.hint.setText({'steel': 'Врезка в сталь: добавляется 1 неразъёмное соединение ПЭ/сталь + муфты. Нужен сварщик на металл.',
                           'pe': 'Врезка в ПЭ: добавляется 1 заглушка + муфты.'}.get(tie, 'Выберите тип врезки — материалы и сертификаты подберутся автоматически.'))
        self.couplings.setEnabled(bool(tie) and self.dialog_enabled())
        c = self.current()
        keep = {role: combo.currentData() for role, combo in self.role_combos.items()} or dict(getattr(self, 'chosen', {}) or {})
        picked = {}
        for role in gn.ROLES:
            options = gn.role_items(db, role)
            picked[role] = keep.get(role) if keep.get(role) in [i for i, _n in options] else (options[0][0] if options else None)
        mats = gn.materials(db, None, c, picked)
        self.mat_table.setRowCount(len(mats))
        self.role_combos = {}
        for r, m in enumerate(mats):
            self.mat_table.setItem(r, 0, QTableWidgetItem(m['label']))
            combo = QComboBox()
            combo.addItem('— в Справочнике ГСН нет позиции с такой ролью —' if not gn.role_items(db, m['role']) else '— выберите —', None)
            for item_id, name in gn.role_items(db, m['role']):
                combo.addItem(name, item_id)
            combo.setCurrentIndex(max(0, combo.findData(picked.get(m['role']))))
            combo.currentIndexChanged.connect(lambda *_: self.refresh_lists())
            self.role_combos[m['role']] = combo
            self.mat_table.setCellWidget(r, 1, combo)
            self.mat_table.setItem(r, 2, QTableWidgetItem(f'{m["quantity"]:g}'.replace('.', ',')))
            self.mat_table.setItem(r, 3, QTableWidgetItem(m['unit']))
        self.refresh_lists()

    def dialog_enabled(self):
        return not getattr(self.dialog, 'locked', False)

    def refresh_lists(self):
        c = self.current()
        picked = {role: combo.currentData() for role, combo in self.role_combos.items()}
        self.certs = gn.certificates(db, None, c, picked)
        states = {'ok': '#16A34A', 'soon': '#D97706', 'expired': '#DC2626', 'none': '#65758b'}
        self.cert_table.setRowCount(len(self.certs))
        for r, x in enumerate(self.certs):
            from .gsn_catalog import cert_state
            state, text = cert_state(x['valid_to'])
            for col, v in enumerate((x['name'], x['number'], 'по умолчанию' if x['kind'] == 'default' else 'зависимый', x['reason'], text, x['path'])):
                item = QTableWidgetItem(v)
                if col == 4:
                    item.setForeground(QColor(states[state]))
                self.cert_table.setItem(r, col, item)
        self.atts = gn.attestations(db, None, c)
        self.att_table.setRowCount(len(self.atts))
        for r, a in enumerate(self.atts):
            for col, v in enumerate((a['title'], a['welder'], a['number'], a['date'], a['reason'], a['path'])):
                self.att_table.setItem(r, col, QTableWidgetItem(v or ''))

    def set_enabled_inputs(self, enabled):
        for w in (self.pe, self.steel, self.pressure, self.tie_in, self.couplings):
            w.setEnabled(enabled)
        for combo in self.role_combos.values():
            combo.setEnabled(enabled)
        self.couplings.setEnabled(enabled and bool(self.tie_in.currentData()))

    def load(self):
        self.refresh()

    def open_cert(self):
        r = self.cert_table.currentRow()
        if 0 <= r < len(self.certs):
            open_file(self, self.certs[r]['path'])

    def open_att(self):
        r = self.att_table.currentRow()
        if 0 <= r < len(self.atts):
            open_file(self, self.atts[r]['path'])

    def print_certs(self):
        print_files(self, [x['path'] for x in self.certs])

    def print_atts(self):
        print_files(self, [a['path'] for a in self.atts])


class GsnIdTab(QTabWidget):
    """Исполнительная документация монтажа ГСН: 12 документов комплекта (договор и справка об оплате — на вкладке «Договор и клиент»)."""
    def __init__(self, dialog):
        super().__init__()
        self.docs = DocsTab(dialog)
        self.addTab(self.docs, 'Документы')
        self.currentChanged.connect(lambda *_: self.load())

    def load(self):
        self.docs.load()
