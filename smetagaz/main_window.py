"""
Главное окно приложения. Динамическая генерация вкладок из БД + Глобальный поиск с навигацией.
"""
import sys
import time
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
from PyQt6.QtCore import QSize, Qt, QTimer, QLockFile
from PyQt6.QtGui import QShortcut, QKeySequence
from .workspace_view import WorkspaceView, open_record
from .config import DATA_DIR
from .data_services import search, SOURCES
from concurrent.futures import ThreadPoolExecutor

from .database import db
from .services import AutoBackupService, NoBackupService
from .estimates_registry import EstimatesView
from .contracts_registry import ContractsRegistryView
from .materials_view import MaterialsView
from .statistics_view import StatisticsView
from .settings_view import SettingsView
from .gsv_view import GsvProjectsView
from .today_view import TodayView
from .executive_view import ExecutiveDocsView

from .gsv_catalog import GsvCatalogView
from .gsn_catalog import GsnCatalogView
from .estimates_ui import EstimatesModule
from .extra_views import GsnProjectsView, WeldersView, CalculatorsView, WriteoffView
from .legal_entities_view import LegalEntitiesView
from .audit_view import AuditView
from .error_view import ErrorLogView
from .staff_view import StaffView
from .counterparty_ui import CounterpartyView, LegalDirectoryView
from .orders_view import OrdersView
from .docs_view import DocumentsView
from .ip_view import IpView
from .incoming_view import IncomingView, process_files
from . import error_log
from .counterparty_ui import SmrView  # noqa: F401

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
        self.offset=0;self.generation+=1;self.more.setEnabled(False);self.timer.start()
    def next_page(self):
        if not self.more.isEnabled():return        # страница ещё загружается — повторные нажатия не пропускают результаты
        self.more.setEnabled(False);self.offset+=100;self.generation+=1;self.timer.start()
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


# Боковое меню по разделам: (название раздела, [модули]). Раздел из одного модуля показывается обычной кнопкой.
NAV_SECTIONS = [
    ('Сегодня', ['tasks']),
    ('Услуги', ['gsv', 'contracts', 'gsn', 'ip', 'fl']),
    ('Сметы', ['estimates']),
    ('Клиенты', ['clients']),
    ('Юрлица', ['legal_entities', 'smr', 'to', 'le_other']),
    ('Работники', ['orders', 'welders', 'staff']),
    ('Документы', ['docs']),
    ('Дополнительно', ['writeoff', 'calculators', 'stats', 'exec', 'workspace', 'incoming', 'audit', 'errors']),
    ('Справочники', ['gsv_catalog', 'gsn_catalog', 'materials']),
    ('Настройки', ['settings']),
]
KNOWN_TABS = [
    ("tasks", "Сегодня"), ("gsv", "Проекты ГСВ"), ("contracts", "Монтаж ГСВ"), ("gsn", "Монтаж ГСН"), ("ip", "СМР (ИП)"), ("fl", "СМР (физлица)"), ("le_other", "Прочие (юр.лица)"),
    ("clients", "Клиенты"), ("legal_entities", "Справочник юрлиц"), ("smr", "СМР (юрлица)"), ("to", "ТО (юрлица)"),
    ("orders", "Наряды"), ("docs", "Документы"), ("welders", "Сварщики"), ("writeoff", "Списание"), ("calculators", "Калькуляторы"), ("stats", "Статистика"),
    ("estimates", "Реестр смет"), ("exec", "Исполнительная док."), ("workspace", "Все реестры · быстрый обзор"), ("audit", "Журнал и корзина"), ("errors", "Журнал ошибок"), ("staff", "Сотрудники и бригады"), ("incoming", "Входящие документы"),
    ("gsv_catalog", "Справочники ГСВ"), ("gsn_catalog", "Справочник ГСН"), ("materials", "Справочник"),
    ("settings", "Настройки"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.app_name = db.get_setting("app_name", "ПТО")
        self.setWindowTitle(self.app_name)
        if getattr(db, 'is_remote', False):
            self.setWindowTitle(f'{self.app_name} · {db.user} · сервер {db.cfg["host"]}')
        elif getattr(db, 'side_by_side', False):
            self.setWindowTitle(f'{self.app_name} · локально, параллельно с ПТО Сервером')
        self.setAcceptDrops(True)       # файлы можно перетаскивать в любое место окна: откроется проверка входящего документа
        self.err_timer = QTimer(self); self.err_timer.setInterval(20000); self.err_timer.timeout.connect(self.update_error_badge); self.err_timer.start()
        self.resize(1350, 820)
        self.backup_service = NoBackupService() if (getattr(db, 'is_remote', False) or getattr(db, 'side_by_side', False)) else AutoBackupService()
        QShortcut(QKeySequence("Ctrl+K"), self).activated.connect(lambda: GlobalSearchDialog(self).exec())
        for keys, handler in (("Ctrl+N", self.shortcut_new), ("Ctrl+S", self.shortcut_save), ("Ctrl+F", self.shortcut_find), ("F1", self.show_help)):
            QShortcut(QKeySequence(keys), self).activated.connect(handler)
        QTimer.singleShot(8000, self.check_updates_quietly)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setFixedWidth(264);sidebar.setObjectName("sidebar")
        self.sidebar_layout = QVBoxLayout(sidebar)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(6, 4, 6, 4)
        self.logo_mark = QLabel()
        self.logo_mark.setFixedSize(40, 40)
        logo = QLabel("ПТО")
        logo.setObjectName("brand")
        brand_row.addWidget(self.logo_mark)
        brand_row.addWidget(logo, 1)
        self.sidebar_layout.addLayout(brand_row)

        btn_search = QPushButton("Поиск · Ctrl+K")
        btn_search.setProperty("type","primary")
        btn_search.clicked.connect(lambda: GlobalSearchDialog(self).exec())
        self.sidebar_layout.addWidget(btn_search)
        self.sidebar_layout.addSpacing(15)

        self.stack = QStackedWidget()
        root_layout.addWidget(sidebar)
        content=QWidget();content_layout=QVBoxLayout(content);content_layout.setContentsMargins(0,0,0,0);content_layout.setSpacing(0)
        header=QFrame();header.setObjectName('pageHeader');head=QVBoxLayout(header);head.setContentsMargins(24,17,24,16)
        title_row=QHBoxLayout();self.page_title=QLabel();self.page_title.setObjectName('pageTitle');title_row.addWidget(self.page_title,1)
        self.btn_help=QPushButton('?  Справка · F1');self.btn_help.setToolTip('Справка по разделу, горячие клавиши, проверка обновлений');self.btn_help.clicked.connect(self.show_help);title_row.addWidget(self.btn_help)
        head.addLayout(title_row)
        self.page_subtitle=QLabel('Данные, документы и отчёты в одном рабочем пространстве');self.page_subtitle.setObjectName('pageSubtitle');head.addWidget(self.page_subtitle)
        content_layout.addWidget(header);content_layout.addWidget(self.stack,1);root_layout.addWidget(content,1)
        nav=QScrollArea();nav.setObjectName('navigation');nav.setWidgetResizable(True);nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_content=QWidget();nav_content.setObjectName('navContent');self.nav_layout=QVBoxLayout(nav_content);self.nav_layout.setContentsMargins(0,0,4,0);self.nav_layout.setSpacing(3);nav.setWidget(nav_content);self.sidebar_layout.addWidget(nav,1)

        self.view_classes = {
            "workspace": WorkspaceView,
            "audit": AuditView,
            "errors": ErrorLogView,
            "staff": StaffView,
            "incoming": IncomingView,
            "clients": lambda: WorkspaceView("crm.clients"),
            "tasks": TodayView,
            "estimates": EstimatesModule,
            "contracts": ContractsRegistryView,
            "gsv": GsvProjectsView,
            "gsn": GsnProjectsView,
            "legal_entities": LegalDirectoryView,
            "smr": lambda: CounterpartyView("smr"),
            "to": lambda: CounterpartyView("to"),
            "ip": IpView,
            "fl": lambda: CounterpartyView("fl"),
            "le_other": lambda: CounterpartyView("le"),
            "orders": OrdersView,
            "docs": DocumentsView,
            "exec": ExecutiveDocsView,
            "materials": MaterialsView,
            "welders": WeldersView,
            "gsv_catalog": GsvCatalogView,
            "gsn_catalog": GsnCatalogView,
            "calculators": CalculatorsView,
            "writeoff": WriteoffView,
            "stats": StatisticsView,
            "settings": SettingsView
        }

        self.tabs_buttons = []
        self.views = []
        self.build_dynamic_tabs()

        self.nav_layout.addStretch()
        if getattr(db, 'is_remote', False):
            from .network_ui import attach_status
            self.net_label = attach_status(self, db)
            self.sidebar_layout.addWidget(self.net_label)
            self.net_timer = QTimer(self)
            self.net_timer.timeout.connect(db.ping)
            self.net_timer.start(30000)
        if getattr(db, 'is_remote', False) or getattr(db, 'side_by_side', False):
            self._changes_pending = False
            self.live_timer = QTimer(self)
            self.live_timer.timeout.connect(self.live_refresh)
            self.live_timer.start(3000)         # раз в 3 секунды спрашиваем, не менял ли данные кто-то другой
        self.btn_toggle_theme = QPushButton("Переключить тему")
        self.btn_toggle_theme.clicked.connect(self.toggle_theme)
        self.sidebar_layout.addWidget(self.btn_toggle_theme)

        self.refresh_ui()

    def build_dynamic_tabs(self):
        tabs_json = db.get_setting("tabs_config", "[]")
        from .database import parse_tabs_config
        tabs_data = parse_tabs_config(tabs_json)

        existing_ids = {t["id"] for t in tabs_data}
        changed = False
        for t_id, t_name in KNOWN_TABS:
            if t_id not in existing_ids:
                tabs_data.append({"id": t_id, "name": t_name, "visible": 1})
                changed = True
        if changed:
            db.set_setting("tabs_config", json.dumps(tabs_data))
        config = {t["id"]: t for t in tabs_data}
        placed = {tab_id for _title, ids in NAV_SECTIONS for tab_id in ids}
        sections = [(title, list(ids)) for title, ids in NAV_SECTIONS]
        extra = [t["id"] for t in tabs_data if t["id"] not in placed and t["id"] in self.view_classes]
        if extra:      # модули, которых нет в схеме меню, попадают в «Дополнительно»
            for title, ids in sections:
                if title == 'Дополнительно':
                    ids.extend(extra)
        from .icons import icon
        shown_sections = 0
        for title, ids in sections:
            hidden = set(getattr(db, 'hidden', ()))           # разделы, закрытые для этого пользователя администратором сервера
            visible = [i for i in ids if i in self.view_classes and config.get(i, {}).get("visible", 1) and i not in hidden]
            if not visible:
                continue
            if shown_sections:      # разделы отделены друг от друга линией; сворачиваемых деревьев нет
                line = QFrame()
                line.setObjectName("navDivider")
                line.setFixedHeight(1)
                self.nav_layout.addSpacing(6)
                self.nav_layout.addWidget(line)
                self.nav_layout.addSpacing(4)
            shown_sections += 1
            first_name = config.get(visible[0], {}).get("name") or dict(KNOWN_TABS).get(visible[0], visible[0])
            if len(visible) > 1 or first_name.casefold() != title.casefold():
                header = QLabel(title.upper())
                header.setObjectName("navSection")
                self.nav_layout.addWidget(header)
            target = self.nav_layout
            for tab_id in visible:
                view_class = self.view_classes[tab_id]
                view_instance = QWidget()
                view_instance._tab_id = tab_id
                view_instance._factory = lambda c=view_class, t=tab_id: c(self) if t == "settings" else c()
                name = config.get(tab_id, {}).get("name") or dict(KNOWN_TABS).get(tab_id, tab_id)
                btn = QPushButton(name)
                btn.setIcon(icon(tab_id))
                btn.setIconSize(QSize(20, 20))
                btn.setObjectName("navButton")
                btn.setToolTip(name)
                btn.setCheckable(True)
                btn.setMinimumHeight(32)
                self.stack.addWidget(view_instance)
                target.addWidget(btn)
                self.tabs_buttons.append(btn)
                self.views.append(view_instance)
                btn.clicked.connect(lambda checked, idx=len(self.tabs_buttons) - 1, b=btn: self.switch_tab(idx, b))

        if self.tabs_buttons:
            self.switch_tab(0, self.tabs_buttons[0])

    def live_refresh(self):
        """Данные изменил другой пользователь — открытый раздел перечитывается сам (если человек в нём сейчас ничего не вводит)."""
        from . import live_refresh
        changed = db.poll_changes()
        if changed and live_refresh.relevant(changed):
            self._changes_pending = True
        if not self._changes_pending:
            return
        view = self._current_view()
        if view is None:
            return
        if live_refresh.can_refresh(view):
            self._changes_pending = False
            try:
                if live_refresh.refresh(view):
                    self.statusBar().showMessage('Данные обновлены: их изменил другой пользователь.', 3000)
            except Exception:
                logging.exception('Автообновление раздела не удалось')

    def _current_view(self):
        idx = self.stack.currentIndex()
        return self.views[idx] if 0 <= idx < len(self.views) else None

    @staticmethod
    def _click_button(root, starts=(), contains=()):
        from PyQt6.QtWidgets import QPushButton as _B
        for button in root.findChildren(_B):
            text = button.text().replace('＋', '').replace('+', '').strip().casefold()
            if button.isVisible() and button.isEnabled() and (any(text.startswith(p.casefold()) for p in starts) or any(c.casefold() in text for c in contains)):
                button.click()
                return True
        return False

    def shortcut_new(self):
        if QApplication.activeModalWidget():
            return
        view = self._current_view()
        if view is not None and not self._click_button(view, starts=('Создать договор', 'Создать смету', 'Новый проект', 'Новый клиент', 'Новый', 'Добавить юрлицо', 'Добавить')):
            self.statusBar().showMessage('В этом разделе нет создания записи.', 3000)

    def shortcut_save(self):
        target = QApplication.activeModalWidget() or self._current_view()
        if target is not None:
            self._click_button(target, starts=('Сохранить',))

    def shortcut_find(self):
        from PyQt6.QtWidgets import QLineEdit as _L
        view = self._current_view()
        for edit in (view.findChildren(_L) if view is not None else []):
            if edit.isVisible() and edit.isEnabled() and not edit.isReadOnly():
                edit.setFocus();edit.selectAll();return

    def show_help(self):
        from .help_view import HelpDialog
        view = self._current_view()
        HelpDialog(getattr(view, '_tab_id', ''), self).exec()

    def check_updates_quietly(self):
        """Раз в неделю, если задан адрес: сообщает о новой версии в подзаголовке страницы."""
        try:
            from . import updater
            if not db.get_setting('update_url', '').strip():
                return
            newer, info, message = updater.check(db)
            if newer:
                self.page_subtitle.setText(message + ' Справка → «Проверить обновления».')
        except Exception:
            logging.info('Проверка обновлений не удалась', exc_info=True)

    def switch_tab(self, idx, target_btn):
        view = self.views[idx]
        if hasattr(view, '_factory'):
            replacement = view._factory()
            self.stack.removeWidget(view)
            from PyQt6.QtWidgets import QScrollArea
            holder = QScrollArea()          # широкая страница прокручивается и не растягивает главное окно
            holder.setWidgetResizable(True)
            holder.setFrameShape(QScrollArea.Shape.NoFrame)
            holder.setWidget(replacement)
            self.stack.insertWidget(idx, holder)
            replacement._tab_id=view._tab_id
            replacement._factory_saved = view._factory
            self.views[idx] = replacement
            view.deleteLater()
        self.stack.setCurrentIndex(idx)
        for b in self.tabs_buttons: b.setChecked(False)
        target_btn.setChecked(True)
        self.page_title.setText(target_btn.text())
        error_log.set_section(target_btn.text())

        view = self.views[idx]
        self._changes_pending = False
        if hasattr(view, 'load_data'): view.load_data()
        elif hasattr(view, 'calculate'): view.calculate()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        event.acceptProposedAction()
        if paths and process_files(self, paths):
            for view in self.views:
                if isinstance(view, IncomingView):
                    view.load_data()

    def update_error_badge(self):
        n = error_log.unseen_count()
        base = self.windowTitle().split('  ·  новых ошибок')[0]
        self.setWindowTitle(f'{base}  ·  новых ошибок: {n}  (Дополнительно → Журнал ошибок)' if n else base)

    def closeEvent(self, event):
        """Закрытие без зависания: окно скрывается сразу, нужная копия (если последней больше 30 минут) делается в фоне, затем программа завершается."""
        if getattr(self, '_closing', False):
            event.ignore()
            return
        if getattr(self, '_exit_ready', False) or not self.backup_service.exit_backup_needed():
            self.backup_service.close()
            self._exit_ready = True
            from . import edit_locks
            edit_locks.release_all(db)          # открытые карточки не должны оставаться «занятыми»
            event.accept()
            return
        event.ignore()
        self._closing = True
        self.hide()
        self._exit_future = self.backup_service.start_exit_backup()
        self._exit_started = time.monotonic()
        self._exit_timer = QTimer(self)
        self._exit_timer.timeout.connect(self._finish_exit)
        self._exit_timer.start(100)

    def _finish_exit(self):
        if not self._exit_future.done() and time.monotonic() - self._exit_started < 180:
            return
        self._exit_timer.stop()
        self._exit_ready = True
        self._closing = False
        self.close()                        # повторное закрытие уже без копии
        QApplication.quit()

    def toggle_theme(self):
        is_dark = db.get_setting("is_dark", "0") == "1"
        db.set_setting("is_dark", "0" if is_dark else "1")
        self.release_hidden_views()
        self.refresh_ui()

    def release_hidden_views(self):
        """Открытые ранее, но не показанные сейчас страницы возвращаются в «ленивое» состояние: стиль всего приложения применяется только к видимому
        (на 4000+ виджетов смена темы занимала секунды); при следующем открытии страница создаётся заново и загружает данные."""
        current = self.stack.currentIndex()
        for idx, view in enumerate(self.views):
            factory = getattr(view, '_factory_saved', None)
            if idx == current or factory is None or getattr(view, '_keep_alive', False):
                continue
            if getattr(view, 'job', None) is not None or getattr(view, '_busy', False):
                continue                                    # идёт фоновая операция — страницу не трогаем
            placeholder = QWidget()
            placeholder._factory = factory
            placeholder._tab_id = view._tab_id
            holder = self.stack.widget(idx)
            self.stack.removeWidget(holder)
            self.stack.insertWidget(idx, placeholder)
            self.views[idx] = placeholder
            from PyQt6 import sip
            sip.delete(holder)                              # сразу, а не через очередь событий: иначе стиль применится и к ним

    def refresh_ui(self):
        is_dark = db.get_setting("is_dark", "0") == "1"
        theme = "dark" if is_dark else "light"
        accent = db.get_setting("accent_color", "#0284C7")
        f_family = db.get_setting("font_family", "Segoe UI")
        from .database import safe_font_size
        f_size = safe_font_size(db.get_setting("font_size", "10"))

        app = QApplication.instance()
        from . import theme
        windows = [w for w in app.topLevelWidgets() if w.isVisible()]
        for w in windows: w.setUpdatesEnabled(False)       # без промежуточных перерисовок при смене стиля всего приложения
        try:
            theme.apply(app,is_dark,f_family,f_size,accent)
            from .icons import icon, logo_pixmap
            self.logo_mark.setPixmap(logo_pixmap('#3DB2A3' if is_dark else '#1B5E57', 40))
            for view, btn in zip(self.views, self.tabs_buttons):
                btn.setIcon(icon(getattr(view, '_tab_id', 'workspace'), theme.icon_color(is_dark)))
            for view in self.views:
                if hasattr(view, 'refresh_ui'): view.refresh_ui()
        finally:
            for w in windows: w.setUpdatesEnabled(True)

def global_exception_handler(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt): return sys.__excepthook__(exc_type, exc_value, exc_traceback)
    error_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    logging.critical(f"Критическая ошибка:\n{error_text}")
    print("\n" + "="*50 + f"\nКРИТИЧЕСКАЯ ОШИБКА:\n{error_text}", file=sys.stderr)
    try: QMessageBox.critical(None, "Ошибка", f"Произошла ошибка:\n{exc_value}")
    except Exception: pass

def main():
    sys.excepthook = global_exception_handler
    error_log.install()
    app = QApplication(sys.argv)
    from pathlib import Path as _P
    for name in ('icon.ico', 'icon.png'):      # свой значок: положите файл в smetagaz/assets
        icon_file = _P(__file__).parent / 'assets' / name
        if icon_file.exists():
            from PyQt6.QtGui import QIcon
            app.setWindowIcon(QIcon(str(icon_file)))
            break
    lock = QLockFile(str(DATA_DIR / 'app.lock'))
    if not lock.tryLock(100):
        QMessageBox.warning(None, 'ПТО', 'Эта папка данных уже открыта другим экземпляром.');return
    import os
    os.chdir(DATA_DIR)
    if getattr(db, 'is_remote', False):
        from .network_ui import connect_client, wait_for_connection
        if not connect_client(db):
            return
        db.on_lost = lambda: wait_for_connection(db)          # при обрыве связи действие не теряется, а ждёт возвращения сервера
    else:
        server_lock = QLockFile(str(DATA_DIR / 'server.lock'))
        if server_lock.tryLock(100):
            server_lock.unlock()
        else:
            db.side_by_side = True          # ПТО Сервер уже работает с этой базой: работаем рядом с ним (копии и восстановление отключены, карточки блокируются)
    db.init_db()
    from .security import login
    if not login(db):return
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
