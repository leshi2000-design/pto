"""
Стартовый экран «Сегодня»: слева — дела выбранного дня, доска задач и реестр,
справа — календарь, в котором графически отмечены задачи со сроком, договоры,
оплаты, работы, акты и ежемесячные даты.
"""
import json
from datetime import date, timedelta

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame, QTabWidget,
                              QCalendarWidget, QListWidget, QListWidgetItem, QSplitter, QToolButton, QDialog,
                              QLineEdit, QComboBox, QSpinBox, QCheckBox, QMessageBox, QTableWidget,
                              QTableWidgetItem, QHeaderView, QAbstractItemView, QFormLayout, QDateEdit)
from PyQt6.QtCore import Qt, QDate, QLocale, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush, QTextCharFormat, QFont

from .database import db
from . import board_domain as board
from . import agenda_domain as agenda
from .agenda_domain import KINDS, KIND_ORDER, ISO
from .tasks_view import KanbanTab, TaskEditDialog, EventEditDialog, rgba, is_dark

MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
WEEKDAYS = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье']


def long_date(day):
    return f'{WEEKDAYS[day.weekday()].capitalize()}, {day.day} {MONTHS[day.month - 1]} {day.year}'


def to_date(qdate):
    return date(qdate.year(), qdate.month(), qdate.day())


def to_qdate(day):
    return QDate(day.year, day.month, day.day)


# --- ЕЖЕМЕСЯЧНЫЕ ДАТЫ ---

class RecurringEditDialog(QDialog):
    def __init__(self, rid=None, parent=None):
        super().__init__(parent)
        self.rid = rid
        self.color = agenda.PALETTE[0]
        self.setWindowTitle('Ежемесячная дата')
        self.resize(460, 380)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.preset = QComboBox()
        self.preset.addItem('— выбрать шаблон —')
        self.preset.addItems(agenda.RECURRING_PRESETS)
        self.preset.activated.connect(self.apply_preset)
        form.addRow('Шаблон', self.preset)
        self.title = QLineEdit()
        self.title.setPlaceholderText('Например: Зарплата, Аванс, Сдача актов')
        form.addRow('Название *', self.title)

        row = QHBoxLayout()
        self.day = QSpinBox()
        self.day.setRange(1, 31)
        self.day.setValue(1)
        self.last_day = QCheckBox('последний день месяца')
        self.last_day.toggled.connect(lambda on: self.day.setEnabled(not on))
        row.addWidget(self.day)
        row.addWidget(self.last_day, 1)
        form.addRow('Число месяца', row)

        self.shift = QComboBox()
        for code, name in agenda.SHIFTS:
            self.shift.addItem(name, code)
        form.addRow('Если выходной', self.shift)
        self.note = QLineEdit()
        form.addRow('Заметка', self.note)
        self.start = QDateEdit(QDate.currentDate())
        self.start.setLocale(QLocale(QLocale.Language.Russian))
        self.start.setCalendarPopup(True)
        self.start.setDisplayFormat('MMMM yyyy')
        self.use_start = QCheckBox('начиная с месяца')
        row = QHBoxLayout()
        row.addWidget(self.use_start)
        row.addWidget(self.start, 1)
        form.addRow('Начало', row)

        swatches = QHBoxLayout()
        self.swatches = []
        for color in agenda.PALETTE:
            b = QToolButton()
            b.setFixedSize(24, 24)
            b.clicked.connect(lambda _, c=color: self.set_color(c))
            self.swatches.append((color, b))
            swatches.addWidget(b)
        swatches.addStretch()
        form.addRow('Цвет', swatches)
        self.active = QCheckBox('Показывать в календаре')
        self.active.setChecked(True)
        form.addRow('', self.active)
        self.hint = QLabel()
        self.hint.setStyleSheet('color: #65758b;')
        layout.addWidget(self.hint)
        layout.addStretch()

        bar = QHBoxLayout()
        save = QPushButton('Сохранить')
        save.setProperty('type', 'primary')
        save.clicked.connect(self.save)
        cancel = QPushButton('Отмена')
        cancel.clicked.connect(self.reject)
        bar.addStretch()
        bar.addWidget(cancel)
        bar.addWidget(save)
        layout.addLayout(bar)
        for signal in (self.day.valueChanged, self.last_day.toggled, self.shift.currentIndexChanged):
            signal.connect(self.update_hint)
        if rid:
            row = db.fetchone('SELECT title,day_of_month,shift,color,note,start_month,active FROM recurring_dates WHERE id=?', (rid,))
            if row:
                self.title.setText(row[0])
                self.last_day.setChecked(row[1] == 0)
                self.day.setValue(row[1] or 31)
                self.shift.setCurrentIndex(max(0, self.shift.findData(row[2])))
                self.color = row[3] or self.color
                self.note.setText(row[4] or '')
                if row[5]:
                    self.use_start.setChecked(True)
                    self.start.setDate(QDate.fromString(row[5][:7] + '-01', 'yyyy-MM-dd'))
                self.active.setChecked(bool(row[6]))
        self.set_color(self.color)
        self.update_hint()

    def apply_preset(self, index):
        if index > 0:
            name = self.preset.itemText(index)
            if name != 'Другое':
                self.title.setText(name)
                self.set_color(agenda.PALETTE[(index - 1) % len(agenda.PALETTE)])
            self.title.setFocus()

    def set_color(self, color):
        self.color = color
        for c, b in self.swatches:
            b.setStyleSheet(f'QToolButton {{ background: {c}; border-radius: 12px; border: {"3px solid #0f172a" if c == color else "1px solid #94a3b8"}; }}')

    def update_hint(self, *_):
        day = 0 if self.last_day.isChecked() else self.day.value()
        today = date.today()
        nxt = agenda.occurrence(day, self.shift.currentData(), today.year, today.month)
        if nxt < today:
            nxt = agenda.occurrence(day, self.shift.currentData(), today.year + (today.month == 12), today.month % 12 + 1)
        self.hint.setText(f'Ближайшая дата: {nxt.strftime("%d.%m.%Y")}, {WEEKDAYS[nxt.weekday()]}. В коротких месяцах (например, 31-е в феврале) берётся последний день.')

    def save(self):
        title = self.title.text().strip()
        if not title:
            QMessageBox.warning(self, 'Ежемесячная дата', 'Введите название')
            return
        values = (title, 0 if self.last_day.isChecked() else self.day.value(), self.shift.currentData(), self.color, self.note.text().strip(),
                  self.start.date().toString('yyyy-MM') if self.use_start.isChecked() else '', int(self.active.isChecked()))
        if self.rid:
            db.execute('UPDATE recurring_dates SET title=?,day_of_month=?,shift=?,color=?,note=?,start_month=?,active=? WHERE id=?', (*values, self.rid))
        else:
            self.rid = db.execute('INSERT INTO recurring_dates(title,day_of_month,shift,color,note,start_month,active) VALUES(?,?,?,?,?,?,?)', values).lastrowid
        self.accept()


class RecurringDialog(QDialog):
    """Список ежемесячных дат: зарплата, аванс, сдача актов и т. п."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Ежемесячные даты')
        self.resize(660, 420)
        layout = QVBoxLayout(self)
        intro = QLabel('Даты, которые повторяются каждый месяц. Они автоматически отмечаются в календаре на все будущие месяцы.')
        intro.setWordWrap(True)
        intro.setStyleSheet('color: #65758b;')
        layout.addWidget(intro)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Название', 'Число месяца', 'Перенос с выходных', 'Показывать'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit(True))
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        for title, fn, kind in (('＋ Добавить', lambda: self.edit(False), 'primary'), ('Изменить', lambda: self.edit(True), None), ('Удалить', self.remove, 'danger')):
            b = QPushButton(title)
            if kind:
                b.setProperty('type', kind)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        close = QPushButton('Закрыть')
        close.clicked.connect(self.accept)
        bar.addWidget(close)
        layout.addLayout(bar)
        self.load()

    def load(self):
        rows = db.fetchall('SELECT id,title,day_of_month,shift,color,active FROM recurring_dates ORDER BY CASE day_of_month WHEN 0 THEN 99 ELSE day_of_month END,title')
        shifts = {'none': 'нет', 'prev': 'на пятницу', 'next': 'на понедельник'}
        self.table.setRowCount(len(rows))
        for r, (rid, title, day, shift, color, active) in enumerate(rows):
            values = [title, 'последний день' if day == 0 else str(day), shifts.get(shift, ''), 'да' if active else 'нет']
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, rid)
                if c == 0:
                    item.setForeground(QColor(color or '#DB2777'))
                    item.setFont(QFont(item.font().family(), item.font().pointSize(), QFont.Weight.Bold))
                self.table.setItem(r, c, item)

    def edit(self, existing):
        rid = None
        if existing:
            row = self.table.currentRow()
            if row < 0:
                return
            rid = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        RecurringEditDialog(rid, self).exec()
        self.load()

    def remove(self):
        row = self.table.currentRow()
        if row < 0:
            return
        if QMessageBox.question(self, 'Удаление', 'Удалить ежемесячную дату?') == QMessageBox.StandardButton.Yes:
            db.execute('DELETE FROM recurring_dates WHERE id=?', (self.table.item(row, 0).data(Qt.ItemDataRole.UserRole),))
            self.load()


# --- КАЛЕНДАРЬ С ОТМЕТКАМИ ---

class MarkerCalendar(QCalendarWidget):
    """Календарь, в ячейках которого рисуются цветные точки по видам событий."""
    def __init__(self):
        super().__init__()
        self.marks = {}
        self.hidden_kinds = set()
        self.setLocale(QLocale(QLocale.Language.Russian))
        self.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
        self.setMinimumSize(430, 340)
        weekend = QTextCharFormat()
        weekend.setForeground(QColor('#DC2626'))
        self.setWeekdayTextFormat(Qt.DayOfWeek.Saturday, weekend)
        self.setWeekdayTextFormat(Qt.DayOfWeek.Sunday, weekend)

    def paintCell(self, painter, rect, qdate):
        super().paintCell(painter, rect, qdate)
        kinds = [k for k in KIND_ORDER if k in self.marks.get(qdate.toString('yyyy-MM-dd'), {}) and k not in self.hidden_kinds]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        faded = qdate.month() != self.monthShown()
        if qdate == QDate.currentDate():
            painter.setPen(QPen(QColor('#2563EB'), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)
        if 'overdue' in kinds:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor('#DC2626')))
            x, y = rect.right() - 2, rect.top() + 2
            painter.drawPolygon([self._pt(x - 11, y), self._pt(x, y), self._pt(x, y + 11)])
        shown = kinds[:5]
        if shown:
            size, gap = 7, 3
            total = len(shown) * size + (len(shown) - 1) * gap
            x = rect.center().x() - total // 2
            y = rect.bottom() - size - 4
            painter.setPen(Qt.PenStyle.NoPen)
            for kind in shown:
                color = QColor(KINDS[kind][1])
                if faded:
                    color.setAlpha(110)
                painter.setBrush(QBrush(color))
                painter.drawEllipse(x, y, size, size)
                x += size + gap
        painter.restore()

    @staticmethod
    def _pt(x, y):
        from PyQt6.QtCore import QPoint
        return QPoint(int(x), int(y))


class LegendButton(QToolButton):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        label, color, _ = KINDS[kind]
        self.setText(label)
        self.setCheckable(True)
        self.setChecked(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('Показать / скрыть в календаре и списке дня')
        self.toggled.connect(self.restyle)
        self.color = color
        self.restyle()

    def restyle(self, *_):
        on = self.isChecked()
        self.setStyleSheet(f'QToolButton {{ border: 1px solid {self.color if on else "#94a3b8"}; border-radius: 9px; padding: 2px 8px 2px 6px; '
                           f'background: {rgba(self.color, 0.14) if on else "transparent"}; color: {("#e5edf8" if is_dark() else "#17263d") if on else "#94a3b8"}; font-size: 11px; }}')
        self.setText(('● ' if on else '○ ') + KINDS[self.kind][0])


class CalendarPanel(QWidget):
    date_selected = pyqtSignal(object)
    data_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel('Календарь дел')
        title.setStyleSheet('font-size: 15px; font-weight: 700;')
        layout.addWidget(title)
        self.calendar = MarkerCalendar()
        self.calendar.clicked.connect(lambda qd: self.date_selected.emit(to_date(qd)))
        self.calendar.currentPageChanged.connect(lambda *_: self.reload_marks())
        layout.addWidget(self.calendar, 1)

        legend = QWidget()
        grid = QHBoxLayout(legend)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.legend_buttons = []
        flow = QVBoxLayout()
        flow.setSpacing(4)
        row1, row2, row3 = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        for i, kind in enumerate(KIND_ORDER):
            b = LegendButton(kind)
            b.toggled.connect(self.on_legend)
            self.legend_buttons.append(b)
            (row1 if i < 3 else row2 if i < 6 else row3).addWidget(b)
        for row in (row1, row2, row3):
            row.addStretch()
            flow.addLayout(row)
        grid.addLayout(flow)
        layout.addWidget(legend)

        bar = QHBoxLayout()
        self.btn_event = QPushButton('＋ Событие')
        self.btn_event.clicked.connect(self.add_event)
        self.btn_task = QPushButton('＋ Задача')
        self.btn_task.clicked.connect(self.add_task)
        self.btn_recurring = QPushButton('🔁 Ежемесячные даты')
        self.btn_recurring.clicked.connect(self.manage_recurring)
        bar.addWidget(self.btn_event)
        bar.addWidget(self.btn_task)
        bar.addWidget(self.btn_recurring)
        layout.addLayout(bar)
        self.reload_marks()

    def hidden_kinds(self):
        return {b.kind for b in self.legend_buttons if not b.isChecked()}

    def restyle(self):
        for b in self.legend_buttons:
            b.restyle()

    def on_legend(self, *_):
        self.calendar.hidden_kinds = self.hidden_kinds()
        self.calendar.updateCells()
        self.data_changed.emit()

    def selected(self):
        return to_date(self.calendar.selectedDate())

    def visible_range(self):
        year, month = self.calendar.yearShown(), self.calendar.monthShown()
        first = date(year, month, 1)
        # показываем и хвосты соседних месяцев, видимые в сетке
        return first - timedelta(days=7), first + timedelta(days=42)

    def reload_marks(self):
        start, end = self.visible_range()
        self.calendar.marks = agenda.month_summary(agenda.events_between(db, start, end))
        self.calendar.hidden_kinds = self.hidden_kinds()
        self.calendar.updateCells()

    def go_to(self, day):
        self.calendar.setSelectedDate(to_qdate(day))
        self.reload_marks()

    def add_event(self):
        if EventEditDialog(self.selected().strftime(ISO), parent=self).exec():
            self.data_changed.emit()

    def add_task(self):
        if TaskEditDialog(parent=self, due=self.selected().strftime(ISO)).exec():
            self.data_changed.emit()

    def manage_recurring(self):
        RecurringDialog(self).exec()
        self.data_changed.emit()


# --- СПИСОК ДЕЛ ДНЯ ---

class EventRow(QFrame):
    def __init__(self, ev):
        super().__init__()
        self.setObjectName('eventRow')
        color = ev['color']
        self.setStyleSheet(f"QFrame#eventRow {{ background: {rgba(color, 0.10)}; border: 1px solid {rgba(color, 0.35)}; border-left: 4px solid {color}; border-radius: 7px; }} "
                           "QLabel { background: transparent; border: none; }")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        icon = QLabel(ev['icon'])
        icon.setStyleSheet('font-size: 18px;')
        layout.addWidget(icon)
        col = QVBoxLayout()
        col.setSpacing(1)
        title = QLabel((f"{ev['time']} — " if ev['time'] else '') + ev['title'])
        title.setStyleSheet('font-weight: 600;' + (f' color: {color};' if ev['kind'] == 'overdue' else ''))
        title.setWordWrap(True)
        col.addWidget(title)
        if ev['detail']:
            detail = QLabel(ev['detail'])
            detail.setStyleSheet('color: #65758b; font-size: 11px;')
            detail.setWordWrap(True)
            col.addWidget(detail)
        layout.addLayout(col, 1)
        kind = QLabel(ev['kind_label'])
        kind.setStyleSheet(f'color: {color}; font-size: 10px; font-weight: 600;')
        layout.addWidget(kind, 0, Qt.AlignmentFlag.AlignTop)


class DayTab(QWidget):
    """Список дел выбранного дня. Для сегодняшнего дня сверху показываются просроченные задачи."""
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        head = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet('font-size: 18px; font-weight: 700;')
        head.addWidget(self.title, 1)
        self.btn_prev = QToolButton()
        self.btn_prev.setText('◀')
        self.btn_next = QToolButton()
        self.btn_next.setText('▶')
        self.btn_today = QPushButton('Сегодня')
        for w in (self.btn_prev, self.btn_today, self.btn_next):
            head.addWidget(w)
        layout.addLayout(head)
        self.summary = QLabel()
        self.summary.setStyleSheet('color: #65758b;')
        layout.addWidget(self.summary)
        self.list = QListWidget()
        self.list.setSpacing(4)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setStyleSheet('QListWidget { border: none; background: transparent; } QListWidget::item { border: none; } QListWidget::item:selected { background: transparent; }')
        self.list.itemDoubleClicked.connect(self.open_item)
        layout.addWidget(self.list, 1)
        self.hint = QLabel('Двойной щелчок по записи открывает её карточку.')
        self.hint.setStyleSheet('color: #94a3b8; font-size: 11px;')
        layout.addWidget(self.hint)

    def section(self, text, color):
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        label = QLabel(text)
        label.setStyleSheet(f'font-weight: 700; color: {color}; padding: 6px 2px 0 2px; background: transparent;')
        item.setSizeHint(QSize(100, 30))
        self.list.addItem(item)
        self.list.setItemWidget(item, label)

    def add_event(self, ev):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, ev)
        row = EventRow(ev)
        item.setSizeHint(row.sizeHint() + QSize(0, 4))
        self.list.addItem(item)
        self.list.setItemWidget(item, row)

    def show_day(self, day, events, overdue):
        today = date.today()
        self.title.setText(('Сегодня · ' if day == today else 'Завтра · ' if day == today + timedelta(days=1) else 'Вчера · ' if day == today - timedelta(days=1) else '') + long_date(day))
        self.btn_today.setEnabled(day != today)
        self.list.clear()
        if overdue:
            self.section(f'⚠ Просроченные задачи ({len(overdue)})', '#DC2626')
            for ev in overdue:
                self.add_event(ev)
        if events:
            if overdue:
                self.section('Дела этого дня', '#2563EB')
            for ev in events:
                self.add_event(ev)
        if not events and not overdue:
            item = QListWidgetItem('На этот день ничего не запланировано.\nДобавьте задачу или событие кнопками под календарём.')
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setSizeHint(QSize(100, 90))
            self.list.addItem(item)
        parts = []
        counts = {}
        for ev in events:
            counts[ev['kind']] = counts.get(ev['kind'], 0) + 1
        for kind in KIND_ORDER:
            if kind in counts:
                parts.append(f'{KINDS[kind][0].lower()}: {counts[kind]}')
        self.summary.setText(' · '.join(parts) if parts else '')

    def texts(self):
        """Заголовки и пояснения записей списка (для проверок и поиска)."""
        result = []
        for i in range(self.list.count()):
            ev = self.list.item(i).data(Qt.ItemDataRole.UserRole)
            if ev:
                result.append(f"{ev['title']} {ev['detail']}")
        return result

    def open_item(self, item):
        ev = item.data(Qt.ItemDataRole.UserRole)
        if ev:
            self.owner.open_event(ev)


# --- ГЛАВНЫЙ ЭКРАН ---

class StatChip(QFrame):
    def __init__(self, caption, color):
        super().__init__()
        self.setObjectName('metricCard')
        self.color = color
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(0)
        self.value = QLabel('0')
        self.value.setStyleSheet(f'font-size: 22px; font-weight: 700; color: {color};')
        self.caption = QLabel(caption)
        self.caption.setStyleSheet('color: #65758b; font-size: 11px;')
        layout.addWidget(self.value)
        layout.addWidget(self.caption)

    def set(self, n):
        self.value.setText(str(n))


class TodayView(QWidget):
    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)

        self.summary = QLabel('')
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        self.summary.setStyleSheet('font-size: 14px; padding: 4px 2px;')
        outer.addWidget(self.summary)

        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split, 1)
        self.tabs = QTabWidget()
        self.day = DayTab(self)
        self.board = KanbanTab()
        self.tabs.addTab(self.board, '📋 Доска задач')
        self.tabs.addTab(self.day, '📅 Сегодня')
        self.tabs.addTab(self._table_tab(), '🗂 Реестр задач')
        split.addWidget(self.tabs)
        self.panel = CalendarPanel()
        self.panel.setMinimumWidth(440)
        split.addWidget(self.panel)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([620, 520])
        self.split = split
        self.btn_calendar = QPushButton('📆 Календарь')
        self.btn_calendar.setCheckable(True)
        self.btn_calendar.setToolTip('Показать или скрыть календарь справа. Выбор запоминается для каждой вкладки.')
        self.btn_calendar.toggled.connect(self.on_calendar_toggle)
        self.tabs.setCornerWidget(self.btn_calendar, Qt.Corner.TopRightCorner)
        try:
            self.calendar_pref = {**{'board': False, 'day': True, 'registry': False}, **json.loads(db.get_setting('today_calendar', '{}') or '{}')}
        except (ValueError, TypeError):
            self.calendar_pref = {'board': False, 'day': True, 'registry': False}

        self.day.btn_today.clicked.connect(lambda: self.select_day(date.today()))
        self.day.btn_prev.clicked.connect(lambda: self.select_day(self.panel.selected() - timedelta(days=1)))
        self.day.btn_next.clicked.connect(lambda: self.select_day(self.panel.selected() + timedelta(days=1)))
        self.panel.date_selected.connect(self.select_day)
        self.panel.data_changed.connect(self.load_data)
        self.board.changed.connect(self.load_data)
        self.tabs.currentChanged.connect(self.on_tab)
        self.tabs.currentChanged.connect(self.apply_calendar_pref)
        self.apply_calendar_pref()
        self.tabs.setCurrentWidget(self.board)      # при открытии раздела — доска задач
        self.board.load_boards()
        self.load_data()

    def tab_key(self):
        widget = self.tabs.currentWidget()
        return 'board' if widget is self.board else 'day' if widget is self.day else 'registry'

    def apply_calendar_pref(self, *_):
        visible = self.calendar_pref.get(self.tab_key(), False)
        self.btn_calendar.blockSignals(True)
        self.btn_calendar.setChecked(visible)
        self.btn_calendar.blockSignals(False)
        self.panel.setVisible(visible)

    def on_calendar_toggle(self, visible):
        self.calendar_pref[self.tab_key()] = bool(visible)
        self.panel.setVisible(bool(visible))
        try:
            db.set_setting('today_calendar', json.dumps(self.calendar_pref))
        except Exception:
            pass

    def _table_tab(self):
        from .task_catalog import TasksTable
        self.registry_table = TasksTable()
        return self.registry_table

    def on_tab(self, index):
        if index == 0:
            self.board.load_boards()
        elif index == 2:
            self.registry_table.reload_catalog()
            self.registry_table.load_data()

    def refresh_ui(self):
        self.panel.restyle()
        self.load_data()

    def select_day(self, day):
        self.panel.go_to(day)
        self.tabs.setCurrentWidget(self.day)
        self.load_day()

    def load_data(self):
        """Полное обновление: метки календаря, список дня, счётчики, доска."""
        self.panel.reload_marks()
        self.load_day()
        self.board.load_boards()
        if self.tabs.currentWidget() is self.registry_table:
            self.registry_table.reload_catalog()
            self.registry_table.load_data()
        info = board.summary(db)
        parts = []
        for piece in info['text'].split(' · '):
            red = 'просрочено' in piece
            amber = 'к подписанию' in piece
            color = '#DC2626' if red else '#D97706' if amber else '#475569'
            parts.append(f'<span style="color:{color};{"font-weight:600;" if red or amber else ""}">{piece}</span>')
        self.summary.setText(' &nbsp;·&nbsp; '.join(parts))

    def load_day(self, *_):
        day = self.panel.selected()
        hidden = self.panel.hidden_kinds()
        events = [e for e in agenda.events_between(db, day, day) if e['kind'] not in hidden]
        overdue = []
        if day == date.today() and 'overdue' not in hidden:
            ids_today = {e['ref'][1] for e in events if e['kind'] == 'overdue'}
            for tid, title, due, urgency in agenda.overdue_tasks(db):
                if tid in ids_today:
                    continue
                overdue.append({'date': day, 'kind': 'overdue', 'title': title, 'detail': agenda.due_label(due) + (f' · {urgency}' if urgency else ''),
                                'ref': ('kanban_tasks', tid), 'color': KINDS['overdue'][1], 'icon': KINDS['overdue'][2], 'time': '', 'kind_label': KINDS['overdue'][0]})
        self.day.show_day(day, events, overdue)

    def show_date_str(self, date_str):
        self.select_day(date.fromisoformat(date_str))

    def open_event(self, ev):
        table, rid = ev['ref'] or (None, None)
        if table == 'kanban_tasks':
            TaskEditDialog(rid, self).exec()
        elif table == 'calendar_events':
            EventEditDialog(ev['date'].strftime(ISO), rid, self).exec()
        elif table == 'recurring_dates':
            RecurringEditDialog(rid, self).exec()
        elif table == 'welding_jobs':
            from .welding_view import JobDialog
            JobDialog(rid, parent=self).exec()
        elif table == 'payments':
            row = db.fetchone('SELECT owner_type,owner_id,estimate_id FROM payments WHERE id=?', (rid,))
            if row:
                owner, oid, eid = row
                from .workspace_view import open_record
                if eid or owner == 'estimates':
                    open_record('estimates', eid or oid, self)
                elif owner:
                    open_record(owner, oid, self)
        elif table in ('contracts', 'gsv_projects', 'gsn_projects', 'le_contracts', 'smr_contracts'):
            from .workspace_view import open_record
            open_record(table, rid, self)
        self.load_data()
