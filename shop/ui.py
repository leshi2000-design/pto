"""Desktop UI for the independent Магазин application."""
from pathlib import Path
from decimal import Decimal
from datetime import date
import json
import shutil
import hashlib
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QSize, QDate
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPlainTextEdit, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QLabel, QMessageBox, QFileDialog, QDialog, QDialogButtonBox, QHeaderView,
    QListWidget, QListWidgetItem, QFrame, QGridLayout, QApplication, QStyle, QCalendarWidget)
from .core import Store
from . import documents, backup, sources
from .design import THEME
from .accounting import EVENTS

KINDS = {'receipt': 'Поступление', 'invoice': 'Счёт', 'shipment': 'Отгрузка'}
STATUSES = {'draft': 'Черновик', 'posted': 'Проведён', 'cancelled': 'Отменён'}


class Form(QDialog):
    def __init__(self, title, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 720 if len(fields) > 8 else 400)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.fields = {}
        for key, label, value in fields:
            if isinstance(value, list):
                widget = QComboBox()
                for text, data in value:
                    widget.addItem(text, data)
            elif key in ('details', 'seller_details', 'categories'):
                widget = QPlainTextEdit(str(value))
            else:
                widget = QLineEdit(str(value))
            self.fields[key] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {key: widget.currentData() if isinstance(widget, QComboBox) else
                widget.toPlainText().strip() if isinstance(widget, QPlainTextEdit) else widget.text().strip()
                for key, widget in self.fields.items()}


class DocumentDialog(QDialog):
    def __init__(self, store, parent, kind=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Новый документ')
        self.resize(850, 550)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kind = QComboBox()
        for key, title in KINDS.items():
            self.kind.addItem(title, key)
        if kind:
            self.kind.setCurrentIndex(self.kind.findData(kind))
            self.kind.setEnabled(False)
        self.party = QComboBox()
        for row in store.rows('SELECT * FROM parties ORDER BY name'):
            self.party.addItem(row['name'], row['id'])
        self.currency = QLineEdit('BYN')
        self.day = QLineEdit(date.today().isoformat())
        self.reference = QLineEdit()
        self.due_day = QLineEdit()
        form.addRow('Документ', self.kind)
        form.addRow('Контрагент / поставщик', self.party)
        form.addRow('Валюта', self.currency)
        form.addRow('Дата (ГГГГ-ММ-ДД)', self.day)
        form.addRow('Основание / номер накладной поставщика', self.reference)
        form.addRow('Оплатить до (ГГГГ-ММ-ДД, необязательно)', self.due_day)
        layout.addLayout(form)
        layout.addWidget(QLabel('Цена — без НДС. Количество: до 3 знаков, цена: до 2. НДС задаётся для каждой строки.'))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Товар', 'Количество', 'Цена без НДС', 'НДС, %'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        bar = QHBoxLayout()
        add = QPushButton('Добавить позицию')
        remove = QPushButton('Удалить позицию')
        price = QPushButton('Подставить цену из прайса')
        retail = QPushButton('Розничная цена')
        add.clicked.connect(self.add_line)
        remove.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        bar.addWidget(add)
        bar.addWidget(remove)
        price.clicked.connect(self.offer_price)
        bar.addWidget(price)
        retail.clicked.connect(self.retail_price)
        bar.addWidget(retail)
        layout.addLayout(bar)
        self.error = QLabel('')
        self.error.setStyleSheet('color:#b42318')
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.add_line()

    def retail_price(self):
        row = max(self.table.currentRow(), 0)
        if row >= self.table.rowCount():
            return
        price = self.store.retail(self.table.cellWidget(row, 0).currentData(), self.currency.text().strip(), self.day.text().strip())
        if price:
            self.table.item(row, 2).setText(documents.money(price['price']))
            self.table.item(row, 3).setText(str(Decimal(price['tax_bp']) / 100))
            self.error.setText('')
        else:
            self.error.setText('На выбранную дату розничная цена не установлена')

    def offer_price(self):
        row = self.table.currentRow()
        if row < 0:
            row = 0
        if row >= self.table.rowCount():
            return
        pid = self.table.cellWidget(row, 0).currentData()
        offers = self.store.rows('SELECT * FROM offers WHERE product_id=? AND currency=? ORDER BY price', (pid, self.currency.text().strip()))
        if not offers:
            self.error.setText('Для этого товара нет цен в выбранной валюте')
            return
        choices = [(f"{o['supplier']} · {documents.money(o['price'])} {o['currency']}", o['price']) for o in offers]
        dialog = Form('Выберите предложение', [('price', 'Прайс', choices)], self)
        if dialog.exec():
            self.table.item(row, 2).setText(documents.money(dialog.values()['price']))
            self.error.setText('')

    def add_line(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        combo = QComboBox()
        for product in self.store.catalog():
            combo.addItem(f"{product['sku']} · {product['name']} (склад: {Decimal(product['stock']) / 1000})", product['id'])
        self.table.setCellWidget(row, 0, combo)
        for column, text in enumerate(('1', '0.00', '0'), 1):
            self.table.setItem(row, column, QTableWidgetItem(text))
        combo.currentIndexChanged.connect(lambda _, row=row: self.autofill_retail(row))
        self.autofill_retail(row)

    def autofill_retail(self, row):
        if self.kind.currentData() == 'receipt' or row >= self.table.rowCount():
            return
        price = self.store.retail(self.table.cellWidget(row, 0).currentData(), self.currency.text().strip())
        if price:
            self.table.item(row, 2).setText(documents.money(price['price']))
            self.table.item(row, 3).setText(str(Decimal(price['tax_bp']) / 100))

    def save(self):
        try:
            items = [{'product_id': self.table.cellWidget(row, 0).currentData(),
                      'quantity': self.table.item(row, 1).text(), 'price': self.table.item(row, 2).text(),
                      'tax': self.table.item(row, 3).text()} for row in range(self.table.rowCount())]
            self.store.document(self.kind.currentData(), self.party.currentData(), items, self.currency.text().strip(), self.day.text().strip(), self.reference.text().strip(), self.due_day.text().strip())
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc))


class CrawlWorker(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, configs):
        super().__init__()
        self.configs = configs

    def run(self):
        results = []
        for config in self.configs:
            try:
                products, errors, limited = sources.crawl(config, self.progress.emit)
                results.append((config, products, errors, limited))
            except Exception as exc:
                results.append((config, [], [str(exc)], False))
        self.result.emit(results)


class Window(QMainWindow):
    def __init__(self, root, store=None):
        super().__init__()
        self.store = store or Store(root)
        documents.ensure_templates(self.store)
        self.worker = None
        self._closed = False
        QApplication.instance().setStyle('Fusion')
        QApplication.instance().setStyleSheet(THEME)
        self.setWindowTitle('Магазин — товары, склад и документы')
        self.resize(1400, 850)
        self.setMinimumSize(1080, 700)
        central = QWidget()
        shell = QHBoxLayout(central)
        shell.setContentsMargins(16, 16, 16, 12)
        shell.setSpacing(22)
        sidebar = QWidget()
        sidebar.setObjectName('Sidebar')
        sidebar.setFixedWidth(250)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 26, 18, 20)
        brand = QLabel('Магазин')
        brand.setObjectName('Brand')
        side.addWidget(brand)
        brand_note = QLabel('ТОВАРЫ · СКЛАД · ПРОДАЖИ')
        brand_note.setObjectName('BrandNote')
        side.addWidget(brand_note)
        side.addSpacing(30)
        self.navigation = QListWidget()
        self.navigation.setObjectName('Navigation')
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setIconSize(QSize(20, 20))
        side.addWidget(self.navigation, 1)
        side_note = QLabel('Локальный учёт\nДанные под вашим контролем')
        side_note.setObjectName('BrandNote')
        side.addWidget(side_note)
        shell.addWidget(sidebar)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 7, 0, 0)
        layout.setSpacing(16)
        shell.addWidget(content, 1)
        top = QHBoxLayout()
        title = QLabel('Рабочее пространство')
        title.setObjectName('PageTitle')
        top.addWidget(title)
        top.addStretch()
        settings = QPushButton('Реквизиты организации')
        settings.clicked.connect(lambda: self.guard(self.seller))
        top.addWidget(settings)
        layout.addLayout(top)
        self.summary = QLabel()
        self.summary.setObjectName('Muted')
        self.metric_values = []
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        for text in ('Товаров в справочнике', 'Товаров в наличии', 'Предложений поставщиков', 'Документов'):
            card = QFrame()
            card.setObjectName('Metric')
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 14, 18, 14)
            label = QLabel(text)
            label.setObjectName('MetricTitle')
            value = QLabel('0')
            value.setObjectName('MetricValue')
            card_layout.addWidget(label)
            card_layout.addWidget(value)
            self.metric_values.append(value)
            metrics.addWidget(card, 1)
        layout.addLayout(metrics)
        layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tables = {}
        self.page('Товары', 'products', ['Артикул', 'Название', 'Ед.', 'Категория', 'Прайсов'],
                  [('Добавить товар', self.add_product), ('Установить розничную цену', self.set_retail), ('Обновить', self.refresh)])
        self.page('Прайсы', 'offers', ['Товар', 'Поставщик', 'Цена', 'Валюта', 'Источник', 'Обновлено'],
                  [('Импорт Excel / CSV', self.import_prices), ('Добавить цену', self.add_offer), ('Обновить список', self.refresh)])
        self.page('Контрагенты', 'parties', ['Тип', 'Название / ФИО', 'УНП', 'Реквизиты'],
                  [('Добавить контрагента', self.add_party)])
        self.page('Накладные', 'documents', ['Номер', 'Дата', 'Вид', 'Контрагент', 'Валюта', 'Статус'],
                  [('Поступление', lambda: self.add_document('receipt')), ('Позиции', self.show_lines), ('Провести', self.post),
                   ('Отменить', self.cancel), ('По шаблону', self.export)])
        attachment = QPushButton('Прикрепить исходную накладную / файл')
        attachment.clicked.connect(lambda: self.guard(self.attach_source))
        self.tabs.widget(3).layout().insertWidget(1, attachment)
        self.page('Сайты поставщиков', 'sources', ['Поставщик', 'Сайт', 'Категории', 'Лимит страниц'],
                  [('Добавить сайт', self.add_source), ('Изменить', self.edit_source), ('Удалить', self.remove_source),
                   ('Обновить цены сейчас', self.update_prices), ('Результат обхода', self.show_update_log)])
        self.page('Резервные копии', 'backups', ['Архив', 'Размер, КБ'],
                  [('Создать копию', self.make_backup), ('Восстановить в новую папку', self.restore_backup)])
        self.page('Склад', 'stock', ['Артикул', 'Товар', 'Ед.', 'Остаток', 'Резерв', 'Доступно'],
                  [('Поступление', lambda: self.add_document('receipt')), ('Движения и покупатели', self.stock_history), ('Обновить', self.refresh)])
        self.page('Розничные цены', 'retail', ['Дата', 'Артикул', 'Товар', 'Цена без НДС', 'НДС %', 'Валюта'],
                  [('Установить цену', self.set_retail), ('Обновить', self.refresh)])
        self.page('Счета', 'invoices', ['Номер', 'Дата', 'Покупатель', 'Сумма', 'Оплачено', 'Долг', 'Валюта', 'Оплата / передача'],
                  [('Новый счёт', lambda: self.add_document('invoice')), ('Позиции', self.show_lines), ('Выставить / резерв', self.post),
                   ('Записать оплату', self.add_payment), ('Передать товар', self.deliver), ('По шаблону', self.export), ('Отменить', self.cancel)])
        self.page('Оплаты', 'payments', ['Дата', 'Счёт', 'Покупатель', 'Сумма', 'Валюта', 'Способ', 'Основание', 'Статус'],
                  [('Записать оплату', self.add_payment), ('Отменить оплату', self.cancel_payment)])
        self.page('Неоплаты', 'debts', ['Счёт', 'Покупатель', 'Срок оплаты', 'Сумма', 'Оплачено', 'Долг', 'Валюта', 'Товар передан'],
                  [('Записать оплату', self.add_payment), ('Отчёт по шаблону', lambda: self.export_report('debts')), ('Обновить', self.refresh)])
        self.month = date.today().strftime('%Y-%m')
        self.page('Статистика', 'statistics', ['Дата', 'Товар', 'Покупатель', 'Количество', 'Ед.', 'Выручка с НДС', 'Себестоимость', 'Маржа без НДС', 'Валюта'],
                  [('Выбрать месяц', self.choose_month), ('Отчёт по шаблону', lambda: self.export_report('statistics'))])
        self.stats_summary = QLabel()
        self.stats_summary.setWordWrap(True)
        self.tabs.widget(self.tabs.count()-1).layout().insertWidget(1, self.stats_summary)
        self.page('Календарь', 'calendar', ['Дата', 'Событие', 'Документ', 'Контрагент / товар', 'Подробности'],
                  [('Все события', lambda: self.refresh_calendar(None)), ('Отчёт по шаблону', lambda: self.export_report('calendar'))])
        self.calendar_widget = QCalendarWidget()
        self.calendar_widget.setMaximumHeight(230)
        self.calendar_widget.setGridVisible(True)
        self.calendar_widget.clicked.connect(lambda day: self.refresh_calendar(day.toString('yyyy-MM-dd')))
        self.tabs.widget(self.tabs.count()-1).layout().insertWidget(1, self.calendar_widget)
        self.calendar_day = None
        order = ['Склад', 'Товары', 'Прайсы', 'Розничные цены', 'Накладные', 'Счета', 'Оплаты', 'Неоплаты', 'Календарь', 'Статистика', 'Контрагенты', 'Сайты поставщиков', 'Резервные копии']
        for target, title in enumerate(order):
            index = next(i for i in range(self.tabs.count()) if self.tabs.tabText(i) == title)
            self.tabs.tabBar().moveTab(index, target)
        self.tabs.tabBar().hide()
        icons = [QStyle.StandardPixmap.SP_DirIcon, QStyle.StandardPixmap.SP_FileDialogDetailedView,
                 QStyle.StandardPixmap.SP_DirHomeIcon, QStyle.StandardPixmap.SP_FileIcon,
                 QStyle.StandardPixmap.SP_BrowserReload, QStyle.StandardPixmap.SP_DialogSaveButton]
        for index in range(self.tabs.count()):
            self.navigation.addItem(QListWidgetItem(self.style().standardIcon(icons[index % len(icons)]), self.tabs.tabText(index)))
        self.navigation.currentRowChanged.connect(self.tabs.setCurrentIndex)
        self.tabs.currentChanged.connect(self.navigation.setCurrentRow)
        self.navigation.setCurrentRow(0)
        foot = QLabel('●  Автоматические резервные копии   ·   Обновление цен каждый час, пока программа открыта')
        foot.setObjectName('Footer')
        foot.setWordWrap(True)
        layout.addWidget(foot)
        self.setCentralWidget(central)
        self.refresh()
        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(lambda: self.guard(self.auto_backup))
        self.backup_timer.start(3600000)
        self.price_timer = QTimer(self)
        self.price_timer.timeout.connect(self.update_prices)
        self.price_timer.start(3600000)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(lambda: self.guard(self.refresh))
        if getattr(self.store, 'remote', False):
            self.refresh_timer.start(30000)
            self.statusBar().showMessage('Сетевой режим: общая база на сервере · Обновление списков каждые 30 секунд')
        QTimer.singleShot(0, lambda: self.guard(self.auto_backup))
        QTimer.singleShot(1000, self.update_prices)

    def guard(self, action):
        try:
            action()
        except Exception as exc:
            QMessageBox.warning(self, 'Не удалось выполнить действие', str(exc))

    def page(self, title, key, headers, actions):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        heading = QLabel(title)
        heading.setStyleSheet('font-size:19px;font-weight:600;color:#25364b')
        layout.addWidget(heading)
        bar = QGridLayout()
        bar.setSpacing(8)
        for index, (label, action) in enumerate(actions):
            button = QPushButton(label)
            if index == 0:
                button.setProperty('primary', True)
            button.clicked.connect(lambda checked=False, action=action: self.guard(action))
            bar.addWidget(button, index // 4, index % 4)
        bar.setColumnStretch(4, 1)
        layout.addLayout(bar)
        search = QLineEdit()
        search.setPlaceholderText('Поиск по всем столбцам…')
        layout.addWidget(search)
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(43)
        table.setWordWrap(False)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        if key in ('products', 'stock', 'retail', 'parties', 'backups'):
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            flexible = {'products': 1, 'stock': 1, 'retail': 2, 'parties': 1, 'backups': 0}[key]
            table.horizontalHeader().setSectionResizeMode(flexible, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        search.textChanged.connect(lambda text: self.filter(table, text))
        self.tables[key] = table
        self.tabs.addTab(widget, title)

    def filter(self, table, text):
        for row in range(table.rowCount()):
            table.setRowHidden(row, text.casefold() not in ' '.join(table.item(row, column).text() for column in range(table.columnCount())).casefold())

    def fill(self, key, rows):
        table = self.tables[key]
        table.setRowCount(len(rows))
        for index, (identity, values) in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                item.setData(Qt.ItemDataRole.UserRole, identity)
                table.setItem(index, column, item)

    def selected(self, key):
        table = self.tables[key]
        if table.currentRow() < 0:
            raise ValueError('Выберите строку')
        return table.item(table.currentRow(), 0).data(Qt.ItemDataRole.UserRole)

    def configs(self):
        row = self.store.conn.execute("SELECT value FROM settings WHERE key='web_sources'").fetchone()
        return json.loads(row[0]) if row else []

    def save_configs(self, configs):
        self.store.set_settings({'web_sources': json.dumps(configs, ensure_ascii=False)})
        self.refresh()

    def refresh(self, stock_only=False):
        if self._closed:
            return
        products = self.store.catalog()
        counts = [len(products), sum(p['stock'] > 0 for p in products),
                  self.store.conn.execute('SELECT COUNT(*) FROM offers').fetchone()[0],
                  self.store.conn.execute('SELECT COUNT(*) FROM documents').fetchone()[0]]
        for label, count in zip(self.metric_values, counts):
            label.setText(str(count))
        self.fill('products', [(p['id'], (p['sku'], p['name'], p['unit'], p['category'], p['offer_count']))
                               for p in products if not stock_only or p['stock'] > 0])
        self.fill('offers', [(r['id'], (r['name'], r['supplier'], documents.money(r['price']), r['currency'], r['source'], r['updated']))
                             for r in self.store.rows('SELECT o.*,p.name FROM offers o JOIN products p ON p.id=o.product_id ORDER BY p.name,o.supplier')])
        self.fill('parties', [(p['id'], ('Юрлицо' if p['kind'] == 'company' else 'Физлицо', p['name'], p['tax_id'], p['details']))
                             for p in self.store.rows('SELECT * FROM parties ORDER BY name')])
        self.fill('documents', [(d['id'], (d['number'], d['day'], KINDS[d['kind']], d['party_name'], d['currency'], STATUSES[d['status']]))
                                for d in self.store.rows("SELECT * FROM documents WHERE kind<>'invoice' ORDER BY id DESC")])
        self.fill('sources', [(index, (c['supplier'], c['url'], c['categories'], c['max_pages'])) for index, c in enumerate(self.configs())])
        files = sorted((self.store.root / 'backups').glob('*.zip'), reverse=True)
        self.fill('backups', [(str(p), (p.name, p.stat().st_size // 1024)) for p in files])
        self.summary.setText('Склад и прайсы учитываются отдельно. Остатки меняются после проведения накладных.')
        stocked_ids = {r['product_id'] for r in self.store.rows('SELECT DISTINCT product_id FROM movements')}
        self.fill('stock', [(p['id'], (p['sku'], p['name'], p['unit'], Decimal(p['stock'])/1000, Decimal(p['reserved'])/1000, Decimal(p['available'])/1000))
            for p in products if p['id'] in stocked_ids])
        self.fill('retail', [(r['product_id'], (r['day'], r['sku'], r['name'], documents.money(r['price']), Decimal(r['tax_bp'])/100, r['currency']))
            for r in self.store.rows('SELECT r.*,p.sku,p.name FROM retail_prices r JOIN products p ON p.id=r.product_id ORDER BY r.day DESC,r.id DESC')])
        invoices = self.store.invoices()
        self.fill('invoices', [(d['id'], (d['number'], d['day'], d['party_name'], documents.money(d['total']), documents.money(d['paid']), documents.money(d['debt']), d['currency'],
            STATUSES[d['status']] + ' · ' + d['payment_status'] + (' · Передан' if d['shipped'] else ' · Не передан'))) for d in invoices])
        self.fill('payments', [(r['id'], (r['day'], r['number'], r['party_name'], documents.money(r['amount']), r['currency'], r['method'], r['reference'], 'Отменена' if r['cancelled'] else 'Учтена'))
            for r in self.store.rows('SELECT p.*,d.number,d.party_name,d.currency FROM payments p JOIN documents d ON d.id=p.invoice_id ORDER BY p.day DESC,p.id DESC')])
        self.fill('debts', [(d['id'], (d['number'], d['party_name'], d['due_day'], documents.money(d['total']), documents.money(d['paid']), documents.money(d['debt']), d['currency'], 'Да' if d['shipped'] else 'Нет')) for d in self.store.debts()])
        report = self.store.statistics(self.month)
        self.fill('statistics', [(r['document_id'], (r['day'], r['name'], r['party_name'], Decimal(r['quantity'])/1000, r['unit'], documents.money(r['gross']),
            documents.money(r['cost']) if r['cost'] is not None else 'Неизвестна', documents.money(r['margin']) if r['margin'] is not None else 'Неизвестна', r['currency'])) for r in report['sales']])
        summaries = [f"{currency}: выручка {documents.money(g['revenue'])}; маржа без НДС {documents.money(g['margin'])}" + (' · Есть продажи без известной себестоимости' if g['unknown_cost'] else '') for currency, g in report['totals'].items()]
        quantities = ', '.join(f'{Decimal(q)/1000} {unit}' for unit, q in report['quantities'].items())
        self.stats_summary.setText(f'{self.month} · Продано: {quantities or "0"}\n' + '\n'.join(summaries) + '\nМаржа = продажи без НДС − закупочная себестоимость FIFO. Расходы магазина не учтены.')
        self.refresh_calendar(self.calendar_day)

    def add_product(self):
        dialog = Form('Новый товар', [('sku', 'Артикул', ''), ('name', 'Название', ''), ('unit', 'Единица', 'шт'), ('category', 'Категория', '')], self)
        if dialog.exec():
            self.store.product(**dialog.values())
            self.refresh()

    def add_party(self):
        dialog = Form('Контрагент', [('kind', 'Тип', [('Юрлицо', 'company'), ('Физлицо', 'person')]),
                      ('name', 'Название / ФИО', ''), ('tax_id', 'УНП (9 цифр для юрлица)', ''),
                      ('address', 'Юридический / почтовый адрес', ''), ('bank', 'Наименование банка', ''),
                      ('bic', 'БИК', ''), ('iban', 'IBAN BY…', ''), ('details', 'Контакты, руководитель, примечание', '')], self)
        if dialog.exec():
            values = dialog.values()
            if values['kind'] == 'company' and (not values['tax_id'].isdigit() or len(values['tax_id']) != 9):
                raise ValueError('Для юрлица укажите УНП из 9 цифр')
            details = '\n'.join(filter(None, [values.pop('address'), values.pop('bank'), values.pop('bic'), values.pop('iban'), values['details']]))
            values['details'] = details
            self.store.party(**values)
            self.refresh()

    def seller(self):
        values = {r['key']: r['value'] for r in self.store.rows('SELECT * FROM settings')}
        dialog = Form('Реквизиты вашей организации', [('seller', 'Наименование', values.get('seller', '')),
                      ('seller_unp', 'УНП (9 цифр)', values.get('seller_unp', '')),
                      ('seller_address', 'Юридический / почтовый адрес', values.get('seller_address', '')),
                      ('seller_bank', 'Наименование банка', values.get('seller_bank', '')),
                      ('seller_bic', 'БИК банка', values.get('seller_bic', '')),
                      ('seller_iban', 'IBAN (BY, 28 символов)', values.get('seller_iban', '')),
                      ('seller_director', 'Руководитель / основание полномочий', values.get('seller_director', '')),
                      ('seller_phone', 'Телефон', values.get('seller_phone', '')),
                      ('seller_email', 'Email', values.get('seller_email', ''))], self)
        if dialog.exec():
            self.store.save_organization(dialog.values())

    def add_offer(self):
        dialog = Form('Цена поставщика', [('product_id', 'Товар', [(p['name'], p['id']) for p in self.store.catalog()]),
                      ('supplier', 'Поставщик', ''), ('price', 'Цена', ''), ('currency', 'Валюта', 'BYN'), ('source', 'Источник / прайс', 'Ручной прайс')], self)
        if dialog.exec():
            self.store.offer(**dialog.values())
            self.refresh()

    def import_prices(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Прайс', '', 'Прайсы (*.xlsx *.csv)')
        if not path:
            return
        headers, rows = sources.read_price(path)
        choices = [(header or f'Столбец {i+1}', i) for i, header in enumerate(headers)]
        dialog = Form('Сопоставление столбцов прайса', [('supplier', 'Поставщик', ''), ('currency', 'Валюта', 'BYN'),
                      ('sku', 'Артикул', choices), ('name', 'Название', choices), ('price', 'Цена', choices),
                      ('unit', 'Единица', [('шт (по умолчанию)', None)] + choices)], self)
        aliases = {'sku': ('артикул', 'код', 'sku'), 'name': ('название', 'наименование', 'товар', 'name'),
                   'price': ('цена', 'стоимость', 'price'), 'unit': ('ед', 'unit')}
        for key, names in aliases.items():
            for index, header in enumerate(headers):
                if any(name in header.casefold() for name in names):
                    combo = dialog.fields[key]
                    combo.setCurrentIndex(combo.findData(index))
                    break
        if dialog.exec():
            values = dialog.values()
            count = sources.import_price(self.store, path, {k: values[k] for k in ('sku', 'name', 'price', 'unit')}, values['supplier'], values['currency'])
            self.refresh()
            QMessageBox.information(self, 'Прайс импортирован', f'Обработано строк: {count}. Остатки не изменены.')

    def add_document(self, kind=None):
        if not self.store.catalog() or not self.store.rows('SELECT id FROM parties LIMIT 1'):
            raise ValueError('Сначала добавьте товары и контрагента')
        if DocumentDialog(self.store, self, kind).exec():
            self.refresh()

    def active_document(self):
        title = self.tabs.tabText(self.tabs.currentIndex())
        return self.selected('invoices' if title == 'Счета' else 'debts' if title == 'Неоплаты' else 'documents')

    def show_lines(self):
        _, values, items = self.document_preview(self.active_document())
        text = '\n'.join(f"{r['name']} — {r['quantity']} {r['unit']} × {r['price']} · НДС {r['tax_rate']}%" for r in items)
        QMessageBox.information(self, values['number'], text + f"\nИтого: {values['total']} {values['currency']}")

    def document_preview(self, doc_id):
        return documents.context(self.store, doc_id, require_posted=False)

    def post(self):
        self.store.post(self.active_document())
        self.refresh()

    def shipment(self):
        self.store.shipment_from_invoice(self.active_document())
        self.refresh()

    def cancel(self):
        doc_id = self.active_document()
        if QMessageBox.question(self, 'Отмена документа', 'Отменить документ и его складские движения?') == QMessageBox.StandardButton.Yes:
            backup.create(self.store)
            self.store.cancel(doc_id)
            self.refresh()

    def export(self):
        doc_id = self.active_document()
        doc, _, _ = documents.context(self.store, doc_id)
        template, _ = QFileDialog.getOpenFileName(self, 'Выберите шаблон', str(self.store.root / 'templates'), 'Шаблоны (*.html *.docx *.xlsx)')
        if not template:
            return
        output, _ = QFileDialog.getSaveFileName(self, 'Готовый документ', str(self.store.root / 'documents' / (doc['number'] + Path(template).suffix)), 'Документы (*' + Path(template).suffix + ')')
        if output:
            documents.export(self.store, doc_id, template, output)
            # Preserve custom templates and issued files even when users export elsewhere.
            template_path = Path(template).resolve()
            saved_template = self.store.root / 'templates' / (hashlib.sha256(template_path.read_bytes()).hexdigest()[:16] + template_path.suffix)
            if template_path != saved_template:
                shutil.copy2(template_path, saved_template)
            archive_path = self.store.root / 'documents' / (doc['number'] + Path(output).suffix)
            if Path(output).resolve() != archive_path:
                shutil.copy2(output, archive_path)
            self.sync_file(saved_template)
            self.sync_file(archive_path)
            QMessageBox.information(self, 'Документ сформирован', output)

    def attach_source(self):
        doc_id = self.selected('documents')
        path, _ = QFileDialog.getOpenFileName(self, 'Исходная накладная или другой файл')
        if path:
            source = Path(path)
            folder = self.store.root / 'sources' / f'document-{doc_id}'
            folder.mkdir(exist_ok=True)
            destination = folder / (hashlib.sha256(source.read_bytes()).hexdigest()[:12] + '-' + source.name)
            if source.resolve() != destination:
                shutil.copy2(source, destination)
            self.sync_file(destination)
            self.statusBar().showMessage('Исходный файл сохранён и включён в резервные копии: ' + str(destination))

    def source_form(self, config=None):
        config = config or {}
        fields = [('supplier', 'Поставщик', ''), ('url', 'Адрес сайта', ''), ('categories', 'URL нужных категорий (по одному в строке)', ''),
                  ('category_name', 'Категория в справочнике', 'Из интернета'), ('currency', 'Валюта', 'BYN'),
                  ('max_pages', 'Лимит страниц разделов (1–10000)', '300'),
                  ('link_selector', 'Ссылки товаров / страниц (CSS, необязательно)', ''),
                  ('card_selector', 'Карточка в каталоге (CSS, необязательно)', ''),
                  ('name_selector', 'Название (CSS, необязательно)', ''), ('price_selector', 'Цена (CSS, необязательно)', ''),
                  ('sku_selector', 'Артикул (CSS, необязательно)', '')]
        dialog = Form('Источник цен · JSON-LD распознаётся автоматически', [(k, label, config.get(k, default)) for k, label, default in fields], self)
        if dialog.exec():
            values = dialog.values()
            limit = int(values['max_pages'])
            if not values['supplier'] or not values['url'] or not values['categories'] or not 1 <= limit <= 10000:
                raise ValueError('Заполните поставщика, сайт, категории и лимит 1–10000')
            values['max_pages'] = limit
            return values

    def add_source(self):
        value = self.source_form()
        if value:
            self.save_configs(self.configs() + [value])

    def edit_source(self):
        configs = self.configs()
        index = self.selected('sources')
        value = self.source_form(configs[index])
        if value:
            configs[index] = value
            self.save_configs(configs)

    def remove_source(self):
        configs = self.configs()
        index = self.selected('sources')
        if QMessageBox.question(self, 'Удалить источник', 'Удалить настройки сайта? Сохранённые предложения останутся.') == QMessageBox.StandardButton.Yes:
            configs.pop(index)
            self.save_configs(configs)

    def update_prices(self):
        if self.worker is not None and self.worker.isRunning() or not self.configs():
            return
        self.worker = CrawlWorker(self.configs())
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.result.connect(self.web_result)
        self.worker.start()

    def show_update_log(self):
        path = self.store.root / 'sources' / 'last-update.json'
        if not path.exists():
            raise ValueError('Обход сайтов ещё не выполнялся на этом компьютере')
        log = json.loads(path.read_text(encoding='utf-8'))
        errors = '\n'.join(log.get('errors', [])) or 'Ошибок нет'
        QMessageBox.information(self, 'Последнее обновление сайтов', f'Обновлено предложений: {log["updated"]}\n{errors}')

    def web_result(self, results):
        errors = []
        count = 0
        try:
            for config, products, problems, limited in results:
                count += sources.apply_web_prices(self.store, config, products)
                errors.extend(problems)
                if limited:
                    errors.append(config['supplier'] + ': достигнут лимит страниц; обработана часть каталога')
            self.refresh()
            text = f'Обновлено предложений: {count}'
            if errors:
                text += '\n' + '\n'.join(errors[:10])
            self.statusBar().showMessage(text.replace('\n', ' · '))
            log = self.store.root / 'sources' / 'last-update.json'
            log.write_text(json.dumps({'updated': count, 'errors': errors}, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            self.statusBar().showMessage('Обновление цен не выполнено: ' + str(exc))

    def auto_backup(self):
        if self._closed:
            return
        backup.create(self.store)
        self.refresh()

    def sync_file(self, path):
        if getattr(self.store, 'remote', False):
            self.store.upload_file(path)

    def make_backup(self):
        path = backup.create(self.store)
        self.refresh()
        QMessageBox.information(self, 'Резервная копия создана', str(path))

    def restore_backup(self):
        archive, _ = QFileDialog.getOpenFileName(self, 'Архив резервной копии', str(self.store.root / 'backups'), 'ZIP (*.zip)')
        if not archive:
            return
        dialog = Form('Восстановление', [('destination', 'Новая папка данных (не должна существовать)', str(self.store.root.parent / 'magazin-restored'))], self)
        if dialog.exec():
            path = backup.restore(archive, dialog.values()['destination'])
            QMessageBox.information(self, 'Копия проверена и восстановлена', f'Рабочая база не заменена. Запустите программу с --data-dir "{path}"')

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, 'Обновляются цены', 'Дождитесь завершения текущего обновления цен.')
            event.ignore()
            return
        try:
            backup.create(self.store)
        except Exception as exc:
            QMessageBox.warning(self, 'Резервная копия не создана', str(exc))
            event.ignore()
            return
        self.backup_timer.stop()
        self.price_timer.stop()
        self.refresh_timer.stop()
        self._closed = True
        self.store.close()
        event.accept()

    def set_retail(self):
        title = self.tabs.tabText(self.tabs.currentIndex())
        key = {'Товары': 'products', 'Склад': 'stock', 'Розничные цены': 'retail'}.get(title)
        selected = self.selected(key) if key and self.tables[key].currentRow() >= 0 else None
        products = [(p['name'] + ' · ' + p['sku'], p['id']) for p in self.store.catalog()]
        dialog = Form('Реестр розничных цен', [('product_id', 'Товар', products), ('price', 'Цена продажи без НДС', ''),
            ('tax', 'НДС, %', '0'), ('day', 'Действует с (ГГГГ-ММ-ДД)', date.today().isoformat()), ('currency', 'Валюта', 'BYN'), ('note', 'Основание цены', '')], self)
        if selected:
            combo = dialog.fields['product_id']
            combo.setCurrentIndex(combo.findData(selected))
        if dialog.exec():
            self.store.set_retail(**dialog.values())
            self.refresh()

    def add_payment(self):
        choices = [(f"{d['number']} · {d['party_name']} · долг {documents.money(d['debt'])} {d['currency']}", d['id'])
            for d in self.store.invoices() if d['status'] == 'posted']
        if not choices:
            raise ValueError('Сначала выставите счёт')
        dialog = Form('Оплата по счёту', [('invoice_id', 'Счёт', choices), ('amount', 'Сумма в валюте счёта', ''),
            ('day', 'Дата оплаты', date.today().isoformat()), ('method', 'Способ', [('Банк', 'Банк'), ('Наличные', 'Наличные'), ('Карта', 'Карта')]), ('reference', 'Платёжное поручение / основание', '')], self)
        if self.tabs.tabText(self.tabs.currentIndex()) in ('Счета', 'Неоплаты'):
            try:
                doc_id = self.active_document()
                combo = dialog.fields['invoice_id']
                combo.setCurrentIndex(combo.findData(doc_id))
            except ValueError:
                pass
        if dialog.exec():
            self.store.payment(**dialog.values())
            self.refresh()

    def cancel_payment(self):
        pid = self.selected('payments')
        if QMessageBox.question(self, 'Отмена оплаты', 'Отменить эту запись оплаты? Задолженность будет пересчитана.') == QMessageBox.StandardButton.Yes:
            backup.create(self.store)
            self.store.cancel_payment(pid)
            self.refresh()

    def deliver(self):
        invoice_id = self.active_document()
        dialog = Form('Передача товара клиенту', [('day', 'Фактическая дата передачи', date.today().isoformat())], self)
        if dialog.exec():
            existing = self.store.rows('SELECT * FROM documents WHERE invoice_id=?', (invoice_id,))
            if existing and existing[0]['status'] == 'draft':
                shipment_id = existing[0]['id']
                self.store.reschedule_shipment(shipment_id, dialog.values()['day'])
            else:
                shipment_id = self.store.shipment_from_invoice(invoice_id, dialog.values()['day'])
            self.store.post(shipment_id)
            self.refresh()
            self.statusBar().showMessage('Товар передан: остатки списаны, накладная доступна в модуле «Накладные»')

    def stock_history(self):
        pid = self.selected('stock')
        rows = self.store.rows('''SELECT m.quantity,d.day,d.number,d.party_name,d.kind FROM movements m
            JOIN documents d ON d.id=m.document_id WHERE m.product_id=? ORDER BY d.day,d.id''', (pid,))
        dialog = QDialog(self)
        dialog.setWindowTitle('Движения товара: поступления и покупатели')
        dialog.resize(900, 550)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(rows), 5)
        table.setHorizontalHeaderLabels(['Дата', 'Документ', 'Операция', 'Контрагент', 'Количество'])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for index, row in enumerate(rows):
            for column, value in enumerate((row['day'], row['number'], KINDS[row['kind']], row['party_name'], Decimal(row['quantity'])/1000)):
                table.setItem(index, column, QTableWidgetItem(str(value)))
        layout.addWidget(table)
        dialog.exec()

    def choose_month(self):
        dialog = Form('Статистика продаж', [('month', 'Месяц (ГГГГ-ММ)', self.month)], self)
        if dialog.exec():
            month = dialog.values()['month']
            date.fromisoformat(month + '-01')
            self.month = month
            self.refresh()

    def refresh_calendar(self, day):
        self.calendar_day = day
        self.fill('calendar', [(e['document_id'], (e['day'], EVENTS.get(e['kind'], e['kind']), e['number'] or '',
            e['party_name'] or e['product_name'] or '', e['details'])) for e in self.store.calendar(day)])
        from PyQt6.QtGui import QTextCharFormat
        self.calendar_widget.setDateTextFormat(QDate(), QTextCharFormat())
        for event in self.store.calendar():
            fmt = QTextCharFormat()
            fmt.setFontWeight(700)
            fmt.setFontUnderline(True)
            self.calendar_widget.setDateTextFormat(QDate.fromString(event['day'], 'yyyy-MM-dd'), fmt)

    def export_report(self, key):
        table = self.tables[key]
        template, _ = QFileDialog.getOpenFileName(self, 'Шаблон отчёта HTML', str(self.store.root / 'templates'), 'HTML (*.html)')
        if not template:
            return
        output, _ = QFileDialog.getSaveFileName(self, 'Сохранить отчёт', str(self.store.root / 'documents' / (key + '.html')), 'HTML (*.html)')
        if output:
            headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
            rows = [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount()) if not table.isRowHidden(r)]
            summary = self.stats_summary.text() if key == 'statistics' else ''
            documents.export_report(template, output, self.tabs.tabText(self.tabs.currentIndex()), headers, rows, summary)
            if Path(output).resolve().parent != self.store.root / 'documents':
                shutil.copy2(output, self.store.root / 'documents' / Path(output).name)
            self.sync_file(self.store.root / 'documents' / Path(output).name)
            QMessageBox.information(self, 'Отчёт сформирован', output)
