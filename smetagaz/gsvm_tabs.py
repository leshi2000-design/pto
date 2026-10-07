"""Вкладки карточки договора «Монтаж ГСВ»: оборудование, трубопроводы и стыки, график работ, исполнительная документация, шаблоны и теги."""
import os
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QComboBox,
                              QDoubleSpinBox, QSpinBox, QLineEdit, QMessageBox, QFileDialog, QAbstractItemView, QHeaderView, QTabWidget, QCheckBox,
                              QListWidget, QListWidgetItem, QMenu, QInputDialog, QApplication)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor

from .database import db
from . import gsvm_domain as md
from . import gsvm_docs as dd
from .domain_widgets import OptionalDate
from .platform_utils import open_local

STATE_TEXT = {'none': ('не создан', '#65758b'), 'fresh': ('актуален', '#16A34A'), 'stale': ('данные изменились — переформируйте', '#D97706'),
              'missing': ('файл не найден — сформируйте заново', '#DC2626'), 'linked': ('привязан готовый файл', '#2563EB')}


def open_file(parent, path, verb=None):
    if not path or not os.path.isfile(path):
        QMessageBox.warning(parent, 'Файл', 'Файл не найден по сохранённому пути:\n' + (path or '(путь не указан)'))
        return False
    try:
        open_local(path, verb)
        return True
    except OSError as e:
        QMessageBox.warning(parent, 'Файл', str(e))
        return False


def print_files(parent, paths):
    """Печать через системное окно: по одному файлу; недоступные файлы перечисляются в итоге."""
    missing = [p for p in paths if not p or not os.path.isfile(p)]
    ok = [p for p in paths if p and os.path.isfile(p)]
    for p in ok:
        try:
            open_local(p, 'print')
        except OSError as e:
            missing.append(f'{p} ({e})')
    if missing:
        QMessageBox.warning(parent, 'Печать', 'Не удалось отправить на печать:\n' + '\n'.join(missing))
    elif not ok:
        QMessageBox.information(parent, 'Печать', 'Нет файлов для печати.')


def make_table(headers, widths=()):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.horizontalHeader().setStretchLastSection(True)
    for i, w in enumerate(widths):
        t.setColumnWidth(i, w)
    return t


def read_item(table, r, c):
    item = table.item(r, c)
    return item.text().strip() if item else ''


# --- ОБОРУДОВАНИЕ ----------------------------------------------------------------------------

class EquipmentTab(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Оборудование, установленное на объекте. Типы стандартные, но можно ввести свой. К оборудованию прикрепляется файл паспорта или '
                                'сертификата — он копируется в папку договора.'))
        self.table = make_table(['Оборудование', 'Тип / модель', 'Серийный номер', 'Примечание', 'Паспорт / сертификат (файл)'], (230, 230, 170, 200))
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for text, fn in (('＋ Добавить оборудование', lambda: self.add_row()), ('Убрать строку', self.remove_row), ('Прикрепить файл…', self.attach),
                         ('Открыть файл', self.open_selected), ('Убрать файл', self.clear_file)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)

    def kind_combo(self, kind=''):
        combo = QComboBox()
        combo.setEditable(True)
        for k in md.EQUIPMENT_KINDS:
            combo.addItem(md.EQUIPMENT_LABELS.get(k, k), k)
        combo.setCurrentIndex(-1)
        combo.setEditText(md.EQUIPMENT_LABELS.get(kind, kind))
        combo.lineEdit().setPlaceholderText('Выберите или введите тип…')
        return combo

    def add_row(self, row=None):
        row = row or {}
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setCellWidget(r, 0, self.kind_combo(row.get('kind', '')))
        for c, key in ((1, 'model'), (2, 'serial'), (3, 'note')):
            self.table.setItem(r, c, QTableWidgetItem(row.get(key, '') or ''))
        self.set_file(r, row.get('file_path', ''))

    def set_file(self, r, path):
        item = QTableWidgetItem(os.path.basename(path) if path else '')
        item.setData(Qt.ItemDataRole.UserRole, path or '')
        item.setToolTip(path or '')
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if path and not os.path.isfile(path):
            item.setForeground(QColor('#DC2626'))
            item.setToolTip('Файл не найден: ' + path)
        self.table.setItem(r, 4, item)

    def kind_at(self, r):
        text = self.table.cellWidget(r, 0).currentText().strip()
        for k in md.EQUIPMENT_KINDS:
            if text == md.EQUIPMENT_LABELS.get(k, k):
                return k
        return text

    def rows(self):
        return [dict(kind=self.kind_at(r), model=read_item(self.table, r, 1), serial=read_item(self.table, r, 2), note=read_item(self.table, r, 3),
                     file_path=self.table.item(r, 4).data(Qt.ItemDataRole.UserRole) or '') for r in range(self.table.rowCount())]

    def load(self, cid):
        self.table.setRowCount(0)
        for row in md.equipment(db, cid) if cid else []:
            self.add_row(row)

    def save(self, cid):
        md.save_equipment(db, cid, self.rows())

    def remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def attach(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, 'Оборудование', 'Выберите строку оборудования.')
            return
        if not self.dialog.ensure_saved():
            return
        if not md.contract_folder(db, self.dialog.contract_id) and not self.dialog.ask_folder():
            QMessageBox.information(self, 'Оборудование', 'Паспорта оборудования хранятся в папке договора: сначала привяжите или создайте её.')
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Паспорт или сертификат оборудования', '', 'Документы (*.pdf *.jpg *.jpeg *.png *.docx *.xlsx);;Все файлы (*)')
        if path:
            try:
                self.set_file(r, md.store_equipment_file(db, self.dialog.contract_id, path))
            except (ValueError, OSError) as e:
                QMessageBox.warning(self, 'Оборудование', str(e))

    def open_selected(self):
        r = self.table.currentRow()
        if r >= 0:
            open_file(self, self.table.item(r, 4).data(Qt.ItemDataRole.UserRole))

    def clear_file(self):
        r = self.table.currentRow()
        if r >= 0:
            self.set_file(r, '')


# --- ТРУБОПРОВОДЫ И СТЫКИ --------------------------------------------------------------------

class CustomJointDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Произвольный стык')
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.name.setPlaceholderText('Тип и диаметр трубы, например: Сталь 57x3')
        self.count = QSpinBox()
        self.count.setRange(0, 100000)
        form.addRow('Тип и диаметр трубы', self.name)
        form.addRow('Количество стыков, шт.', self.count)
        form.addRow(QLabel('Такой трубопровод остаётся только в таблице стыков и не добавляется в таблицу трубопроводов.'))
        ok = QPushButton('Добавить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.accept)
        form.addRow(ok)


class PipesTab(QWidget):
    changed = pyqtSignal()

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self._loading = False
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>Трубопроводы</b> — из справочника ГСВ («Справочники ГСВ» → трубопроводы). Количество в метрах, до двух знаков.'))
        self.top = make_table(['Наименование трубопровода', 'Количество, м', 'Сертификат', 'Примечание'], (330, 130, 220))
        layout.addWidget(self.top, 2)
        bar = QHBoxLayout()
        for text, fn in (('＋ Добавить трубопровод', lambda: self.add_pipe()), ('Убрать строку', self.remove_pipe), ('Взять данные из сметы', self.from_estimate)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.estimate_note = QLabel('')
        self.estimate_note.setStyleSheet('color: #65758b;')
        bar.addWidget(self.estimate_note, 1)
        layout.addLayout(bar)

        layout.addWidget(QLabel('<b>Стыки</b> — строки повторяют трубопроводы верхней таблицы; количество стыков вводится вручную.'))
        self.bottom = make_table(['Наименование трубопровода', 'Количество стыков, шт.', 'Примечание'], (330, 170))
        layout.addWidget(self.bottom, 2)
        bar = QHBoxLayout()
        for text, fn in (('＋ Добавить произвольный стык', self.add_custom), ('Удалить строку', self.remove_joint)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.total = QLabel('')
        self.total.setStyleSheet('font-weight: 700;')
        bar.addWidget(self.total, 1)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        self.btn_work = QPushButton('Внести в график работ…')
        self.btn_work.setProperty('type', 'primary')
        self.btn_work.clicked.connect(self.dialog.open_work_entry)
        self.btn_consumption = QPushButton('Расход строительных материалов')
        self.btn_consumption.clicked.connect(self.dialog.open_consumption)
        bar.addWidget(self.btn_work)
        bar.addWidget(self.btn_consumption)
        bar.addStretch()
        layout.addLayout(bar)

    # верхняя таблица
    def pipe_combo(self, pipeline_id=None):
        combo = QComboBox()
        combo.addItem('Выберите трубопровод…', None)
        for pid, name, active in db.fetchall('SELECT id,name,active FROM gsv_pipelines WHERE active=1 OR id=? ORDER BY name', (pipeline_id,)):
            combo.addItem(name + ('' if active else ' · архив'), pid)
        combo.setCurrentIndex(max(0, combo.findData(pipeline_id)))
        return combo

    def add_pipe(self, pipeline_id=None, quantity=0.0, note='', from_estimate=0):
        r = self.top.rowCount()
        self.top.insertRow(r)
        combo = self.pipe_combo(pipeline_id)
        self.top.setCellWidget(r, 0, combo)
        spin = QDoubleSpinBox()
        spin.setRange(0, 1e7)
        spin.setDecimals(2)
        spin.setSuffix(' м')
        spin.setValue(quantity or 0)
        spin.setProperty('from_estimate', int(bool(from_estimate)))
        spin.valueChanged.connect(lambda *_, s=spin: s.setProperty('from_estimate', 0))      # ручное изменение отвязывает строку от сметы
        self.top.setCellWidget(r, 1, spin)
        cert = QTableWidgetItem()
        cert.setFlags(cert.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.top.setItem(r, 2, cert)
        self.top.setItem(r, 3, QTableWidgetItem(note or ''))
        combo.currentIndexChanged.connect(lambda *_: (self.refresh_cert(combo, cert), self.sync_bottom()))
        self.refresh_cert(combo, cert)
        if not self._loading:
            self.sync_bottom()

    def refresh_cert(self, combo, item):
        row = db.fetchone('SELECT c.cert_number,c.name FROM gsv_pipelines p LEFT JOIN certificates c ON c.id=p.certificate_id WHERE p.id=?', (combo.currentData(),))
        item.setText((f'№ {row[0] or "—"} · {row[1] or ""}' if row and (row[0] or row[1]) else 'Сертификат не указан в справочнике') if combo.currentData() else '')

    def remove_pipe(self):
        r = self.top.currentRow()
        if r >= 0:
            self.top.removeRow(r)
            self.sync_bottom()

    def pipe_rows(self):
        return [dict(pipeline_id=self.top.cellWidget(r, 0).currentData(), quantity=self.top.cellWidget(r, 1).value(), note=read_item(self.top, r, 3),
                     from_estimate=self.top.cellWidget(r, 1).property('from_estimate')) for r in range(self.top.rowCount())]

    def from_estimate(self):
        if not self.dialog.ensure_saved():
            return
        if not self.dialog.estimate_id:
            QMessageBox.information(self, 'Смета', 'К договору не привязана смета. Создайте или привяжите её на вкладке «Договор и клиент».')
            return
        try:
            self.dialog.save_panels()
            n = md.pipelines_from_estimate(db, self.dialog.contract_id)
        except ValueError as e:
            QMessageBox.warning(self, 'Смета', str(e))
            return
        if not n:
            QMessageBox.information(self, 'Смета', 'В смете нет позиций, наименование которых совпадает с трубопроводами справочника ГСВ.')
            return
        self.load(self.dialog.contract_id)
        self.estimate_note.setText(f'Из сметы взято позиций: {n}. Эти строки обновляются вместе со сметой.')

    # нижняя таблица
    def joint_rows(self):
        rows = []
        for r in range(self.bottom.rowCount()):
            name_item = self.bottom.item(r, 0)
            rows.append(dict(id=name_item.data(Qt.ItemDataRole.UserRole), pipeline_id=name_item.data(Qt.ItemDataRole.UserRole + 1), custom=name_item.data(Qt.ItemDataRole.UserRole + 2),
                             name=name_item.text().strip(), count=self.bottom.cellWidget(r, 1).value(), note=read_item(self.bottom, r, 2)))
        return rows

    def add_joint_row(self, name, count=0, note='', rid=None, pipeline_id=None, custom=0):
        r = self.bottom.rowCount()
        self.bottom.insertRow(r)
        item = QTableWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, rid)
        item.setData(Qt.ItemDataRole.UserRole + 1, pipeline_id)
        item.setData(Qt.ItemDataRole.UserRole + 2, custom)
        if custom:
            item.setForeground(QColor('#7C3AED'))
            item.setToolTip('Произвольный стык: есть только в этой таблице')
        self.bottom.setItem(r, 0, item)
        spin = QSpinBox()
        spin.setRange(0, 100000)
        spin.setValue(count or 0)
        spin.valueChanged.connect(self.update_total)
        self.bottom.setCellWidget(r, 1, spin)
        self.bottom.setItem(r, 2, QTableWidgetItem(note or ''))

    def sync_bottom(self):
        """Строки нижней таблицы следуют за верхней, введённые количества сохраняются."""
        if self._loading:
            return
        old = self.joint_rows()
        counts = {r['pipeline_id']: (r['count'], r['note'], r['id']) for r in old if r['pipeline_id'] and not r['custom']}
        customs = [r for r in old if r['custom']]
        self.bottom.setRowCount(0)
        seen = set()
        for p in self.pipe_rows():
            pid = p['pipeline_id']
            if not pid or pid in seen:
                continue
            seen.add(pid)
            name = db.fetchone('SELECT name FROM gsv_pipelines WHERE id=?', (pid,))[0]
            count, note, rid = counts.get(pid, (0, '', None))
            self.add_joint_row(name, count, note, rid, pid, 0)
        for r in customs:
            self.add_joint_row(r['name'], r['count'], r['note'], r['id'], None, 1)
        self.update_total()

    def add_custom(self):
        d = CustomJointDialog(self)
        if d.exec() and d.name.text().strip():
            self.add_joint_row(d.name.text().strip(), d.count.value(), '', None, None, 1)
            self.update_total()

    def remove_joint(self):
        r = self.bottom.currentRow()
        if r < 0:
            return
        if self.bottom.item(r, 0).data(Qt.ItemDataRole.UserRole + 2):
            self.bottom.removeRow(r)
            self.update_total()
        else:
            QMessageBox.information(self, 'Стыки', 'Эта строка повторяет трубопровод из верхней таблицы. Чтобы убрать её, удалите трубопровод в верхней таблице или введите 0 стыков.')

    def update_total(self, *_):
        total = sum(self.bottom.cellWidget(r, 1).value() for r in range(self.bottom.rowCount()))
        self.total.setText(f'Всего стыков по объекту: {total} шт.')

    def load(self, cid):
        self._loading = True
        self.top.setRowCount(0)
        self.bottom.setRowCount(0)
        if cid:
            for p in md.pipelines(db, cid):
                self.add_pipe(p['pipeline_id'], p['quantity'], p['note'], p['from_estimate'])
            for j in md.joints(db, cid):
                self.add_joint_row(j['name'], j['count'], j['note'], j['id'], j['pipeline_id'], j['custom'])
        self._loading = False
        self.update_total()

    def save(self, cid):
        md.save_pipelines(db, cid, self.pipe_rows())
        existing = {j['pipeline_id']: j['id'] for j in md.joints(db, cid) if not j['custom']}
        rows = []
        for r in self.joint_rows():
            if r['custom']:
                r['id'] = None
            else:
                r['id'] = existing.get(r['pipeline_id'])
            rows.append(r)
        md.save_joints(db, cid, [r for r in rows if r['id'] or r['custom']])
        self.load(cid)


# --- ГРАФИК РАБОТ, РАСХОД МАТЕРИАЛОВ ---------------------------------------------------------

class WorkEntryDialog(QDialog):
    """Добавление записи в график сварочных работ: объект, дата, трубопроводы и стыки из карточки, сварщик, расход материалов."""
    def __init__(self, cid, object_name, lines, parent=None):
        super().__init__(parent)
        self.cid = cid
        self.consumption = None
        self.setWindowTitle('Внести в график сварочных работ')
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.object = QLineEdit(object_name)
        self.object.setReadOnly(True)
        form.addRow('Наименование объекта', self.object)
        self.date = OptionalDate()
        from datetime import date as _date
        self.date.set_value(_date.today().isoformat())
        form.addRow('Дата работ *', self.date)
        self.welder = QComboBox()
        self.welder.setEditable(True)
        self.welder.addItem('', None)
        for rid, name in db.fetchall('SELECT id,name FROM welders ORDER BY name'):
            self.welder.addItem(name, rid)
        form.addRow('Сварщик (из модуля «Сварщики»)', self.welder)
        layout.addWidget(QLabel('Свариваемые трубопроводы и количество стыков взяты из карточки договора. Для расчёта расхода материалов выберите норму для каждой строки.'))
        self.table = make_table(['Трубопровод', 'Стыков, шт.', 'Норма расхода (модуль «Списание»)'], (360, 110))
        layout.addWidget(self.table, 1)
        profiles = db.fetchall('SELECT id,name FROM norm_profiles ORDER BY name')
        for name, count in lines:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.item(r, 0).setFlags(self.table.item(r, 0).flags() & ~Qt.ItemFlag.ItemIsEditable)
            spin = QSpinBox()
            spin.setRange(0, 100000)
            spin.setValue(count)
            self.table.setCellWidget(r, 1, spin)
            combo = QComboBox()
            combo.addItem('— норма не выбрана —', None)
            for pid, pname in profiles:
                combo.addItem(pname, pid)
            combo.setCurrentIndex(max(0, combo.findData(md.guess_profile(db, name))))
            self.table.setCellWidget(r, 2, combo)
        bar = QHBoxLayout()
        calc = QPushButton('Расход материалов')
        calc.clicked.connect(self.calculate)
        bar.addWidget(calc)
        bar.addStretch()
        layout.addLayout(bar)
        self.result = make_table(['Материал', 'Ед.', 'Расход'], (360, 80))
        self.result.setMaximumHeight(170)
        layout.addWidget(self.result)
        bottom = QHBoxLayout()
        self.status = QLabel('')
        bottom.addWidget(self.status, 1)
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        cancel = QPushButton('Отмена')
        cancel.clicked.connect(self.reject)
        bottom.addWidget(save)
        bottom.addWidget(cancel)
        layout.addLayout(bottom)

    def lines(self):
        return [(self.table.item(r, 0).text(), self.table.cellWidget(r, 1).value()) for r in range(self.table.rowCount())]

    def calculate(self):
        volumes, skipped = [], []
        for r in range(self.table.rowCount()):
            count = self.table.cellWidget(r, 1).value()
            profile = self.table.cellWidget(r, 2).currentData()
            if count and profile:
                volumes.append((profile, count))
            elif count:
                skipped.append(self.table.item(r, 0).text())
        try:
            rows = md.calc_consumption(db, volumes)
        except ValueError as e:
            QMessageBox.warning(self, 'Расход материалов', str(e))
            return None
        self.result.setRowCount(len(rows))
        for i, m in enumerate(rows):
            for c, v in enumerate((m['name'], m['unit'], m['qty'])):
                self.result.setItem(i, c, QTableWidgetItem(v))
        self.consumption = rows
        self.status.setText('Не выбрана норма для: ' + ', '.join(skipped) if skipped else f'Материалов в расчёте: {len(rows)}')
        return rows

    def save(self):
        try:
            if self.consumption is None and any(self.table.cellWidget(r, 2).currentData() for r in range(self.table.rowCount())):
                if self.calculate() is None:
                    return
            lines = self.lines()
            day = self.date.value()
            if not day:
                raise ValueError('Укажите дату работ')
            text = self.welder.currentText().strip()
            wid = self.welder.currentData() if self.welder.currentIndex() >= 0 and text == self.welder.itemText(self.welder.currentIndex()) else None
            md.create_work_entry(db, self.cid, day, self.object.text(), wid, text, lines, self.consumption or [])
        except Exception as e:
            QMessageBox.warning(self, 'График работ', str(e))
            return
        self.accept()


class ConsumptionDialog(QDialog):
    def __init__(self, cid, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Расход строительных материалов по договору')
        self.resize(780, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Сумма по записям графика работ этого договора:'))
        summary = make_table(['Материал', 'Ед.', 'Всего'], (400, 80))
        rows = md.consumption_summary(db, cid)
        summary.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for c, v in enumerate(row):
                summary.setItem(i, c, QTableWidgetItem(str(v)))
        layout.addWidget(summary)
        layout.addWidget(QLabel('По записям:'))
        detail = make_table(['Записано', 'Дата работ', 'Материал', 'Ед.', 'Расход'], (150, 100, 280, 60))
        rows = md.consumption_rows(db, cid)
        detail.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for c, v in enumerate(row):
                detail.setItem(i, c, QTableWidgetItem(str(v or '')))
        layout.addWidget(detail, 1)
        if not rows:
            layout.addWidget(QLabel('Расход появится после записи в график работ с выбранными нормами.'))
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)


# --- ИСПОЛНИТЕЛЬНАЯ ДОКУМЕНТАЦИЯ -------------------------------------------------------------

class RulesDialog(QDialog):
    """Зависимые сертификаты и сертификаты по умолчанию — общие настройки всей программы (справочник сертификатов ГСВ)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Зависимые сертификаты и сертификаты по умолчанию')
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Настройки действуют для всех объектов монтажа ГСВ: сертификат подтягивается в исполнительную документацию автоматически.'))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel('<b>Зависимые сертификаты</b>: «если в объекте … — добавить сертификат …»'))
        self.rules = make_table(['Условие', 'Значение', 'Сертификат', 'Номер'], (330, 220, 260))
        pl.addWidget(self.rules, 1)
        bar = QHBoxLayout()
        self.kind = QComboBox()
        for k, label in md.RULE_TYPES.items():
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
        pl.addWidget(QLabel('<b>Сертификаты по умолчанию</b> — подтягиваются во все объекты вне зависимости от обстоятельств.'))
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
        kind = self.kind.currentData()
        if kind == 'equipment_kind':
            for k in md.EQUIPMENT_KINDS:
                self.value.addItem(k, k)
        elif kind == 'pipeline':
            for pid, name in db.fetchall('SELECT id,name FROM gsv_pipelines ORDER BY name'):
                self.value.addItem(name, str(pid))
            self.value.setEditable(False)
            return
        self.value.setEditable(True)
        self.value.setEditText('')
        self.value.lineEdit().setPlaceholderText('Например: 32 или название производителя' if kind == 'pipeline_text' else 'Тип оборудования')

    def load(self):
        rows = md.cert_rules(db)
        self.rules.setRowCount(len(rows))
        for r, (rid, cond, value, cid, name, number) in enumerate(rows):
            for c, v in enumerate((md.RULE_TYPES[cond], md.value_label(db, cond, value), name, number)):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, rid)
                self.rules.setItem(r, c, item)
        ids = md.default_certs(db)
        self.defaults.setRowCount(len(ids))
        for r, cid in enumerate(ids):
            row = db.fetchone('SELECT name,coalesce(cert_number,\'\'),coalesce(file_path,\'\') FROM certificates WHERE id=?', (cid,))
            for c, v in enumerate(row or ('', '', '')):
                item = QTableWidgetItem(str(v))
                item.setData(Qt.ItemDataRole.UserRole, cid)
                self.defaults.setItem(r, c, item)

    def pick_certificate(self):
        from .gsv_catalog import CertificatePicker
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
                md.add_cert_rule(db, kind, value, cert)
            except ValueError as e:
                QMessageBox.warning(self, 'Правило', str(e))
            self.load()

    def remove_rule(self):
        r = self.rules.currentRow()
        if r >= 0:
            db.execute('DELETE FROM gsvm_cert_rules WHERE id=?', (self.rules.item(r, 0).data(Qt.ItemDataRole.UserRole),))
            self.load()

    def add_default(self):
        cert = self.pick_certificate()
        if cert:
            db.execute('INSERT OR IGNORE INTO gsvm_default_certs(certificate_id) VALUES(?)', (cert,))
            self.load()

    def remove_default(self):
        r = self.defaults.currentRow()
        if r >= 0:
            db.execute('DELETE FROM gsvm_default_certs WHERE certificate_id=?', (self.defaults.item(r, 0).data(Qt.ItemDataRole.UserRole),))
            self.load()


class CertsTab(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Сертификаты подтягиваются автоматически. Файлы оборудования лежат в папке договора, остальные — в справочнике сертификатов ГСВ (копии не создаются).'))
        self.table = make_table(['Откуда', 'Сертификат', 'Номер', 'Основание', 'Файл'], (130, 300, 130, 280))
        self.table.cellDoubleClicked.connect(lambda *_: self.open_selected())
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for text, fn in (('Открыть', self.open_selected), ('Печать', self.print_selected), ('Печать всех', self.print_all), ('Убрать из списка', self.remove_selected),
                         ('Вернуть убранные', self.restore)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        add = QPushButton('＋ Произвольный сертификат')
        menu = QMenu(add)
        menu.addAction('Из справочника сертификатов…').triggered.connect(self.add_from_catalog)
        menu.addAction('Файл с компьютера…').triggered.connect(self.add_file)
        add.setMenu(menu)
        bar.addWidget(add)
        rules = QPushButton('Зависимости и сертификаты по умолчанию…')
        rules.clicked.connect(self.edit_rules)
        bar.addWidget(rules)
        bar.addStretch()
        layout.addLayout(bar)
        self.rows = []

    def load(self):
        cid = self.dialog.contract_id
        self.rows = md.collect_certs(db, cid) if cid else []
        self.table.setRowCount(len(self.rows))
        for r, c in enumerate(self.rows):
            ok = c['path'] and os.path.isfile(c['path'])
            values = (md.CERT_GROUPS[c['group']], c['title'], c['number'], c['reason'], (os.path.basename(c['path']) if ok else ('файл не найден' if c['path'] else 'файл не указан')))
            for col, v in enumerate(values):
                item = QTableWidgetItem(v)
                item.setToolTip(c['path'])
                if col == 4 and not ok:
                    item.setForeground(QColor('#DC2626'))
                self.table.setItem(r, col, item)

    def current(self):
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def open_selected(self):
        c = self.current()
        if c:
            open_file(self, c['path'])

    def print_selected(self):
        c = self.current()
        if c:
            print_files(self, [c['path']])

    def print_all(self):
        print_files(self, [c['path'] for c in self.rows])

    def remove_selected(self):
        c = self.current()
        if c:
            md.exclude_cert(db, self.dialog.contract_id, c['key'])
            self.load()

    def restore(self):
        md.restore_certs(db, self.dialog.contract_id)
        self.load()

    def add_from_catalog(self):
        if not self.dialog.ensure_saved():
            return
        from .gsv_catalog import CertificatePicker
        d = CertificatePicker(self)
        if d.exec():
            md.add_custom_cert(db, self.dialog.contract_id, cert_id=d.cert_id)
            self.load()

    def add_file(self):
        if not self.dialog.ensure_saved():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Произвольный сертификат', '', 'Документы (*.pdf *.jpg *.jpeg *.png *.docx *.xlsx);;Все файлы (*)')
        if path:
            md.add_custom_cert(db, self.dialog.contract_id, Path(path).stem, path)
            self.load()

    def edit_rules(self):
        RulesDialog(self).exec()
        self.load()


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
            from . import preflight, preflight_ui
            if not preflight_ui.confirm(self, f'«{dd.DOC_KINDS[kind][0]}»', preflight.check_montage(db, self.dialog.contract_id, kind)):
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
        from . import preflight, preflight_ui
        issues, seen = [], set()
        for kind in dd.ID_KINDS:              # сверка один раз для всего комплекта
            for i in preflight.check_montage(db, self.dialog.contract_id, kind):
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


class AttestationsTab(QWidget):
    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Аттестаты производителя работ и сварщиков, протоколы и другие документы из модуля «Сварщики». Хранится только ссылка на файл.'))
        self.table = make_table(['Документ', 'Тип', 'Сварщик', 'Номер', 'Дата', 'Файл'], (300, 140, 180, 110, 100))
        self.table.cellDoubleClicked.connect(lambda *_: self.open_selected())
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for text, fn in (('Выбрать из справочника…', self.choose), ('Открыть', self.open_selected), ('Печать', self.print_selected), ('Печать всех', self.print_all), ('Убрать', self.remove)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.rows = []

    def load(self):
        self.rows = md.attestations(db, self.dialog.contract_id) if self.dialog.contract_id else []
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            for c, v in enumerate((row[1], row[2], row[3], row[4], row[5], row[6])):
                self.table.setItem(r, c, QTableWidgetItem(str(v or '')))

    def current_path(self):
        r = self.table.currentRow()
        return self.rows[r][6] if 0 <= r < len(self.rows) else None

    def choose(self):
        if not self.dialog.ensure_saved():
            return
        d = QDialog(self)
        d.setWindowTitle('Аттестаты и документы сварщиков')
        d.resize(760, 560)
        layout = QVBoxLayout(d)
        search = QLineEdit()
        search.setPlaceholderText('Поиск по названию, сварщику, номеру…')
        layout.addWidget(search)
        lst = QListWidget()
        layout.addWidget(lst, 1)
        chosen = {r[0] for r in self.rows}
        items = db.fetchall("""SELECT d.id,d.title,d.document_type,coalesce(w.name,''),coalesce(d.number,'') FROM welding_documents d LEFT JOIN welders w ON w.id=d.welder_id ORDER BY d.title""")

        def fill():
            lst.clear()
            q = search.text().casefold()
            for did, title, kind, welder, number in items:
                text = f'{title} · {kind}' + (f' · {welder}' if welder else '') + (f' · № {number}' if number else '')
                if q and q not in text.casefold():
                    continue
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, did)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if did in chosen else Qt.CheckState.Unchecked)
                lst.addItem(item)
        fill()
        search.textChanged.connect(lambda *_: (collect(), fill()))

        def collect():
            for i in range(lst.count()):
                did = lst.item(i).data(Qt.ItemDataRole.UserRole)
                (chosen.add if lst.item(i).checkState() == Qt.CheckState.Checked else chosen.discard)(did)
        if not items:
            layout.addWidget(QLabel('В модуле «Сварщики» пока нет документов. Добавьте аттестаты там — и выберите их здесь.'))
        ok = QPushButton('Сохранить выбор')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(d.accept)
        layout.addWidget(ok)
        if d.exec():
            collect()
            md.set_attestations(db, self.dialog.contract_id, chosen)
            self.load()

    def open_selected(self):
        p = self.current_path()
        if p is not None:
            open_file(self, p)

    def print_selected(self):
        p = self.current_path()
        if p is not None:
            print_files(self, [p])

    def print_all(self):
        print_files(self, [r[6] for r in self.rows])

    def remove(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.rows):
            md.set_attestations(db, self.dialog.contract_id, [x[0] for i, x in enumerate(self.rows) if i != r])
            self.load()


class IdTab(QTabWidget):
    """Исполнительная документация монтажа ГСВ — независима от общего модуля «Исполнительная документация»."""
    def __init__(self, dialog):
        super().__init__()
        self.certs = CertsTab(dialog)
        self.docs = DocsTab(dialog)
        self.attestations = AttestationsTab(dialog)
        self.addTab(self.certs, 'Сертификаты')
        self.addTab(self.docs, 'Документы')
        self.addTab(self.attestations, 'Аттестаты')
        self.currentChanged.connect(lambda *_: self.load())

    def load(self):
        self.certs.load()
        self.docs.load()
        self.attestations.load()


# --- ШАБЛОНЫ И ТЕГИ --------------------------------------------------------------------------

class TemplatesTab(QWidget):
    """Шаблоны всех документов раздела и редактор тегов: имя, источник данных, формат, текст «если пусто»."""
    def __init__(self, dialog=None):
        super().__init__()
        self.dialog = dialog
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Шаблоны и теги действуют только в разделе «Монтаж ГСВ». Теги записываются в документе в фигурных скобках, например {НОМЕР_ДОГОВОРА}.'))
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
                            'Оборудование и трубопроводы справочника получают теги автоматически.'))
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
        self.load_tags()

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
    def load_tags(self):
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
