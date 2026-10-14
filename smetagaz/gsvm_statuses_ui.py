"""Интерфейс статусов «Монтаж ГСВ»: выбор статусов в карточке, редактор справочника, передача исполнительной документации."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QLineEdit, QTabWidget, QToolButton,
                              QMessageBox, QComboBox, QCheckBox, QFormLayout)

from .database import db
from . import gsvm_statuses as gs
from .date_widgets import DateEdit  # noqa: F401
from .domain_widgets import OptionalDate

PALETTE = ['#DC2626', '#D97706', '#CA8A04', '#16A34A', '#0D9488', '#0891B2', '#2563EB', '#7C3AED', '#C026D3', '#64748B']


def _icon(color):
    pix = QPixmap(12, 12)
    pix.fill(QColor(color))
    return QIcon(pix)


class StatusPicker(QWidget):
    """Два списка с галочками (статусы работы и клиента) и кнопка редактирования справочника."""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.lists = {}
        for kind, title in gs.KINDS.items():
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            lst = QListWidget()
            lst.setMaximumHeight(150)
            self.lists[kind] = lst
            col.addWidget(lst)
            row.addLayout(col)
        layout.addLayout(row)
        edit = QPushButton('Редактировать список статусов…')
        edit.clicked.connect(self.edit_catalog)
        layout.addWidget(edit, 0, Qt.AlignmentFlag.AlignLeft)
        self.reload()

    def reload(self, selected=None):
        selected = set(selected) if selected is not None else self.ids()
        for kind, lst in self.lists.items():
            lst.clear()
            for sid, name, color in gs.catalog(db, kind):
                item = QListWidgetItem(_icon(color), name)
                item.setData(Qt.ItemDataRole.UserRole, sid)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if sid in selected else Qt.CheckState.Unchecked)
                lst.addItem(item)

    def ids(self):
        result = set()
        for lst in self.lists.values():
            for i in range(lst.count()):
                if lst.item(i).checkState() == Qt.CheckState.Checked:
                    result.add(lst.item(i).data(Qt.ItemDataRole.UserRole))
        return result

    def set_ids(self, ids):
        self.reload(ids)

    def edit_catalog(self):
        keep = self.ids()
        StatusEditorDialog(self).exec()
        self.reload(keep)


class StatusPage(QWidget):
    def __init__(self, kind):
        super().__init__()
        self.kind, self.current_id, self.color = kind, None, PALETTE[0]
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        left.addWidget(self.list, 1)
        bar = QHBoxLayout()
        self.btn_new, self.btn_up, self.btn_down = QPushButton('＋ Новый'), QPushButton('▲'), QPushButton('▼')
        for b in (self.btn_up, self.btn_down):
            b.setFixedWidth(36)
        for b in (self.btn_new, self.btn_up, self.btn_down):
            bar.addWidget(b)
        bar.addStretch()
        left.addLayout(bar)
        root.addLayout(left, 5)
        form = QVBoxLayout()
        self.heading = QLabel()
        form.addWidget(self.heading)
        self.name = QLineEdit()
        self.name.setPlaceholderText('Название статуса')
        form.addWidget(self.name)
        swatches = QHBoxLayout()
        self.swatches = []
        for color in PALETTE:
            b = QToolButton()
            b.setFixedSize(24, 24)
            b.clicked.connect(lambda _=False, c=color: self.set_color(c))
            self.swatches.append((color, b))
            swatches.addWidget(b)
        swatches.addStretch()
        form.addLayout(swatches)
        self.usage = QLabel()
        form.addWidget(self.usage)
        form.addStretch()
        buttons = QHBoxLayout()
        self.btn_delete, self.btn_save = QPushButton('Удалить'), QPushButton('Сохранить')
        self.btn_delete.setProperty('type', 'danger')
        self.btn_save.setProperty('type', 'primary')
        buttons.addWidget(self.btn_delete)
        buttons.addStretch()
        buttons.addWidget(self.btn_save)
        form.addLayout(buttons)
        root.addLayout(form, 4)
        self.list.currentItemChanged.connect(lambda cur, _: self.select(cur))
        self.btn_new.clicked.connect(self.start_new)
        self.btn_save.clicked.connect(self.save)
        self.btn_delete.clicked.connect(self.remove)
        self.btn_up.clicked.connect(lambda: self.move(-1))
        self.btn_down.clicked.connect(lambda: self.move(1))
        self.load()
        self.list.setCurrentRow(0) if self.list.count() else self.start_new()

    def load(self, select=None):
        wanted = select or self.current_id
        self.list.blockSignals(True)
        self.list.clear()
        for sid, name, color in gs.catalog(db, self.kind):
            item = QListWidgetItem(_icon(color), f'{name}   ·   {gs.status_usage(db, sid)}')
            item.setData(Qt.ItemDataRole.UserRole, sid)
            self.list.addItem(item)
            if sid == wanted:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def set_color(self, color):
        self.color = color
        for c, b in self.swatches:
            b.setStyleSheet(f'QToolButton {{ background:{c}; border-radius:12px; border:{"3px solid #0f172a" if c == color else "1px solid #94a3b8"}; }}')

    def start_new(self):
        self.current_id = None
        self.list.blockSignals(True)
        self.list.setCurrentItem(None)
        self.list.blockSignals(False)
        self.heading.setText('Новый статус')
        self.name.clear()
        self.set_color(PALETTE[self.list.count() % len(PALETTE)])
        self.usage.setText('')
        self.btn_delete.setEnabled(False)
        self.name.setFocus()

    def select(self, item):
        if not item:
            return
        self.current_id = item.data(Qt.ItemDataRole.UserRole)
        name, color = db.fetchone("SELECT name,coalesce(color,'#2563EB') FROM gsvm_status_catalog WHERE id=?", (self.current_id,))
        self.heading.setText(f'Статус «{name}»')
        self.name.setText(name)
        self.set_color(color)
        self.usage.setText(f'Используется в договорах: {gs.status_usage(db, self.current_id)}')
        self.btn_delete.setEnabled(True)

    def save(self):
        try:
            self.current_id = gs.save_status(db, self.kind, self.name.text(), self.color, self.current_id)
        except Exception as e:
            QMessageBox.warning(self, 'Статусы', str(e))
            return
        self.load(self.current_id)
        self.select(self.list.currentItem())

    def move(self, direction):
        if self.current_id:
            gs.move_status(db, self.kind, self.current_id, direction)
            self.load(self.current_id)

    def remove(self):
        if not self.current_id:
            return
        try:
            if QMessageBox.question(self, 'Удаление', 'Удалить статус из справочника?') != QMessageBox.StandardButton.Yes:
                return
            gs.delete_status(db, self.current_id)
        except Exception as e:
            QMessageBox.warning(self, 'Статусы', str(e))
            return
        self.current_id = None
        self.load()
        self.list.setCurrentRow(0) if self.list.count() else self.start_new()


class StatusEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Статусы договоров «Монтаж ГСВ»')
        self.resize(780, 480)
        layout = QVBoxLayout(self)
        hint = QLabel('На одном договоре можно выбрать несколько статусов работы и клиента. Справочник действует только в разделе «Монтаж ГСВ».')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        tabs = QTabWidget()
        for kind, title in gs.KINDS.items():
            tabs.addTab(StatusPage(kind), title)
        layout.addWidget(tabs, 1)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)


class IdTransferBox(QWidget):
    """Передача исполнительной документации: галочка, кому передано, дата."""
    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        self.done = QCheckBox('ИД передано')
        self.recipient = QComboBox()
        self.recipient.addItem('— не выбрано —', '')
        for name in gs.RECIPIENTS:
            self.recipient.addItem(name, name)
        self.day = OptionalDate()
        form.addRow(self.done)
        form.addRow('Кому передано', self.recipient)
        form.addRow('Дата передачи', self.day)
        self.done.toggled.connect(self.on_toggle)

    def on_toggle(self, on):
        if on and self.day.is_empty():
            self.day.set_value(__import__('datetime').date.today().isoformat())      # при отметке по умолчанию стоит сегодняшняя дата

    def values(self):
        return dict(id_transferred=int(self.done.isChecked()), id_recipient=self.recipient.currentData() or '', id_transfer_date=self.day.value())

    def fill(self, c):
        self.done.blockSignals(True)
        self.done.setChecked(bool(c.get('id_transferred')))
        self.done.blockSignals(False)
        self.recipient.setCurrentIndex(max(0, self.recipient.findData(c.get('id_recipient') or '')))
        self.day.set_value(c.get('id_transfer_date') or '')
