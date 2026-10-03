"""
Переиспользуемые табличные виджеты общего назначения:
- ReorderTableWidget: QTableWidget с drag&drop для изменения порядка строк.
- SmartTableManager: автоматическое адаптивное выравнивание колонок.
"""
from PyQt6.QtWidgets import QTableWidget, QHeaderView, QAbstractItemView
from PyQt6.QtCore import QObject, pyqtSignal


class ReorderTableWidget(QTableWidget):
    order_changed = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setAlternatingRowColors(True)

    def dropEvent(self, event):
        super().dropEvent(event)
        self.order_changed.emit()


class SmartTableManager(QObject):
    """
    Автоматически настраивает колонки: "главная" колонка (обычно наименование) 
    растягивается на всё свободное пространство, а остальные автоматически 
    подстраиваются под ширину содержимого.
    """
    def __init__(self, table: QTableWidget, main_col: int = 0, default_widths: dict = None):
        super().__init__(table)
        self.table = table
        self.main_col = main_col
        self.apply_auto_layout()

    def apply_auto_layout(self):
        header = self.table.horizontalHeader()
        header.setResizeContentsPrecision(100)
        header.setMinimumSectionSize(80)  # Минимальная ширина для пустых колонок

        for i in range(self.table.columnCount()):
            if i == self.main_col:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)

    def adjust_main_column(self):
        # Метод оставлен пустым для обратной совместимости со старым кодом в других вкладках.
        # Вся работа теперь выполняется автоматически движком Qt.
        pass
