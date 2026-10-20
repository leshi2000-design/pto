"""Раздел «Наряды»: выдача заданий бригаде или работникам на объект, плановые объёмы, закрытие с фактом, документ наряда."""
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QGroupBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QTextEdit)

from . import orders_domain as od
from . import staff_domain as sd
from . import volumes_domain as vd
from . import gsv_project_domain as gd
from .database import db
from .date_widgets import DateEdit
from .dates import display_date

STATUS_COLORS = {'Выдан': '#0284C7', 'В работе': '#D97706', 'Закрыт': '#15803D', 'Отменён': '#8A8886'}


def _iso(d):
    return d.toString('yyyy-MM-dd')


class OrderDialog(QDialog):
    def __init__(self, order_id=None, parent=None, preset=None):
        super().__init__(parent)
        self.order_id = order_id
        self.setWindowTitle('Наряд')
        self.resize(1000, 780)
        self._loading = True
        layout = QVBoxLayout(self)
        form = QFormLayout()
        row = QHBoxLayout()
        self.kind = QComboBox()
        self.kind.addItems(od.KINDS)
        self.number = QLineEdit()
        self.number.setPlaceholderText('автоматически')
        self.number.setMaximumWidth(120)
        self.date = DateEdit(QDate.currentDate())
        self.status = QComboBox()
        self.status.addItems(od.STATUSES)
        for w, label in ((self.kind, 'Вид'), (self.number, '№'), (self.date, 'Дата'), (self.status, 'Статус')):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        row.addStretch()
        form.addRow(row)
        self.object = QComboBox()
        self.object.setEditable(True)
        self.object.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.object.lineEdit().setPlaceholderText('Начните вводить: номер договора, объект, клиент…')
        self.object.addItem('', None)
        for table, rid, label in od.objects(db):
            self.object.addItem(label, (table, rid))
        self.object.setCurrentIndex(0)
        self.object_text = QLineEdit()
        self.object_text.setPlaceholderText('или впишите объект вручную (если нет договора)')
        form.addRow('Объект', self.object)
        form.addRow('', self.object_text)
        self.crew = QComboBox()
        self.crew.addItem('— без бригады —', None)
        for cid, name, *_ in sd.crews(db, True):
            self.crew.addItem(name, cid)
        self.leader = QComboBox()
        self.leader.addItem('— не назначен —', None)
        self.staff = sd.staff_list(db, active_only=True)
        for r in self.staff:
            self.leader.addItem(r[1], r[0])
        row = QHBoxLayout()
        row.addWidget(self.crew, 1)
        row.addWidget(QLabel('Бригадир'))
        row.addWidget(self.leader, 1)
        form.addRow('Бригада', row)
        self.start = DateEdit(QDate.currentDate())
        self.end = DateEdit(QDate.currentDate())
        self.to_schedule = QCheckBox('Поставить работников в график занятости')
        self.to_schedule.setChecked(True)
        row = QHBoxLayout()
        for w, label in ((self.start, 'Срок с'), (self.end, 'по')):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        row.addWidget(self.to_schedule)
        row.addStretch()
        form.addRow(row)
        self.task = QLineEdit()
        self.task.setPlaceholderText('Что нужно сделать (кратко)')
        form.addRow('Задание', self.task)
        layout.addLayout(form)
        self.permit_box = QGroupBox('Наряд-допуск на работы повышенной опасности')
        pf = QFormLayout(self.permit_box)
        self.hazard = QComboBox()
        self.hazard.addItem('— выберите вид работ —', '')
        for h in od.HAZARDS:
            self.hazard.addItem(h, h)
        self.place = QLineEdit()
        self.place.setPlaceholderText('Место проведения работ (по умолчанию — объект)')
        self.time_from = QLineEdit()
        self.time_to = QLineEdit()
        for w in (self.time_from, self.time_to):
            w.setPlaceholderText('чч:мм')
            w.setMaximumWidth(80)
        self.supervisor = self.person_combo()
        self.performer = self.person_combo()
        self.admitter = self.person_combo()
        self.safety = QTextEdit()
        self.safety.setFixedHeight(60)
        self.safety.setPlaceholderText('Меры безопасности: что сделано и что должно быть выполнено до начала работ')
        self.ppe = QLineEdit()
        self.ppe.setPlaceholderText('Средства индивидуальной защиты')
        self.briefing = QCheckBox('Целевой инструктаж проведён')
        self.closing_note = QLineEdit()
        self.closing_note.setPlaceholderText('Отметка о закрытии допуска: работы закончены, люди выведены, инструмент убран')
        pf.addRow('Вид работ', self.hazard)
        pf.addRow('Место', self.place)
        row = QHBoxLayout()
        row.addWidget(QLabel('Время с'))
        row.addWidget(self.time_from)
        row.addWidget(QLabel('по'))
        row.addWidget(self.time_to)
        row.addStretch()
        pf.addRow(row)
        pf.addRow('Ответственный руководитель', self.supervisor)
        pf.addRow('Ответственный исполнитель', self.performer)
        pf.addRow('Допускающий', self.admitter)
        pf.addRow('Меры безопасности', self.safety)
        pf.addRow('СИЗ', self.ppe)
        pf.addRow(self.briefing)
        pf.addRow('Закрытие допуска', self.closing_note)
        layout.addWidget(self.permit_box)
        self.workers = QListWidget()
        self.workers.setMaximumHeight(130)
        self.workers.setFlow(QListWidget.Flow.LeftToRight)
        self.workers.setWrapping(True)
        self.workers.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.workers.setSpacing(2)
        for r in self.staff:
            it = QListWidgetItem(f'{r[1]} · {r[2]}' if len(r) > 2 and r[2] else r[1])
            it.setData(Qt.ItemDataRole.UserRole, r[0])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.workers.addItem(it)
        layout.addWidget(QLabel('<b>Работники</b> (отметьте; при выборе бригады отмечается её состав)'))
        layout.addWidget(self.workers)
        layout.addWidget(QLabel('<b>Объёмы наряда</b> — плановые работы и материалы; факт вносится при закрытии наряда'))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Вид', 'Наименование', 'Ед.', 'План', 'Факт', 'Примечание'])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 100), (2, 60), (3, 90), (4, 90), (5, 200)):
            self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for text, fn in (('Из объёмов договора', self.from_volumes), ('＋ Работа из справочника', lambda: self.add_catalog('Работа')),
                         ('＋ Материал из справочника', lambda: self.add_catalog('Материал')), ('＋ Произвольная', lambda: self.add_row()), ('Удалить строку', self.remove_row)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.note = QLineEdit()
        self.note.setPlaceholderText('Примечание')
        layout.addWidget(self.note)
        self.info = QLabel('')
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        bar = QHBoxLayout()
        self.btn_save = QPushButton('Сохранить')
        self.btn_save.setProperty('type', 'primary')
        self.btn_save.clicked.connect(self.save_clicked)
        self.btn_close_order = QPushButton('Закрыть наряд')
        self.btn_close_order.clicked.connect(self.close_order)
        self.btn_apply = QPushButton('Факт → в объёмы договора')
        self.btn_apply.clicked.connect(self.apply_facts)
        self.btn_doc = QPushButton('Сформировать документ')
        self.btn_doc.clicked.connect(self.make_document)
        cancel = QPushButton('Закрыть окно')
        cancel.clicked.connect(self.reject)
        for b in (self.btn_save, self.btn_close_order, self.btn_apply, self.btn_doc):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(cancel)
        layout.addLayout(bar)
        self.kind.currentIndexChanged.connect(self.kind_changed)
        self.crew.currentIndexChanged.connect(self.crew_changed)
        self.object.currentIndexChanged.connect(self.object_changed)
        self.start.dateChanged.connect(lambda d: self.end.date() < d and self.end.setDate(d))
        if order_id:
            self.fill(od.get_order(db, order_id))
        elif preset:
            self.apply_preset(preset)
            if preset.get('kind'):
                self.kind.setCurrentText(preset['kind'])
        self.kind_changed()
        self._loading = False
        self.refresh_buttons()

    def person_combo(self):
        box = QComboBox()
        box.addItem('— не назначен —', None)
        for r in self.staff:
            box.addItem(r[1], r[0])
        return box

    def kind_changed(self, *_):
        permit = self.kind.currentText() == od.KIND_PERMIT
        self.permit_box.setVisible(permit)
        self.setWindowTitle('Наряд-допуск' if permit else 'Наряд-задание')
        if not self.order_id and not self.number.text().strip():
            self.number.setPlaceholderText('автоматически (Д-01/26)' if permit else 'автоматически')

    # --- заполнение
    def apply_preset(self, preset):
        i = self.find_object(preset.get('owner_type'), preset.get('owner_id'))
        if i >= 0:
            self.object.setCurrentIndex(i)

    def find_object(self, otype, oid):
        for i in range(self.object.count()):
            if self.object.itemData(i) == (otype, oid):
                return i
        return -1

    def fill(self, o):
        self.kind.setCurrentText(o['kind'])
        self.hazard.setCurrentIndex(max(0, self.hazard.findData(o['hazard'] or '')))
        self.place.setText(o['place'] or '')
        self.time_from.setText(o['time_from'] or '')
        self.time_to.setText(o['time_to'] or '')
        for box, key in ((self.supervisor, 'supervisor_id'), (self.performer, 'performer_id'), (self.admitter, 'admitter_id')):
            box.setCurrentIndex(max(0, box.findData(o[key])))
        self.safety.setPlainText(o['safety'] or '')
        self.ppe.setText(o['ppe'] or '')
        self.briefing.setChecked(bool(o['briefing']))
        self.closing_note.setText(o['closing_note'] or '')
        self.number.setText(o['number'])
        self.date.setDate(QDate.fromString(o['order_date'], 'yyyy-MM-dd'))
        self.status.setCurrentText(o['status'])
        i = self.find_object(o['owner_type'], o['owner_id'])
        self.object.setCurrentIndex(max(0, i))
        self.object_text.setText(o['object_text'] or '')
        self.crew.setCurrentIndex(max(0, self.crew.findData(o['crew_id'])))
        self.leader.setCurrentIndex(max(0, self.leader.findData(o['leader_id'])))
        self.start.setDate(QDate.fromString(o['start_date'], 'yyyy-MM-dd'))
        self.end.setDate(QDate.fromString(o['end_date'], 'yyyy-MM-dd'))
        self.to_schedule.setChecked(bool(o['to_schedule']))
        self.task.setText(o['task'])
        self.note.setText(o['note'])
        chosen = set(o['workers'])
        for i in range(self.workers.count()):
            it = self.workers.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in chosen else Qt.CheckState.Unchecked)
        self.table.setRowCount(0)
        for l in o['lines']:
            self.add_row(l['kind'], l['name'], l['unit'], l['plan_qty'], l['fact_qty'], l['note'], l['catalog_id'])

    def crew_changed(self):
        if self._loading:
            return
        cid = self.crew.currentData()
        if not cid:
            return
        members = set(sd.crew_members(db, cid))
        for i in range(self.workers.count()):
            it = self.workers.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in members else Qt.CheckState.Unchecked)
        row = db.fetchone('SELECT leader_id FROM crews WHERE id=?', (cid,))
        if row and row[0]:
            self.leader.setCurrentIndex(max(0, self.leader.findData(row[0])))

    def object_changed(self):
        if self._loading or self.order_id or self.table.rowCount():
            return
        data = self.object.currentData()
        if data and data[0] in vd.OWNERS and QMessageBox.question(self, 'Наряд', 'Взять плановые объёмы из вкладки «Объёмы» договора?') == QMessageBox.StandardButton.Yes:
            self.from_volumes()

    # --- объёмы наряда
    def add_row(self, kind='Работа', name='', unit='', plan=1, fact=None, note='', catalog_id=None):
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
        for c, v in ((3, plan), (4, fact)):
            it = QTableWidgetItem('' if v in (None, '') else ('%g' % float(v)))
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, c, it)
        self.table.setItem(r, 5, QTableWidgetItem(note))

    def lines(self):
        out = []
        for r in range(self.table.rowCount()):
            cell = lambda c: (self.table.item(r, c).text() if self.table.item(r, c) else '').strip()
            out.append(dict(kind=self.table.cellWidget(r, 0).currentText(), name=cell(1), unit=cell(2), plan_qty=cell(3).replace(',', '.') or 0,
                            fact_qty=cell(4).replace(',', '.'), note=cell(5), catalog_id=self.table.item(r, 1).data(Qt.ItemDataRole.UserRole)))
        return out

    def from_volumes(self):
        data = self.object.currentData()
        if not data or data[0] not in vd.OWNERS:
            QMessageBox.information(self, 'Наряд', 'Выберите договор с вкладкой «Объёмы» (Монтаж ГСВ, Монтаж ГСН, СМР).')
            return
        lines = od.lines_from_volumes(db, *data)
        if not lines:
            QMessageBox.information(self, 'Наряд', 'У договора нет внесённых объёмов.')
            return
        if self.table.rowCount() and QMessageBox.question(self, 'Наряд', 'Заменить строки наряда объёмами договора?') != QMessageBox.StandardButton.Yes:
            return
        self.table.setRowCount(0)
        for l in lines:
            self.add_row(l['kind'], l['name'], l['unit'], l['plan_qty'], None, '', l['catalog_id'])

    def add_catalog(self, kind):
        from .dialogs_common import WorkSelectionDialog, MaterialSelectionDialog
        dlg = (WorkSelectionDialog if kind == 'Работа' else MaterialSelectionDialog)(self)
        if dlg.exec() and dlg.selected:
            self.add_row(kind, dlg.selected['name'], dlg.selected['unit'], 1, None, '', dlg.selected.get('id'))

    def remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    # --- сохранение
    def checked_workers(self):
        return [self.workers.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.workers.count()) if self.workers.item(i).checkState() == Qt.CheckState.Checked]

    def values(self):
        data = self.object.currentData()
        text = self.object.currentText().strip()
        owner = data if data and text == self.object.itemText(self.object.currentIndex()) else None
        return dict(kind=self.kind.currentText(), hazard=self.hazard.currentData() or '', place=self.place.text(), time_from=self.time_from.text(), time_to=self.time_to.text(),
                    supervisor_id=self.supervisor.currentData(), performer_id=self.performer.currentData(), admitter_id=self.admitter.currentData(),
                    safety=self.safety.toPlainText(), ppe=self.ppe.text(), briefing=self.briefing.isChecked(), closing_note=self.closing_note.text(),
                    number=self.number.text().strip(), order_date=_iso(self.date.date()), status=self.status.currentText(),
                    owner_type=owner[0] if owner else '', owner_id=owner[1] if owner else None, object_text=self.object_text.text().strip() or (text if not owner else ''),
                    crew_id=self.crew.currentData(), leader_id=self.leader.currentData(), start_date=_iso(self.start.date()), end_date=_iso(self.end.date()),
                    task=self.task.text(), note=self.note.text(), to_schedule=self.to_schedule.isChecked())

    def save(self, ask=True):
        values, workers = self.values(), self.checked_workers()
        if ask and values['status'] in od.ACTIVE:
            warns = od.warnings(db, workers or sd.crew_members(db, values['crew_id']) if values['crew_id'] else workers, values['start_date'], values['end_date'], self.order_id)
            if warns and QMessageBox.question(self, 'Проверка наряда', 'Обратите внимание:\n\n• ' + '\n• '.join(warns[:10]) + '\n\nВсё равно сохранить наряд?') != QMessageBox.StandardButton.Yes:
                return False
        try:
            self.order_id = od.save_order(db, values, workers, self.lines(), self.order_id)
        except Exception as e:
            QMessageBox.warning(self, 'Наряд', str(e))
            return False
        self.fill(od.get_order(db, self.order_id))
        self.refresh_buttons()
        return True

    def save_clicked(self):
        if self.save():
            self.info.setText('Наряд сохранён.')

    def close_order(self):
        if not self.save(ask=False):
            return
        if QMessageBox.question(self, 'Закрыть наряд', 'Закрыть наряд? Строки без введённого факта будут приняты по плану.') != QMessageBox.StandardButton.Yes:
            return
        try:
            od.close_order(db, self.order_id, {})
        except Exception as e:
            QMessageBox.warning(self, 'Наряд', str(e))
            return
        self.fill(od.get_order(db, self.order_id))
        self.refresh_buttons()
        o = od.get_order(db, self.order_id)
        if o['owner_type'] in vd.OWNERS and QMessageBox.question(self, 'Объёмы договора', 'Внести фактически выполненное в объёмы договора?') == QMessageBox.StandardButton.Yes:
            self.apply_facts()
        self.info.setText('Наряд закрыт.')

    def apply_facts(self):
        if not self.order_id:
            return
        try:
            n = od.apply_facts_to_volumes(db, self.order_id)
        except Exception as e:
            QMessageBox.warning(self, 'Объёмы договора', str(e))
            return
        self.info.setText(f'В объёмы договора внесено строк: {n}.')
        self.refresh_buttons()

    def make_document(self):
        if not self.save(ask=False):
            return
        try:
            path = od.generate(db, self.order_id, str(gd.DATA_DIR / 'Наряды'))
        except Exception as e:
            QMessageBox.warning(self, 'Наряд', str(e))
            return
        self.info.setText('Документ: ' + path)
        from .gsvm_tabs import open_file
        open_file(self, path)

    def refresh_buttons(self):
        o = od.get_order(db, self.order_id) if self.order_id else None
        closed = bool(o) and o['status'] == 'Закрыт'
        self.btn_close_order.setEnabled(bool(o) and o['status'] in od.ACTIVE)
        self.btn_apply.setEnabled(closed and not o['facts_applied'] and o['owner_type'] in vd.OWNERS)
        self.btn_doc.setEnabled(True)


class OrdersView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер, объект, бригада…')
        self.search.textChanged.connect(self.load_data)
        self.status = QComboBox()
        self.status.addItem('Все статусы', '')
        for s in od.STATUSES:
            self.status.addItem(s, s)
        self.status.currentIndexChanged.connect(self.load_data)
        self.kind = QComboBox()
        self.kind.addItem('Все виды', '')
        for k in od.KINDS:
            self.kind.addItem(k, k)
        self.kind.currentIndexChanged.connect(self.load_data)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.kind)
        bar.addWidget(self.status)
        for text, fn, kind in (('Создать наряд', self.add, 'primary'), ('Создать наряд-допуск', self.add_permit, ''), ('Открыть', self.edit, ''), ('Документ', self.document, ''), ('Удалить', self.delete, 'danger')):
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        tpl = QPushButton('Шаблон наряда…')
        menu = QMenu(tpl)
        for kind in od.KINDS:
            sub_menu = menu.addMenu(kind)
            sub_menu.addAction('Открыть текущий шаблон').triggered.connect(lambda _=False, k=kind: self.open_template(k))
            sub_menu.addAction('Выбрать свой шаблон (Word или Excel)…').triggered.connect(lambda _=False, k=kind: self.choose_template(k))
            sub_menu.addAction('Вернуть стандартный').triggered.connect(lambda _=False, k=kind: self.reset_template(k))
        menu.addAction('Какие теги можно использовать').triggered.connect(self.show_tags)
        tpl.setMenu(menu)
        bar.addWidget(tpl)
        layout.addLayout(bar)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['№', 'Дата', 'Вид', 'Объект', 'Бригада', 'Работников', 'Срок', 'Позиций', 'Статус'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 80), (1, 100), (2, 110), (4, 150), (5, 90), (6, 190), (7, 80), (8, 100)):
            self.table.setColumnWidth(col, width)
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table, 1)
        self.total = QLabel('')
        layout.addWidget(self.total)

    def load_data(self, *_):
        rows = od.list_orders(db, self.search.text().strip(), self.status.currentData() or '', kind=self.kind.currentData() or '')
        self.table.setRowCount(len(rows))
        for r, o in enumerate(rows):
            vals = [o['number'], display_date(o['date']), 'Допуск' if o['kind'] == od.KIND_PERMIT else 'Задание', o['object'], o['crew'], o['workers'], f'{display_date(o["start"])} – {display_date(o["end"])}', o['lines'], o['status']]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, o['id'])
                if c == 8:
                    it.setForeground(QColor(STATUS_COLORS.get(o['status'], '#605E5C')))
                self.table.setItem(r, c, it)
        active = sum(1 for o in rows if o['status'] in od.ACTIVE)
        self.total.setText(f'Нарядов: {len(rows)} · в работе: {active}')

    def selected(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def add(self):
        OrderDialog(parent=self).exec()
        self.load_data()

    def add_permit(self):
        OrderDialog(parent=self, preset={'kind': od.KIND_PERMIT}).exec()
        self.load_data()

    def edit(self, *_):
        oid = self.selected()
        if oid:
            OrderDialog(oid, self).exec()
            self.load_data()

    def delete(self):
        oid = self.selected()
        if oid and QMessageBox.question(self, 'Удаление', 'Удалить выбранный наряд?') == QMessageBox.StandardButton.Yes:
            od.delete_order(db, oid)
            self.load_data()

    def document(self):
        oid = self.selected()
        if not oid:
            QMessageBox.information(self, 'Наряд', 'Выберите наряд в таблице.')
            return
        try:
            path = od.generate(db, oid, str(gd.DATA_DIR / 'Наряды'))
        except Exception as e:
            QMessageBox.warning(self, 'Наряд', str(e))
            return
        from .gsvm_tabs import open_file
        open_file(self, path)

    def open_template(self, kind=od.KIND_TASK):
        from .gsvm_tabs import open_file
        open_file(self, od.template_path(db, kind))

    def choose_template(self, kind=od.KIND_TASK):
        path, _ = QFileDialog.getOpenFileName(self, 'Шаблон: ' + kind, '', gd.TEMPLATE_FILTER)
        if path:
            db.set_setting(od.template_setting(kind), path)

    def reset_template(self, kind=od.KIND_TASK):
        db.set_setting(od.template_setting(kind), '')

    def show_tags(self):
        QMessageBox.information(self, 'Теги шаблона наряда', 'Впишите в шаблон (Word или Excel) в фигурных скобках:\n\n' + '\n'.join(f'{{{k}}} — {v}' for k, v in od.TAG_HELP))
