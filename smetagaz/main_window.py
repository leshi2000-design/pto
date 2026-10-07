"""
Главное окно приложения. Динамическая генерация вкладок из БД + Глобальный поиск с навигацией.
"""
import sys
import logging
import traceback
import json
try:
    import qdarktheme
except ImportError:
    qdarktheme = None

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                              QHBoxLayout, QPushButton, QLabel, QStackedWidget,
                              QFrame, QScrollArea, QMessageBox, QDialog, QLineEdit, QListWidget, QListWidgetItem)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt, QTimer, QLockFile
from PyQt6.QtGui import QShortcut, QKeySequence
from .workspace_view import WorkspaceView, open_record
from .config import DATA_DIR
from .data_services import search, SOURCES
from concurrent.futures import ThreadPoolExecutor

from .database import db
from .services import AutoBackupService
from .estimates_registry import EstimatesView
from .contracts_registry import ContractsRegistryView
from .materials_view import MaterialsView
from .statistics_view import StatisticsView
from .settings_view import SettingsView
from .gsv_view import GsvProjectsView
from .today_view import TodayView
from .executive_view import ExecutiveDocsView

from .gsv_catalog import GsvCatalogView
from .extra_views import GsnProjectsView, WeldersView, CalculatorsView, WriteoffView
from .legal_entities_view import LegalEntitiesView
from .counterparty_ui import SmrView

class GlobalSearchDialog(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setWindowTitle("Глобальный поиск · Ctrl+K");self.resize(850,600)
        layout=QVBoxLayout(self);self.inp=QLineEdit();self.inp.setPlaceholderText("Слова или начало слова: клиент, телефон, номер, название файла…")
        layout.addWidget(self.inp);self.results=QListWidget();layout.addWidget(self.results)
        self.status=QLabel("Поиск по всем реестрам. Содержимое вложений не индексируется.");layout.addWidget(self.status)
        self.more=QPushButton("Следующие 100 результатов");layout.addWidget(self.more);self.more.clicked.connect(self.next_page)
        self.offset=0;self.generation=0;self.future=None;self.pool=ThreadPoolExecutor(max_workers=1)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(250);self.timer.timeout.connect(self.submit)
        self.poller=QTimer(self);self.poller.setInterval(50);self.poller.timeout.connect(self.poll);self.poller.start()
        self.inp.textChanged.connect(self.changed);self.results.itemActivated.connect(self.open)
    def changed(self,*_):
        self.offset=0;self.generation+=1;self.timer.start()
    def next_page(self):self.offset+=100;self.generation+=1;self.timer.start()
    def submit(self):
        if self.future and not self.future.done():self.timer.start();return
        self.request_generation=self.generation
        self.future=self.pool.submit(search,db,self.inp.text(),101,self.offset)
    def poll(self):
        if not self.future or not self.future.done():return
        future=self.future;self.future=None
        if self.request_generation!=self.generation:return
        try:rows=future.result()
        except Exception as e:self.status.setText(str(e));return
        self.results.clear();self.more.setEnabled(len(rows)>100)
        for kind,rid,title,snippet in rows[:100]:
            item=QListWidgetItem(f"{SOURCES[kind][0]} · {title or 'Без названия'}\n{snippet}");item.setData(Qt.ItemDataRole.UserRole,(kind,rid));self.results.addItem(item)
        self.status.setText(f"Показано: {len(rows[:100])}. Поиск по словам и их началу; двойной щелчок — карточка.")
    def open(self,item):
        kind,rid=item.data(Qt.ItemDataRole.UserRole);open_record(kind,rid,self)
    def reject(self):
        self.timer.stop();self.poller.stop();self.pool.shutdown(wait=False,cancel_futures=True);super().reject()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.app_name = db.get_setting("app_name", "СМЕТА-ГАЗ 1.0")
        self.setWindowTitle(self.app_name)
        self.resize(1350, 820)
        self.backup_service = AutoBackupService()
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(lambda: GlobalSearchDialog(self).exec())

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(232);sidebar.setObjectName("sidebar")
        self.sidebar_layout = QVBoxLayout(sidebar)

        logo = QLabel("СМЕТА · ГАЗ")
        logo.setObjectName("brand")

        logo.setWordWrap(True)
        self.sidebar_layout.addWidget(logo)

        btn_search = QPushButton("Поиск · Ctrl+K")
        btn_search.setProperty("type","primary")
        btn_search.clicked.connect(lambda: GlobalSearchDialog(self).exec())
        self.sidebar_layout.addWidget(btn_search)
        self.sidebar_layout.addSpacing(15)

        self.stack = QStackedWidget()
        root_layout.addWidget(sidebar)
        content=QWidget();content_layout=QVBoxLayout(content);content_layout.setContentsMargins(0,0,0,0);content_layout.setSpacing(0)
        header=QFrame();header.setObjectName('pageHeader');head=QVBoxLayout(header);head.setContentsMargins(24,17,24,16)
        self.page_title=QLabel();self.page_title.setObjectName('pageTitle');head.addWidget(self.page_title)
        self.page_subtitle=QLabel('Данные, документы и отчёты в одном рабочем пространстве');self.page_subtitle.setObjectName('pageSubtitle');head.addWidget(self.page_subtitle)
        content_layout.addWidget(header);content_layout.addWidget(self.stack,1);root_layout.addWidget(content,1)
        nav=QScrollArea();nav.setObjectName('navigation');nav.setWidgetResizable(True);nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_content=QWidget();nav_content.setObjectName('navContent');self.nav_layout=QVBoxLayout(nav_content);self.nav_layout.setContentsMargins(0,0,4,0);self.nav_layout.setSpacing(3);nav.setWidget(nav_content);self.sidebar_layout.addWidget(nav,1)

        self.view_classes = {
            "workspace": WorkspaceView,
            "clients": lambda: WorkspaceView("crm.clients"),
            "tasks": TodayView,
            "estimates": EstimatesView,
            "contracts": ContractsRegistryView,
            "gsv": GsvProjectsView,
            "gsn": GsnProjectsView,
            "legal_entities": LegalEntitiesView,
            "smr": SmrView,
            "exec": ExecutiveDocsView,
            "materials": MaterialsView,
            "welders": WeldersView,
            "gsv_catalog": GsvCatalogView,
            "calculators": CalculatorsView,
            "writeoff": WriteoffView,
            "stats": StatisticsView,
            "settings": SettingsView
        }

        self.tabs_buttons = []
        self.views = []
        self.build_dynamic_tabs()

        self.nav_layout.addStretch()
        self.btn_toggle_theme = QPushButton("Переключить тему")
        self.btn_toggle_theme.clicked.connect(self.toggle_theme)
        self.sidebar_layout.addWidget(self.btn_toggle_theme)

        self.refresh_ui()

    def build_dynamic_tabs(self):
        tabs_json = db.get_setting("tabs_config", "[]")
        try:
            tabs_data = json.loads(tabs_json)
        except (ValueError, TypeError) as e:
            logging.warning(f"Некорректный tabs_config, сброшен: {e}")
            tabs_data = []

        known_tabs = [
            ("workspace", "Все реестры · быстрый обзор"),
            ("clients", "Клиенты"),
            ("tasks", "Сегодня"),
            ("estimates", "Реестр смет"),
            ("contracts", "Монтаж ГСВ"),
            ("gsv", "Проекты ГСВ"),
            ("gsn", "Монтаж ГСН"),
            ("legal_entities", "Юрлица"),
            ("smr", "СМР"),
            ("exec", "Исполнительная док."),
            ("materials", "Справочник"),
            ("welders", "Сварщики"),
            ("gsv_catalog", "Справочники ГСВ"),
            ("calculators", "Калькуляторы"),
            ("writeoff", "Списание"),
            ("stats", "Статистика"),
            ("settings", "Настройки")
        ]

        existing_ids = {t["id"] for t in tabs_data}
        changed = False

        for t_id, t_name in known_tabs:
            if t_id not in existing_ids:
                insert_idx = len(tabs_data)
                for i, tab in enumerate(tabs_data):
                    if tab["id"] in ("stats", "settings"):
                        insert_idx = i
                        break
                tabs_data.insert(insert_idx, {"id": t_id, "name": t_name, "visible": 1})
                changed = True

        if changed:
            db.set_setting("tabs_config", json.dumps(tabs_data))

        for tab_cfg in tabs_data:
            if not tab_cfg.get("visible", 1): continue

            tab_id = tab_cfg["id"]
            if tab_id not in self.view_classes: continue

            view_class = self.view_classes[tab_id]
            view_instance = QWidget();view_instance._tab_id=tab_id
            view_instance._factory = lambda c=view_class, t=tab_id: c(self) if t == "settings" else c()

            btn = QPushButton(tab_cfg["name"])
            from .icons import icon
            btn.setIcon(icon(tab_id))
            btn.setObjectName("navButton");btn.setToolTip(tab_cfg["name"])
            btn.setCheckable(True)
            btn.setMinimumHeight(32)

            self.stack.addWidget(view_instance)
            self.nav_layout.addWidget(btn)

            self.tabs_buttons.append(btn)
            self.views.append(view_instance)

            btn.clicked.connect(lambda checked, idx=len(self.tabs_buttons)-1, b=btn: self.switch_tab(idx, b))

        if self.tabs_buttons:
            self.switch_tab(0, self.tabs_buttons[0])

    def switch_tab(self, idx, target_btn):
        view = self.views[idx]
        if hasattr(view, '_factory'):
            replacement = view._factory()
            self.stack.removeWidget(view)
            self.stack.insertWidget(idx, replacement)
            replacement._tab_id=view._tab_id
            self.views[idx] = replacement
            view.deleteLater()
        self.stack.setCurrentIndex(idx)
        for b in self.tabs_buttons: b.setChecked(False)
        target_btn.setChecked(True)
        self.page_title.setText(target_btn.text())

        view = self.views[idx]
        if hasattr(view, 'load_data'): view.load_data()
        elif hasattr(view, 'calculate'): view.calculate()

    def closeEvent(self, event):
        self.backup_service.close()
        event.accept()

    def toggle_theme(self):
        is_dark = db.get_setting("is_dark", "0") == "1"
        db.set_setting("is_dark", "0" if is_dark else "1")
        self.refresh_ui()

    def refresh_ui(self):
        is_dark = db.get_setting("is_dark", "0") == "1"
        theme = "dark" if is_dark else "light"
        accent = db.get_setting("accent_color", "#0284C7")
        f_family = db.get_setting("font_family", "Segoe UI")
        f_size = int(db.get_setting("font_size", "10"))

        app = QApplication.instance()
        app.setFont(QFont(f_family, f_size))

        from .theme import apply
        apply(app,is_dark,f_family,f_size)

        for view in self.views:
            if hasattr(view, 'refresh_ui'): view.refresh_ui()

def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt): return sys.__excepthook__(exc_type, exc_value, exc_traceback)
    error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logging.critical(f"Критическая ошибка:\n{error_text}")
    print("\n" + "="*50 + f"\nКРИТИЧЕСКАЯ ОШИБКА:\n{error_text}", file=sys.stderr)
    try: QMessageBox.critical(None, "Ошибка", f"Произошла ошибка:\n{exc_value}")
    except Exception: pass

def main():
    sys.excepthook = global_exception_handler
    app = QApplication(sys.argv)
    lock = QLockFile(str(DATA_DIR / 'app.lock'))
    if not lock.tryLock(100):
        QMessageBox.warning(None, 'СМЕТА-ГАЗ', 'Эта папка данных уже открыта другим экземпляром.');return
    import os
    os.chdir(DATA_DIR)
    db.init_db()
    from .security import login
    if not login(db):return
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
