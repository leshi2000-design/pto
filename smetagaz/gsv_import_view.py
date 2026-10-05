"""Окно импорта договоров «Проекты ГСВ» из Excel: привязка столбцов к графам карточки, проверка, импорт."""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
                              QFileDialog, QCheckBox, QMessageBox, QHeaderView, QAbstractItemView, QGroupBox)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from .database import db
from . import gsv_project_import as imp

STATUS_TEXT = {'new': ('Новый', '#16A34A'), 'exists': ('Уже есть', '#D97706'), 'error': ('Ошибка', '#DC2626')}


class ImportProjectsDialog(QDialog):
    def __init__(self, parent=None, path=''):
        super().__init__(parent)
        self.setWindowTitle('Импорт договоров из Excel · Проекты ГСВ')
        self.resize(1200, 880)
        self.headers, self.rows, self.header_row, self.prepared = [], [], 1, []
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.path = QLineEdit(path)
        self.path.setReadOnly(True)
        self.path.setPlaceholderText('Файл Excel (.xlsx) с таблицей договоров')
        browse = QPushButton('Выбрать файл…')
        browse.clicked.connect(self.browse)
        bar.addWidget(self.path, 1)
        bar.addWidget(browse)
        layout.addLayout(bar)

        grp = QGroupBox('Привязка столбцов таблицы к графам карточки договора')
        gl = QVBoxLayout(grp)
        self.hint = QLabel('Выберите файл — столбцы будут подобраны по названиям. Каждому столбцу можно указать графу вручную.')
        self.hint.setWordWrap(True)
        gl.addWidget(self.hint)
        self.map_table = QTableWidget(0, 3)
        self.map_table.setHorizontalHeaderLabels(['Столбец таблицы', 'Пример значения', 'Графа карточки договора'])
        self.map_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.map_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.map_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.map_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.map_table.setMinimumHeight(330)
        self.map_table.verticalHeader().setDefaultSectionSize(26)
        gl.addWidget(self.map_table)
        layout.addWidget(grp)

        opts = QHBoxLayout()
        opts.addWidget(QLabel('Если № ПД уже есть в программе:'))
        self.on_exists = QComboBox()
        self.on_exists.addItem('Пропустить', 'skip')
        self.on_exists.addItem('Обновить данные из таблицы', 'update')
        opts.addWidget(self.on_exists)
        self.infer = QCheckBox('Проставить статусы по датам (акт → «Акт подписан», «Сделано»; договор → «Договор подписан»)')
        self.infer.setChecked(True)
        opts.addWidget(self.infer, 1)
        check = QPushButton('Проверить')
        check.clicked.connect(self.check)
        opts.addWidget(check)
        layout.addLayout(opts)

        self.preview = QTableWidget(0, 8)
        self.preview.setHorizontalHeaderLabels(['Строка', '№ ПД', 'Заказчик', 'Объект', '№ договора', 'Дата заключения', 'Результат проверки', 'Замечания'])
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.horizontalHeader().setStretchLastSection(True)
        for col, width in enumerate((60, 110, 200, 220, 110, 130, 150)):
            self.preview.setColumnWidth(col, width)
        layout.addWidget(self.preview, 1)

        bottom = QHBoxLayout()
        self.summary = QLabel('')
        self.summary.setWordWrap(True)
        bottom.addWidget(self.summary, 1)
        self.run = QPushButton('Импортировать')
        self.run.setProperty('type', 'primary')
        self.run.setEnabled(False)
        self.run.clicked.connect(self.do_import)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        bottom.addWidget(self.run)
        bottom.addWidget(close)
        layout.addLayout(bottom)
        if path:
            self.load_file(path)

    # --- файл и привязка ---
    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Таблица договоров', '', 'Excel (*.xlsx *.xlsm)')
        if path:
            self.load_file(path)

    def load_file(self, path):
        try:
            self.headers, self.rows, self.header_row = imp.read_table(path)
        except Exception as e:
            QMessageBox.warning(self, 'Импорт', f'Не удалось прочитать файл:\n{e}')
            return
        self.path.setText(path)
        mapping = imp.auto_map(self.headers)
        self.map_table.setRowCount(len(self.headers))
        self.combos = []
        for i, header in enumerate(self.headers):
            sample = next((imp.cell_text(r[i]) for r in self.rows if i < len(r) and r[i] not in (None, '')), '')
            self.map_table.setItem(i, 0, QTableWidgetItem(header or f'(столбец {i + 1})'))
            self.map_table.setItem(i, 1, QTableWidgetItem(sample))
            combo = QComboBox()
            combo.addItem('— не импортировать —', '')
            for key, (label, _names) in imp.FIELDS.items():
                combo.addItem(label, key)
            combo.setCurrentIndex(max(0, combo.findData(mapping.get(i, ''))))
            combo.currentIndexChanged.connect(self.mapping_changed)
            self.map_table.setCellWidget(i, 2, combo)
            self.combos.append(combo)
        matched = sum(1 for c in self.combos if c.currentData())
        self.hint.setText(f'Строка заголовков: {self.header_row}. Строк с данными: {len(self.rows)}. Подобрано столбцов: {matched} из {len(self.headers)}. '
                          'Проверьте привязку и нажмите «Проверить».')
        self.preview.setRowCount(0)
        self.run.setEnabled(False)
        self.summary.setText('')

    def mapping(self):
        return {i: c.currentData() for i, c in enumerate(self.combos) if c.currentData()}

    def mapping_changed(self, *_):
        self.run.setEnabled(False)

    # --- проверка ---
    def check(self):
        mapping = self.mapping()
        used = list(mapping.values())
        dup = {k for k in used if used.count(k) > 1}
        if dup:
            QMessageBox.warning(self, 'Привязка', 'Одна графа выбрана для нескольких столбцов: ' + ', '.join(imp.FIELDS[k][0].split('  ')[0] for k in dup))
            return
        if 'client_name' not in used:
            QMessageBox.warning(self, 'Привязка', 'Укажите столбец с заказчиком — без него клиента не создать.')
            return
        self.prepared = imp.prepare(db, self.rows, mapping)
        self.preview.setRowCount(len(self.prepared))
        counts = {'new': 0, 'exists': 0, 'error': 0}
        for r, p in enumerate(self.prepared):
            d = p['data']
            text, color = STATUS_TEXT[p['status']]
            if p['status'] == 'new' and p['messages']:
                text, color = 'Новый, есть замечания', '#D97706'
            counts[p['status']] += 1
            values = [self.header_row + p['row'], d.get('pd_number') or '(будет присвоен)', d.get('client_name', ''), d.get('object_name', ''),
                      d.get('contract_number', ''), d.get('contract_date', ''), text, '; '.join(p['messages'])]
            for c, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                if c == 6:
                    item.setForeground(QColor(color))
                self.preview.setItem(r, c, item)
        self.summary.setText(f'Новых: {counts["new"]} · уже есть в программе: {counts["exists"]} · с ошибками (будут пропущены): {counts["error"]}')
        self.run.setEnabled(counts['new'] + counts['exists'] > 0)

    def do_import(self):
        if not self.prepared:
            return
        if QMessageBox.question(self, 'Импорт', 'Импортировать проверенные строки? Перед импортом рекомендуется сделать резервную копию базы.') != QMessageBox.StandardButton.Yes:
            return
        report = imp.import_rows(db, self.prepared, self.on_exists.currentData(), self.infer.isChecked())
        text = f'Создано договоров: {report["created"]}, обновлено: {report["updated"]}, пропущено: {report["skipped"]}, ошибок: {len(report["errors"])}.'
        if report['errors']:
            text += '\n\n' + '\n'.join(f'Строка {self.header_row + n}: {msg}' for n, msg in report['errors'][:15])
        self.summary.setText(text.split('\n')[0])
        self.run.setEnabled(False)
        QMessageBox.information(self, 'Импорт завершён', text)
        if self.parent() and hasattr(self.parent(), 'load_data'):
            self.parent().load_data()
