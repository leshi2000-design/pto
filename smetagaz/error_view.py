"""Экран «Журнал ошибок»."""
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, QAbstractItemView,
                              QHeaderView, QMessageBox, QPlainTextEdit, QFileDialog, QApplication, QSplitter)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from . import error_log as el


class ErrorLogView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.level = QComboBox()
        for text, value in (('Все', ''), ('Критические', 'Критическая'), ('Ошибки', 'Ошибка'), ('Предупреждения', 'Предупреждение')):
            self.level.addItem(text, value)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Текст ошибки, раздел…')
        self.btn_copy = QPushButton('Копировать отчёт')
        self.btn_save = QPushButton('Сохранить отчёт…')
        self.btn_clear = QPushButton('Очистить журнал')
        bar.addWidget(self.level)
        bar.addWidget(self.search, 1)
        for b in (self.btn_copy, self.btn_save, self.btn_clear):
            bar.addWidget(b)
        layout.addLayout(bar)
        split = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(['Последний раз', 'Уровень', 'Раздел', 'Источник', 'Повторов', 'Сообщение'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 150), (1, 120), (2, 150), (3, 130), (4, 80)):
            self.table.setColumnWidth(col, width)
        split.addWidget(self.table)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setPlaceholderText('Выберите ошибку, чтобы увидеть подробности')
        split.addWidget(self.details)
        split.setSizes([420, 220])
        layout.addWidget(split, 1)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.rows = []
        self.level.currentIndexChanged.connect(self.load_data)
        self.search.textChanged.connect(self.load_data)
        self.table.itemSelectionChanged.connect(self.show_details)
        self.btn_copy.clicked.connect(self.copy_report)
        self.btn_save.clicked.connect(self.save_report)
        self.btn_clear.clicked.connect(self.clear)

    def load_data(self, *_):
        el.purge()
        self.rows = el.entries(self.level.currentData() or '', self.search.text().strip())
        self.table.setRowCount(len(self.rows))
        colors = {'Критическая': '#B91C1C', 'Ошибка': '#C2410C', 'Предупреждение': '#A16207'}
        for r, row in enumerate(self.rows):
            first_line = (row[6] or '').splitlines()[0] if row[6] else ''
            for c, v in enumerate((row[2], row[3], row[5], row[4], row[8], first_line)):
                item = QTableWidgetItem(str(v))
                if c == 1:
                    item.setForeground(QColor(colors.get(row[3], '#000')))
                if not row[9]:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.table.setItem(r, c, item)
        self.status.setText(f'Записей: {len(self.rows)}. Журнал хранит {el.KEEP_DAYS} дней; одинаковые ошибки складываются в одну строку со счётчиком. Жирным выделены ещё не просмотренные.')
        el.mark_seen()
        self.details.clear()

    def show_details(self):
        r = self.table.currentRow()
        if not 0 <= r < len(self.rows):
            return
        row = self.rows[r]
        self.details.setPlainText(f'Первый раз: {row[1]}\nПоследний раз: {row[2]}\nПовторов: {row[8]}\nУровень: {row[3]}\nИсточник: {row[4]}\nРаздел: {row[5] or "—"}\n\n{row[6]}\n\n{row[7] or ""}')

    def copy_report(self):
        QApplication.clipboard().setText(el.report_text(self.rows))
        self.status.setText('Отчёт скопирован в буфер обмена. Его можно отправить разработчику: личных данных из базы в нём нет.')

    def save_report(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить отчёт', 'pto_errors.txt', 'Текст (*.txt)')
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(el.report_text(self.rows))
            self.status.setText('Отчёт сохранён: ' + path)

    def clear(self):
        if QMessageBox.question(self, 'Очистить журнал', 'Удалить все записи журнала ошибок?') == QMessageBox.StandardButton.Yes:
            el.clear()
            self.load_data()
