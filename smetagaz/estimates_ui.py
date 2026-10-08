"""Раздел «Сметы»: выбор договора, создание сметы (клиент или клиент из договора), вкладка «Шаблоны и теги»."""
import os
from pathlib import Path

from PyQt6.QtWidgets import (QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox, QPushButton, QRadioButton, QCheckBox, QTableWidget,
                              QTableWidgetItem, QAbstractItemView, QTabWidget, QMessageBox, QFileDialog, QHeaderView, QApplication, QButtonGroup)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from .database import db
from . import estimates_domain as ed
from . import report_templates as reports
from .gsvm_docs import FORMATS


def pick_contract(parent, with_estimate, title):
    """Выбор договора из разделов (ГСВ, монтаж, ГСН, СМР; with_estimate=True — ещё и «Юрлица»). Возвращает (таблица, id) или None."""
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.resize(760, 480)
    lay = QVBoxLayout(d)
    search = QLineEdit()
    search.setPlaceholderText("Номер, клиент, объект…")
    lay.addWidget(search)
    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(["Раздел", "Договор"])
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(True)
    table.setColumnWidth(0, 140)
    lay.addWidget(table, 1)
    chosen = []

    def load():
        rows = ed.contract_candidates(db, search.text(), with_estimate)
        table.setRowCount(len(rows))
        for r, (t, rid, label) in enumerate(rows):
            sect, _, rest = label.partition(" · ")
            for c, v in enumerate((sect, rest)):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, (t, rid))
                table.setItem(r, c, it)
    search.textChanged.connect(load)
    load()
    ok = QPushButton("Выбрать")
    ok.setProperty("type", "primary")
    lay.addWidget(ok)

    def accept():
        r = table.currentRow()
        if r >= 0:
            chosen.append(table.item(r, 0).data(Qt.ItemDataRole.UserRole))
            d.accept()
    ok.clicked.connect(accept)
    table.cellDoubleClicked.connect(lambda *_: accept())
    return chosen[0] if d.exec() and chosen else None


class NewEstimateDialog(QDialog):
    """Новая смета: под клиента из базы, под юрлицо или под клиента из карточки договора. По умолчанию смета создаётся без договора."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новая смета")
        self.resize(560, 420)
        self.contract = None
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit()
        self.title.setPlaceholderText("Шифр или наименование объекта (можно оставить пустым)")
        form.addRow("Объект:", self.title)
        lay.addLayout(form)
        lay.addWidget(QLabel("<b>Для кого смета</b>"))
        self.group = QButtonGroup(self)
        self.rb_person = QRadioButton("Клиент из базы «Клиенты»")
        self.rb_legal = QRadioButton("Юрлицо из справочника")
        self.rb_contract = QRadioButton("Клиент из карточки договора")
        self.rb_none = QRadioButton("Пока без клиента")
        for rb in (self.rb_person, self.rb_legal, self.rb_contract, self.rb_none):
            self.group.addButton(rb)
        self.rb_person.setChecked(True)
        self.cmb_person, self.cmb_legal = QComboBox(), QComboBox()
        self.cmb_person.addItem("— выберите клиента —", None)
        for cid, name in db.fetchall("SELECT id,name FROM crm.clients ORDER BY name"):
            self.cmb_person.addItem(name, cid)
        self.cmb_legal.addItem("— выберите юрлицо —", None)
        for lid, name in db.fetchall("SELECT id,name FROM le_clients ORDER BY name"):
            self.cmb_legal.addItem(name, lid)
        self.lbl_contract = QLabel("Договор не выбран")
        self.lbl_contract.setStyleSheet("color:#65758b;")
        pick = QPushButton("Выбрать договор…")
        pick.clicked.connect(self.choose_contract)
        self.chk_link = QCheckBox("Сразу привязать смету к этому договору (по умолчанию смета создаётся без договора)")
        row = QHBoxLayout()
        row.addWidget(self.lbl_contract, 1)
        row.addWidget(pick)
        lay.addWidget(self.rb_person)
        lay.addWidget(self.cmb_person)
        lay.addWidget(self.rb_legal)
        lay.addWidget(self.cmb_legal)
        lay.addWidget(self.rb_contract)
        lay.addLayout(row)
        lay.addWidget(self.chk_link)
        lay.addWidget(self.rb_none)
        lay.addStretch()
        ok = QPushButton("Создать смету")
        ok.setProperty("type", "primary")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok)
        self.group.buttonToggled.connect(self.refresh)
        self.cmb_person.currentIndexChanged.connect(lambda *_: self.rb_person.setChecked(True))
        self.cmb_legal.currentIndexChanged.connect(lambda *_: self.rb_legal.setChecked(True))
        self.refresh()

    def refresh(self, *_):
        self.cmb_person.setEnabled(self.rb_person.isChecked())
        self.cmb_legal.setEnabled(self.rb_legal.isChecked())
        self.chk_link.setEnabled(self.rb_contract.isChecked() and bool(self.contract) and self.contract[0] in ed.CONTRACT_TABLES)

    def choose_contract(self):
        pick = pick_contract(self, True, "Договор, из которого взять клиента")
        if pick:
            from . import board_domain as board
            self.contract = pick
            self.lbl_contract.setText(board.link_label(db, *pick) or "")
            self.rb_contract.setChecked(True)
            self.refresh()

    def values(self):
        """(название, клиент, договор, привязать) для estimates_domain.create_estimate."""
        client = contract = None
        link = False
        if self.rb_person.isChecked() and self.cmb_person.currentData():
            client = ("person", self.cmb_person.currentData())
        elif self.rb_legal.isChecked() and self.cmb_legal.currentData():
            client = ("legal", self.cmb_legal.currentData())
        elif self.rb_contract.isChecked() and self.contract:
            contract = self.contract
            link = self.chk_link.isChecked() and contract[0] in ed.CONTRACT_TABLES
        return self.title.text().strip(), client, contract, link


# --- Шаблоны и теги -----------------------------------------------------------------------------

DOC_KINDS = {
    'estimates': ('Смета', 'Смета по объекту: позиции, итоги, оплаты, клиент и договор.'),
    'estimate_breakdown': ('Расшифровка работ и маржа материалов', 'Работы по статьям, материалы с маржой, итоги и маржа — один документ из окна «Расшифровка и маржа».'),
}


class EstimateTemplatesTab(QWidget):
    """Шаблоны Word/Excel для сметы и расшифровки, список тегов с примерами и редактор своих (русских) тегов."""
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Шаблон — обычный файл Word или Excel. Теги пишутся в двойных фигурных скобках: {{клиент}}, {{итого}}; повторяющиеся строки — {{items.name}}, {{works.margin_sum}}. "
                                "Начислений на работы в смете нет — они уже внутри цены каждой работы справочника."))
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        self.tabs = tabs
        # 1. шаблоны
        page = QWidget()
        pl = QVBoxLayout(page)
        top = QHBoxLayout()
        top.addWidget(QLabel("Документ:"))
        self.kind = QComboBox()
        for key, (name, _hint) in DOC_KINDS.items():
            self.kind.addItem(name, key)
        self.kind.currentIndexChanged.connect(self.load_templates)
        top.addWidget(self.kind, 1)
        pl.addLayout(top)
        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#65758b;")
        pl.addWidget(self.hint)
        self.templates = QTableWidget(0, 2)
        self.templates.setHorizontalHeaderLabels(["Шаблон", "Файл"])
        self.templates.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.templates.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.templates.horizontalHeader().setStretchLastSection(True)
        self.templates.setColumnWidth(0, 280)
        pl.addWidget(self.templates, 1)
        bar = QHBoxLayout()
        for text, fn in (("Подключить шаблон…", self.add_template), ("Заменить файл…", self.replace_template), ("Переименовать", self.rename_template),
                         ("Открыть файл", self.open_template), ("Проверить", self.check_template), ("Убрать из списка", self.remove_template)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        pl.addLayout(bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        pl.addWidget(self.status)
        tabs.addTab(page, "Шаблоны")
        # 2. теги
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel("Теги: имя в шаблоне, источник данных, формат и текст «если данных нет». Стандартные теги можно переименовать или отключить, свои — добавить."))
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск тега…")
        self.search.textChanged.connect(self.filter_rows)
        top.addWidget(self.search, 1)
        pl.addLayout(top)
        self.tags = QTableWidget(0, 6)
        self.tags.setHorizontalHeaderLabels(["Тег", "Источник данных", "Формат", "Если данных нет", "Вкл.", "Пример"])
        self.tags.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tags.horizontalHeader().setStretchLastSection(True)
        for i, w in enumerate((200, 360, 230, 170, 50)):
            self.tags.setColumnWidth(i, w)
        pl.addWidget(self.tags, 1)
        bar = QHBoxLayout()
        for text, fn in (("＋ Новый тег", self.new_tag), ("Удалить / отключить", self.delete_tag), ("Копировать тег", self.copy_tag), ("Сохранить теги", self.save_tags)):
            b = QPushButton(text)
            if text == "Сохранить теги":
                b.setProperty("type", "primary")
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.tag_status = QLabel("")
        bar.addWidget(self.tag_status, 1)
        pl.addLayout(bar)
        tabs.addTab(page, "Теги")
        # 3. таблицы
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel("Повторяющиеся строки: строка таблицы с тегом вида {{таблица.колонка}} размножается по числу записей. В одной строке — только одна таблица."))
        self.table_tags = QTableWidget(0, 3)
        self.table_tags.setHorizontalHeaderLabels(["Таблица", "Колонка (тег)", "Что это"])
        self.table_tags.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_tags.horizontalHeader().setStretchLastSection(True)
        self.table_tags.setColumnWidth(0, 230)
        self.table_tags.setColumnWidth(1, 330)
        self.table_tags.cellDoubleClicked.connect(lambda r, c: self.copy_text(self.table_tags.item(r, 1).text()))
        pl.addWidget(self.table_tags, 1)
        tabs.addTab(page, "Таблицы")
        self.sample = None
        self.load_templates()
        self.load_tags()
        self.load_table_tags()

    # --- шаблоны
    def key(self):
        return self.kind.currentData()

    def load_templates(self, *_):
        self.hint.setText(DOC_KINDS[self.key()][1])
        rows = db.fetchall("SELECT id,name,file_path FROM report_templates WHERE kind=? ORDER BY name,id", (self.key(),))
        self.templates.setRowCount(len(rows))
        for r, (tid, name, path) in enumerate(rows):
            for c, v in enumerate((name, path)):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, tid)
                if c == 1 and not os.path.isfile(path):
                    it.setForeground(QColor("#DC2626"))
                    it.setToolTip("Файл не найден")
                self.templates.setItem(r, c, it)

    def current_template(self):
        r = self.templates.currentRow()
        return self.templates.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def add_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "Подключить шаблон", "", "Word / Excel (*.docx *.xlsx)")
        if path:
            from PyQt6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "Название шаблона", "Название", text=Path(path).stem)
            if ok and name.strip():
                db.execute("INSERT INTO report_templates(kind,name,file_path) VALUES(?,?,?)", (self.key(), name.strip(), path))
                self.load_templates()

    def replace_template(self):
        tid = self.current_template()
        if tid:
            path, _ = QFileDialog.getOpenFileName(self, "Заменить файл шаблона", "", "Word / Excel (*.docx *.xlsx)")
            if path:
                db.execute("UPDATE report_templates SET file_path=? WHERE id=?", (path, tid))
                self.load_templates()

    def rename_template(self):
        tid = self.current_template()
        if tid:
            from PyQt6.QtWidgets import QInputDialog
            old = db.fetchone("SELECT name FROM report_templates WHERE id=?", (tid,))[0]
            name, ok = QInputDialog.getText(self, "Переименовать", "Название", text=old)
            if ok and name.strip():
                db.execute("UPDATE report_templates SET name=? WHERE id=?", (name.strip(), tid))
                self.load_templates()

    def open_template(self):
        tid = self.current_template()
        row = db.fetchone("SELECT file_path FROM report_templates WHERE id=?", (tid,)) if tid else None
        if row and os.path.isfile(row[0]):
            from .platform_utils import open_local
            open_local(row[0])
        elif tid:
            self.status.setText("Файл шаблона не найден на диске.")

    def remove_template(self):
        tid = self.current_template()
        if tid and QMessageBox.question(self, "Шаблон", "Убрать шаблон из списка? Сам файл останется на диске.") == QMessageBox.StandardButton.Yes:
            db.execute("DELETE FROM report_templates WHERE id=?", (tid,))
            self.load_templates()

    def sample_estimate(self):
        row = db.fetchone("SELECT id FROM estimates ORDER BY id DESC LIMIT 1")
        return row[0] if row else None

    def check_template(self):
        tid = self.current_template()
        eid = self.sample_estimate()
        if not tid:
            return
        if not eid:
            self.status.setText("Для проверки нужна хотя бы одна смета.")
            return
        try:
            import tempfile
            src = db.fetchone("SELECT file_path FROM report_templates WHERE id=?", (tid,))[0]
            with tempfile.TemporaryDirectory() as tmp:
                reports.export(db, self.key(), eid, tid, Path(tmp) / ("check" + Path(src).suffix))
            self.status.setText(f"Проверка пройдена на последней смете (№{eid}): все теги шаблона распознаны.")
        except Exception as e:
            self.status.setText("Ошибка: " + str(e))

    # --- теги
    def sample_context(self):
        if self.sample is None:
            eid = self.sample_estimate()
            try:
                self.sample = reports.context(db, "estimates", eid)[0] if eid else {}
            except Exception:
                self.sample = {}
        return self.sample

    def load_tags(self):
        self.sample = None
        ctx = self.sample_context()
        self.sources = ed.source_choices(ctx.keys())
        self.tags.setRowCount(0)
        for row in ed.list_tags(db):
            self.add_row(*row)
        self.filter_rows()

    def add_row(self, tag_id, name, source, fmt, empty_text, auto_key="", enabled=1, note=""):
        r = self.tags.rowCount()
        self.tags.insertRow(r)
        it = QTableWidgetItem(name)
        it.setData(Qt.ItemDataRole.UserRole, tag_id)
        if auto_key:
            it.setForeground(QColor("#2563EB"))
        self.tags.setItem(r, 0, it)
        src = QComboBox()
        for key, label in self.sources:
            src.addItem(label, key)
        if src.findData(source) < 0:
            src.addItem(source, source)
        src.setCurrentIndex(src.findData(source))
        self.tags.setCellWidget(r, 1, src)
        fm = QComboBox()
        for key, label in FORMATS.items():
            fm.addItem(label, key)
        fm.setCurrentIndex(max(0, fm.findData(fmt)))
        self.tags.setCellWidget(r, 2, fm)
        self.tags.setItem(r, 3, QTableWidgetItem(empty_text or ""))
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        chk.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
        self.tags.setItem(r, 4, chk)
        example = QTableWidgetItem(str(self.sample_context().get(name, ""))[:80])
        example.setFlags(example.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.tags.setItem(r, 5, example)

    def text(self, r, c):
        it = self.tags.item(r, c)
        return it.text() if it else ""

    def filter_rows(self, *_):
        q = self.search.text().casefold()
        for r in range(self.tags.rowCount()):
            self.tags.setRowHidden(r, bool(q) and q not in (self.text(r, 0) + self.tags.cellWidget(r, 1).currentText()).casefold())

    def new_tag(self):
        self.add_row(None, "новый_тег", self.sources[0][0], "text", "", "", 1, "")
        self.tags.setCurrentCell(self.tags.rowCount() - 1, 0)
        self.tags.editItem(self.tags.item(self.tags.rowCount() - 1, 0))

    def delete_tag(self):
        r = self.tags.currentRow()
        if r < 0:
            return
        tag_id = self.tags.item(r, 0).data(Qt.ItemDataRole.UserRole)
        if tag_id:
            result = ed.delete_tag(db, tag_id)
            self.tag_status.setText("Тег удалён." if result == "deleted" else "Стандартный тег отключён (включить можно галочкой).")
            self.load_tags()
        else:
            self.tags.removeRow(r)

    def copy_text(self, text):
        QApplication.clipboard().setText(text)
        self.tag_status.setText("Скопировано: " + text)

    def copy_tag(self):
        r = self.tags.currentRow()
        if r >= 0:
            self.copy_text("{{" + self.text(r, 0) + "}}")

    def save_tags(self):
        errors = []
        with db.transaction():
            for r in range(self.tags.rowCount()):
                tag_id = self.tags.item(r, 0).data(Qt.ItemDataRole.UserRole)
                try:
                    new_id = ed.save_tag(db, tag_id, self.text(r, 0), self.tags.cellWidget(r, 1).currentData(), self.tags.cellWidget(r, 2).currentData(), self.text(r, 3),
                                         self.tags.item(r, 4).checkState() == Qt.CheckState.Checked)
                    self.tags.item(r, 0).setData(Qt.ItemDataRole.UserRole, new_id)
                except ValueError as e:
                    errors.append(f"Строка {r + 1}: {e}")
        if errors:
            QMessageBox.warning(self, "Теги", "\n".join(errors))
        else:
            self.tag_status.setText("Теги сохранены.")
            self.load_tags()

    def load_table_tags(self):
        rows = [(f"{name} ({key})", f"{{{{{key}.{col}}}}}", "номер строки" if col == "index" else col) for key, (name, cols) in ed.TABLE_TAGS.items() for col in cols]
        self.table_tags.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table_tags.setItem(r, c, it)


class EstimatesModule(QWidget):
    """Раздел «Сметы»: реестр и «Шаблоны и теги»."""
    def __init__(self):
        super().__init__()
        from .estimates_registry import EstimatesView
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.registry = EstimatesView()
        self.templates = EstimateTemplatesTab()
        self.tabs.addTab(self.registry, "Реестр смет")
        self.tabs.addTab(self.templates, "Шаблоны и теги")
        self.tabs.currentChanged.connect(self.on_tab)
        layout.addWidget(self.tabs)

    def on_tab(self, index):
        if index == 0:
            self.registry.load_data()
        else:
            self.templates.load_templates()
            self.templates.load_tags()

    def load_data(self):
        self.registry.load_data()

    def refresh_ui(self):
        if hasattr(self.registry, 'refresh_ui'):
            self.registry.refresh_ui()
