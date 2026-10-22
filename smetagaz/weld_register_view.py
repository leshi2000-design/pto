"""Вкладка «Заявки, письма, протоколы» модуля «Сварщики»."""
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                             QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QTextEdit)

from . import weld_register_domain as wr
from .database import db
from .date_widgets import DateEdit
from .dates import display_date
from .domain_widgets import OptionalDate
from .pagebar import PageBar

STATUS_COLORS = {'Подготовлена': '#8A8886', 'Подготовлено': '#8A8886', 'Подана': '#D97706', 'Отправлено': '#D97706', 'Исполнена': '#15803D', 'Получен ответ': '#15803D',
                 'Действует': '#15803D', 'Заменён': '#8A8886', 'Архив': '#8A8886'}


def _iso(d):
    return d.toString('yyyy-MM-dd')


class WeldItemDialog(QDialog):
    def __init__(self, kind=None, rid=None, parent=None):
        super().__init__(parent)
        self.rid = rid
        item = wr.get_item(db, rid) if rid else None
        kind = item['kind'] if item else (kind or wr.PROTOCOL)
        self.kind = kind
        self.setWindowTitle(kind)
        self.resize(640, 640)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.number = QLineEdit()
        self.number.setPlaceholderText('введите номер')
        self.date = DateEdit(QDate.currentDate())
        self.status = QComboBox()
        self.status.addItems(wr.STATUSES[kind])
        row = QHBoxLayout()
        for label, w in (('№', self.number), ('Дата', self.date), ('Статус', self.status)):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        form.addRow(row)
        party_label = {wr.ZAYAVKA: 'Кому подана (лаборатория, орган)', wr.LETTER: 'Кому / от кого', wr.PROTOCOL: 'Лаборатория, выдавшая протокол'}[kind]
        self.party = QLineEdit()
        form.addRow(party_label, self.party)
        self.subject = QTextEdit()
        self.subject.setFixedHeight(70)
        self.subject.setPlaceholderText({wr.ZAYAVKA: 'Заявка на проведение механических испытаний сварных соединений…', wr.LETTER: 'О чём письмо',
                                         wr.PROTOCOL: 'Протокол механических испытаний сварных соединений (стыков) №…'}[kind])
        form.addRow('Содержание', self.subject)
        self.valid_to = OptionalDate()
        if kind == wr.PROTOCOL:
            form.addRow('Действует до *', self.valid_to)
            self.date.dateChanged.connect(self.suggest_valid)
            if not rid:
                self.suggest_valid()
        self.basis = QLineEdit()
        self.basis.setPlaceholderText('Заявка №… / письмо №… / основание')
        form.addRow('Основание', self.basis)
        self.file = QLineEdit()
        pick = QPushButton('Выбрать файл…')
        pick.clicked.connect(self.pick_file)
        row = QHBoxLayout()
        row.addWidget(self.file, 1)
        row.addWidget(pick)
        form.addRow('Файл / скан', row)
        self.note = QLineEdit()
        form.addRow('Примечание', self.note)
        layout.addLayout(form)
        self.welders = QListWidget()
        self.welders.setMaximumHeight(150)
        if kind == wr.PROTOCOL:
            layout.addWidget(QLabel('<b>Сварщики, на которых распространяется протокол</b>'))
            for wid, name in db.fetchall('SELECT id,name FROM welders ORDER BY name'):
                it = QListWidgetItem(name)
                it.setData(Qt.ItemDataRole.UserRole, wid)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked)
                self.welders.addItem(it)
            layout.addWidget(self.welders)
        bar = QHBoxLayout()
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        cancel = QPushButton('Отмена')
        cancel.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(cancel)
        bar.addWidget(save)
        layout.addLayout(bar)
        if item:
            self.fill(item)

    def suggest_valid(self, *_):
        """Срок действия протокола по умолчанию — месяц от даты (можно изменить)."""
        d = self.date.date()
        self.valid_to.setDate(QDate(wr.add_month(d.toPyDate()).year, wr.add_month(d.toPyDate()).month, wr.add_month(d.toPyDate()).day))

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Файл документа', '', 'Документы и сканы (*.pdf *.docx *.doc *.xlsx *.xls *.png *.jpg *.jpeg *.tif *.tiff);;Все файлы (*)')
        if path:
            self.file.setText(path)

    def fill(self, d):
        self.number.setText(d['number'])
        self.date.setDate(QDate.fromString(d['doc_date'], 'yyyy-MM-dd'))
        self.status.setCurrentText(d['status'])
        self.party.setText(d['counterparty'])
        self.subject.setPlainText(d['subject'])
        if d['valid_to']:
            self.valid_to.set_value(d['valid_to'])
        self.basis.setText(d['basis'])
        self.file.setText(d['file_path'])
        self.note.setText(d['note'])
        chosen = set(d['welders'])
        for i in range(self.welders.count()):
            it = self.welders.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(Qt.ItemDataRole.UserRole) in chosen else Qt.CheckState.Unchecked)

    def values(self):
        return dict(kind=self.kind, number=self.number.text(), doc_date=_iso(self.date.date()), status=self.status.currentText(), counterparty=self.party.text(), subject=self.subject.toPlainText(),
                    valid_to=self.valid_to.value() if self.kind == wr.PROTOCOL else '', basis=self.basis.text(), file_path=self.file.text(), note=self.note.text())

    def save(self):
        welders = [self.welders.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.welders.count()) if self.welders.item(i).checkState() == Qt.CheckState.Checked]
        try:
            self.rid = wr.save_item(db, self.values(), welders, self.rid)
        except Exception as e:
            QMessageBox.warning(self, self.kind, str(e))
            return
        self.accept()


class MoveFromOutgoingDialog(QDialog):
    """Перенос уже введённых в «Исходящих» заявок, писем и протоколов в журнал сварщиков."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Перенести из исходящих документов')
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Отметьте записи «Регистрации исходящих» (модуль «Документы»), которые относятся к сварщикам, и выберите, чем они станут.'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск: номер, кому, содержание…')
        layout.addWidget(self.search)
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel('Станут:'))
        self.kind = QComboBox()
        self.kind.addItems(wr.KINDS)
        self.kind.setCurrentText(wr.PROTOCOL)
        row.addWidget(self.kind)
        self.remove = QCheckBox('Убрать из исходящих после переноса')
        self.remove.setChecked(True)
        row.addWidget(self.remove)
        row.addStretch()
        layout.addLayout(row)
        bar = QHBoxLayout()
        go = QPushButton('Перенести отмеченные')
        go.setProperty('type', 'primary')
        go.clicked.connect(self.go)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(close)
        bar.addWidget(go)
        layout.addLayout(bar)
        self.moved = 0
        self.search.textChanged.connect(self.load)
        self.load()

    def load(self, *_):
        from . import docs_register_domain as dr
        self.list.clear()
        for d in dr.listing(db, dr.OUT, self.search.text().strip(), limit=300)[1]:
            it = QListWidgetItem(f'{d["reg_number"]} · {display_date(d["reg_date"])} · {d["correspondent"]} · {(d["subject"] or "")[:90]}')
            it.setData(Qt.ItemDataRole.UserRole, d['id'])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.list.addItem(it)

    def go(self):
        ids = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count()) if self.list.item(i).checkState() == Qt.CheckState.Checked]
        if not ids:
            QMessageBox.information(self, 'Перенос', 'Отметьте хотя бы одну запись.')
            return
        if self.remove.isChecked() and QMessageBox.question(self, 'Перенос', f'Перенести записей: {len(ids)} — и убрать их из исходящих?') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.moved += wr.move_from_outgoing(db, ids, self.kind.currentText(), self.remove.isChecked())
        except Exception as e:
            QMessageBox.warning(self, 'Перенос', str(e))
            return
        self.load()
        QMessageBox.information(self, 'Перенос', f'Перенесено записей: {self.moved}.')


class WeldRegisterTab(QWidget):
    COLS = ['Вид', '№', 'Дата', 'Кому / лаборатория', 'Содержание', 'Сварщики', 'Действует до', 'Статус', 'Файл']

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.summary = QLabel('')
        self.summary.setStyleSheet('font-weight:600;')
        layout.addWidget(self.summary)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер, кому, содержание, сварщик…')
        self.kind = QComboBox()
        self.kind.addItem('Все виды', '')
        for k in wr.KINDS:
            self.kind.addItem(k, k)
        self.active = QCheckBox('Только действующие протоколы')
        bar.addWidget(self.search, 1)
        bar.addWidget(self.kind)
        bar.addWidget(self.active)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        for text, fn, kind in (('＋ Заявка', lambda: self.add(wr.ZAYAVKA), 'primary'), ('＋ Письмо', lambda: self.add(wr.LETTER), 'primary'), ('＋ Протокол', lambda: self.add(wr.PROTOCOL), 'primary'),
                               ('Изменить', self.edit, ''), ('Оформить протокол заново', self.renew, ''), ('Открыть файл', self.open_file, ''),
                               ('Перенести из исходящих…', self.move, ''), ('Удалить', self.delete, 'danger')):
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 150), (1, 80), (2, 95), (3, 180), (5, 170), (6, 105), (7, 110), (8, 55)):
            self.table.setColumnWidth(col, width)
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table, 1)
        self.pager = PageBar(100)
        self.pager.changed.connect(self.load_data)
        layout.addWidget(self.pager)
        self.search.textChanged.connect(self.filter_changed)
        self.kind.currentIndexChanged.connect(self.filter_changed)
        self.active.toggled.connect(self.filter_changed)

    def filter_changed(self, *_):
        self.pager.reset()
        self.load_data()

    def load_data(self, *_):
        total, rows = wr.listing(db, self.kind.currentData() or '', self.search.text().strip(), '', self.active.isChecked(), self.pager.size, self.pager.offset)
        self.pager.set_total(total)
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            subject = (d['subject'] or '').replace('\n', ' ')
            vals = [d['kind'], d['number'], display_date(d['doc_date']), d['counterparty'], subject[:120] + ('…' if len(subject) > 120 else ''), d['welder_names'],
                    display_date(d['valid_to']), d['status'], '●' if d['file_path'] else '']
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, d['id'])
                if c == 7:
                    it.setForeground(QColor(STATUS_COLORS.get(d['status'], '#605E5C')))
                if c == 6 and d['state']:
                    it.setForeground(QColor('#DC2626' if d['state'] == 'expired' else '#D97706'))
                    it.setToolTip('Срок действия протокола истёк — оформите новый' if d['state'] == 'expired' else 'Протокол истекает в течение 7 дней')
                self.table.setItem(r, c, it)
        ok, soon, expired = wr.summary(db)
        self.summary.setText(f'Действующих протоколов: {ok}' + (f' · истекает в течение 7 дней: {soon}' if soon else '') + (f' · истёк срок, не заменены: {expired}' if expired else ''))

    def selected(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def add(self, kind):
        if WeldItemDialog(kind, parent=self).exec():
            self.load_data()

    def edit(self, *_):
        rid = self.selected()
        if rid and WeldItemDialog(None, rid, self).exec():
            self.load_data()

    def renew(self):
        rid = self.selected()
        if not rid:
            QMessageBox.information(self, 'Протокол', 'Выберите протокол в таблице.')
            return
        try:
            new = wr.renew_protocol(db, rid)
        except Exception as e:
            QMessageBox.warning(self, 'Протокол', str(e))
            return
        self.load_data()
        WeldItemDialog(None, new, self).exec()          # ввести номер и приложить файл нового протокола
        self.load_data()

    def open_file(self):
        rid = self.selected()
        d = wr.get_item(db, rid) if rid else None
        if not d or not d['file_path']:
            QMessageBox.information(self, 'Файл', 'У выбранной записи нет прикреплённого файла.')
            return
        from .gsvm_tabs import open_file
        open_file(self, d['file_path'])

    def move(self):
        MoveFromOutgoingDialog(self).exec()
        self.load_data()

    def delete(self):
        rid = self.selected()
        if rid and QMessageBox.question(self, 'Удаление', 'Удалить запись?') == QMessageBox.StandardButton.Yes:
            wr.delete_item(db, rid)
            self.load_data()
