"""Раздел «Сотрудники»: люди, допуски и удостоверения со сроками, бригады, назначения на объекты и график занятости."""
import calendar
from datetime import date, timedelta

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                              QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from . import staff_domain as sd
from .database import db
from .date_widgets import DateEdit
from .domain_widgets import OptionalDate
from .edit_lock_ui import guarded

STATE_COLORS = {'expired': '#DC2626', 'soon': '#D97706', 'ok': '#15803D', 'none': '#605E5C'}
STATE_TEXT = {'expired': 'просрочен', 'soon': 'скоро истекает', 'ok': 'действует', 'none': 'без срока'}


def _table(headers, stretch=None):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if stretch is not None:
        t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return t


def _fill(table, rows, ids=None, colors=None):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            item = QTableWidgetItem('' if v is None else str(v))
            if c == 0 and ids is not None:
                item.setData(Qt.ItemDataRole.UserRole, ids[r])
            if colors and colors[r] and c == len(row) - 1:
                item.setForeground(QColor(colors[r]))
            table.setItem(r, c, item)


def _selected(table):
    r = table.currentRow()
    item = table.item(r, 0) if r >= 0 else None
    return item.data(Qt.ItemDataRole.UserRole) if item else None


def _find(combo, value):
    """Индекс элемента с данными value (findData не сравнивает кортежи надёжно)."""
    for i in range(combo.count()):
        if combo.itemData(i) == value:
            return i
    return -1


def _iso(qdate):
    return qdate.toString('yyyy-MM-dd')


class DocDialog(QDialog):
    def __init__(self, staff_id, did=None, parent=None):
        super().__init__(parent)
        self.staff_id, self.did = staff_id, did
        self.setWindowTitle('Допуск / удостоверение')
        self.resize(520, 360)
        f = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.setEditable(True)
        self.kind.addItems(sd.DOC_KINDS)
        self.title = QLineEdit()
        self.number = QLineEdit()
        self.issued_by = QLineEdit()
        self.issue_date = OptionalDate()
        self.valid_to = OptionalDate()
        self.file = QLineEdit()
        browse = QPushButton('Файл…')
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.file, 1)
        row.addWidget(browse)
        self.note = QLineEdit()
        for label, w in (('Вид', self.kind), ('Название', self.title), ('Номер', self.number), ('Кем выдан', self.issued_by), ('Дата выдачи', self.issue_date), ('Действует до', self.valid_to)):
            f.addRow(label, w)
        f.addRow('Скан / файл', row)
        f.addRow('Примечание', self.note)
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        if did:
            r = db.fetchone('SELECT kind,title,number,issued_by,issue_date,valid_to,file_path,note FROM staff_docs WHERE id=?', (did,))
            self.kind.setCurrentText(r[0] or '')
            self.title.setText(r[1] or '')
            self.number.setText(r[2] or '')
            self.issued_by.setText(r[3] or '')
            self.issue_date.set_value(r[4] or '')
            self.valid_to.set_value(r[5] or '')
            self.file.setText(r[6] or '')
            self.note.setText(r[7] or '')

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Файл документа')
        if path:
            self.file.setText(path)

    def save(self):
        try:
            sd.save_doc(db, self.staff_id, dict(kind=self.kind.currentText(), title=self.title.text() or self.kind.currentText(), number=self.number.text(), issued_by=self.issued_by.text(),
                                                 issue_date=self.issue_date.value() or '', valid_to=self.valid_to.value() or '', file_path=self.file.text(), note=self.note.text()), self.did)
        except ValueError as e:
            QMessageBox.warning(self, 'Документ не сохранён', str(e))
            return
        self.accept()


@guarded('staff', lambda d: d.sid, 'Карточка сотрудника')
class StaffDialog(QDialog):
    def __init__(self, sid=None, parent=None):
        super().__init__(parent)
        self.sid = sid
        self.setWindowTitle('Сотрудник')
        self.resize(760, 640)
        layout = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit()
        self.role = QComboBox()
        self.role.setEditable(True)
        self.role.addItems(sd.ROLES)
        self.position = QLineEdit()
        self.phone = QLineEdit()
        self.birth = OptionalDate()
        self.hired = OptionalDate()
        self.active = QCheckBox('Работает')
        self.active.setChecked(True)
        self.note = QTextEdit()
        self.note.setMaximumHeight(60)
        for label, w in (('ФИО', self.name), ('Роль', self.role), ('Должность', self.position), ('Телефон', self.phone), ('Дата рождения', self.birth), ('Принят', self.hired), ('', self.active), ('Примечание', self.note)):
            f.addRow(label, w)
        layout.addLayout(f)
        self.welder_note = QLabel()
        self.welder_note.setStyleSheet('color: #605E5C;')
        layout.addWidget(self.welder_note)
        layout.addWidget(QLabel('<b>Допуски и удостоверения</b>'))
        self.docs = _table(['Вид', 'Название', 'Номер', 'Действует до', 'Состояние'], 1)
        layout.addWidget(self.docs, 1)
        bar = QHBoxLayout()
        for text, fn in (('Добавить документ', self.add_doc), ('Изменить', self.edit_doc), ('Удалить', self.del_doc), ('Открыть файл', self.open_file)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        bar.addWidget(save)
        bar.addWidget(close)
        layout.addLayout(bar)
        self.docs.doubleClicked.connect(lambda *_: self.edit_doc())
        if sid:
            s = sd.get_staff(db, sid)
            self.name.setText(s['name'])
            self.role.setCurrentText(s['role'] or '')
            self.position.setText(s['position'] or '')
            self.phone.setText(s['phone'] or '')
            self.birth.set_value(s['birth_date'] or '')
            self.hired.set_value(s['hired_date'] or '')
            self.active.setChecked(bool(s['active']))
            self.note.setPlainText(s['note'] or '')
            if s.get('welder_id'):
                self.welder_note.setText('Сотрудник связан с модулем «Сварщики»: имя и телефон берутся оттуда, срок удостоверения сварщика учитывается в «Допусках».')
                self.name.setReadOnly(True)
        self.load_docs()

    def load_docs(self):
        rows, ids, colors = [], [], []
        for d in (sd.docs(db, self.sid) if self.sid else []):
            state, left = sd.doc_state(d[6])
            rows.append((d[1], d[2], d[3], d[6], STATE_TEXT[state] + (f' ({left} дн.)' if left is not None and state != 'none' else '')))
            ids.append(d[0])
            colors.append(STATE_COLORS[state])
        _fill(self.docs, rows, ids, colors)

    def save(self):
        try:
            self.sid = sd.save_staff(db, dict(name=self.name.text(), role=self.role.currentText(), position=self.position.text(), phone=self.phone.text(), birth_date=self.birth.value() or '',
                                              hired_date=self.hired.value() or '', active=self.active.isChecked(), note=self.note.toPlainText()), self.sid)
        except ValueError as e:
            QMessageBox.warning(self, 'Сотрудник не сохранён', str(e))
            return False
        return True

    def add_doc(self):
        if self.sid or self.save():
            DocDialog(self.sid, None, self).exec()
            self.load_docs()

    def edit_doc(self):
        did = _selected(self.docs)
        if did:
            DocDialog(self.sid, did, self).exec()
            self.load_docs()

    def del_doc(self):
        did = _selected(self.docs)
        if did and QMessageBox.question(self, 'Удалить документ', 'Удалить выбранный документ?') == QMessageBox.StandardButton.Yes:
            sd.delete_doc(db, did)
            self.load_docs()

    def open_file(self):
        did = _selected(self.docs)
        row = db.fetchone('SELECT file_path FROM staff_docs WHERE id=?', (did,)) if did else None
        if row and row[0]:
            from .platform_utils import open_local
            try:
                open_local(row[0])
            except OSError as e:
                QMessageBox.warning(self, 'Файл', str(e))


class CrewDialog(QDialog):
    def __init__(self, cid=None, parent=None):
        super().__init__(parent)
        self.cid = cid
        self.setWindowTitle('Бригада')
        self.resize(480, 520)
        f = QFormLayout(self)
        self.name = QLineEdit()
        self.leader = QComboBox()
        self.leader.addItem('— не назначен —', None)
        self.members = QListWidget()
        people = db.fetchall('SELECT id,name FROM staff WHERE active=1 ORDER BY name')
        for pid, pname in people:
            self.leader.addItem(pname, pid)
            it = QListWidgetItem(pname)
            it.setData(Qt.ItemDataRole.UserRole, pid)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.members.addItem(it)
        self.active = QCheckBox('Действующая')
        self.active.setChecked(True)
        f.addRow('Название', self.name)
        f.addRow('Бригадир', self.leader)
        f.addRow('Состав', self.members)
        f.addRow('', self.active)
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        if cid:
            row = db.fetchone('SELECT name,leader_id,active FROM crews WHERE id=?', (cid,))
            self.name.setText(row[0])
            self.leader.setCurrentIndex(max(0, self.leader.findData(row[1])))
            self.active.setChecked(bool(row[2]))
            chosen = set(sd.crew_members(db, cid))
            for i in range(self.members.count()):
                if self.members.item(i).data(Qt.ItemDataRole.UserRole) in chosen:
                    self.members.item(i).setCheckState(Qt.CheckState.Checked)

    def save(self):
        ids = [self.members.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.members.count()) if self.members.item(i).checkState() == Qt.CheckState.Checked]
        try:
            sd.save_crew(db, self.name.text(), self.leader.currentData(), ids, self.cid, active=self.active.isChecked())
        except ValueError as e:
            QMessageBox.warning(self, 'Бригада не сохранена', str(e))
            return
        self.accept()


class AssignDialog(QDialog):
    """Назначить сотрудника или бригаду на объект на период; показывает пересечения и просроченные допуски."""
    def __init__(self, aid=None, parent=None, owner=None):
        super().__init__(parent)
        self.aid = aid
        self.setWindowTitle('Назначение на объект')
        self.resize(620, 520)
        f = QFormLayout(self)
        self.who = QComboBox()
        for crew in sd.crews(db, True):
            self.who.addItem(f'Бригада «{crew[1]}» ({crew[4]} чел.)', ('crew', crew[0]))
        for s in sd.staff_list(db, True):
            self.who.addItem(f'{s[1]} — {s[2]}', ('staff', s[0]))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти объект: номер, адрес, клиент…')
        self.search.textChanged.connect(self.load_objects)
        self.object = QComboBox()
        self.free = QLineEdit()
        self.free.setPlaceholderText('или впишите объект вручную')
        self.start = DateEdit(QDate.currentDate())
        self.end = DateEdit(QDate.currentDate().addDays(6))
        self.note = QLineEdit()
        self.info = QLabel()
        self.info.setWordWrap(True)
        for label, w in (('Кто', self.who), ('Поиск объекта', self.search), ('Объект', self.object), ('', self.free), ('С', self.start), ('По', self.end), ('Примечание', self.note)):
            f.addRow(label, w)
        f.addRow(self.info)
        ok = QPushButton('Назначить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        self.object.currentIndexChanged.connect(self.show_readiness)
        self.load_objects()
        if owner:
            i = _find(self.object, owner)
            if i >= 0:
                self.object.setCurrentIndex(i)
        if aid:
            r = db.fetchone('SELECT staff_id,crew_id,owner_type,owner_id,object_text,start_date,end_date,note FROM staff_assign WHERE id=?', (aid,))
            self.who.setCurrentIndex(max(0, _find(self.who, ('staff', r[0]) if r[0] else ('crew', r[1]))))
            self.object.setCurrentIndex(max(0, _find(self.object, (r[2], r[3]))))
            self.free.setText(r[4] or '')
            self.start.setDate(QDate.fromString(r[5], 'yyyy-MM-dd'))
            self.end.setDate(QDate.fromString(r[6], 'yyyy-MM-dd'))
            self.note.setText(r[7] or '')

    def show_readiness(self, *_):
        obj = self.object.currentData()
        issues = sd.readiness(db, obj[0], obj[1]) if obj else []
        icon = {'error': '⛔', 'warn': '⚠', 'info': 'ℹ'}
        self.info.setText(('<b>Готовность объекта:</b><br>' + '<br>'.join(f'{icon[s]} {t}' for s, t in issues[:8]) + ('<br>…' if len(issues) > 8 else '')) if issues else ('Замечаний по готовности объекта нет.' if obj else ''))

    def load_objects(self):
        keep = self.object.currentData()
        self.object.clear()
        self.object.addItem('— объект не выбран —', None)
        for table, rid, label in sd.objects(db, self.search.text().strip()):
            self.object.addItem(label, (table, rid))
        if keep:
            self.object.setCurrentIndex(max(0, _find(self.object, keep)))

    def save(self):
        kind, ident = self.who.currentData()
        obj = self.object.currentData() or ('', None)
        args = dict(start=_iso(self.start.date()), end=_iso(self.end.date()), staff_id=ident if kind == 'staff' else None, crew_id=ident if kind == 'crew' else None,
                    owner_type=obj[0], owner_id=obj[1], object_text=self.free.text(), note=self.note.text())
        try:
            clash = sd.conflicts(db, args['staff_id'], args['crew_id'], args['start'], args['end'], self.aid)
            members = sd.members_of(db, args['staff_id'], args['crew_id'])
            bad = [(db.fetchone('SELECT name FROM staff WHERE id=?', (m,))[0], sd.expired_for(db, m, self.end.date().toPyDate())) for m in members]
            bad = [(n, docs) for n, docs in bad if docs]
            lines = [f'• {n} уже на объекте «{o}» ({s} — {e})' for n, o, s, e in clash] + [f'• {n}: просрочено — {", ".join(d)}' for n, d in bad]
            if lines and QMessageBox.question(self, 'Проверьте назначение', 'Обнаружено:\n' + '\n'.join(lines) + '\n\nВсё равно назначить?') != QMessageBox.StandardButton.Yes:
                return
            sd.add_assignment(db, aid=self.aid, **args)
        except ValueError as e:
            QMessageBox.warning(self, 'Назначение не сохранено', str(e))
            return
        self.accept()


class StaffView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        # сотрудники
        page = QWidget()
        v = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('ФИО, должность, телефон…')
        self.only_active = QCheckBox('Только работающие')
        self.only_active.setChecked(True)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.only_active)
        for text, fn in (('Добавить', self.add), ('Изменить', self.edit), ('Удалить', self.delete), ('Подтянуть сварщиков', self.sync)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text == 'Добавить':
                b.setProperty('type', 'primary')
            bar.addWidget(b)
        v.addLayout(bar)
        self.table = _table(['ФИО', 'Роль', 'Должность', 'Телефон', 'Бригада', 'Ближайший срок'], 0)
        v.addWidget(self.table, 1)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        self.tabs.addTab(page, 'Сотрудники')
        # допуски
        page = QWidget()
        v = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.horizon = QSpinBox()
        self.horizon.setRange(7, 365)
        self.horizon.setValue(sd.WARN_DAYS)
        self.horizon.setSuffix(' дн.')
        self.only_problem = QCheckBox('Только просроченные и истекающие')
        self.only_problem.setChecked(True)
        bar.addWidget(QLabel('Предупреждать за'))
        bar.addWidget(self.horizon)
        bar.addWidget(self.only_problem)
        bar.addStretch()
        v.addLayout(bar)
        self.deadlines = _table(['Сотрудник', 'Документ', 'Номер', 'Действует до', 'Состояние'], 1)
        self.deadlines.doubleClicked.connect(self.open_deadline)
        v.addWidget(self.deadlines, 1)
        self.tabs.addTab(page, 'Допуски и сроки')
        # бригады
        page = QWidget()
        v = QVBoxLayout(page)
        bar = QHBoxLayout()
        for text, fn in (('Новая бригада', self.add_crew), ('Изменить', self.edit_crew), ('Удалить', self.del_crew)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        self.crews = _table(['Бригада', 'Бригадир', 'Человек', 'Состав', 'Статус'], 3)
        self.crews.doubleClicked.connect(lambda *_: self.edit_crew())
        v.addWidget(self.crews, 1)
        self.tabs.addTab(page, 'Бригады')
        # назначения
        page = QWidget()
        v = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.a_search = QLineEdit()
        self.a_search.setPlaceholderText('Кто, объект…')
        bar.addWidget(self.a_search, 1)
        for text, fn in (('Назначить', self.add_assign), ('Изменить', self.edit_assign), ('Удалить', self.del_assign)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text == 'Назначить':
                b.setProperty('type', 'primary')
            bar.addWidget(b)
        v.addLayout(bar)
        self.assign = _table(['С', 'По', 'Кто', 'Объект', 'Примечание'], 3)
        self.assign.doubleClicked.connect(lambda *_: self.edit_assign())
        v.addWidget(self.assign, 1)
        self.tabs.addTab(page, 'Назначения')
        # график
        page = QWidget()
        v = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.prev_m, self.next_m = QPushButton('◀'), QPushButton('▶')
        self.month_label = QLabel()
        self.month_label.setStyleSheet('font-weight: 600;')
        self.month = date.today().replace(day=1)
        self.prev_m.clicked.connect(lambda: self.shift_month(-1))
        self.next_m.clicked.connect(lambda: self.shift_month(1))
        for w in (self.prev_m, self.month_label, self.next_m):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(QLabel('Закрашено — сотрудник назначен на объект (подробности во всплывающей подсказке); красным — просроченный допуск.'))
        v.addLayout(bar)
        self.grid = QTableWidget(0, 0)
        self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        v.addWidget(self.grid, 1)
        self.tabs.addTab(page, 'График')
        # загрузка
        page = QWidget()
        v = QVBoxLayout(page)
        bar = QHBoxLayout()
        today = QDate.currentDate()
        self.l_from = DateEdit(QDate(today.year(), today.month(), 1))
        self.l_to = DateEdit(QDate(today.year(), today.month(), today.daysInMonth()))
        self.only_free = QCheckBox('Только свободные')
        for w in (QLabel('Период с'), self.l_from, QLabel('по'), self.l_to, self.only_free):
            bar.addWidget(w)
        bar.addStretch()
        v.addLayout(bar)
        self.load_table = _table(['Сотрудник', 'Роль', 'Загрузка', 'Рабочих дней занят', 'Дней на двух объектах', 'Допуски', 'Объекты'], 6)
        v.addWidget(self.load_table, 2)
        v.addWidget(QLabel('<b>Пересечения назначений</b> — человек в одни и те же дни назначен на разные объекты'))
        self.overlap_table = _table(['Сотрудник', 'С', 'По', 'Объекты'], 3)
        v.addWidget(self.overlap_table, 1)
        self.tabs.addTab(page, 'Загрузка')
        for w in (self.l_from, self.l_to):
            w.dateChanged.connect(self.load_data)
        self.only_free.toggled.connect(self.load_data)
        # готовность
        page = QWidget()
        v = QVBoxLayout(page)
        bar = QHBoxLayout()
        self.ready_days = QSpinBox()
        self.ready_days.setRange(1, 120)
        self.ready_days.setValue(14)
        self.ready_days.setSuffix(' дн.')
        self.ready_days.valueChanged.connect(self.load_data)
        bar.addWidget(QLabel('Работы начинаются в ближайшие'))
        bar.addWidget(self.ready_days)
        bar.addStretch()
        v.addLayout(bar)
        self.ready_table = _table(['Начало', 'Объект', 'Замечаний', 'Главное'], 3)
        self.ready_table.itemSelectionChanged.connect(self.show_issues)
        v.addWidget(self.ready_table, 2)
        self.ready_details = QTextEdit()
        self.ready_details.setReadOnly(True)
        self.ready_details.setPlaceholderText('Выберите объект, чтобы увидеть, что не готово к началу работ')
        v.addWidget(self.ready_details, 2)
        self.ready_rows = []
        self.tabs.addTab(page, 'Готовность к работам')
        for w in (self.search, self.a_search):
            w.textChanged.connect(self.load_data)
        self.only_active.toggled.connect(self.load_data)
        self.horizon.valueChanged.connect(self.load_data)
        self.only_problem.toggled.connect(self.load_data)
        self.tabs.currentChanged.connect(lambda _: self.load_data())

    # --- загрузка ---
    def load_data(self, *_):
        i = self.tabs.currentIndex()
        if i == 0:
            soon = {}
            for r in sd.all_deadlines(db):
                soon.setdefault(r['staff_id'], r)
            rows, ids, colors = [], [], []
            for sid, name, role, pos, phone, active, crew in sd.staff_list(db, self.only_active.isChecked(), self.search.text().strip()):
                r = soon.get(sid)
                rows.append((name + ('' if active else ' (не работает)'), role, pos, phone, crew, f'{r["title"]} до {r["valid_to"]} — {STATE_TEXT[r["state"]]}' if r else ''))
                ids.append(sid)
                colors.append(STATE_COLORS[r['state']] if r else None)
            _fill(self.table, rows, ids, colors)
        elif i == 1:
            self.deadline_rows = [r for r in sd.all_deadlines(db, warn=self.horizon.value()) if not self.only_problem.isChecked() or r['state'] in ('expired', 'soon')]
            _fill(self.deadlines, [(r['staff'], r['title'], r['number'], r['valid_to'], f'{STATE_TEXT[r["state"]]} ({r["left"]} дн.)') for r in self.deadline_rows],
                  [r['staff_id'] for r in self.deadline_rows], [STATE_COLORS[r['state']] for r in self.deadline_rows])
        elif i == 2:
            rows = sd.crews(db)
            members = {r[0]: ', '.join(x[0] for x in db.fetchall('SELECT s.name FROM crew_members m JOIN staff s ON s.id=m.staff_id WHERE m.crew_id=? ORDER BY s.name', (r[0],))) for r in rows}
            _fill(self.crews, [(r[1], r[2], r[4], members[r[0]], 'действует' if r[3] else 'не действует') for r in rows], [r[0] for r in rows])
        elif i == 3:
            rows = sd.assignments(db, search=self.a_search.text().strip())
            _fill(self.assign, [(r['start'], r['end'], r['who'], r['object'], r['note']) for r in rows], [r['id'] for r in rows])
        elif i == 4:
            self.load_grid()
        elif i == 5:
            a, b = self.l_from.date().toPyDate(), self.l_to.date().toPyDate()
            rows = [r for r in sd.workload(db, a, b) if not self.only_free.isChecked() or r['free']]
            colors = ['#DC2626' if r['overlap_days'] or r['expired'] else ('#15803D' if r['free'] else None) for r in rows]
            _fill(self.load_table, [(r['name'], r['role'], f'{r["percent"]}%' + (' · свободен' if r['free'] else ''), f'{r["busy"]} из {r["workdays"]}', r['overlap_days'] or '',
                                     ', '.join(r['expired']), '; '.join(r['objects'])) for r in rows], [r['staff_id'] for r in rows])
            for k, color in enumerate(colors):
                if color:
                    self.load_table.item(k, 0).setForeground(QColor(color))
            ov = sd.overlaps(db, a, b)
            _fill(self.overlap_table, [(n, s.strftime('%d.%m.%Y'), e.strftime('%d.%m.%Y'), ' ⟷ '.join(o)) for n, s, e, o in ov])
        else:
            self.ready_rows = sd.upcoming(db, self.ready_days.value())
            order = {'error': 0, 'warn': 1, 'info': 2}
            self.ready_rows.sort(key=lambda r: (min([order[s] for s, _t in r['issues']] or [3]), r['start']))
            _fill(self.ready_table, [(r['start'], r['label'], len(r['issues']) or 'всё готово', (r['issues'][0][1] if r['issues'] else '')) for r in self.ready_rows])
            for k, r in enumerate(self.ready_rows):
                sev = min([order[s] for s, _t in r['issues']] or [3])
                self.ready_table.item(k, 2).setForeground(QColor({0: '#DC2626', 1: '#D97706', 2: '#605E5C', 3: '#15803D'}[sev]))
            self.ready_details.clear()

    def show_issues(self):
        r = self.ready_table.currentRow()
        if not 0 <= r < len(self.ready_rows):
            return
        icon = {'error': '⛔', 'warn': '⚠', 'info': 'ℹ'}
        item = self.ready_rows[r]
        lines = [f'<b>{item["label"]}</b> — начало {item["start"] or "не указано"}'] + [f'{icon[s]} {t}' for s, t in item['issues']] if item['issues'] else [f'<b>{item["label"]}</b>: замечаний нет']
        self.ready_details.setHtml('<br>'.join(lines))

    def load_grid(self):
        first = self.month
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        self.month_label.setText(first.strftime('%m.%Y'))
        grid, names = sd.schedule(db, first, last)
        people = [(r[0], r[1]) for r in sd.staff_list(db, True)]
        days = (last - first).days + 1
        self.grid.clear()
        self.grid.setRowCount(len(people))
        self.grid.setColumnCount(days)
        self.grid.setHorizontalHeaderLabels([str(d + 1) for d in range(days)])
        self.grid.setVerticalHeaderLabels([n for _i, n in people])
        for c in range(days):
            self.grid.setColumnWidth(c, 30)
        deadlines = {}
        for r in sd.all_deadlines(db):
            if r['state'] == 'expired':
                deadlines.setdefault(r['staff_id'], _d(r['valid_to']))
        for row, (sid, _n) in enumerate(people):
            for c in range(days):
                day = first + timedelta(days=c)
                labels = grid.get(sid, {}).get(day.isoformat())
                item = QTableWidgetItem('')
                if labels:
                    expired = sid in deadlines and deadlines[sid] and day > deadlines[sid]
                    item.setBackground(QColor('#DC2626' if expired else '#0D9488'))
                    item.setToolTip('\n'.join(labels) + ('\nДопуск просрочен!' if expired else ''))
                elif day.weekday() >= 5:
                    item.setBackground(QColor('#EDEBE9'))
                self.grid.setItem(row, c, item)

    def shift_month(self, delta):
        m = self.month.month - 1 + delta
        self.month = date(self.month.year + m // 12, m % 12 + 1, 1)
        self.load_grid()

    # --- действия ---
    def add(self):
        StaffDialog(None, self).exec()
        self.load_data()

    def edit(self):
        sid = _selected(self.table)
        if sid:
            StaffDialog(sid, self).exec()
            self.load_data()

    def delete(self):
        sid = _selected(self.table)
        if sid and QMessageBox.question(self, 'Удалить сотрудника', 'Удалить сотрудника вместе с его документами и назначениями?\nЕсли он просто уволился, лучше снять отметку «Работает».') == QMessageBox.StandardButton.Yes:
            sd.delete_staff(db, sid)
            self.load_data()

    def sync(self):
        n = sd.sync_welders(db)
        self.load_data()
        QMessageBox.information(self, 'Сварщики', f'Добавлено сотрудников: {n}. Имена и телефоны остальных обновлены из модуля «Сварщики».')

    def open_deadline(self, *_):
        sid = _selected(self.deadlines)
        if sid:
            StaffDialog(sid, self).exec()
            self.load_data()

    def add_crew(self):
        CrewDialog(None, self).exec()
        self.load_data()

    def edit_crew(self):
        cid = _selected(self.crews)
        if cid:
            CrewDialog(cid, self).exec()
            self.load_data()

    def del_crew(self):
        cid = _selected(self.crews)
        if cid and QMessageBox.question(self, 'Удалить бригаду', 'Удалить бригаду и её назначения? Сотрудники останутся.') == QMessageBox.StandardButton.Yes:
            sd.delete_crew(db, cid)
            self.load_data()

    def add_assign(self):
        AssignDialog(None, self).exec()
        self.load_data()

    def edit_assign(self):
        aid = _selected(self.assign)
        if aid:
            AssignDialog(aid, self).exec()
            self.load_data()

    def del_assign(self):
        aid = _selected(self.assign)
        if aid and QMessageBox.question(self, 'Удалить назначение', 'Удалить выбранное назначение?') == QMessageBox.StandardButton.Yes:
            sd.delete_assignment(db, aid)
            self.load_data()


def _d(iso):
    return sd._day(iso)
