"""Оконный режим: у всех окон программы (карточки, реестры, диалоги) есть кнопки «свернуть» и «развернуть», окна растягиваются мышью за край, привязываются к половине экрана клавишами
Win + стрелка (Windows требует для этого кнопку «развернуть»), раскрываются на весь экран клавишей F11 (повторное нажатие возвращает прежний размер), а размер и положение окна
запоминаются отдельно для каждого окна на этом компьютере. Без зависимости от базы данных: размеры хранятся в локальном ini-файле."""
import logging

from PyQt6.QtCore import QEvent, QObject, QSettings, Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QColorDialog, QDialog, QFileDialog, QFontDialog, QInputDialog, QMessageBox, QProgressDialog

SETTINGS_PATH = None          # путь к ini-файлу (задаётся при запуске программы); None — запоминание размеров выключено
SKIP = (QMessageBox, QInputDialog, QFileDialog, QColorDialog, QFontDialog, QProgressDialog)       # короткие системные диалоги остаются обычными
MIN_VISIBLE = 120             # сохранённое окно должно хотя бы частично попадать на какой-то экран


def _settings():
    return QSettings(str(SETTINGS_PATH), QSettings.Format.IniFormat) if SETTINGS_PATH else None


def key_of(widget):
    cls = type(widget)
    return f'{cls.__module__}.{cls.__qualname__}'.replace('/', '_').replace('\\', '_')


def toggle_fullscreen(widget):
    """F11: на весь экран и обратно (возвращается прежнее состояние — обычное или развёрнутое)."""
    if widget.isFullScreen():
        widget.showMaximized() if widget.property('_wm_was_maximized') else widget.showNormal()
    else:
        widget.setProperty('_wm_was_maximized', widget.isMaximized())
        widget.showFullScreen()


def allow_resize_buttons(widget):
    """Кнопки «свернуть» и «развернуть» (а с ними — Win + стрелка, растягивание за край) для окна."""
    widget.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
    widget.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
    if isinstance(widget, QDialog):
        widget.setSizeGripEnabled(True)


def restore_geometry(widget):
    s = _settings()
    if s is None:
        return
    try:
        data = s.value('geometry/' + key_of(widget))
        if data and widget.restoreGeometry(data if not isinstance(data, str) else bytes.fromhex(data)):
            return
    except Exception:
        logging.info('Размер окна не восстановлен', exc_info=True)


def save_geometry(widget):
    s = _settings()
    if s is None or widget.isFullScreen() or widget.isMinimized():
        return
    try:
        s.setValue('geometry/' + key_of(widget), bytes(widget.saveGeometry()).hex())
        s.sync()
    except Exception:
        logging.info('Размер окна не сохранён', exc_info=True)


def attach(widget, remember=True):
    """Подключает возможности оконного режима к одному окну (повторный вызов безвреден)."""
    if widget.property('_wm_attached'):
        return
    widget.setProperty('_wm_attached', True)
    allow_resize_buttons(widget)
    shortcut = QShortcut(QKeySequence('F11'), widget)
    shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
    shortcut.activated.connect(lambda w=widget: toggle_fullscreen(w))
    widget.setProperty('_wm_remember', bool(remember))      # размер восстанавливается при первом показе окна (см. WindowModeFilter)


class WindowModeFilter(QObject):
    """Фильтр событий приложения: каждое открываемое диалоговое окно получает кнопки окна, F11 и запоминание размера."""

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.Polish and isinstance(obj, QDialog) and not isinstance(obj, SKIP) and obj.isWindow() and not obj.property('_wm_attached'):
            try:
                attach(obj)
            except Exception:
                logging.info('Оконный режим не подключён', exc_info=True)
        elif kind == QEvent.Type.Show and obj.property('_wm_attached') and obj.property('_wm_remember') and not obj.property('_wm_restored') and obj.isWindow():
            obj.setProperty('_wm_restored', True)
            restore_geometry(obj)
        elif kind == QEvent.Type.Hide and obj.property('_wm_attached') and obj.property('_wm_remember') and obj.isWindow() and not obj.isVisible():
            save_geometry(obj)
        return False


_filter = None


def install(app, settings_path=None):
    """Включает оконный режим для всего приложения; settings_path — ini-файл для запоминания размеров окон на этом компьютере."""
    global _filter, SETTINGS_PATH
    SETTINGS_PATH = settings_path
    if _filter is None:
        _filter = WindowModeFilter(app)
        app.installEventFilter(_filter)
    return _filter
