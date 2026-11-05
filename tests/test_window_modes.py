"""Оконный режим: кнопки «развернуть/свернуть», F11, запоминание размера окна, компактное меню главного окна."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QVBoxLayout, QLabel

from smetagaz import window_modes as wm


@pytest.fixture
def app(tmp_path):
    a = QApplication.instance() or QApplication([])
    wm.install(a, str(tmp_path / 'geom.ini'))
    yield a
    wm.SETTINGS_PATH = None


class Sample(QDialog):
    def __init__(self):
        super().__init__()
        QVBoxLayout(self).addWidget(QLabel('текст'))


def test_dialog_gets_window_buttons_grip_and_fullscreen_key(app):
    d = Sample()
    assert not d.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint            # по умолчанию у диалога нет кнопки «развернуть» — поэтому не работал Win + стрелка
    d.show()
    assert d.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint and d.windowFlags() & Qt.WindowType.WindowMinimizeButtonHint and d.isSizeGripEnabled()
    wm.toggle_fullscreen(d)
    assert d.isFullScreen()
    wm.toggle_fullscreen(d)
    assert not d.isFullScreen()
    d.showMaximized()
    wm.toggle_fullscreen(d)
    wm.toggle_fullscreen(d)
    assert d.isMaximized()                                                           # из полноэкранного — обратно в развёрнутое
    d.close()


def test_message_boxes_stay_ordinary(app):
    box = QMessageBox()
    box.show()
    assert not box.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint and not box.property('_wm_attached')
    box.close()


def test_size_is_remembered_per_window_class(app):
    d = Sample()
    d.resize(640, 480)
    d.show()
    d.resize(733, 511)
    d.close()
    again = Sample()
    again.show()
    assert (again.width(), again.height()) == (733, 511)
    again.close()
    wm.SETTINGS_PATH = None                                                          # без файла настроек запоминание выключено, ошибок нет
    third = Sample()
    third.show()
    third.close()


def test_fullscreen_size_is_not_saved(app, tmp_path):
    d = Sample()
    d.resize(500, 400)
    d.show()
    wm.toggle_fullscreen(d)
    d.close()
    again = Sample()
    again.show()
    assert not again.isFullScreen() and again.width() < 1000


def test_main_window_compact_sidebar_and_geometry(tmp_path, monkeypatch):
    import sys
    import importlib
    from smetagaz.database import DatabaseManager
    db = DatabaseManager(tmp_path / 'x.db')
    db.init_db()
    for name in ('notes_view', 'gsn_catalog', 'tasks_view', 'today_view', 'workspace_view', 'main_window', 'gsv_view', 'contract_card', 'payments_view'):
        importlib.import_module('smetagaz.' + name)
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    a = QApplication.instance() or QApplication([])
    wm.install(a, str(tmp_path / 'geom.ini'))
    from smetagaz import main_window as mw
    w = mw.MainWindow()
    wm.attach(w)
    w.resize(1300, 800)
    w.show()
    assert w.sidebar.width() == 264 and w.minimumSizeHint().width() < 700
    w.resize(800, 600)
    assert w.sidebar.width() == 64 and all(b.text() == '' and b.toolTip() for b in w.tabs_buttons)                # узкое окно: меню значками, названия в подсказках
    w.resize(1300, 800)
    assert w.sidebar.width() == 264 and all(b.text() for b in w.tabs_buttons)
    wm.toggle_fullscreen(w)
    assert w.isFullScreen()
    wm.toggle_fullscreen(w)
    w.resize(770, 560)
    wm.save_geometry(w)
    again = mw.MainWindow()
    wm.attach(again)
    again.show()
    assert (again.width(), again.height()) == (770, 560)
    db.close()


def test_settings_are_split_into_tabs(tmp_path, monkeypatch):
    import importlib
    import sys
    from smetagaz.database import DatabaseManager
    db = DatabaseManager(tmp_path / 's.db')
    db.init_db()
    for name in ('notes_view', 'gsn_catalog', 'tasks_view', 'today_view', 'workspace_view', 'main_window', 'gsv_view', 'contract_card', 'payments_view', 'settings_view'):
        importlib.import_module('smetagaz.' + name)
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    QApplication.instance() or QApplication([])
    from smetagaz import settings_view as sv
    view = sv.SettingsView(None)
    assert [view.tabs.tabText(i) for i in range(view.tabs.count())] == ['Внешний вид', 'Документы', 'Резервные копии', 'Сеть и доступ', 'Система']
    # на каждой вкладке свои разделы, ничего не потеряно
    from PyQt6.QtWidgets import QGroupBox
    titles = {i: [g.title() for g in view.tabs.widget(i).findChildren(QGroupBox)] for i in range(5)}
    assert any('Название программы' in t for t in titles[0])
    assert any('экспорта' in t for t in titles[1]) and any('Папки договоров' in t for t in titles[1]) and any('Номера разделов' in t for t in titles[1])
    assert any('Копия вне компьютера' in t for t in titles[2]) and any('Ручная копия' in t for t in titles[2]) and any('Excel' in t for t in titles[2])
    assert any('Сетевая работа' == t for t in titles[3]) and any('Веб-доступ' in t for t in titles[3]) and any('Пароль' in t for t in titles[3])
    assert any('Обновление' in t for t in titles[4]) and any('целостности' in t for t in titles[4])
    # выбранная вкладка запоминается
    view.tabs.setCurrentIndex(3)
    again = sv.SettingsView(None)
    assert again.tabs.currentIndex() == 3
    assert hasattr(view, 'off_enabled') and hasattr(view, 'inp_app_name') and hasattr(view, 'table_tabs') and hasattr(view, 'folder_edits')       # поля прежние — сохранение работает как раньше
    db.close()
