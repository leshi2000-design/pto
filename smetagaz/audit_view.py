"""Экран «Журнал и корзина»: что и когда менялось, просмотр изменений и восстановление удалённых записей."""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, QAbstractItemView,
                              QHeaderView, QMessageBox, QDialog, QTextBrowser)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from .database import db
from . import audit_domain as ad

ACTIONS = {'I': 'Создано', 'U': 'Изменено', 'D': 'Удалено'}
PAGE = 300


class AuditView(QWidget):
    def __init__(self):
        super().__init__()
        self.limit = PAGE
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.table_filter = QComboBox()
        self.table_filter.addItem('Все разделы', '')
        for key, (_schema, title) in sorted(ad.AUDITED.items(), key=lambda kv: kv[1][1]):
            self.table_filter.addItem(title, key)
        self.action_filter = QComboBox()
        self.action_filter.addItem('Все действия', '')
        self.action_filter.addItem('Только удалённые (корзина)', 'D')
        self.action_filter.addItem('Изменённые', 'U')
        self.action_filter.addItem('Созданные', 'I')
        self.search = QLineEdit()
        self.search.setPlaceholderText('Номер, название, ФИО, телефон…')
        self.btn_details = QPushButton('Что изменилось…')
        self.btn_restore = QPushButton('Восстановить')
        self.btn_restore.setProperty('type', 'primary')
        self.btn_more = QPushButton('Показать ещё')
        for w in (self.table_filter, self.action_filter):
            bar.addWidget(w)
        bar.addWidget(self.search, 1)
        for w in (self.btn_details, self.btn_restore, self.btn_more):
            bar.addWidget(w)
        layout.addLayout(bar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['Когда', 'Действие', 'Раздел', 'Запись', 'Состояние'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 150), (1, 100), (2, 220), (4, 130)):
            self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)
        self.status = QLabel(f'Журнал хранит изменения {ad.KEEP_DAYS} дней. Удалённую запись можно восстановить вместе с вложенными (оборудование, стыки и т. п.).')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.entries = []
        self.table_filter.currentIndexChanged.connect(self.reset)
        self.action_filter.currentIndexChanged.connect(self.reset)
        self.search.textChanged.connect(self.reset)
        self.btn_more.clicked.connect(self.more)
        self.btn_details.clicked.connect(self.show_details)
        self.btn_restore.clicked.connect(self.restore)
        self.table.doubleClicked.connect(self.show_details)

    def reset(self, *_):
        self.limit = PAGE
        self.load_data()

    def more(self):
        self.limit += PAGE
        self.load_data()

    def load_data(self):
        self.entries = ad.entries(db, self.table_filter.currentData() or '', self.action_filter.currentData() or '', self.search.text().strip(), self.limit)
        self.table.setRowCount(len(self.entries))
        for r, e in enumerate(self.entries):
            state = 'восстановлена' if e['restored'] else ('в корзине' if e['action'] == 'D' else '')
            values = [e['ts'], ACTIONS.get(e['action'], e['action']), ad.AUDITED.get(e['table'], ('', e['table']))[1], e['label'] or f'№{e["record_id"]}', state]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if e['action'] == 'D' and c in (1, 4) and not e['restored']:
                    item.setForeground(QColor('#B91C1C'))
                self.table.setItem(r, c, item)
        self.btn_more.setEnabled(len(self.entries) >= self.limit)

    def current(self):
        r = self.table.currentRow()
        return self.entries[r] if 0 <= r < len(self.entries) else None

    def show_details(self, *_):
        e = self.current()
        if not e:
            return
        rows = ad.diff(e)
        dlg = QDialog(self)
        dlg.setWindowTitle(f'{ACTIONS.get(e["action"], "")} · {e["label"] or e["record_id"]}')
        dlg.resize(640, 480)
        lay = QVBoxLayout(dlg)
        view = QTextBrowser()
        if e['action'] == 'I':
            html = '<p>Запись создана.</p>'
        elif e['action'] == 'U':
            html = '<table cellpadding=5>' + '<tr><th align=left>Поле</th><th align=left>Было</th><th align=left>Стало</th></tr>' + ''.join(
                f'<tr><td>{k}</td><td>{"" if o is None else o}</td><td>{"" if n is None else n}</td></tr>' for k, o, n in rows) + '</table>'
        else:
            html = '<p>Данные удалённой записи:</p><table cellpadding=5>' + ''.join(f'<tr><td>{k}</td><td>{o}</td></tr>' for k, o, _n in rows) + '</table>'
        view.setHtml(html)
        lay.addWidget(view)
        close = QPushButton('Закрыть')
        close.clicked.connect(dlg.accept)
        lay.addWidget(close)
        dlg.exec()

    def restore(self):
        e = self.current()
        if not e or e['action'] != 'D':
            QMessageBox.information(self, 'Восстановление', 'Выберите удалённую запись (действие «Удалено»).')
            return
        if QMessageBox.question(self, 'Восстановление', f'Восстановить «{e["label"] or e["record_id"]}» вместе с вложенными записями?') != QMessageBox.StandardButton.Yes:
            return
        try:
            count = ad.restore(db, e['id'], e['schema'])
        except Exception as ex:
            QMessageBox.warning(self, 'Восстановление', str(ex))
            return
        self.status.setText(f'Восстановлено записей: {count}.')
        self.load_data()
