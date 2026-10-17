"""Окна для номеров договоров: изменить номер / поменять местами и зарезервировать номера."""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QMessageBox, QSpinBox, QGroupBox, QFormLayout
from PyQt6.QtCore import QDate

from .database import db
from .date_widgets import DateEdit
from . import numbering as nm


class NumberDialog(QDialog):
    """Изменить номер карточки или поменяться номерами с другой карточкой."""
    def __init__(self, section, rid, parent=None):
        super().__init__(parent)
        self.section, self.rid = section, rid
        self.changed = False
        self.setWindowTitle('Номер договора · ' + nm.SECTIONS[section]['title'])
        self.resize(560, 300)
        layout = QVBoxLayout(self)
        self.current = QLabel()
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        box = QGroupBox('Изменить номер')
        f = QFormLayout(box)
        self.new = QLineEdit()
        from . import section_codes
        self.new.setPlaceholderText('например 07-26' if section == 'gsv_projects' else f"например 07-{section_codes.code(db, section)}/26")
        f.addRow('Новый номер', self.new)
        hint = QLabel('Если номер занят другой карточкой, программа предложит поменяться номерами.')
        hint.setStyleSheet('color: #605E5C;')
        hint.setWordWrap(True)
        f.addRow(hint)
        btn = QPushButton('Изменить номер')
        btn.setProperty('type', 'primary')
        btn.clicked.connect(self.apply)
        f.addRow(btn)
        layout.addWidget(box)
        swap_box = QGroupBox('Поменяться номерами с другой карточкой')
        sl = QVBoxLayout(swap_box)
        self.other = QComboBox()
        sl.addWidget(self.other)
        swap = QPushButton('Поменять местами')
        swap.clicked.connect(self.swap)
        sl.addWidget(swap)
        layout.addWidget(swap_box)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.reload()

    def reload(self):
        self.current.setText('<b>Сейчас:</b> ' + nm.label(db, self.section, self.rid))
        self.other.clear()
        for rid, text in nm.others(db, self.section, self.rid):
            self.other.addItem(text, rid)

    def apply(self):
        try:
            number = nm.change_number(db, self.section, self.rid, self.new.text())
        except nm.NumberTaken as e:
            if QMessageBox.question(self, 'Номер занят', f'{e}.\n\nПоменять местами номера этих двух карточек?') == QMessageBox.StandardButton.Yes:
                self.do_swap(e.other_id)
            return
        except ValueError as e:
            QMessageBox.warning(self, 'Номер не изменён', str(e))
            return
        self.changed = True
        self.new.clear()
        self.reload()
        QMessageBox.information(self, 'Номер изменён', f'Новый номер: {number}.\nДокументы по этому договору помечены как устаревшие — переформируйте их.')

    def swap(self):
        other = self.other.currentData()
        if other is None:
            return
        if QMessageBox.question(self, 'Поменять местами', f'Поменять номера:\n{nm.label(db, self.section, self.rid)}\nи\n{nm.label(db, self.section, other)}?') == QMessageBox.StandardButton.Yes:
            self.do_swap(other)

    def do_swap(self, other):
        try:
            nm.swap_numbers(db, self.section, self.rid, other)
        except ValueError as e:
            QMessageBox.warning(self, 'Обмен не выполнен', str(e))
            return
        self.changed = True
        self.reload()
        QMessageBox.information(self, 'Номера обменяны', 'Номера поменялись местами. Документы обеих карточек переформируйте, если они уже создавались.')


class ReserveDialog(QDialog):
    """Создать пустые карточки с очередными номерами."""
    def __init__(self, section, parent=None):
        super().__init__(parent)
        self.section = section
        self.created = []
        self.setWindowTitle('Зарезервировать номера · ' + nm.SECTIONS[section]['title'])
        layout = QVBoxLayout(self)
        f = QFormLayout()
        self.count = QSpinBox()
        self.count.setRange(1, 100)
        self.count.setValue(1)
        self.day = DateEdit(QDate.currentDate())
        f.addRow('Сколько номеров', self.count)
        f.addRow('Год по дате', self.day)
        layout.addLayout(f)
        note = QLabel('Будут созданы пустые карточки с очередными номерами. Позже откройте карточку и заполните её данными — номер сохранится.')
        note.setWordWrap(True)
        note.setStyleSheet('color: #605E5C;')
        layout.addWidget(note)
        row = QHBoxLayout()
        ok = QPushButton('Зарезервировать')
        ok.setProperty('type', 'primary')
        ok.clicked.connect(self.run)
        cancel = QPushButton('Отмена')
        cancel.clicked.connect(self.reject)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        layout.addLayout(row)

    def run(self):
        try:
            from datetime import date
            d = self.day.date()
            self.created = nm.reserve(db, self.section, self.count.value(), date(d.year(), d.month(), d.day()))
        except ValueError as e:
            QMessageBox.warning(self, 'Резерв номеров', str(e))
            return
        numbers = ', '.join(n for _i, n in self.created)
        QMessageBox.information(self, 'Номера зарезервированы', f'Созданы карточки: {numbers}')
        self.accept()
