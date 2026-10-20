"""Единый ввод и показ дат: дд.мм.гггг, ввод цифрами (14102026) или выбор в календаре; календарь всегда открывается на сегодняшнем месяце."""
import re
import weakref

from PyQt6.QtCore import QDate, QLocale, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QCalendarWidget, QLineEdit, QWidget

RU = QLocale(QLocale.Language.Russian, QLocale.Country.Belarus)
from .dates import display_date, ISO  # noqa: F401


class PopupCalendar(QCalendarWidget):
    def __init__(self, owner):
        super().__init__()
        self._owner = weakref.ref(owner)
        self.setLocale(RU)
        self.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setHorizontalHeaderFormat(QCalendarWidget.HorizontalHeaderFormat.ShortDayNames)
        self.setGridVisible(False)
        self.setMinimumSize(320, 240)

    def showEvent(self, event):
        super().showEvent(event)
        owner = self._owner()
        if owner is not None and owner.is_empty():       # поле «Не указана» не должно открывать календарь на 1900 годе
            today = QDate.currentDate()
            self.setCurrentPage(today.year(), today.month())


def parse_typed(text, base, partial_ok=False):
    """Разбор набранного вручную: «14», «1410», «141026», «14102026», «14.10.26», «1.5», «14/10/2026», «2026-10-14». base — дата, из которой берутся недостающие части.
    Возвращает QDate или None, если ввод не даёт допустимой даты."""
    text = str(text or '').strip()
    if not text:
        return None
    m = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if m:
        d = QDate(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return d if d.isValid() else None
    parts = [p for p in re.split(r'[\s.,/\-]+', text) if p]
    if len(parts) == 1 and re.fullmatch(r'\d+', parts[0]):
        digits = parts[0]
        if len(digits) > 8:
            return None
        parts = [p for p in (digits[:2], digits[2:4], digits[4:]) if p]
    if not parts or len(parts) > 3 or not all(p.isdigit() for p in parts):
        return None
    day = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else base.month()
    year = base.year()
    if len(parts) > 2:
        y = parts[2]
        if len(y) == 3:
            if not partial_ok:
                return None
        else:
            year = int(y) + (2000 if len(y) <= 2 else 0)
    if not 1 <= day <= 31 or not 1 <= month <= 12 or not 1900 <= year <= 9999:
        return None
    return QDate(year, month, min(day, QDate(year, month, 1).daysInMonth()))


def parse_month(text, base):
    """Месяц и год: «10.2026», «10.26», «102026», «10» (год текущий)."""
    parts = [p for p in re.split(r'[\s.,/\-]+', str(text or '').strip()) if p]
    if len(parts) == 1 and parts[0].isdigit() and len(parts[0]) > 2:
        parts = [parts[0][:2], parts[0][2:]]
    if not parts or len(parts) > 2 or not all(p.isdigit() for p in parts):
        return None
    month = int(parts[0])
    year = base.year()
    if len(parts) == 2:
        if len(parts[1]) == 3:
            return None
        year = int(parts[1]) + (2000 if len(parts[1]) <= 2 else 0)
    if not 1 <= month <= 12 or not 1900 <= year <= 9999:
        return None
    return QDate(year, month, 1)


def _canonical(digits, month_mode):
    """Цифры → «дд.мм.гггг» (или «мм.гггг»): точки ставятся сами."""
    if month_mode:
        digits = digits[:6]
        return digits[:2] + ('.' + digits[2:] if len(digits) > 2 else '')
    digits = digits[:8]
    out = digits[:2]
    if len(digits) > 2:
        out += '.' + digits[2:4]
    if len(digits) > 4:
        out += '.' + digits[4:]
    return out


def _calendar_icon():
    from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor('#8A8886'))
    pen.setWidthF(2.2)
    p.setPen(pen)
    p.drawRoundedRect(5, 7, 22, 20, 3, 3)
    p.drawLine(5, 13, 27, 13)
    p.drawLine(11, 4, 11, 9)
    p.drawLine(21, 4, 21, 9)
    for x in (10, 16, 22):
        for y in (18, 23):
            p.drawPoint(x, y)
    p.end()
    return QIcon(pm)


class DateEdit(QLineEdit):
    """Поле даты — обычная строка: печатайте дату целиком (14102026 — точки добавятся сами; можно 14.10.26, 14.10, 7), ничто не блокируется.
    Дата принимается при выходе из поля или Enter; неверный ввод возвращает прежнюю дату. ↑/↓ — день, PgUp/PgDn — месяц, значок справа — календарь.
    Совместим с прежним QDateEdit: date(), setDate(), dateChanged, setDisplayFormat(), setMinimumDate(), setSpecialValueText() и др."""
    dateChanged = pyqtSignal(QDate)

    def __init__(self, *args, calendarPopup=True, **kwargs):
        parent = None
        initial = None
        for a in args:
            if isinstance(a, QDate):
                initial = a
            elif isinstance(a, QWidget):
                parent = a
        super().__init__(parent)
        self._min, self._max = QDate(1900, 1, 1), QDate(9999, 12, 31)
        self._format = 'dd.MM.yyyy'
        self._special = ''
        self._date = initial if initial is not None and initial.isValid() else QDate.currentDate()
        self._dirty = False
        self._calendar = None
        self.setMaxLength(12)
        self.setPlaceholderText('дд.мм.гггг')
        self.setToolTip('Печатайте дату цифрами: 14102026 (точки добавятся сами), 14.10.26, 14.10 — год текущий. ↑↓ — день, PgUp/PgDn — месяц. Значок справа — календарь.')
        self.textEdited.connect(self._on_edited)
        self.editingFinished.connect(self._commit)
        self.addAction(_calendar_icon(), QLineEdit.ActionPosition.TrailingPosition).triggered.connect(self.show_calendar)
        self.setMinimumWidth(120)
        self._refresh_text()

    # --- совместимость с QDateEdit
    def lineEdit(self):
        return self

    def displayFormat(self):
        return self._format

    def setDisplayFormat(self, fmt):
        self._format = fmt
        self.setPlaceholderText(self._special or ('дд.мм.гггг' if self._day_mode() else 'мм.гггг'))
        self._refresh_text()

    def setCalendarPopup(self, enabled):
        pass

    def setSelectedSection(self, section):
        self.selectAll()

    def setSpecialValueText(self, text):
        self._special = text or ''
        self.setPlaceholderText(self._special or ('дд.мм.гггг' if self._day_mode() else 'мм.гггг'))
        self._refresh_text()

    def minimumDate(self):
        return QDate(self._min)

    def maximumDate(self):
        return QDate(self._max)

    def setMinimumDate(self, d):
        self._min = QDate(d)
        if self._calendar is not None:
            self._calendar.setMinimumDate(self._min)
        if self._date < self._min:
            self.setDate(self._min)

    def setMaximumDate(self, d):
        self._max = QDate(d)
        if self._calendar is not None:
            self._calendar.setMaximumDate(self._max)

    def setDateRange(self, lo, hi):
        self.setMaximumDate(hi)
        self.setMinimumDate(lo)

    def calendarWidget(self):
        if self._calendar is None:
            cal = PopupCalendar(self)
            cal.setWindowFlags(Qt.WindowType.Popup)
            cal.setMinimumDate(self._min)
            cal.setMaximumDate(self._max)
            cal.clicked.connect(self._calendar_picked)
            cal.activated.connect(self._calendar_picked)
            self._calendar = cal
        return self._calendar

    def is_empty(self):
        return bool(self._special) and self.date() == self._min

    def _day_mode(self):
        return self._format.startswith('dd')

    # --- значение
    def date(self):
        if self._dirty:                      # набрано, но ещё не принято (например, сразу нажали «Сохранить»)
            self._commit()
        return QDate(self._date)

    def setDate(self, d):
        if not isinstance(d, QDate) or not d.isValid():
            return
        d = max(self._min, min(self._max, d))
        changed = d != self._date
        self._date = QDate(d)
        self._dirty = False
        self._refresh_text()
        if changed:
            self.dateChanged.emit(QDate(d))

    def _refresh_text(self):
        if self._special and self._date == self._min:
            self.setText('')
        elif self._day_mode():
            self.setText(self._date.toString('dd.MM.yyyy'))
        else:
            self.setText(RU.toString(self._date, self._format))

    def _on_edited(self, text):
        self._dirty = True
        digits = re.sub(r'\D', '', text)
        if text and re.fullmatch(r'[\d.]+', text) and self.cursorPosition() == len(text):
            canon = _canonical(digits, not self._day_mode())
            dots_ok = all(i in (2, 5) for i, ch in enumerate(text) if ch == '.') if self._day_mode() else all(i == 2 for i, ch in enumerate(text) if ch == '.')
            if dots_ok and canon != text:
                self.setText(canon)

    def _commit(self):
        if not self._dirty:
            return
        self._dirty = False
        text = self.text().strip()
        if not text:
            if self._special:
                self.setDate(self._min)
            else:
                self._refresh_text()
            return
        base = self._date if self._date != self._min or not self._special else QDate.currentDate()
        d = parse_typed(text, base) if self._day_mode() else parse_month(text, base)
        if d is None or not (self._min <= d <= self._max):
            self._refresh_text()
            self._flash()
            return
        self.setDate(d)
        self._refresh_text()

    def _flash(self):
        self.setStyleSheet('QLineEdit { border:1px solid #D13438; }')
        QTimer.singleShot(900, lambda: self.setStyleSheet(''))

    # --- ввод
    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and not self.isReadOnly():
            base = self.date()
            if self.is_empty():
                base = QDate.currentDate()
            step = 1 if key in (Qt.Key.Key_Up, Qt.Key.Key_PageUp) else -1
            if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) or not self._day_mode():
                self.setDate(base.addMonths(step))
            else:
                self.setDate(base.addDays(step))
            self.selectAll()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, self.selectAll)          # набираемая дата заменяет прежнюю

    def focusOutEvent(self, event):
        self._commit()
        super().focusOutEvent(event)

    def show_calendar(self):
        if self.isReadOnly() or not self.isEnabled():
            return
        self._commit()
        cal = self.calendarWidget()
        current = QDate.currentDate() if self.is_empty() else self._date
        cal.setSelectedDate(current)
        cal.setCurrentPage(current.year(), current.month())
        cal.move(self.mapToGlobal(self.rect().bottomLeft()))
        cal.show()

    def _calendar_picked(self, d):
        if self._calendar is not None:
            self._calendar.hide()
        self.setDate(d if self._day_mode() else QDate(d.year(), d.month(), 1))
        self.setFocus()


def install_display_patch():
    """Даты в формате ГГГГ-ММ-ДД, попадающие в таблицы, показываются как дд.мм.гггг; исходное значение остаётся в данных ячейки."""
    from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem
    if getattr(QTableWidget, '_pto_date_patch', False):
        return
    original = QTableWidget.setItem

    def set_item(self, row, column, item):
        if item is not None:
            text = item.text()
            shown = display_date(text)
            if shown != text:
                item.setData(Qt.ItemDataRole.UserRole + 77, text)
                item.setText(shown)
        return original(self, row, column, item)

    QTableWidget.setItem = set_item
    QTableWidget._pto_date_patch = True
    # во всех таблицах скрыты порядковые номера строк (1, 2, 3…): записи упорядочены по номеру договора/акта или по дате
    init = QTableWidget.__init__

    def table_init(self, *args, **kwargs):
        init(self, *args, **kwargs)
        self.verticalHeader().setVisible(False)

    QTableWidget.__init__ = table_init
