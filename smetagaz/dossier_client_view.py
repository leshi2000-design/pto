"""Экран «Досье клиента»: сводка, договоры всех разделов, сметы, оплаты, заметки, задачи, файлы."""
from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QPushButton, QFrame, QFormLayout, QLineEdit,
                              QDoubleSpinBox, QCheckBox, QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from .database import db
from . import dossier_client as dc


def money(v):
    return f'{float(v or 0):,.2f}'.replace(',', ' ').replace('.', ',')


def day(v):
    from .gsv_project_domain import date_short
    return date_short(v).rstrip('г.') if v else ''


def make_table(headers, widths=()):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.horizontalHeader().setStretchLastSection(True)
    for i, w in enumerate(widths):
        t.setColumnWidth(i, w)
    return t


def fill(table, rows, right=(), data=None, red=()):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem('' if v is None else str(v))
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if c == 0 and data:
                it.setData(Qt.ItemDataRole.UserRole, data[r])
            if c in right:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if c in red and row[c] not in ('', '0,00'):
                it.setForeground(QColor('#DC2626'))
            table.setItem(r, c, it)


class SaleDialog(QDialog):
    """Продажа по чеку: что куплено, сумма, номер чека. Не связана со сметой и договором."""
    def __init__(self, kind, cid, sid=None, parent=None):
        super().__init__(parent)
        from PyQt6.QtCore import QDate
        from .date_widgets import DateEdit
        self.kind, self.cid, self.sid = kind, cid, sid
        self.setWindowTitle('Продажа по чеку')
        self.resize(480, 320)
        f = QFormLayout(self)
        self.title = QLineEdit()
        self.title.setPlaceholderText('Например: котёл настенный')
        self.date = DateEdit(QDate.currentDate())
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1e9)
        self.amount.setDecimals(2)
        self.amount.setSuffix(' BYN')
        self.receipt = QLineEdit()
        self.receipt.setPlaceholderText('номер чека')
        self.note = QLineEdit()
        self.paid = QCheckBox('Оплачено полностью (внести оплату датой продажи)')
        self.paid.setChecked(True)
        for label, w in (('Что куплено *', self.title), ('Дата', self.date), ('Сумма', self.amount), ('№ чека', self.receipt), ('Примечание', self.note)):
            f.addRow(label, w)
        f.addRow(self.paid)
        ok = QPushButton('Сохранить')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.save)
        f.addRow(ok)
        if sid:
            r = db.fetchone('SELECT title,sale_date,amount,receipt_no,note FROM client_sales WHERE id=?', (sid,))
            self.title.setText(r[0])
            self.date.setDate(QDate.fromString(r[1], 'yyyy-MM-dd'))
            self.amount.setValue(r[2] or 0)
            self.receipt.setText(r[3] or '')
            self.note.setText(r[4] or '')
            self.paid.setVisible(False)      # оплаты уже существующей продажи — кнопкой «Оплаты…»

    def save(self):
        try:
            self.sid = dc.save_sale(db, self.kind, self.cid, dict(title=self.title.text(), date=self.date.date().toString('yyyy-MM-dd'), amount=self.amount.value(), receipt=self.receipt.text(),
                                                                  note=self.note.text()), self.sid, paid_now=self.paid.isChecked() and self.paid.isVisible())
        except ValueError as e:
            QMessageBox.warning(self, 'Продажа не сохранена', str(e))
            return
        self.accept()


class DossierWidget(QWidget):
    """kind: 'person' — клиент из «Клиентов», 'legal' — юрлицо."""
    def __init__(self, kind, cid, parent=None):
        super().__init__(parent)
        self.kind, self.cid = kind, cid
        layout = QVBoxLayout(self)
        self.header = QLabel('')
        self.header.setTextFormat(Qt.TextFormat.RichText)
        self.header.setWordWrap(True)
        layout.addWidget(self.header)
        self.summary = QLabel('')
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setStyleSheet('padding:6px 8px;border:1px solid #cbd5e1;border-radius:6px;')
        layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.t_contracts = make_table(['Раздел', '№', 'Дата', 'Объект', 'Сумма', 'Оплачено', 'Долг', 'Подписан'], (120, 110, 90, 280, 100, 100, 100))
        self.t_contracts.doubleClicked.connect(self.open_contract)
        self.tabs.addTab(self.t_contracts, 'Договоры')
        self.t_estimates = make_table(['Смета', 'Дата', 'Итого', 'Оплачено', 'Долг', 'Договор'], (320, 90, 100, 100, 100))
        self.t_estimates.doubleClicked.connect(self.open_estimate)
        self.tabs.addTab(self.t_estimates, 'Сметы')
        sales_page = QWidget()
        sl = QVBoxLayout(sales_page)
        sl.setContentsMargins(0, 0, 0, 0)
        sbar = QHBoxLayout()
        for text, fn in (('Добавить продажу по чеку', self.add_sale), ('Изменить', self.edit_sale), ('Оплаты…', self.sale_payments), ('Удалить', self.delete_sale)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            if text.startswith('Добавить'):
                b.setProperty('type', 'primary')
            sbar.addWidget(b)
        sbar.addStretch()
        sl.addLayout(sbar)
        self.t_sales = make_table(['Дата', 'Что куплено', '№ чека', 'Сумма', 'Оплачено', 'Долг'], (100, 320, 100, 100, 100))
        self.t_sales.doubleClicked.connect(self.edit_sale)
        sl.addWidget(self.t_sales, 1)
        self.tabs.addTab(sales_page, 'Чеки')
        self.t_payments = make_table(['Дата', 'Сумма', 'Раздел', 'Договор / смета', 'Примечание'], (100, 110, 120, 280))
        self.tabs.addTab(self.t_payments, 'Оплаты')
        self.t_notes = make_table(['Дата', 'Заметка', 'Привязка'], (100, 320))
        self.tabs.addTab(self.t_notes, 'Заметки')
        self.t_tasks = make_table(['Задача', 'Статус', 'Срок', 'Привязка'], (360, 120, 100))
        self.tabs.addTab(self.t_tasks, 'Задачи')
        from .client_files import ClientFilesWidget
        self.files = ClientFilesWidget(cid, kind=kind)
        self.tabs.addTab(self.files, 'Файлы')
        bar = QHBoxLayout()
        refresh = QPushButton('Обновить')
        refresh.clicked.connect(self.load)
        bar.addWidget(refresh)
        bar.addStretch()
        layout.addLayout(bar)
        self.load()

    def load(self):
        d = dc.client_dossier(db, self.kind, self.cid)
        self.data = d
        info, t = d['info'], d['totals']
        self.header.setText(f"<h3 style='margin:0'>{info['name']}</h3><span style='color:#605E5C'>{' · '.join(info['lines'])}</span>")
        debt_color = '#DC2626' if t['debt'] > 0 else '#16A34A'
        self.summary.setText(f"Договоров: <b>{t['contracts']}</b> · смет: <b>{t['estimates']}</b> · на сумму <b>{money(t['amount'])}</b> · оплачено <b>{money(t['paid'])}</b> · "
                             f"<span style='color:{debt_color}'>долг <b>{money(t['debt'])}</b></span>"
                             + (f" · <span style='color:#B45309'>неподписанных договоров: <b>{t['unsigned']}</b></span>" if t['unsigned'] else ''))
        fill(self.t_contracts, [(c['section'], c['number'], day(c['date']), c['object'], money(c['amount']), money(c['paid']), money(c['debt']), 'да' if c['signed'] else 'нет')
                                for c in d['contracts']], right=(4, 5, 6), data=[(c['table'], c['id']) for c in d['contracts']], red=(6,))
        fill(self.t_estimates, [(e['title'], day(e['date']), money(e['total']), money(e['paid']), money(e['debt']), e['contract'] or '— без договора —') for e in d['estimates']],
             right=(2, 3, 4), data=[e['id'] for e in d['estimates']])
        fill(self.t_sales, [(day(s['date']), s['title'], s['receipt'], money(s['amount']), money(s['paid']), money(s['debt'])) for s in d['sales']], right=(3, 4, 5), data=[s['id'] for s in d['sales']], red=(5,))
        fill(self.t_payments, [(day(p['date']), money(p['amount']), p['section'], p['label'], p['note']) for p in d['payments']], right=(1,))
        fill(self.t_notes, [(day(n['date']), n['title'], n['link']) for n in d['notes']], data=[n['id'] for n in d['notes']])
        fill(self.t_tasks, [(t_['title'] + (' (архив)' if t_['archived'] else ''), t_['status'], day(t_['due']), t_['link']) for t_ in d['tasks']])
        for i, (name, n) in enumerate((('Договоры', len(d['contracts'])), ('Сметы', len(d['estimates'])), ('Чеки', len(d['sales'])), ('Оплаты', len(d['payments'])), ('Заметки', len(d['notes'])), ('Задачи', len(d['tasks'])))):
            self.tabs.setTabText(i, f'{name} ({n})')
        self.files.load()

    def open_contract(self, *_):
        r = self.t_contracts.currentRow()
        if r >= 0:
            table, rid = self.t_contracts.item(r, 0).data(Qt.ItemDataRole.UserRole)
            from .workspace_view import open_record
            open_record(table, rid, self)
            self.load()

    def sale_id(self):
        r = self.t_sales.currentRow()
        item = self.t_sales.item(r, 0) if r >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add_sale(self):
        SaleDialog(self.kind, self.cid, None, self).exec()
        self.load()

    def edit_sale(self, *_):
        sid = self.sale_id()
        if sid:
            SaleDialog(self.kind, self.cid, sid, self).exec()
            self.load()

    def sale_payments(self):
        sid = self.sale_id()
        if sid:
            from .payments_view import PaymentsDialog
            PaymentsDialog('client_sales', sid, self).exec()
            self.load()

    def delete_sale(self):
        sid = self.sale_id()
        if sid and QMessageBox.question(self, 'Удалить продажу', 'Удалить запись о продаже?') == QMessageBox.StandardButton.Yes:
            try:
                dc.delete_sale(db, sid)
            except Exception as e:
                QMessageBox.warning(self, 'Продажа не удалена', str(e))
            self.load()

    def open_estimate(self, *_):
        r = self.t_estimates.currentRow()
        if r >= 0:
            from .workspace_view import open_record
            open_record('estimates', self.t_estimates.item(r, 0).data(Qt.ItemDataRole.UserRole), self)
            self.load()


class DossierDialog(QDialog):
    def __init__(self, kind, cid, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Досье клиента')
        self.resize(1000, 640)
        layout = QVBoxLayout(self)
        layout.addWidget(DossierWidget(kind, cid, self))
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
