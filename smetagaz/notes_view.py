"""Интерфейс заметок: вкладка «Заметки» в разделе «Сегодня» и окно заметок карточки договора."""
from datetime import date

from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QComboBox, QPushButton, QListWidget, QListWidgetItem,
                              QSplitter, QMessageBox, QDateEdit)
from PyQt6.QtCore import Qt, QDate, pyqtSignal

from .database import db
from . import notes_domain as nd
from .pagebar import PageBar


class NotesPanel(QWidget):
    """Список заметок слева, редактор справа. link=(таблица, id) — режим одной карточки: показываются только её заметки, привязка фиксирована."""
    changed = pyqtSignal()

    def __init__(self, link=None, parent=None):
        super().__init__(parent)
        self.fixed_link = link
        self.note_id = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.scope = QComboBox()
        for key, text in (('all', 'Все заметки'), ('free', 'Независимые'), ('linked', 'Привязанные')):
            self.scope.addItem(text, key)
        self.scope.currentIndexChanged.connect(self.search_changed)
        self.scope.setVisible(not link)
        bar.addWidget(self.scope)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск по заметкам…')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.search_changed)
        bar.addWidget(self.search, 1)
        new = QPushButton('➕ Новая заметка')
        new.setProperty('type', 'primary')
        new.clicked.connect(lambda: self.new_note())
        bar.addWidget(new)
        layout.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.on_select)
        ll.addWidget(self.list, 1)
        self.pager = PageBar(60)
        self.pager.changed.connect(self.load_list)
        ll.addWidget(self.pager)
        split.addWidget(left)
        editor = QWidget()
        el = QVBoxLayout(editor)
        self.title = QLineEdit()
        self.title.setPlaceholderText('Заголовок')
        el.addWidget(self.title)
        row = QHBoxLayout()
        row.addWidget(QLabel('Дата:'))
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat('dd.MM.yyyy')
        row.addWidget(self.day)
        row.addStretch()
        el.addLayout(row)
        self.link_row = QWidget()
        lr = QHBoxLayout(self.link_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.addWidget(QLabel('Привязать к:'))
        self.section = QComboBox()
        self.section.addItem('— независимая заметка —', '')
        for table, name in nd.LINK_TABLES.items():
            self.section.addItem(name, table)
        self.section.currentIndexChanged.connect(lambda *_: self.fill_records())
        lr.addWidget(self.section)
        self.record = QComboBox()
        self.record.setMinimumWidth(240)
        self.record.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        lr.addWidget(self.record, 1)
        self.open_btn = QPushButton('Открыть карточку')
        self.open_btn.clicked.connect(self.open_linked)
        lr.addWidget(self.open_btn)
        el.addWidget(self.link_row)
        self.link_row.setVisible(not link)
        self.body = QTextEdit()
        self.body.setPlaceholderText('Текст заметки. Дата заметки отмечается в календаре раздела «Сегодня».')
        el.addWidget(self.body, 1)
        bar = QHBoxLayout()
        self.status = QLabel('')
        bar.addWidget(self.status, 1)
        self.btn_delete = QPushButton('Удалить')
        self.btn_delete.setProperty('type', 'danger')
        self.btn_delete.clicked.connect(self.delete)
        bar.addWidget(self.btn_delete)
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        bar.addWidget(save)
        el.addLayout(bar)
        split.addWidget(editor)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        self.new_note()
        self.load_list()

    # --- список
    def search_changed(self, *_):
        self.pager.reset()
        self.load_list()

    def load_list(self, *_):
        keep = self.note_id
        self.list.blockSignals(True)
        self.list.clear()
        rows, total = nd.page_notes(db, self.scope.currentData() or 'all', self.search.text(), self.fixed_link, limit=self.pager.size, offset=self.pager.offset)
        before = self.pager.offset
        self.pager.set_total(total)
        if self.pager.offset != before:          # последнюю страницу опустошили — показываем новую последнюю
            rows, _ = nd.page_notes(db, self.scope.currentData() or 'all', self.search.text(), self.fixed_link, limit=self.pager.size, offset=self.pager.offset)
        for n in rows:
            day = date.fromisoformat(n['date']).strftime('%d.%m.%Y') if n['date'] else ''
            text = f"{day}  {n['title']}" + (f"\n🔗 {n['link']}" if n['link'] and not self.fixed_link else '')
            item = QListWidgetItem(('📌 ' if n['link_table'] else '📝 ') + text)
            item.setData(Qt.ItemDataRole.UserRole, n['id'])
            self.list.addItem(item)
            if n['id'] == keep:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def on_select(self, current, _previous=None):
        if current is not None:
            self.show_note(current.data(Qt.ItemDataRole.UserRole))

    def show_note(self, note_id):
        n = nd.get_note(db, note_id)
        if not n:
            return
        self.note_id = note_id
        self.title.setText(n['title'])
        self.body.setPlainText(n['body'])
        self.day.setDate(QDate.fromString(n['note_date'], 'yyyy-MM-dd'))
        self.section.blockSignals(True)
        self.section.setCurrentIndex(max(0, self.section.findData(n['link_table'] or '')))
        self.section.blockSignals(False)
        self.fill_records(n['link_id'])
        self.btn_delete.setEnabled(True)
        self.status.setText('')

    def new_note(self, day=None):
        self.note_id = None
        self.title.clear()
        self.body.clear()
        self.day.setDate(QDate.fromString(day, 'yyyy-MM-dd') if day else QDate.currentDate())
        self.section.blockSignals(True)
        self.section.setCurrentIndex(0)
        self.section.blockSignals(False)
        self.fill_records()
        self.btn_delete.setEnabled(False)
        self.list.blockSignals(True)
        self.list.clearSelection()
        self.list.setCurrentRow(-1)
        self.list.blockSignals(False)
        self.title.setFocus()

    def fill_records(self, selected=None):
        table = self.section.currentData()
        self.record.clear()
        self.record.setEnabled(bool(table))
        self.open_btn.setEnabled(bool(table))
        if not table:
            return
        for rid, label in nd.records(db, table):
            self.record.addItem(label, rid)
        if selected is not None:
            index = self.record.findData(selected)
            if index < 0:
                label = nd.link_label(db, table, selected)
                if label:
                    self.record.addItem(label, selected)
                    index = self.record.count() - 1
            self.record.setCurrentIndex(max(0, index))

    def current_link(self):
        if self.fixed_link:
            return self.fixed_link
        table = self.section.currentData()
        return (table, self.record.currentData()) if table else ('', None)

    def open_linked(self):
        table, rid = self.current_link()
        if not table or not rid:
            return
        if table == 'crm.clients':
            from .workspace_view import RecordDialog
            RecordDialog('crm.clients', rid, self).exec()
        elif table == 'le_clients':
            from .counterparty_ui import LegalClientDialog
            LegalClientDialog(rid, self).exec()
        else:
            from .workspace_view import open_record
            open_record(table, rid, self)

    def save(self):
        try:
            self.note_id = nd.save_note(db, self.title.text(), self.body.toPlainText(), self.day.date().toString('yyyy-MM-dd'), self.current_link(), self.note_id)
        except ValueError as e:
            QMessageBox.warning(self, 'Заметка', str(e))
            return
        self.status.setText('Сохранено · отмечено в календаре на ' + self.day.date().toString('dd.MM.yyyy'))
        self.load_list()
        self.changed.emit()

    def delete(self):
        if self.note_id and QMessageBox.question(self, 'Удаление', 'Удалить заметку?') == QMessageBox.StandardButton.Yes:
            nd.delete_note(db, self.note_id)
            self.new_note()
            self.load_list()
            self.changed.emit()

    def refresh_ui(self):
        self.load_list()


class NotesDialog(QDialog):
    """Заметки одной карточки (договора, проекта): кнопка «Заметки» в карточках."""
    def __init__(self, table, rid, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Заметки · ' + (nd.link_label(db, table, rid) or ''))
        self.resize(860, 520)
        layout = QVBoxLayout(self)
        self.panel = NotesPanel((table, rid), self)
        layout.addWidget(self.panel)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)


def open_notes(parent, table, rid):
    NotesDialog(table, rid, parent).exec()
