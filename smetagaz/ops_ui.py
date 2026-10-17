"""Окна для администратора и руководителя: «Кто в сети и что открыто» (со снятием зависшей блокировки) и журнал входов и действий администратора.
Работают и в клиенте (данные берутся у сервера), и в окне «ПТО Сервер» (данные берутся напрямую): источник передаётся функциями."""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .server_core import ROLES

LOCK_TITLES = {'gsvm': 'Договор монтажа ГСВ', 'gsn': 'Договор монтажа ГСН', 'gsv': 'Договор проекта ГСВ', 'estimate': 'Смета', 'cp': 'Договор (СМР / ТО / ИП)',
               'lecontract': 'Договор юрлица', 'dossier': 'Досье клиента', 'staff': 'Карточка сотрудника', 'material': 'Карточка позиции справочника'}
EVENTS = {'login': 'Вход', 'login_token': 'Вход (сохранённый)', 'login_fail': 'Неудачный вход', 'login_blocked': 'Блокировка входа', 'logout': 'Выход',
          'user_add': 'Пользователь создан', 'user_update': 'Пользователь изменён', 'user_delete': 'Пользователь удалён', 'password': 'Смена пароля',
          'lock_release': 'Снята блокировка карточки'}
BAD_EVENTS = ('login_fail', 'login_blocked')


def lock_title(key):
    kind, _, ident = str(key).partition(':')
    return f'{LOCK_TITLES.get(kind, kind)} № {ident}'


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def _fill(table, rows, bad=lambda r: False, keys=None):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(str(value if value is not None else ''))
            if keys is not None and c == 0:
                item.setData(Qt.ItemDataRole.UserRole, keys[r])
            if bad(row):
                item.setForeground(Qt.GlobalColor.red)
            table.setItem(r, c, item)


class OnlineWidget(QWidget):
    """Подключённые пользователи и открытые карточки. fetch() -> (sessions, locks); release(key) снимает блокировку (None — кнопки нет)."""
    def __init__(self, fetch, release=None, parent=None):
        super().__init__(parent)
        self.fetch, self.release = fetch, release
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('<b>Сейчас работают</b>'))
        self.sessions = _table(['Логин', 'Имя', 'Роль', 'Компьютер', 'Адрес', 'Вошёл', 'Последний запрос'])
        layout.addWidget(self.sessions, 1)
        layout.addWidget(QLabel('<b>Открытые карточки</b> (их сейчас правят — остальным они доступны только для просмотра)'))
        self.locks = _table(['Что открыто', 'Кто', 'Компьютер', 'С какого времени'])
        layout.addWidget(self.locks, 1)
        bar = QHBoxLayout()
        self.free = QPushButton('Снять блокировку выбранной карточки')
        self.free.setToolTip('Нужна, если карточка осталась «занятой» после сбоя. Несохранённые правки того, кто её открыл, могут пропасть.')
        self.free.clicked.connect(self.release_selected)
        self.free.setVisible(release is not None)
        bar.addWidget(self.free)
        bar.addStretch()
        self.note = QLabel('')
        bar.addWidget(self.note)
        layout.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.load)
        self.timer.start(5000)
        self.load()

    def load(self):
        try:
            sessions, locks = self.fetch()
        except Exception as e:
            self.note.setText(f'Не удалось получить данные: {e}')
            return
        self.note.setText('Обновляется каждые 5 секунд')
        rows = [(s[0], s[1], ROLES.get(s[2], s[2]), s[6] if len(s) > 6 else '', s[3], s[4], s[5]) for s in sessions]
        _fill(self.sessions, rows)
        _fill(self.locks, [(lock_title(k), u, h, since) for k, u, h, since in locks], keys=[k for k, *_ in locks])

    def release_selected(self):
        row = self.locks.currentRow()
        item = self.locks.item(row, 0) if row >= 0 else None
        if item is None:
            QMessageBox.information(self, 'Блокировки', 'Выберите карточку в списке.')
            return
        if QMessageBox.question(self, 'Снять блокировку', f'Снять блокировку «{item.text()}»? Если {self.locks.item(row, 1).text()} ещё работает с карточкой, '
                                'её сохранение может затереть чьи-то правки.') != QMessageBox.StandardButton.Yes:
            return
        try:
            self.release(item.data(Qt.ItemDataRole.UserRole))
        except Exception as e:
            QMessageBox.warning(self, 'Блокировки', str(e))
        self.load()


class JournalWidget(QWidget):
    """Журнал входов и действий администратора. fetch(event) -> строки (время, событие, логин, адрес, компьютер, подробности)."""
    def __init__(self, fetch, parent=None):
        super().__init__(parent)
        self.fetch = fetch
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem('Все события', None)
        self.filter.addItem('Только неудачные входы', 'login_fail')
        for key in ('login', 'login_token', 'login_blocked', 'user_add', 'user_update', 'password', 'user_delete', 'lock_release'):
            self.filter.addItem(EVENTS[key], key)
        self.filter.currentIndexChanged.connect(self.load)
        refresh = QPushButton('Обновить')
        refresh.clicked.connect(self.load)
        bar.addWidget(QLabel('Показывать:'))
        bar.addWidget(self.filter)
        bar.addWidget(refresh)
        bar.addStretch()
        layout.addLayout(bar)
        self.table = _table(['Время', 'Событие', 'Логин', 'Адрес', 'Компьютер', 'Подробности'])
        layout.addWidget(self.table, 1)
        self.note = QLabel('Последние 500 записей. Журнал хранит до 20 000 записей.')
        layout.addWidget(self.note)
        self.load()

    def load(self, *_):
        try:
            rows = self.fetch(self.filter.currentData())
        except Exception as e:
            self.note.setText(f'Не удалось получить журнал: {e}')
            return
        shown = [(r[0].replace('T', ' '), EVENTS.get(r[1], r[1]), r[2], r[3], r[4], r[5]) for r in rows]
        _fill(self.table, shown, bad=lambda row: row[1] in (EVENTS['login_fail'], EVENTS['login_blocked']))


class OpsDialog(QDialog):
    def __init__(self, fetch_online, release, fetch_journal=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Кто в сети')
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(OnlineWidget(fetch_online, release), 'Кто в сети и что открыто')
        if fetch_journal is not None:
            tabs.addTab(JournalWidget(fetch_journal), 'Журнал входов и действий')
        layout.addWidget(tabs)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        layout.addWidget(close)


def client_dialog(db, parent=None):
    """Окно для сетевого клиента: руководителю — «кто в сети», администратору — ещё и журнал."""
    def online():
        data = db.ops_online()
        return data['sessions'], data['locks']
    journal = (lambda event: db.ops_journal(500, event)) if db.role == 'admin' else None
    return OpsDialog(online, db.ops_release_lock, journal, parent)
