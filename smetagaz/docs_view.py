"""Модуль «Документы»: регистрация исходящих, регистрация приказов, прочие документы по организации."""
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

STATUS_COLORS = {'Зарегистрирован': '#0284C7', 'Отправлен': '#D97706', 'Получен ответ': '#15803D', 'Действует': '#15803D', 'Исполнен': '#0284C7', 'Отменён': '#8A8886', 'В архиве': '#8A8886'}
# подписи полей и видимость по журналам: (подпись, показывать)
FIELDS = {
    dr.OUT: dict(party='Кому адресован', client=True, doc_number=None, doc_date=None, executor='Подготовил', due='Срок ответа', answer='Ответ получен (№, дата)', problem='ответ не получен в срок',
                 title='Исходящий документ', new='Зарегистрировать исходящий'),
    dr.ORDER: dict(party=None, client=False, doc_number=None, doc_date='Вступает в силу', executor='Ответственный за исполнение', due='Срок исполнения', answer='С приказом ознакомлены',
                   problem='срок исполнения прошёл', title='Приказ', new='Зарегистрировать приказ'),
    dr.OTHER: dict(party='Организация / орган', client=True, doc_number='Номер документа', doc_date='Дата документа', executor='Ответственный за хранение', due='Действует до', answer=None,
                   problem='срок действия истёк', title='Документ организации', new='Зарегистрировать документ'),
}
COLUMNS = {
    dr.OUT: ['Рег. №', 'Дата', 'Вид', 'Кому', 'Содержание', 'Подготовил', 'Срок ответа', 'Статус', 'Файл'],
    dr.ORDER: ['Рег. №', 'Дата', 'Вид приказа', 'Содержание', 'Ответственный', 'Срок', 'Статус', 'Файл'],
    dr.OTHER: ['Рег. №', 'Дата рег.', 'Вид', 'Организация / орган', 'Содержание', 'Номер, дата документа', 'Действует до', 'Статус', 'Файл'],
}


def _iso(d):
    return d.toString('yyyy-MM-dd')


class DocRegisterDialog(QDialog):
    def __init__(self, register, doc_id=None, parent=None):
        super().__init__(parent)
        self.register, self.doc_id = register, doc_id
        self.cfg, self.f = dr.REGISTERS[register], FIELDS[register]
        self.setWindowTitle(self.f['title'])
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.number = QLineEdit()
        self.number.setPlaceholderText('введите исходящий номер' if register == dr.OUT else 'автоматически')
        self.reg_date = DateEdit(QDate.currentDate())
        self.status = QComboBox()
        self.status.addItems(self.cfg['statuses'])
        row = QHBoxLayout()
        for label, w in (('№ *' if register == dr.OUT else '№', self.number), ('Дата регистрации', self.reg_date), ('Статус', self.status)):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        form.addRow(row)
        self.kind = QComboBox()
        self.kind.setEditable(True)
        self.kind.addItems(self.cfg['kinds'])
        form.addRow('Вид', self.kind)
        self.correspondent = QLineEdit()
        self.doc_number = QLineEdit()
        self.doc_date = OptionalDate()
        self.client = QComboBox()
        from .legal_entities_view import populate_client_combo
        populate_client_combo(self.client)
        if self.f['party']:
            form.addRow(self.f['party'], self.correspondent)
        if self.f['client']:
            form.addRow('Юрлицо из справочника', self.client)
        if self.f['doc_number']:
            row = QHBoxLayout()
            row.addWidget(self.doc_number, 1)
            row.addWidget(QLabel(self.f['doc_date']))
            row.addWidget(self.doc_date)
            form.addRow(self.f['doc_number'], row)
        elif self.f['doc_date']:
            form.addRow(self.f['doc_date'], self.doc_date)
        self.subject = QTextEdit()
        self.subject.setFixedHeight(90)
        form.addRow('Содержание', self.subject)
        self.executor = QLineEdit()
        form.addRow(self.f['executor'], self.executor)
        self.due = OptionalDate()
        form.addRow(self.f['due'], self.due)
        self.answer = QLineEdit()
        if self.f['answer']:
            form.addRow(self.f['answer'], self.answer)
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
        self.number.setText(d['reg_number'])
        self.reg_date.setDate(QDate.fromString(d['reg_date'], 'yyyy-MM-dd'))
        self.status.setCurrentText(d['status'])
        self.kind.setCurrentText(d['kind'] or '')
        self.correspondent.setText(d['correspondent'])
        self.doc_number.setText(d['doc_number'] or '')
        self.doc_date.set_value(d['doc_date'])
        from .legal_entities_view import populate_client_combo
        populate_client_combo(self.client, d['client_id'])
        self.subject.setPlainText(d['subject'] or '')
        self.executor.setText(d['executor'] or '')
        self.due.set_value(d['due_date'])
        self.answer.setText(d['answer_ref'] or '')
        self.file.setText(d['file_path'] or '')
        self.note.setText(d['note'] or '')

    def values(self):
        party = self.correspondent.text().strip()
        if not party and self.client.currentData() and self.client.currentText():
            party = self.client.currentText()
        return dict(register=self.register, reg_number=self.number.text().strip(), reg_date=_iso(self.reg_date.date()), status=self.status.currentText(), kind=self.kind.currentText().strip(),
                    correspondent=party, client_id=self.client.currentData() if self.f['client'] else None, doc_number=self.doc_number.text(), doc_date=self.doc_date.value(),
                    subject=self.subject.toPlainText(), executor=self.executor.text(), due_date=self.due.value(), answer_ref=self.answer.text(), file_path=self.file.text(), note=self.note.text())

    def save(self):
        try:
            self.doc_id = dr.save_doc(db, self.values(), self.doc_id)
        except Exception as e:
            QMessageBox.warning(self, self.f['title'], str(e))
            return
        self.accept()


class RegisterTab(QWidget):
    def __init__(self, register):
        super().__init__()
        self.register = register
        self.cfg, self.f = dr.REGISTERS[register], FIELDS[register]
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер, вид, содержание, исполнитель…')
        self.status = QComboBox()
        self.status.addItem('Все статусы', '')
        for s in self.cfg['statuses']:
            self.status.addItem(s, s)
        self.problems = QCheckBox('Просроченные' if register != dr.OTHER else 'Истёкшие')
        bar.addWidget(self.search, 1)
        bar.addWidget(self.status)
        bar.addWidget(self.problems)
        layout.addLayout(bar)
        bar = QHBoxLayout()
        buttons = [(self.f['new'], self.add, 'primary'), ('Изменить', self.edit, ''), ('Открыть файл', self.open_file, '')]
        if register == dr.OUT:
            buttons.append(('Получен ответ', lambda: self.mark('Получен ответ'), ''))
        elif register == dr.ORDER:
            buttons.append(('Исполнен', lambda: self.mark('Исполнен'), ''))
            buttons.append(('Отменить приказ', lambda: self.mark('Отменён'), ''))
        buttons.append(('В архив', lambda: self.mark('В архиве'), ''))
        if register == dr.OUT:
            buttons.append(('Подтянуть исходящие юрлиц', self.import_outgoing, ''))
        buttons.append(('Удалить', self.delete, 'danger'))
        for text, fn, kind in buttons:
            b = QPushButton(text)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        layout.addLayout(bar)
        headers = COLUMNS[register]
        self.table = QTableWidget(0, len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(headers.index('Содержание'), QHeaderView.ResizeMode.Stretch)
        for col in range(len(headers)):
            if col != headers.index('Содержание'):
                self.table.setColumnWidth(col, 60 if headers[col] == 'Файл' else 120 if headers[col] in ('Рег. №', 'Статус') else 150)
        self.table.doubleClicked.connect(self.edit)
        layout.addWidget(self.table, 1)
        self.pager = PageBar(100)
        self.pager.changed.connect(self.load_data)
        layout.addWidget(self.pager)
        self.info = QLabel('')
        layout.addWidget(self.info)
        self.search.textChanged.connect(self.filter_changed)
        self.status.currentIndexChanged.connect(self.filter_changed)
        self.problems.toggled.connect(self.filter_changed)

    def filter_changed(self, *_):
        self.pager.reset()
        self.load_data()

    def row_values(self, d):
        subject = (d['subject'] or '').replace('\n', ' ')
        short = subject[:140] + ('…' if len(subject) > 140 else '')
        file = '●' if d['file_path'] else ''
        who = d['client_name'] or d['correspondent']
        if self.register == dr.OUT:
            return [d['reg_number'], display_date(d['reg_date']), d['kind'], who, short, d['executor'], display_date(d['due_date']), d['status'], file], 6, 7
        if self.register == dr.ORDER:
            return [d['reg_number'], display_date(d['reg_date']), d['kind'], short, d['executor'], display_date(d['due_date']), d['status'], file], 5, 6
        doc = ' '.join(x for x in (d['doc_number'], display_date(d['doc_date']) if d['doc_date'] else '') if x)
        return [d['reg_number'], display_date(d['reg_date']), d['kind'], who, short, doc, display_date(d['due_date']), d['status'], file], 6, 7

    def load_data(self, *_):
        total, rows = dr.listing(db, self.register, self.search.text().strip(), self.status.currentData() or '', self.problems.isChecked(), self.pager.size, self.pager.offset)
        self.pager.set_total(total)
        self.table.setRowCount(len(rows))
        for r, d in enumerate(rows):
            vals, due_col, status_col = self.row_values(d)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 0:
                    it.setData(Qt.ItemDataRole.UserRole, d['id'])
                if c == status_col:
                    it.setForeground(QColor(STATUS_COLORS.get(d['status'], '#605E5C')))
                if c == due_col and d['state']:
                    it.setForeground(QColor('#DC2626' if d['state'] == 'overdue' else '#D97706'))
                    it.setToolTip(self.f['problem'] if d['state'] == 'overdue' else 'Срок действия истекает в течение 30 дней')
                self.table.setItem(r, c, it)
        bad = dr.problems(db, self.register)
        self.info.setText(f'Записей: {total}' + (f' · {self.f["problem"]}: {bad}' if bad else ''))

    def selected(self):
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def add(self):
        if DocRegisterDialog(self.register, parent=self).exec():
            self.load_data()

    def edit(self, *_):
        did = self.selected()
        if did and DocRegisterDialog(self.register, did, self).exec():
            self.load_data()

    def mark(self, status):
        did = self.selected()
        if did:
            dr.set_status(db, did, status)
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
            QMessageBox.information(self, 'Файл', 'У выбранной записи нет прикреплённого файла.')
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
        if db.get_setting('docs_outgoing_imported', '') != '1':      # журнал исходящих юрлиц переносится сюда один раз
            try:
                dr.import_outgoing(db)
                db.set_setting('docs_outgoing_imported', '1')
            except Exception:
                pass
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        for register in (dr.OUT, dr.ORDER, dr.OTHER):
            self.tabs.addTab(RegisterTab(register), dr.REGISTERS[register]['title'])
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda *_: self.load_data())

    def load_data(self):
        w = self.tabs.currentWidget()
        if hasattr(w, 'load_data'):
            w.load_data()
