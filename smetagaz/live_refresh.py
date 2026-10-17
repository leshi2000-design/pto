"""Автообновление открытого раздела, когда данные изменил кто-то другой (по сети или второй экземпляр программы на сервере)."""
from PyQt6.QtWidgets import (QAbstractItemView, QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTableWidget, QTextEdit)

IGNORE_TABLES = {'edit_locks', 'audit_log', 'audit_ctx', 'settings', 'error_log', 'backups'}        # служебные таблицы: списки из-за них не обновляем
TEXT_WIDGETS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


def relevant(tables):
    """Есть ли среди изменённых таблиц те, что видны пользователю."""
    return bool(set(tables) - IGNORE_TABLES)


def can_refresh(view):
    """Нельзя обновлять, пока открыто модальное окно или человек что-то вводит в этом разделе."""
    if view is None or not view.isVisible() or QApplication.activeModalWidget() is not None:
        return False
    focus = QApplication.focusWidget()
    if focus is not None and view.isAncestorOf(focus):
        if isinstance(focus, TEXT_WIDGETS) and not getattr(focus, 'isReadOnly', lambda: False)():
            return False
        if isinstance(focus, QAbstractItemView) and focus.state() == QAbstractItemView.State.EditingState:
            return False
    return True


def _snapshot(view):
    state = []
    for table in view.findChildren(QAbstractItemView):
        marker = None
        if isinstance(table, QTableWidget):
            row = table.currentRow()
            item = table.item(row, 0) if row >= 0 else None
            if item is not None:
                marker = (item.data(0x0100), item.text(), table.currentColumn())      # 0x0100 = Qt.UserRole
        state.append((table, table.verticalScrollBar().value(), table.horizontalScrollBar().value(), marker))
    return state


def _restore(state):
    for table, vert, horiz, marker in state:
        try:
            if marker is not None and isinstance(table, QTableWidget):
                for row in range(table.rowCount()):
                    item = table.item(row, 0)
                    if item is not None and item.data(0x0100) == marker[0] and (marker[0] is not None or item.text() == marker[1]):
                        table.setCurrentCell(row, max(0, marker[2]))
                        break
            table.verticalScrollBar().setValue(vert)
            table.horizontalScrollBar().setValue(horiz)
        except RuntimeError:
            pass                                          # виджет пересоздан при обновлении


def refresh(view):
    """Перечитывает раздел, сохраняя прокрутку и выбранную запись. -> True, если обновили."""
    loader = getattr(view, 'load_data', None)
    if loader is None or getattr(view, 'no_autorefresh', False):
        return False
    state = _snapshot(view)
    loader()
    _restore(state)
    return True
