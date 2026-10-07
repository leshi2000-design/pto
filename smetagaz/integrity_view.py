"""Окно проверки целостности базы (кнопка в «Настройках»)."""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QMessageBox, QFileDialog,
                              QApplication)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from .database import db
from . import integrity

LEVELS = {'error': ('Ошибка', '#DC2626'), 'warn': ('Предупреждение', '#B45309'), 'info': ('К сведению', '#65758b')}


class IntegrityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Проверка целостности базы')
        self.resize(1000, 600)
        self.findings = []
        layout = QVBoxLayout(self)
        intro = QLabel('Проверка ничего не меняет. Она ищет договоры без клиента, оплаты без договора, ссылки на удалённых клиентов, пропавшие файлы паспортов, '
                       'сертификатов и документов, папки и шаблоны, которых нет на диске, а также выполняет служебные проверки SQLite.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.summary = QLabel('')
        self.summary.setStyleSheet('font-weight: 600;')
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Уровень', 'Раздел проверки', 'Описание'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 120)
        self.table.setColumnWidth(1, 130)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_record())
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.run = QPushButton('Проверить')
        self.run.setProperty('type', 'primary')
        self.run.clicked.connect(self.check)
        self.fix = QPushButton('Снять ссылки на удалённых клиентов')
        self.fix.clicked.connect(self.fix_clients)
        self.fix.setEnabled(False)
        export = QPushButton('Сохранить отчёт…')
        export.clicked.connect(self.export)
        record = QPushButton('Открыть запись')
        record.clicked.connect(self.open_record)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        for b in (self.run, record, self.fix, export):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(close)
        layout.addLayout(bar)

    def check(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.findings = integrity.check(db)
        finally:
            QApplication.restoreOverrideCursor()
        counts = integrity.summary(self.findings)
        self.table.setRowCount(len(self.findings))
        for r, f in enumerate(self.findings):
            label, color = LEVELS[f['level']]
            for c, v in enumerate((label, f['category'], f['text'])):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setForeground(QColor(color))
                item.setToolTip(f['text'])
                self.table.setItem(r, c, item)
        self.summary.setText('Проблем не найдено.' if not self.findings else f'Ошибок: {counts["error"]} · предупреждений: {counts["warn"]} · к сведению: {counts["info"]}')
        self.fix.setEnabled(any(f['fix'] == 'client_link' for f in self.findings))

    def fix_clients(self):
        if QMessageBox.question(self, 'Исправление', 'Снять ссылки на несуществующих клиентов? Перед этим будет создана резервная копия базы. Названия и телефоны в договорах не изменятся.') != QMessageBox.StandardButton.Yes:
            return
        try:
            db.safety_backup('integrity_fix')
        except Exception as e:
            QMessageBox.warning(self, 'Исправление отменено', f'Не удалось создать резервную копию базы:\n{e}')
            return
        n = integrity.fix_dangling_clients(db)
        QMessageBox.information(self, 'Исправление', f'Исправлено записей: {n}.')
        self.check()

    def open_record(self):
        r = self.table.currentRow()
        if r < 0 or not self.findings[r]['ref']:
            return
        table, rid = self.findings[r]['ref']
        try:
            from .workspace_view import open_record
            open_record(table, rid, self)
        except Exception as e:
            QMessageBox.information(self, 'Запись', f'Эту запись нельзя открыть отсюда: {e}')

    def export(self):
        if not self.findings:
            QMessageBox.information(self, 'Отчёт', 'Нет замечаний для сохранения.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить отчёт', 'Проверка_базы.xlsx', 'Excel (*.xlsx)')
        if not path:
            return
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['Уровень', 'Раздел проверки', 'Описание'])
        for f in self.findings:
            ws.append([LEVELS[f['level']][0], f['category'], f['text']])
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str):
                    c.data_type = 's'
        ws.column_dimensions['C'].width = 120
        try:
            wb.save(path)
        except OSError as e:
            QMessageBox.warning(self, 'Отчёт', str(e))
