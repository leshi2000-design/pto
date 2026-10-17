"""Раздел «Входящие документы»: перетащите накладные, сертификаты и подписанные акты — программа предложит реквизиты и объект, вы проверяете и сохраняете."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QTabWidget, QAbstractItemView, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                              QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import incoming_domain as inc
from . import staff_domain as sd
from .database import db
from .domain_widgets import OptionalDate


class ReviewDialog(QDialog):
    """Проверка распознанных реквизитов. Нажатие «Сохранить» — единственное, что записывает данные."""
    def __init__(self, path, parent=None, did=None):
        super().__init__(parent)
        self.path, self.did = path, did
        self.saved = False
        self.setWindowTitle('Входящий документ · проверка')
        self.resize(760, 760)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'<b>{os.path.basename(path)}</b>'))
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet('color: #B45309;')
        layout.addWidget(self.warning)
        f = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItems(inc.KINDS)
        self.number = QLineEdit()
        self.date = OptionalDate()
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e9)
        self.amount.setDecimals(2)
        self.amount.setSpecialValueText('не указана')
        self.counterparty = QLineEdit()
        self.note = QLineEdit()
        for label, w in (('Вид документа', self.kind), ('Номер', self.number), ('Дата', self.date), ('Сумма', self.amount), ('Контрагент', self.counterparty), ('Примечание', self.note)):
            f.addRow(label, w)
        layout.addLayout(f)
        layout.addWidget(QLabel('<b>Объект</b> (предложения программы — сверху, проверьте):'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти другой объект: номер, адрес, клиент…')
        self.search.textChanged.connect(self.load_objects)
        layout.addWidget(self.search)
        self.object = QComboBox()
        layout.addWidget(self.object)
        self.reasons = QLabel()
        self.reasons.setStyleSheet('color: #605E5C;')
        self.reasons.setWordWrap(True)
        layout.addWidget(self.reasons)
        self.object.currentIndexChanged.connect(self.show_reason)
        self.copy = QCheckBox('Скопировать файл в папку объекта (или во «Входящие», если папка не привязана)')
        self.copy.setChecked(True)
        self.signed = QCheckBox('Это подписанный акт: отметить акт подписанным у объекта и поставить дату акта')
        layout.addWidget(self.copy)
        layout.addWidget(self.signed)
        layout.addWidget(QLabel('Распознанный текст:'))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumHeight(130)
        layout.addWidget(self.text)
        bar = QHBoxLayout()
        bar.addStretch()
        skip = QPushButton('Пропустить')
        skip.clicked.connect(self.reject)
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        bar.addWidget(skip)
        bar.addWidget(ok)
        layout.addLayout(bar)
        self.kind.currentTextChanged.connect(lambda k: self.signed.setVisible(k == 'Акт'))
        self.suggest = []
        self.run_analysis()

    def run_analysis(self):
        r = inc.analyze(db, self.path)
        self.warning.setText(r['warning'])
        self.kind.setCurrentText(r['kind'])
        self.number.setText(r['number'])
        self.date.set_value(r['date'] or '')
        self.amount.setValue(r['amount'] or 0)
        self.counterparty.setText(r['counterparty'])
        self.text.setPlainText(r['text'][:5000])
        self.suggest = r['candidates']
        self.signed.setVisible(r['kind'] == 'Акт')
        self.load_objects()

    def load_objects(self):
        keep = self.object.currentData()
        self.object.blockSignals(True)
        self.object.clear()
        self.object.addItem('— объект не выбран —', None)
        seen = set()
        if not self.search.text().strip():
            for table, rid, label, score, why in self.suggest:
                self.object.addItem(f'★ {label}', (table, rid))
                seen.add((table, rid))
        for table, rid, label in sd.objects(db, self.search.text().strip()):
            if (table, rid) not in seen:
                self.object.addItem(label, (table, rid))
        self.object.blockSignals(False)
        index = -1
        for i in range(self.object.count()):
            if self.object.itemData(i) == keep and keep:
                index = i
        self.object.setCurrentIndex(index if index >= 0 else (1 if self.suggest and not self.search.text().strip() else 0))
        self.show_reason()

    def show_reason(self, *_):
        data = self.object.currentData()
        why = next((w for t, i, _l, _s, w in self.suggest if (t, i) == data), None)
        self.reasons.setText(('Предложено, потому что найдено: ' + ', '.join(why)) if why else '')

    def save(self):
        obj = self.object.currentData() or ('', None)
        if self.signed.isVisible() and self.signed.isChecked() and not obj[0]:
            QMessageBox.warning(self, 'Акт', 'Чтобы отметить акт подписанным, выберите объект.')
            return
        fields = dict(kind=self.kind.currentText(), number=self.number.text().strip(), doc_date=self.date.value() or '', amount=self.amount.value() or None,
                      counterparty=self.counterparty.text().strip(), owner_type=obj[0], owner_id=obj[1], note=self.note.text().strip())
        try:
            inc.save(db, self.path, fields, copy=self.copy.isChecked(), mark_signed=self.signed.isVisible() and self.signed.isChecked())
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, 'Документ не сохранён', str(e))
            return
        self.saved = True
        self.accept()


def process_files(parent, paths):
    """Последовательно открывает окно проверки для каждого файла; возвращает число сохранённых."""
    saved = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        if is_invoice(path, parent):
            from .invoice_ui import InvoiceReviewDialog
            d = InvoiceReviewDialog(path, parent)
        else:
            d = ReviewDialog(path, parent)
        d.exec()
        saved += int(d.saved)
    return saved


def is_invoice(path, parent=None):
    """Накладная ли это: Excel с таблицей товаров, PDF со словом «накладная», фото (по имени файла или по вопросу пользователю)."""
    from . import invoice_parse as ip
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in ('.xlsx', '.xlsm'):
            head, _mapping = ip.find_header(ip.read_excel_rows(path, 80))
            return head is not None
        if ext == '.pdf':
            text, _warn = inc.extract_text(path)
            return inc.guess_kind(text, os.path.basename(path)) == 'Накладная'
        if ext in inc.IMAGE_EXT:
            if ip.looks_like_invoice(path):
                return True
            box = QMessageBox(parent)
            box.setWindowTitle('Что на фотографии?')
            box.setText(f'{os.path.basename(path)}\n\nЭто накладная? Для накладной программа распознает товары и реквизиты.')
            yes = box.addButton('Накладная', QMessageBox.ButtonRole.AcceptRole)
            box.addButton('Другой документ', QMessageBox.ButtonRole.RejectRole)
            box.exec()
            return box.clickedButton() is yes
    except Exception:
        return False
    return False


class IncomingView(QWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        page = QWidget()
        page.setAcceptDrops(False)
        self.tabs.addTab(page, 'Документы')
        layout = QVBoxLayout(page)
        hint = QLabel('Перетащите сюда накладные, сертификаты и подписанные акты (или нажмите «Добавить файлы»). Программа предложит реквизиты и объект, а сохранится только то, что вы подтвердите.')
        hint.setWordWrap(True)
        hint.setStyleSheet('border: 2px dashed #9AA5A3; border-radius: 8px; padding: 14px; color: #605E5C;')
        layout.addWidget(hint)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер, контрагент, файл, примечание…')
        self.kind = QComboBox()
        self.kind.addItem('Все виды', '')
        for k in inc.KINDS:
            self.kind.addItem(k, k)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.kind)
        for text, fn in (('Добавить файлы…', self.pick), ('Открыть файл', self.open_file), ('Открыть объект', self.open_object), ('Удалить запись', self.delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text.startswith('Добавить'):
                b.setProperty('type', 'primary')
            bar.addWidget(b)
        layout.addLayout(bar)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['Добавлен', 'Вид', 'Номер', 'Дата', 'Сумма', 'Контрагент', 'Объект', 'Файл'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        layout.addWidget(self.table, 1)
        self.rows = []
        self.search.textChanged.connect(self.load_data)
        self.kind.currentIndexChanged.connect(self.load_data)
        from .invoice_ui import InvoicesTab
        self.invoices_tab = InvoicesTab()
        self.tabs.addTab(self.invoices_tab, 'Накладные и товары')
        self.tabs.currentChanged.connect(lambda *_: self.load_data())

    def load_data(self, *_):
        if hasattr(self, 'invoices_tab') and self.tabs.currentIndex() == 1:
            self.invoices_tab.load_data()
        self.rows = inc.listing(db, self.search.text().strip(), self.kind.currentData() or '')
        self.table.setRowCount(len(self.rows))
        for r, d in enumerate(self.rows):
            vals = (d['created'][:16].replace('T', ' '), d['kind'], d['number'], d['date'], f'{d["amount"]:,.2f}'.replace(',', ' ') if d['amount'] else '', d['counterparty'], d['object'], d['name'])
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))

    def current(self):
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def pick(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Входящие документы', '', 'Документы (*.pdf *.docx *.xlsx *.xlsm *.txt *.png *.jpg *.jpeg *.tif *.tiff);;Все файлы (*)')
        if paths:
            process_files(self, paths)
            self.load_data()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        event.acceptProposedAction()
        process_files(self, paths)
        self.load_data()

    def edit(self):
        d = self.current()
        if d and os.path.isfile(d['path']):
            from .incoming_edit import EditDialog
            EditDialog(d, self).exec()
            self.load_data()

    def open_file(self):
        d = self.current()
        if d:
            from .platform_utils import open_local
            try:
                open_local(d['path'])
            except OSError as e:
                QMessageBox.warning(self, 'Файл', str(e))

    def open_object(self):
        d = self.current()
        if d and d['owner_type']:
            from .workspace_view import open_record
            open_record(d['owner_type'], d['owner_id'], self)

    def delete(self):
        d = self.current()
        if d and QMessageBox.question(self, 'Удалить запись', 'Удалить запись о документе? Сам файл останется на диске.') == QMessageBox.StandardButton.Yes:
            inc.delete(db, d['id'])
            self.load_data()
