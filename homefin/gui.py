"""Графический интерфейс (PyQt6). Вся логика — в homefin.core."""
from __future__ import annotations

import sys
import time
from datetime import date

from PyQt6.QtCore import QDate, QEvent, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QKeySequence
from PyQt6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
                             QFormLayout, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
                             QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QStackedWidget, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from . import __version__, exchange
from .core import Finance, add_months, month_bounds, parse_date
from .money import fmt
from .theme import C, app_icon, apply as apply_theme, logo_pixmap

RED, GREEN, AMBER = QColor(C["bad"]), QColor(C["good"]), QColor(C["warn"])


def qd(d: date | str) -> QDate:
    d = parse_date(d)
    return QDate(d.year, d.month, d.day)


def pd(w: QDateEdit) -> str:
    return w.date().toString("yyyy-MM-dd")


def make_date(d: date | str | None = None) -> QDateEdit:
    w = QDateEdit(qd(d or date.today()))
    w.setCalendarPopup(True)
    w.setDisplayFormat("dd.MM.yyyy")
    return w


def make_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.setAlternatingRowColors(True)
    return t


def fill(t: QTableWidget, rows: list[list], ids: list | None = None, right: tuple[int, ...] = (), colors=None):
    t.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem("" if v is None else str(v))
            if c in right:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if colors and colors.get((r, c)):
                it.setForeground(colors[(r, c)])
            if c == 0 and ids:
                it.setData(Qt.ItemDataRole.UserRole, ids[r])
            t.setItem(r, c, it)


def selected_id(t: QTableWidget):
    r = t.currentRow()
    return t.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 and t.item(r, 0) else None


def combo(items: list[tuple[str, object]], allow_none: str | None = None) -> QComboBox:
    c = QComboBox()
    if allow_none is not None:
        c.addItem(allow_none, None)
    for text, data in items:
        c.addItem(text, data)
    return c


def guard(parent, fn, *a, **kw):
    """Показывает ошибку ввода окном, а не падением."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001 — ошибки ввода и БД показываем пользователю
        QMessageBox.warning(parent, "Ошибка", str(e))
        return None


# ===================================================================== диалоги
class TxDialog(QDialog):
    def __init__(self, fin: Finance, parent=None, tx=None, day: str | None = None):
        super().__init__(parent)
        self.fin, self.tx = fin, tx
        self.setWindowTitle("Операция")
        self.kind = combo([("Расход", "expense"), ("Доход", "income"), ("Перевод", "transfer")])
        self.date = make_date(day)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("0,00")
        self.account = combo([(a["name"], a["id"]) for a in fin.accounts()])
        self.to_account = combo([(a["name"], a["id"]) for a in fin.accounts()])
        self.category = QComboBox()
        self.note = QLineEdit()
        form = QFormLayout(self)
        for label, w in (("Тип", self.kind), ("Дата", self.date), ("Сумма", self.amount), ("Счёт", self.account),
                         ("На счёт", self.to_account), ("Категория", self.category), ("Примечание", self.note)):
            form.addRow(label, w)
        self._rows = form
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        if tx:
            self.kind.setCurrentIndex(self.kind.findData(tx["kind"]))
            self.date.setDate(qd(tx["date"]))
            self.amount.setText(f"{tx['amount_cents'] / 100:.2f}")
            self.account.setCurrentIndex(self.account.findData(tx["account_id"]))
            if tx["to_account_id"]:
                self.to_account.setCurrentIndex(self.to_account.findData(tx["to_account_id"]))
            self.note.setText(tx["note"])
        self._kind_changed()
        if tx and tx["category_id"]:
            self.category.setCurrentIndex(self.category.findData(tx["category_id"]))

    def _kind_changed(self):
        k = self.kind.currentData()
        self._rows.setRowVisible(self.to_account, k == "transfer")
        self._rows.setRowVisible(self.category, k != "transfer")
        self.category.clear()
        self.category.addItem("— без категории —", None)
        if k != "transfer":
            for c in self.fin.categories(k):
                self.category.addItem(c["name"], c["id"])

    def save(self):
        args = (pd(self.date), self.kind.currentData(), self.amount.text(), self.account.currentData(),
                self.category.currentData(), self.note.text(), self.to_account.currentData())
        if self.tx:
            self.fin.update_transaction(self.tx["id"], *args)
        else:
            self.fin.add_transaction(*args)

    def accept(self):
        try:
            self.save()
        except Exception as e:  # noqa: BLE001 — ошибки ввода показываем пользователю
            QMessageBox.warning(self, "Ошибка", str(e))
            return
        super().accept()


def simple_form(parent, title, fields: list[tuple[str, QWidget]]) -> bool:
    d = QDialog(parent)
    d.setWindowTitle(title)
    f = QFormLayout(d)
    for label, w in fields:
        f.addRow(label, w)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    f.addRow(bb)
    return d.exec() == QDialog.DialogCode.Accepted


# ===================================================================== вкладки
class Page(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__()
        self.win, self.fin = win, win.fin

    def refresh(self):  # переопределяется
        pass

    def changed(self):
        self.win.refresh_all()


class OverviewPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.summary)
        box = QGroupBox("Напоминания по коммунальным платежам")
        bl = QVBoxLayout(box)
        self.rem = make_table(["Услуга", "Период", "Сумма", "Срок", "Статус"])
        bl.addWidget(self.rem)
        lay.addWidget(box)
        box2 = QGroupBox("Счета")
        b2 = QVBoxLayout(box2)
        self.acc = make_table(["Счёт", "Остаток"])
        b2.addWidget(self.acc)
        lay.addWidget(box2)
        try:
            import pyqtgraph as pg
            self.chart = pg.PlotWidget()
            self.chart.setMinimumHeight(200)
            self.chart.setBackground(C["panel"])
            lay.addWidget(self.chart)
        except ImportError:
            self.chart = None

    def refresh(self):
        cur = self.fin.currency
        today = date.today()
        a, b = month_bounds(today.strftime("%Y-%m"))
        inc, exp = self.fin.totals(a, b)
        self.summary.setText(
            f"<h2>Всего на счетах: {fmt(self.fin.total_balance(), cur)}</h2>"
            f"<p>За {today:%m.%Y}: доходы <b style='color:#15803D'>{fmt(inc, cur)}</b>, "
            f"расходы <b style='color:#B91C1C'>{fmt(exp, cur)}</b>, итог <b>{fmt(inc - exp, cur)}</b></p>")
        rows, colors = [], {}
        for i, (bl, left) in enumerate(self.fin.reminders(today)):
            status = f"просрочен на {-left} дн." if left < 0 else ("сегодня" if left == 0 else f"через {left} дн.")
            rows.append([bl["service"], bl["period"], fmt(bl["amount_cents"], cur), bl["due_date"], status])
            colors[(i, 4)] = RED if left < 0 else AMBER
        fill(self.rem, rows, right=(2,), colors=colors)
        fill(self.acc, [[x["name"], fmt(bal, cur)] for x, bal in self.fin.balances()], right=(1,))
        if self.chart is not None:
            import pyqtgraph as pg
            self.chart.clear()
            data = self.fin.monthly(6)
            xs = list(range(len(data)))
            self.chart.addItem(pg.BarGraphItem(x=[x - 0.2 for x in xs], height=[d[1] / 100 for d in data], width=0.35,
                                               brush="#15803D"))
            self.chart.addItem(pg.BarGraphItem(x=[x + 0.2 for x in xs], height=[d[2] / 100 for d in data], width=0.35,
                                               brush="#B91C1C"))
            self.chart.getAxis("bottom").setTicks([[(x, d[0]) for x, d in zip(xs, data)]])
            self.chart.setTitle("Доходы (зелёный) и расходы (красный) за 6 месяцев")


class TransactionsPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.f_from = make_date(date.today().replace(day=1))
        self.f_to = make_date(date.today())
        self.f_kind = combo([("Расходы", "expense"), ("Доходы", "income"), ("Переводы", "transfer")], "Все типы")
        self.f_acc = QComboBox()
        self.f_cat = QComboBox()
        self.f_text = QLineEdit()
        self.f_text.setPlaceholderText("Поиск по примечанию…")
        for w in (QLabel("с"), self.f_from, QLabel("по"), self.f_to, self.f_kind, self.f_acc, self.f_cat, self.f_text):
            bar.addWidget(w)
        lay.addLayout(bar)
        self.table = make_table(["Дата", "Тип", "Сумма", "Счёт", "Категория", "Примечание"])
        self.table.doubleClicked.connect(self.edit)
        lay.addWidget(self.table)
        self.total = QLabel()
        lay.addWidget(self.total)
        btns = QHBoxLayout()
        for text, fn in (("Добавить", self.add), ("Изменить", self.edit), ("Удалить", self.delete),
                         ("Экспорт CSV…", self.export_csv), ("Экспорт Excel…", self.export_xlsx),
                         ("Импорт CSV…", self.import_csv)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        lay.addLayout(btns)
        self._loading = True
        self._reload_filters()
        self._loading = False
        for w in (self.f_from, self.f_to):
            w.dateChanged.connect(self.refresh)
        for w in (self.f_kind, self.f_acc, self.f_cat):
            w.currentIndexChanged.connect(self.refresh)
        self.f_text.textChanged.connect(self.refresh)

    def _reload_filters(self):
        for cb, items, none in ((self.f_acc, [(a["name"], a["id"]) for a in self.fin.accounts()], "Все счета"),
                                (self.f_cat, [(c["name"], c["id"]) for c in self.fin.categories()], "Все категории")):
            cur = cb.currentData()
            cb.blockSignals(True)
            cb.clear()
            cb.addItem(none, None)
            for t, d in items:
                cb.addItem(t, d)
            cb.setCurrentIndex(max(0, cb.findData(cur)))
            cb.blockSignals(False)

    def filters(self):
        return dict(date_from=pd(self.f_from), date_to=pd(self.f_to), account_id=self.f_acc.currentData(),
                    category_id=self.f_cat.currentData(), kind=self.f_kind.currentData(), text=self.f_text.text().strip())

    def refresh(self, *_):
        if getattr(self, "_loading", False):
            return
        self._loading = True
        self._reload_filters()
        self._loading = False
        cur = self.fin.currency
        txs = self.fin.transactions(**self.filters())
        rows, colors, ids = [], {}, []
        inc = exp = 0
        for i, t in enumerate(txs):
            sign = {"income": "+", "expense": "−", "transfer": ""}[t["kind"]]
            acc = t["account"] + (f" → {t['to_account']}" if t["to_account"] else "")
            rows.append([parse_date(t["date"]).strftime("%d.%m.%Y"), exchange.KIND_RU[t["kind"]],
                         sign + fmt(t["amount_cents"]), acc, t["category"] or "", t["note"]])
            colors[(i, 2)] = GREEN if t["kind"] == "income" else (RED if t["kind"] == "expense" else None)
            ids.append(t["id"])
            inc += t["amount_cents"] if t["kind"] == "income" else 0
            exp += t["amount_cents"] if t["kind"] == "expense" else 0
        fill(self.table, rows, ids, right=(2,), colors=colors)
        self.total.setText(f"Записей: {len(txs)}   Доходы: {fmt(inc, cur)}   Расходы: {fmt(exp, cur)}   "
                           f"Разница: {fmt(inc - exp, cur)}")

    def add(self):
        if TxDialog(self.fin, self).exec():
            self.changed()

    def edit(self, *_):
        tid = selected_id(self.table)
        if tid is None:
            return
        row = self.fin.db.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
        if TxDialog(self.fin, self, row).exec():
            self.changed()

    def delete(self):
        tid = selected_id(self.table)
        if tid is not None and QMessageBox.question(self, "Удаление", "Удалить выбранную операцию?") == \
                QMessageBox.StandardButton.Yes:
            self.fin.delete_transaction(tid)
            self.changed()

    def _save_dialog(self, filt, default):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить", default, filt)
        return path

    def export_csv(self):
        if p := self._save_dialog("CSV (*.csv)", "operations.csv"):
            n = guard(self, exchange.export_csv, self.fin, p, **self.filters())
            if n is not None:
                QMessageBox.information(self, "Экспорт", f"Выгружено операций: {n}")

    def export_xlsx(self):
        if p := self._save_dialog("Excel (*.xlsx)", "operations.xlsx"):
            n = guard(self, exchange.export_xlsx, self.fin, p, **self.filters())
            if n is not None:
                QMessageBox.information(self, "Экспорт", f"Выгружено операций: {n}")

    def import_csv(self):
        p, _ = QFileDialog.getOpenFileName(self, "Импорт операций", "", "CSV (*.csv)")
        if p:
            res = guard(self, exchange.import_csv, self.fin, p)
            if res:
                ok, errs = res
                QMessageBox.information(self, "Импорт", f"Импортировано: {ok}\nОшибок: {len(errs)}\n" + "\n".join(errs[:10]))
                self.changed()


class UtilitiesPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.f_status = combo([("Неоплаченные", "unpaid"), ("Оплаченные", "paid")], "Все")
        self.f_service = QComboBox()
        top.addWidget(QLabel("Счета на оплату:"))
        top.addWidget(self.f_status)
        top.addWidget(self.f_service)
        top.addStretch()
        lay.addLayout(top)
        self.table = make_table(["Период", "Услуга", "Расход", "Сумма", "Срок оплаты", "Оплачен", "Примечание"])
        lay.addWidget(self.table)
        btns = QHBoxLayout()
        for text, fn in (("Новый счёт…", self.new_bill), ("Оплатить…", self.pay), ("Отменить оплату", self.unpay),
                         ("Изменить", self.edit_bill), ("Удалить", self.delete_bill), ("Показания…", self.readings),
                         ("Тарифы…", self.tariffs), ("Услуги…", self.services)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        lay.addLayout(btns)
        self.stats = QLabel()
        lay.addWidget(self.stats)
        self.f_status.currentIndexChanged.connect(self.refresh)
        self.f_service.currentIndexChanged.connect(self.refresh)
        self._loading = False

    def refresh(self, *_):
        if self._loading:
            return
        self._loading = True
        cur_s = self.f_service.currentData()
        self.f_service.clear()
        self.f_service.addItem("Все услуги", None)
        for s in self.fin.services():
            self.f_service.addItem(s["name"], s["id"])
        self.f_service.setCurrentIndex(max(0, self.f_service.findData(cur_s)))
        self._loading = False
        cur = self.fin.currency
        today = date.today()
        bills = self.fin.bills(self.f_status.currentData(), None, self.f_service.currentData())
        rows, colors, ids = [], {}, []
        for i, b in enumerate(bills):
            cons = f"{b['consumption']} {b['unit']}".strip() if b["consumption"] else ""
            rows.append([b["period"], b["service"], cons, fmt(b["amount_cents"], cur), b["due_date"] or "",
                         parse_date(b["paid_date"]).strftime("%d.%m.%Y") if b["paid_date"] else "—", b["note"]])
            ids.append(b["id"])
            if b["paid_date"]:
                colors[(i, 5)] = GREEN
            elif b["due_date"] and parse_date(b["due_date"]) < today:
                colors[(i, 4)] = RED
        fill(self.table, rows, ids, right=(3,), colors=colors)
        year = [s for p, s in self.fin.utility_stats(self.f_service.currentData(), 12)]
        self.stats.setText(f"За последние 12 месяцев начислено: {fmt(sum(year), cur)} "
                           f"(в среднем {fmt(sum(year) // 12, cur)} в месяц)")

    def new_bill(self):
        svcs = self.fin.services()
        if not svcs:
            return
        service = combo([(s["name"], s["id"]) for s in svcs])
        today = date.today()
        period = QLineEdit(add_months(today.replace(day=1), -1).strftime("%Y-%m"))
        amount = QLineEdit()
        amount.setPlaceholderText("пусто = расчёт по показаниям и тарифу")
        due = QLineEdit()
        due.setPlaceholderText("дд.мм.гггг (необязательно)")
        note = QLineEdit()

        def suggest():
            due.setText(self.fin.next_period_due(service.currentData(), period.text()) or "")
        service.currentIndexChanged.connect(suggest)
        suggest()
        if simple_form(self, "Новый счёт", [("Услуга", service), ("Период (ГГГГ-ММ)", period), ("Сумма", amount),
                                            ("Срок оплаты", due), ("Примечание", note)]):
            if guard(self, self.fin.create_bill, service.currentData(), period.text(), amount.text() or None,
                     due.text() or None, None, note.text()) is not None:
                self.changed()

    def _bill(self):
        bid = selected_id(self.table)
        if bid is None:
            QMessageBox.information(self, "Счёт", "Выберите счёт в таблице")
        return bid

    def pay(self):
        bid = self._bill()
        if bid is None:
            return
        acc = combo([(a["name"], a["id"]) for a in self.fin.accounts()])
        d = make_date()
        if simple_form(self, "Оплата счёта", [("Со счёта", acc), ("Дата оплаты", d)]):
            if guard(self, self.fin.pay_bill, bid, acc.currentData(), pd(d)) is not None:
                self.changed()

    def unpay(self):
        if (bid := self._bill()) is not None:
            self.fin.unpay_bill(bid)
            self.changed()

    def edit_bill(self):
        bid = self._bill()
        if bid is None:
            return
        b = self.fin.db.execute("SELECT * FROM bills WHERE id=?", (bid,)).fetchone()
        amount = QLineEdit(f"{b['amount_cents'] / 100:.2f}")
        due = QLineEdit(parse_date(b["due_date"]).strftime("%d.%m.%Y") if b["due_date"] else "")
        note = QLineEdit(b["note"])
        if simple_form(self, "Счёт", [("Сумма", amount), ("Срок оплаты", due), ("Примечание", note)]):
            if guard(self, self.fin.update_bill, bid, amount.text(), due.text() or None, note.text()) is not None:
                self.changed()

    def delete_bill(self):
        bid = self._bill()
        if bid is not None and QMessageBox.question(self, "Удаление", "Удалить счёт? Связанная оплата останется в операциях.") \
                == QMessageBox.StandardButton.Yes:
            self.fin.delete_bill(bid)
            self.changed()

    def readings(self):
        ReadingsDialog(self.fin, self).exec()
        self.changed()

    def tariffs(self):
        TariffsDialog(self.fin, self).exec()
        self.changed()

    def services(self):
        ServicesDialog(self.fin, self).exec()
        self.changed()


class ReadingsDialog(QDialog):
    def __init__(self, fin: Finance, parent=None):
        super().__init__(parent)
        self.fin = fin
        self.setWindowTitle("Показания счётчиков")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        self.service = combo([(s["name"], s["id"]) for s in fin.services() if s["metered"]])
        lay.addWidget(self.service)
        self.table = make_table(["Дата", "Показание", "Расход с прошлого"])
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.date = make_date()
        self.value = QLineEdit()
        self.value.setPlaceholderText("показание")
        add, rm = QPushButton("Добавить / обновить"), QPushButton("Удалить")
        for w in (self.date, self.value, add, rm):
            row.addWidget(w)
        lay.addLayout(row)
        add.clicked.connect(self.add)
        rm.clicked.connect(self.remove)
        self.service.currentIndexChanged.connect(self.load)
        self.load()

    def load(self):
        sid = self.service.currentData()
        rows = self.fin.readings(sid) if sid else []
        fill(self.table, [[parse_date(d).strftime("%d.%m.%Y"), v, "" if c is None else c] for _, d, v, c in rows],
             [r[0] for r in rows], right=(1, 2))

    def add(self):
        if guard(self, self.fin.add_reading, self.service.currentData(), pd(self.date), self.value.text()) is not None:
            self.value.clear()
            self.load()

    def remove(self):
        if (rid := selected_id(self.table)) is not None:
            self.fin.delete_reading(rid)
            self.load()


class TariffsDialog(QDialog):
    def __init__(self, fin: Finance, parent=None):
        super().__init__(parent)
        self.fin = fin
        self.setWindowTitle("Тарифы")
        self.resize(620, 420)
        lay = QVBoxLayout(self)
        self.service = combo([(s["name"], s["id"]) for s in fin.services()])
        lay.addWidget(self.service)
        self.table = make_table(["Действует с", "Тариф за ед.", "Порог (ед./мес.)", "Тариф сверх порога"])
        lay.addWidget(self.table)
        form = QHBoxLayout()
        self.date = make_date()
        self.rate, self.limit, self.rate2 = QLineEdit(), QLineEdit(), QLineEdit()
        self.rate.setPlaceholderText("тариф")
        self.limit.setPlaceholderText("порог (необяз.)")
        self.rate2.setPlaceholderText("тариф сверх")
        add, rm = QPushButton("Добавить"), QPushButton("Удалить")
        for w in (self.date, self.rate, self.limit, self.rate2, add, rm):
            form.addWidget(w)
        lay.addLayout(form)
        add.clicked.connect(self.add)
        rm.clicked.connect(self.remove)
        self.service.currentIndexChanged.connect(self.load)
        self.load()

    def load(self):
        sid = self.service.currentData()
        rows = self.fin.tariffs(sid) if sid else []
        fill(self.table, [[parse_date(r["valid_from"]).strftime("%d.%m.%Y"), r["rate"], r["tier_limit"] or "",
                           r["tier_rate"] or ""] for r in rows], [r["id"] for r in rows], right=(1, 2, 3))

    def add(self):
        if guard(self, self.fin.add_tariff, self.service.currentData(), pd(self.date), self.rate.text(),
                 self.limit.text() or None, self.rate2.text() or None) is not None:
            self.load()

    def remove(self):
        if (tid := selected_id(self.table)) is not None:
            self.fin.delete_tariff(tid)
            self.load()


class ServicesDialog(QDialog):
    def __init__(self, fin: Finance, parent=None):
        super().__init__(parent)
        self.fin = fin
        self.setWindowTitle("Коммунальные услуги")
        self.resize(560, 400)
        lay = QVBoxLayout(self)
        self.table = make_table(["Услуга", "Ед.", "Счётчик", "Фикс. часть", "Лицевой счёт"])
        lay.addWidget(self.table)
        row = QHBoxLayout()
        for text, fn in (("Добавить…", self.add), ("Изменить…", self.edit), ("В архив", self.archive)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        lay.addLayout(row)
        self.load()

    def load(self):
        rows = self.fin.services()
        fill(self.table, [[s["name"], s["unit"], "да" if s["metered"] else "нет", fmt(s["fixed_cents"]),
                           s["account_number"]] for s in rows], [s["id"] for s in rows])

    def _edit(self, s=None):
        name, unit = QLineEdit(s["name"] if s else ""), QLineEdit(s["unit"] if s else "")
        metered = QCheckBox("есть счётчик (расход считается по показаниям)")
        metered.setChecked(bool(s["metered"]) if s else True)
        fixed = QLineEdit(f"{s['fixed_cents'] / 100:.2f}" if s else "0")
        acc = QLineEdit(s["account_number"] if s else "")
        if simple_form(self, "Услуга", [("Название", name), ("Единица", unit), ("", metered),
                                        ("Фиксированная часть", fixed), ("Лицевой счёт", acc)]):
            return name.text(), unit.text(), metered.isChecked(), fixed.text(), acc.text()

    def add(self):
        if (v := self._edit()) and guard(self, self.fin.add_service, *v) is not None:
            self.load()

    def edit(self):
        sid = selected_id(self.table)
        if sid is None:
            return
        s = self.fin.db.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
        if (v := self._edit(s)) and guard(self, self.fin.update_service, sid, *v) is not None:
            self.load()

    def archive(self):
        if (sid := selected_id(self.table)) is not None:
            self.fin.archive_service(sid)
            self.load()


class BudgetPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.month = QLineEdit(date.today().strftime("%Y-%m"))
        self.month.setMaximumWidth(100)
        prev, nxt = QPushButton("◀"), QPushButton("▶")
        top.addWidget(QLabel("Месяц:"))
        for w in (prev, self.month, nxt):
            top.addWidget(w)
        top.addStretch()
        lay.addLayout(top)
        self.table = make_table(["Категория", "Лимит", "Потрачено", "Остаток", "Использовано"])
        lay.addWidget(self.table)
        btns = QHBoxLayout()
        b1, b2 = QPushButton("Задать лимит…"), QPushButton("Снять лимит")
        btns.addWidget(b1)
        btns.addWidget(b2)
        btns.addStretch()
        lay.addLayout(btns)
        self.bars: list[QProgressBar] = []
        b1.clicked.connect(self.set_limit)
        b2.clicked.connect(self.clear_limit)
        prev.clicked.connect(lambda: self.shift(-1))
        nxt.clicked.connect(lambda: self.shift(1))
        self.month.editingFinished.connect(self.refresh)

    def shift(self, n):
        y, m = map(int, self.month.text().split("-"))
        self.month.setText(add_months(date(y, m, 1), n).strftime("%Y-%m"))
        self.refresh()

    def refresh(self):
        try:
            rows = self.fin.budget_status(self.month.text())
        except ValueError:
            return
        cur = self.fin.currency
        out, colors = [], {}
        self.table.setRowCount(len(rows))
        for i, (cid, name, limit, spent) in enumerate(rows):
            out.append([name, fmt(limit, cur), fmt(spent, cur), fmt(limit - spent, cur), ""])
            if spent > limit:
                colors[(i, 3)] = RED
        fill(self.table, out, [r[0] for r in rows], right=(1, 2, 3), colors=colors)
        for i, (_, _, limit, spent) in enumerate(rows):
            bar = QProgressBar()
            bar.setRange(0, 100)
            pct = int(spent * 100 / limit) if limit else 0
            bar.setValue(min(pct, 100))
            bar.setFormat(f"{pct}%")
            bar.setStyleSheet("QProgressBar::chunk{background:%s}" % ("#B91C1C" if pct >= 100 else "#B45309" if pct >= 80 else "#15803D"))
            self.table.setCellWidget(i, 4, bar)

    def set_limit(self):
        cat = combo([(c["name"], c["id"]) for c in self.fin.categories("expense")])
        limit = QLineEdit()
        if simple_form(self, "Лимит на месяц", [("Категория", cat), ("Лимит", limit)]):
            if guard(self, self.fin.set_budget, cat.currentData(), limit.text()) is not None:
                self.refresh()

    def clear_limit(self):
        if (cid := selected_id(self.table)) is not None:
            self.fin.set_budget(cid, "")
            self.refresh()


class ReportsPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.d_from = make_date(date.today().replace(month=1, day=1))
        self.d_to = make_date(date.today())
        self.kind = combo([("Доходы по категориям", "income")], "Расходы по категориям")
        btn = QPushButton("Сформировать")
        for w in (QLabel("с"), self.d_from, QLabel("по"), self.d_to, self.kind, btn):
            top.addWidget(w)
        top.addStretch()
        lay.addLayout(top)
        try:
            import pyqtgraph as pg
            self.chart = pg.PlotWidget()
            self.chart.setBackground(C["panel"])
            self.chart.setMinimumHeight(220)
            lay.addWidget(self.chart)
        except ImportError:
            self.chart = None
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet("font-family:monospace")
        lay.addWidget(self.text)
        btn.clicked.connect(self.refresh)

    def refresh(self):
        a, b = pd(self.d_from), pd(self.d_to)
        kind = self.kind.currentData() or "expense"
        self.text.setPlainText(exchange.report_text(self.fin, a, b))
        if self.chart is not None:
            import pyqtgraph as pg
            self.chart.clear()
            data = self.fin.by_category(a, b, kind)[:12]
            xs = list(range(len(data)))
            self.chart.addItem(pg.BarGraphItem(x=xs, height=[d[1] / 100 for d in data], width=0.6,
                                               brush="#15803D" if kind == "income" else "#B91C1C"))
            self.chart.getAxis("bottom").setTicks([[(x, d[0][:10]) for x, d in zip(xs, data)]])


class SettingsPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        box = QGroupBox("Счета")
        bl = QVBoxLayout(box)
        self.acc = make_table(["Счёт", "Тип", "Начальный остаток", "Текущий остаток"])
        bl.addWidget(self.acc)
        r = QHBoxLayout()
        for text, fn in (("Добавить…", self.add_acc), ("Изменить…", self.edit_acc), ("В архив", self.arch_acc)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r.addWidget(b)
        bl.addLayout(r)
        lay.addWidget(box)

        box2 = QGroupBox("Категории")
        b2 = QVBoxLayout(box2)
        self.cat = make_table(["Категория", "Тип"])
        b2.addWidget(self.cat)
        r2 = QHBoxLayout()
        for text, fn in (("Добавить…", self.add_cat), ("Переименовать…", self.ren_cat), ("В архив", self.arch_cat)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r2.addWidget(b)
        b2.addLayout(r2)
        lay.addWidget(box2)

        box3 = QGroupBox("Регулярные операции (зарплата, подписки, аренда…)")
        b3 = QVBoxLayout(box3)
        self.rec = make_table(["Название", "Тип", "Сумма", "День", "Счёт", "Категория", "Активна"])
        b3.addWidget(self.rec)
        r3 = QHBoxLayout()
        for text, fn in (("Добавить…", self.add_rec), ("Вкл/выкл", self.toggle_rec), ("Удалить", self.del_rec)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            r3.addWidget(b)
        b3.addLayout(r3)
        lay.addWidget(box3)

        row = QHBoxLayout()
        self.currency = QLineEdit(self.fin.currency)
        self.currency.setMaximumWidth(70)
        self.currency.editingFinished.connect(lambda: (self.fin.set_setting("currency", self.currency.text().strip() or "BYN"),
                                                       self.changed()))
        row.addWidget(QLabel("Валюта:"))
        row.addWidget(self.currency)
        pw = QPushButton("Пароль…")
        pw.clicked.connect(self.password)
        row.addWidget(pw)
        row.addWidget(QLabel("Автоблокировка, мин:"))
        self.autolock = QSpinBox()
        self.autolock.setRange(0, 240)
        self.autolock.setSpecialValueText("выкл.")
        self.autolock.setValue(int(self.fin.get_setting("autolock_min", "10")))
        self.autolock.setToolTip("Через сколько минут бездействия запросить пароль (работает, если пароль задан)")
        self.autolock.valueChanged.connect(lambda v: self.fin.set_setting("autolock_min", v))
        row.addWidget(self.autolock)
        for text, fn in (("Резервная копия…", self.backup), ("Восстановить из копии…", self.restore)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

    def refresh(self):
        accs = self.fin.accounts()
        cur = self.fin.currency
        fill(self.acc, [[a["name"], a["kind"], fmt(a["initial_cents"], cur), fmt(self.fin.balance(a["id"]), cur)]
                        for a in accs], [a["id"] for a in accs], right=(2, 3))
        cats = self.fin.categories()
        fill(self.cat, [[c["name"], "Расход" if c["kind"] == "expense" else "Доход"] for c in cats], [c["id"] for c in cats])
        rec = self.fin.recurring()
        fill(self.rec, [[r["name"], exchange.KIND_RU[r["kind"]], fmt(r["amount_cents"], cur), r["day"], r["account"],
                         r["category"] or "", "да" if r["active"] else "нет"] for r in rec], [r["id"] for r in rec], right=(2,))

    KINDS = [("Карта", "card"), ("Наличные", "cash"), ("Вклад / накопления", "savings"), ("Электронный кошелёк", "wallet")]

    def _acc_form(self, a=None):
        name = QLineEdit(a["name"] if a else "")
        kind = combo(self.KINDS)
        if a:
            kind.setCurrentIndex(max(0, kind.findData(a["kind"])))
        init = QLineEdit(f"{a['initial_cents'] / 100:.2f}" if a else "0")
        if simple_form(self, "Счёт", [("Название", name), ("Тип", kind), ("Начальный остаток", init)]):
            return name.text(), kind.currentData(), init.text()

    def add_acc(self):
        if (v := self._acc_form()) and guard(self, self.fin.add_account, *v) is not None:
            self.changed()

    def edit_acc(self):
        aid = selected_id(self.acc)
        if aid is None:
            return
        a = self.fin.db.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone()
        if (v := self._acc_form(a)) and guard(self, self.fin.update_account, aid, *v) is not None:
            self.changed()

    def arch_acc(self):
        if (aid := selected_id(self.acc)) is not None:
            self.fin.archive_account(aid)
            self.changed()

    def add_cat(self):
        name, kind = QLineEdit(), combo([("Расход", "expense"), ("Доход", "income")])
        if simple_form(self, "Категория", [("Название", name), ("Тип", kind)]) and name.text().strip():
            self.fin.add_category(name.text(), kind.currentData())
            self.changed()

    def ren_cat(self):
        if (cid := selected_id(self.cat)) is not None:
            name = QLineEdit(self.cat.item(self.cat.currentRow(), 0).text())
            if simple_form(self, "Переименовать", [("Название", name)]) and name.text().strip():
                self.fin.rename_category(cid, name.text())
                self.changed()

    def arch_cat(self):
        if (cid := selected_id(self.cat)) is not None:
            self.fin.archive_category(cid)
            self.changed()

    def add_rec(self):
        name, amount = QLineEdit(), QLineEdit()
        kind = combo([("Расход", "expense"), ("Доход", "income")])
        acc = combo([(a["name"], a["id"]) for a in self.fin.accounts()])
        cat = QComboBox()
        day = QSpinBox()
        day.setRange(1, 31)
        day.setValue(1)
        start = make_date()

        def cats():
            cat.clear()
            cat.addItem("— без категории —", None)
            for c in self.fin.categories(kind.currentData()):
                cat.addItem(c["name"], c["id"])
        kind.currentIndexChanged.connect(cats)
        cats()
        if simple_form(self, "Регулярная операция", [("Название", name), ("Тип", kind), ("Сумма", amount), ("Счёт", acc),
                                                     ("Категория", cat), ("День месяца", day), ("Начиная с", start)]):
            if guard(self, self.fin.add_recurring, name.text(), kind.currentData(), amount.text(), acc.currentData(),
                     cat.currentData(), day.value(), pd(start)) is not None:
                self.fin.run_recurring()
                self.changed()

    def toggle_rec(self):
        if (rid := selected_id(self.rec)) is not None:
            on = self.rec.item(self.rec.currentRow(), 6).text() == "да"
            self.fin.set_recurring_active(rid, not on)
            self.changed()

    def del_rec(self):
        if (rid := selected_id(self.rec)) is not None:
            self.fin.delete_recurring(rid)
            self.changed()

    def password(self):
        from .gui_extra import PasswordDialog
        PasswordDialog(self.fin, self).exec()
        self.changed()

    def backup(self):
        folder = QFileDialog.getExistingDirectory(self, "Куда сохранить копию")
        if folder:
            p = guard(self, self.fin.backup, folder)
            if p:
                QMessageBox.information(self, "Копия", f"Сохранено:\n{p}")

    def restore(self):
        p, _ = QFileDialog.getOpenFileName(self, "Файл копии", "", "База (*.db)")
        if p and QMessageBox.question(self, "Восстановление", "Текущие данные будут заменены. Продолжить?") == \
                QMessageBox.StandardButton.Yes:
            if guard(self, self.fin.restore, p) is not None:
                self.changed()


# ===================================================================== окно
class MainWindow(QMainWindow):
    SUBTITLES = {"Обзор": "Остатки, напоминания и динамика за полгода",
                 "Операции": "Доходы, расходы и переводы между счетами",
                 "Календарь": "Все платежи, поступления и сроки оплаты по дням",
                 "Коммунальные платежи": "Счета, показания счётчиков и тарифы",
                 "Копилка": "Накопления на цели: отпуск, ремонт, подушка безопасности",
                 "Бюджет": "Месячные лимиты по категориям",
                 "Отчёты": "Итоги и структура расходов за период",
                 "Счета и настройки": "Счета, категории, регулярные операции, резервные копии"}

    def __init__(self, fin: Finance, backup_dir: str | None = None):
        super().__init__()
        self.fin, self.backup_dir = fin, backup_dir
        self.setWindowTitle(f"Домашняя бухгалтерия {__version__}")
        self.resize(1200, 780)
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(250)
        sl = QVBoxLayout(side)
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 4, 6, 4)
        mark = QLabel()
        mark.setPixmap(logo_pixmap(40))
        mark.setFixedSize(40, 40)
        name = QLabel("Домашняя\nбухгалтерия")
        name.setObjectName("brand")
        brand.addWidget(mark)
        brand.addWidget(name, 1)
        sl.addLayout(brand)
        add = QPushButton("Новая операция · Ctrl+N")
        add.setProperty("type", "primary")
        add.clicked.connect(lambda: self.pages[1][0].add())
        sl.addWidget(add)
        sl.addSpacing(12)

        self.stack = QStackedWidget()
        from .gui_extra import CalendarPage, GoalsPage
        self.pages = [(OverviewPage(self), "Обзор"), (TransactionsPage(self), "Операции"),
                      (CalendarPage(self), "Календарь"), (UtilitiesPage(self), "Коммунальные платежи"),
                      (GoalsPage(self), "Копилка"), (BudgetPage(self), "Бюджет"),
                      (ReportsPage(self), "Отчёты"), (SettingsPage(self), "Счета и настройки")]
        self.nav: list[QPushButton] = []
        group = QButtonGroup(self)
        for i, (page, title) in enumerate(self.pages):
            if title in ("Операции", "Бюджет", "Счета и настройки"):
                sec = QLabel({"Операции": "ДЕНЬГИ", "Бюджет": "АНАЛИТИКА", "Счета и настройки": "СИСТЕМА"}[title])
                sec.setObjectName("navSection")
                sl.addWidget(sec)
            b = QPushButton(title)
            b.setObjectName("navButton")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.go(i))
            group.addButton(b)
            sl.addWidget(b)
            self.nav.append(b)
            self.stack.addWidget(page)
        sl.addStretch(1)
        self.lock_btn = QPushButton("🔒 Заблокировать · Ctrl+L")
        self.lock_btn.clicked.connect(self.lock)
        sl.addWidget(self.lock_btn)
        root.addWidget(side)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        header = QFrame()
        header.setObjectName("pageHeader")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(24, 17, 24, 8)
        self.page_title = QLabel()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel()
        self.page_subtitle.setObjectName("pageSubtitle")
        hl.addWidget(self.page_title)
        hl.addWidget(self.page_subtitle)
        cl.addWidget(header)
        cl.addWidget(self.stack, 1)
        root.addWidget(content, 1)
        for p, _ in self.pages:
            if p.layout():
                p.layout().setContentsMargins(24, 8, 24, 16)

        act = QAction("Новая операция", self)
        act.setShortcut(QKeySequence("Ctrl+N"))
        act.triggered.connect(lambda: self.pages[1][0].add())
        self.addAction(act)
        lock_act = QAction("Заблокировать", self)
        lock_act.setShortcut(QKeySequence("Ctrl+L"))
        lock_act.triggered.connect(self.lock)
        self.addAction(lock_act)
        self.setWindowIcon(app_icon())
        self._locked, self._last_activity = False, time.monotonic()
        QApplication.instance().installEventFilter(self)
        self._idle_timer = QTimer(self)
        self._idle_timer.timeout.connect(self._check_idle)
        self._idle_timer.start(10_000)
        created = self.fin.run_recurring()
        if created:
            self.statusBar().showMessage(f"Создано регулярных операций: {created}", 8000)
        self.go(0)
        QTimer.singleShot(300, self.nag)

    def go(self, i: int):
        self.nav[i].setChecked(True)
        self.stack.setCurrentIndex(i)
        title = self.pages[i][1]
        self.page_title.setText(title)
        self.page_subtitle.setText(self.SUBTITLES.get(title, ""))
        self.pages[i][0].refresh()

    # ---- блокировка паролем
    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.MouseMove, QEvent.Type.Wheel):
            self._last_activity = time.monotonic()
        return False

    def _check_idle(self):
        minutes = int(self.fin.get_setting("autolock_min", "10") or 0)
        if minutes and time.monotonic() - self._last_activity > minutes * 60:
            self.lock()

    def lock(self):
        from .gui_extra import LockDialog
        if self._locked or not self.fin.has_password():
            return
        self._locked = True
        self.centralWidget().setVisible(False)  # за окном пароля содержимое не видно
        ok = LockDialog(self.fin, self).exec() == QDialog.DialogCode.Accepted
        self.centralWidget().setVisible(True)
        self._locked, self._last_activity = False, time.monotonic()
        if not ok:
            self.close()

    def refresh_all(self):
        self.lock_btn.setVisible(self.fin.has_password())
        self.pages[self.stack.currentIndex()][0].refresh()
        # остальные обновятся при переключении; обзор — всегда актуален
        if self.stack.currentIndex() != 0:
            self.pages[0][0].refresh()

    def nag(self):
        due = [(b, d) for b, d in self.fin.reminders() if d <= 3]
        if due:
            lines = [f"• {b['service']} за {b['period']} — {fmt(b['amount_cents'], self.fin.currency)} "
                     f"({'просрочено на ' + str(-d) + ' дн.' if d < 0 else 'срок через ' + str(d) + ' дн.' if d else 'срок сегодня'})"
                     for b, d in due]
            QMessageBox.warning(self, "Пора платить", "\n".join(lines))

    def closeEvent(self, e):
        if self.backup_dir:
            try:
                self.fin.backup(self.backup_dir)
            except Exception:  # noqa: BLE001 — копия при выходе не должна мешать закрыть окно
                pass
        super().closeEvent(e)


def main(argv=None):
    from .exchange import default_db_path
    app = QApplication(argv or sys.argv)
    apply_theme(app)
    app.setWindowIcon(app_icon())
    path = default_db_path()
    fin = Finance(path)
    from .gui_extra import ask_password
    if not ask_password(fin):
        return 0
    win = MainWindow(fin, backup_dir=str(path.parent / "backups"))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
