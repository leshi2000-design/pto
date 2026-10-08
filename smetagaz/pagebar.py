"""Панель страниц для реестров: «← Назад · записей N · страница X из Y · Далее →». Запросы страниц делает сам реестр (LIMIT/OFFSET)."""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtCore import pyqtSignal


class PageBar(QWidget):
    changed = pyqtSignal()

    def __init__(self, size=100, parent=None):
        super().__init__(parent)
        self.size = size
        self.offset = 0
        self.total = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        self.first = QPushButton('⏮')
        self.prev = QPushButton('← Назад')
        self.label = QLabel('')
        self.next = QPushButton('Далее →')
        self.last = QPushButton('⏭')
        layout.addStretch()
        for w in (self.first, self.prev, self.label, self.next, self.last):
            layout.addWidget(w)
        layout.addStretch()
        self.first.setFixedWidth(40)
        self.last.setFixedWidth(40)
        self.prev.setFixedWidth(100)
        self.next.setFixedWidth(100)
        self.first.clicked.connect(lambda: self.go(0))
        self.prev.clicked.connect(lambda: self.go(self.offset - self.size))
        self.next.clicked.connect(lambda: self.go(self.offset + self.size))
        self.last.clicked.connect(lambda: self.go(max(0, (self.total - 1) // self.size * self.size)))
        self.set_total(0)

    def go(self, offset):
        offset = max(0, offset)
        if offset != self.offset:
            self.offset = offset
            self.changed.emit()

    def reset(self):
        self.offset = 0

    def pages(self):
        return max(1, -(-self.total // self.size))

    def set_total(self, total):
        """Вызывается реестром после подсчёта; если страница вышла за конец (записи удалили), возвращает на последнюю."""
        self.total = int(total or 0)
        if self.offset >= self.total and self.offset > 0:
            self.offset = max(0, (self.total - 1) // self.size * self.size)
        page = self.offset // self.size + 1
        self.label.setText(f'Записей: {self.total} · страница {page} из {self.pages()}')
        self.prev.setEnabled(self.offset > 0)
        self.first.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset + self.size < self.total)
        self.last.setEnabled(self.offset + self.size < self.total)
        self.setVisible(self.total > self.size or self.offset > 0)
