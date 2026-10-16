"""Единый ввод и показ дат: дд.мм.гггг, ввод цифрами (14102026) или выбор в календаре; календарь всегда открывается на сегодняшнем месяце."""
import re
import weakref

from PyQt6.QtCore import QDate, QLocale, Qt
from PyQt6.QtWidgets import QCalendarWidget, QDateEdit

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


class DateEdit(QDateEdit):
    """QDateEdit в формате дд.мм.гггг. Цифры можно вводить с клавиатуры: выделенная секция принимает «14», затем «10», затем «2026»."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setLocale(RU)
        self.setDisplayFormat('dd.MM.yyyy')
        self.setMinimumDate(QDate(1900, 1, 1))
        self.setCalendarPopup(True)
        self.setCalendarWidget(PopupCalendar(self))
        self.setToolTip('Введите дату цифрами (например, 14102026) или выберите в календаре')

    def is_empty(self):
        return False

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason):
            self.setSelectedSection(QDateEdit.Section.DaySection)


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
