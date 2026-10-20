"""Модуль «Документы»: журнал регистрации входящих, исходящих и внутренних документов и журнал исходящих писем юрлицам."""
from datetime import date

from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                             QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from . import docs_register_domain as dr
from .database import db
from .date_widgets import DateEdit
from .dates import display_date
from .domain_widgets import OptionalDate
from .pagebar import PageBar

STATUS_COLORS = {'Зарегистрирован': '#0284C7', 'На исполнении': '#D97706', 'Исполнен': '#15803D', 'В архиве': '#8A8886'}


def _iso(d):
    return d.toString('yyyy-MM-dd')


class DocRegisterDialog(QDialog):
    def __init__(self, doc_id=None, parent=None, direction='Входящий'):
        super().__init__(parent)
        self.doc_id = doc_id
        self.setWindowTitle('Документ журнала регистрации')
        self.resize(640, 640)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.direction = QComboBox()
        self.direction.addItems(dr.DIRECTIONS)
        self.direction.setCurrentText(direction)
        self.number = QLineEdit()
        self.number.setPlaceholderText('автоматически')
        self.reg_date = DateEdit(QDate.currentDate())
        row = QHBoxLayout()
        for label, w in (('Направление', self.direction), ('№', self.number), ('Дата регистрации', self.reg_date)):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        form.addRow(row)
        self.kind = QComboBox()
        self.kind.setEditable(True)
        self.kind.addItems(dr.KINDS)
        self.doc_number = QLineEdit()
        self.doc_number.setPlaceholderText('номер документа у корреспондента')
        self.doc_date = OptionalDate()
        row = QHBoxLayout()
        for label, w in (('Вид', self.kind), ('Номер документа', self.doc_number), ('Дата документа', self.doc_date)):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        form.addRow(row)
        self.correspondent = QLineEdit()
        self.correspondent.setPlaceholderText('От кого получен / кому адресован')
        form.addRow('Корреспондент', self.correspondent)
        from .legal_entities_view import populate_client_combo
        self.client = QComboBox()
        populate_client_combo(self.client)
        form.addRow('Юрлицо (из справочника)', self.client)
        self.subject = QTextEdit()
        self.subject.setFixedHeight(80)
        form.addRow('Содержание', self.subject)
        self.executor = QLineEdit()
        self.executor.setPlaceholderText('Ответственный исполнитель')
        self.due = OptionalDate()
        self.status = QComboBox()
        self.status.addItems(dr.STATUSES)
        row = QHBoxLayout()
        for label, w in (('Исполнитель', self.executor), ('Срок исполнения', self.due), ('Статус', self.status)):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        form.addRow(row)
        self.answer = QLineEdit()
        self.answer.setPlaceholderText('Номер ответного документа / ссылка на связанный документ')
        form.addRow('Ответ / связь', self.answer)
        self.file = QLineEdit()
        pick = QPushButton('Выбрать файл…')
        pick.clicked.connect(self.pick_file)
        row = QHBoxLayout()
        row.addWidget(self.file, 1)
        row.addWidget(pick)
        form.addRow('Файл', row)
        self.note = QLineEdit()
        form.addRow('Примечание', self.note)
        layout.addLayout(form)
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
        if doc_id:
            self.fill(dr.get_doc(db, doc_id))

    def pick_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Файл документа', '', 'Документы и сканы (*.pdf *.docx *.doc *.xlsx *.xls *.png *.jpg *.jpeg *.tif *.tiff);;Все файлы (*)')
        if path:
            self.file.setText(path)

    def fill(self, d):
        self.direction.setCurrentText(d['direction'])
        self.number.setText(d['reg_number'])
        self.reg_date.setDate(QDate.fromString(d['reg_date'], 'yyyy-MM-dd'))
        self.kind.setCurrentText(d['kind'] or '')
        self.doc_number.setText(d['doc_number'] or '')
        self.doc_date.set_value(d['doc_date'])
        self.correspondent.setText(d['correspondent'])
        from .legal_entities_view import populate_client_combo
        populate_client_combo(self.client, d['client_id'])
        self.subject.setPlainText(d['subject'] or '')
        self.executor.setText(d['executor'] or '')
        self.due.set_value(d['due_date'])
        self.status.setCurrentText(d['status'])
        self.answer.setText(d['answer_ref'] or '')
        self.file.setText(d['file_path'] or '')
        self.note.setText(d['note'] or '')

    def values(self):
        return dict(direction=self.direction.currentText(), reg_number=self.number.text().strip(), reg_date=_iso(self.reg_date.date()), kind=self.kind.currentText().strip(),
                    doc_number=self.doc_number.text(), doc_date=self.doc_date.value(), correspondent=self.correspondent.text(), client_id=self.client.currentData(),
                    subject=self.subject.toPlainText(), executor=self.executor.text(), due_date=self.due.value(), status=self.status.currentText(), answer_ref=self.answer.text(),
                    file_path=self.file.text(), note=self.note.text())

    def save(self):
        try:
            self.doc_id = dr.save_doc(db, self.values(), self.doc_id)
        except Exception as e:
            QMessageBox.warning(self, 'Регистрация документа', str(e))
            return
        self.accept()


class DocRegisterTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер, корреспондент, содержание, исполнитель…')
        self.direction = QComboBox()
        self.direction.addItem('Все документы', '')
        for d in dr.DIRECTIONS:
            self.direction.addItem(d, d)
        self.status = QComboBox()
        self.status.addItem('Все статусы', '')
        for s in dr.STATUSES:
            self.status.addItem(s, s)
        self.overdue = QCheckBox('Просроченные')
        bar.addWidget(self.search, 1)
        for w in (self.direction, self.status, self.overdue):
            bar.addWidget(w)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        for text, fn, kind in (('Зарегистрировать', self.add, 'primary'), ('Изменить', self.edit, ''), ('Исполнен', self.done, ''), ('Открыть файл', self.open_file, ''),
                               ('Подтянуть исходящие юрлиц', self.import_outgoing, ''), ('Удалить', self.delete, 'danger')):
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['Рег. №', 'Дата', 'Вид', 'Корреспондент', 'Содержание', 'Исполнитель', 'Срок', 'Статус', 'Файл'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 100), (1, 95), (2, 120), (3, 190), (5, 140), (6, 95), (7, 120), (8, 60)):
            self.table.setColumnWidth(col, width)
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table, 1)
        self.pager = PageBar(100)
        self.pager.changed.connect(self.load_data)
        layout.addWidget(self.pager)
        self.info = QLabel('')
        layout.addWidget(self.info)
        self.search.textChanged.connect(self.filter_changed)
        self.direction.currentIndexChanged.connect(self.filter_changed)
        self.status.currentIndexChanged.connect(self.filter_changed)
        self.overdue.toggled.connect(self.filter_changed)

    def filter_changed(self, *_):
        self.pager.reset()
        self.load_data()

    def load_data(self, *_):
        total, rows = dr.listing(db, self.search.text().strip(), self.direction.currentData() or '', self.status.currentData() or '', self.overdue.isChecked(),
                                 self.pager.size, self.pager.offset)
        self.pager.set_total(total)
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            subject = (d['subject'] or '').replace('\n', ' ')
            vals = [d['reg_number'], display_date(d['reg_date']), f'{d["direction"]} · {d["kind"]}' if d['kind'] else d['direction'], d['client_name'] or d['correspondent'],
                    subject[:140] + ('…' if len(subject) > 140 else ''), d['executor'], display_date(d['due_date']), d['status'], '●' if d['file_path'] else '']
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, d['id'])
                if c == 7:
                    it.setForeground(QColor(STATUS_COLORS.get(d['status'], '#605E5C')))
                if c == 6 and d['overdue']:
                    it.setForeground(QColor('#DC2626'))
                    it.setToolTip('Срок исполнения прошёл')
                self.table.setItem(r, c, it)
        overdue = dr.listing(db, overdue_only=True, limit=1)[0]
        self.info.setText(f'Документов: {total}' + (f' · просрочено исполнением: {overdue}' if overdue else ''))

    def selected(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def add(self):
        if DocRegisterDialog(parent=self, direction=self.direction.currentData() or 'Входящий').exec():
            self.load_data()

    def edit(self, *_):
        did = self.selected()
        if did and DocRegisterDialog(did, self).exec():
            self.load_data()

    def done(self):
        did = self.selected()
        if did:
            dr.set_status(db, did, 'Исполнен')
            self.load_data()

    def delete(self):
        did = self.selected()
        if did and QMessageBox.question(self, 'Удаление', 'Удалить запись журнала?') == QMessageBox.StandardButton.Yes:
            dr.delete_doc(db, did)
            self.load_data()

    def open_file(self):
        did = self.selected()
        d = dr.get_doc(db, did) if did else None
        if not d or not d['file_path']:
            QMessageBox.information(self, 'Файл', 'У выбранного документа нет прикреплённого файла.')
            return
        from .gsvm_tabs import open_file
        open_file(self, d['file_path'])

    def import_outgoing(self):
        n = dr.import_outgoing(db)
        QMessageBox.information(self, 'Журнал', f'Добавлено исходящих писем юрлицам: {n}.' if n else 'Все исходящие юрлиц уже есть в журнале.')
        self.load_data()


class DocumentsView(QWidget):
    def __init__(self):
        super().__init__()
        from .legal_entities_view import OutgoingLogRegistry
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.register = DocRegisterTab()
        self.outgoing = OutgoingLogRegistry()
        self.tabs.addTab(self.register, 'Регистрация документов')
        self.tabs.addTab(self.outgoing, 'Исходящие юрлицам')
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda *_: self.load_data())

    def load_data(self):
        w = self.tabs.currentWidget()
        if hasattr(w, 'load_data'):
            w.load_data()
