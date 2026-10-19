"""Единый ввод и показ дат: дд.мм.гггг, ввод цифрами (14102026) или выбор в календаре; календарь всегда открывается на сегодняшнем месяце."""
import re
import weakref

from PyQt6.QtCore import QDate, QLocale, Qt, QTimer
from PyQt6.QtWidgets import QCalendarWidget, QDateEdit, QApplication

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
    Возвращает QDate или None, если ввод (пока) не даёт допустимой даты."""
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
        parts = [digits[:2], digits[2:4], digits[4:]]
        parts = [p for p in parts if p]
    if not parts or len(parts) > 3 or not all(p.isdigit() for p in parts):
        return None
    day = int(parts[0])
    month = int(parts[1]) if len(parts) > 1 else base.month()
    year = base.year()
    if len(parts) > 2:
        y = parts[2]
        if len(y) == 3:
            if not partial_ok:
                return None                 # год ещё набирается
        else:
            year = int(y) + (2000 if len(y) <= 2 else 0)
    if not 1 <= day <= 31 or not 1 <= month <= 12 or not 1900 <= year <= 9999:
        return None
    probe = QDate(year, month, 1)
    return QDate(year, month, min(day, probe.daysInMonth()))


class DateEdit(QDateEdit):
    """QDateEdit в формате дд.мм.гггг. Цифры можно вводить с клавиатуры: выделенная секция принимает «14», затем «10», затем «2026»."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLocale(RU)
        self.setDisplayFormat('dd.MM.yyyy')
        self.setMinimumDate(QDate(1900, 1, 1))
        self.setCalendarPopup(True)
        self.setCalendarWidget(PopupCalendar(self))
        self._reset_typing()
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(2500)                    # пауза в наборе — следующая цифра начнёт новую дату
        self._idle.timeout.connect(self._reset_typing)
        self.setToolTip('Печатайте дату целиком: 14102026, 14.10.26, 14.10 или только день; Ctrl+V вставляет скопированную дату; ▾ — календарь')

    def is_empty(self):
        return False

    # --- простой ручной ввод: просто печатайте дату целиком, без перехода по секциям -----------------------------------------------
    def _typing_enabled(self):
        return self.displayFormat().startswith('dd') and not self.isReadOnly()

    def _reset_typing(self):
        self._typed = ''
        self._base = None

    def _apply_typed(self):
        base = self._base or QDate.currentDate()
        d = parse_typed(self._typed, base, partial_ok=True)
        if d is None:
            return False
        if self.minimumDate() <= d <= self.maximumDate():
            self.setDate(d)
            self.lineEdit().selectAll()
            return True
        return False

    def keyPressEvent(self, event):
        if not self._typing_enabled():
            return super().keyPressEvent(event)
        if not hasattr(self, '_typed'):
            self._reset_typing()
        if event.matches(__import__('PyQt6.QtGui', fromlist=['QKeySequence']).QKeySequence.StandardKey.Paste):
            d = parse_typed(QApplication.clipboard().text(), self.date() if not self.is_empty() else QDate.currentDate())
            if d is not None and self.minimumDate() <= d <= self.maximumDate():
                self.setDate(d)
                self.lineEdit().selectAll()
            return
        key, text = event.key(), event.text()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Escape):
            self._reset_typing()
            return super().keyPressEvent(event)
        if text and (text.isdigit() or text in '.,/- ') and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            if not self._typed:
                self._base = QDate.currentDate() if self.is_empty() else self.date()
            candidate = self._typed + text
            if text in '.,/- ' and (not self._typed or self._typed[-1] in '.,/- '):
                return                                  # разделитель без числа перед ним не нужен
            old = self._typed
            self._typed = candidate
            if not self._apply_typed():
                self._typed = old
            self._idle.start()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and self._typed:
            self._typed = self._typed[:-1]
            if self._typed:
                self._apply_typed()
            self._idle.start()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._reset_typing()
        if self._typing_enabled():
            QTimer.singleShot(0, self.lineEdit().selectAll)         # целиком выделенная дата заменяется набираемой
        elif event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason):
            self.setSelectedSection(QDateEdit.Section.DaySection)

    def focusOutEvent(self, event):
        self._reset_typing()
        super().focusOutEvent(event)


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
