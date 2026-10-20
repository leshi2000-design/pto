"""Календарь платежей, копилки, пароль и блокировка экрана."""
from __future__ import annotations


from PyQt6.QtCore import QDate, QLocale, QPointF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (QCalendarWidget, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QProgressBar, QPushButton, QVBoxLayout)

from .core import parse_date
from .gui import (Page, TxDialog, combo, fill, guard, make_date, make_table, pd, selected_id, simple_form)
from .money import fmt
from .theme import C, logo_pixmap

GREEN, RED, AMBER, GREY = QColor(C["good"]), QColor(C["bad"]), QColor(C["warn"]), QColor("#6B7280")
MARK_COLORS = {"income": GREEN, "expense": RED, "bill": AMBER, "planned": GREY}
TYPE_RU = {"income": "Поступление", "expense": "Платёж", "bill": "Счёт к оплате", "planned": "По плану"}


class MarkedCalendar(QCalendarWidget):
    """Календарь с цветными точками под числами: зелёная — поступление, красная — платёж,
    жёлтая — счёт к оплате, серая — запланировано."""

    def __init__(self):
        super().__init__()
        self.marks: dict[str, set[str]] = {}
        self.setLocale(QLocale(QLocale.Language.Russian))
        self.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setGridVisible(False)
        self.setMinimumSize(520, 400)

    def paintCell(self, painter: QPainter, rect, d: QDate):
        super().paintCell(painter, rect, d)
        types = self.marks.get(d.toString("yyyy-MM-dd"))
        if not types:
            return
        order = [t for t in ("income", "expense", "bill", "planned") if t in types]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0 = rect.center().x() - (len(order) - 1) * 5
        y = rect.bottom() - 6
        for i, t in enumerate(order):
            c = QPointF(x0 + i * 10, y)
            if t == "planned":
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(MARK_COLORS[t], 1.6))
            else:
                painter.setBrush(MARK_COLORS[t])
                painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(c, 3.2, 3.2)
        painter.restore()


class CalendarPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.cal = MarkedCalendar()
        left.addWidget(self.cal)
        legend = QLabel("<span style='color:%s'>●</span> поступление &nbsp; <span style='color:%s'>●</span> платёж "
                        "&nbsp; <span style='color:%s'>●</span> счёт к оплате &nbsp; <span style='color:%s'>○</span> по плану"
                        % (C["good"], C["bad"], C["warn"], "#6B7280"))
        legend.setTextFormat(Qt.TextFormat.RichText)
        left.addWidget(legend)
        self.month_sum = QLabel()
        self.month_sum.setTextFormat(Qt.TextFormat.RichText)
        left.addWidget(self.month_sum)
        left.addStretch(1)
        lay.addLayout(left, 3)

        right = QVBoxLayout()
        self.day_title = QLabel()
        self.day_title.setStyleSheet("font-size:16px;font-weight:600")
        right.addWidget(self.day_title)
        self.table = make_table(["Что", "Описание", "Сумма"])
        right.addWidget(self.table, 1)
        btns = QHBoxLayout()
        add, pay = QPushButton("Добавить операцию"), QPushButton("Оплатить счёт…")
        add.setProperty("type", "primary")
        add.clicked.connect(self.add)
        pay.clicked.connect(self.pay)
        btns.addWidget(add)
        btns.addWidget(pay)
        right.addLayout(btns)
        lay.addLayout(right, 2)

        self.events: dict[str, list[dict]] = {}
        self._period = ""
        self.cal.selectionChanged.connect(self.show_day)
        self.cal.currentPageChanged.connect(lambda *_: self.refresh())

    def refresh(self):
        self._period = f"{self.cal.yearShown():04d}-{self.cal.monthShown():02d}"
        self.events = self.fin.calendar_events(self._period)
        self.cal.marks = {d: {e["type"] for e in evs} for d, evs in self.events.items()}
        cur = self.fin.currency
        inc = sum(e["cents"] for v in self.events.values() for e in v if e["type"] == "income")
        exp = sum(e["cents"] for v in self.events.values() for e in v if e["type"] == "expense")
        bills = sum(e["cents"] for v in self.events.values() for e in v if e["type"] == "bill")
        plan_in = sum(e["cents"] for v in self.events.values() for e in v if e["type"] == "planned" and e["kind"] == "income")
        plan_out = sum(e["cents"] for v in self.events.values() for e in v if e["type"] == "planned" and e["kind"] == "expense")
        self.month_sum.setText(
            f"<b>{self._period}</b>: поступления <b style='color:{C['good']}'>{fmt(inc, cur)}</b>, "
            f"платежи <b style='color:{C['bad']}'>{fmt(exp, cur)}</b><br>"
            f"ещё к оплате по счетам: <b style='color:{C['warn']}'>{fmt(bills, cur)}</b>, по плану: "
            f"<b style='color:{C['good']}'>+{fmt(plan_in, cur)}</b> / <b style='color:{C['bad']}'>−{fmt(plan_out, cur)}</b>")
        self.cal.updateCells()
        self.show_day()

    def _day(self) -> str:
        return self.cal.selectedDate().toString("yyyy-MM-dd")

    def show_day(self):
        if self.cal.selectedDate().toString("yyyy-MM") != self._period:
            return  # выбран день соседнего месяца — страница сейчас перерисуется
        d = self._day()
        evs = self.events.get(d, [])
        self.day_title.setText(parse_date(d).strftime("%d.%m.%Y"))
        cur = self.fin.currency
        rows, colors = [], {}
        for i, e in enumerate(evs):
            sign = "+" if e["type"] == "income" or e.get("kind") == "income" else "−"  # у планового kind — доход/расход
            rows.append([TYPE_RU[e["type"]], e["title"], sign + fmt(e["cents"], cur)])
            colors[(i, 0)] = MARK_COLORS[e["type"]]
        fill(self.table, rows, [e.get("bill_id") or 0 for e in evs], right=(2,), colors=colors)

    def add(self):
        if TxDialog(self.fin, self, day=self._day()).exec():
            self.changed()

    def pay(self):
        bid = selected_id(self.table)
        if not bid:
            QMessageBox.information(self, "Оплата", "Выберите в списке строку «Счёт к оплате»")
            return
        acc = combo([(a["name"], a["id"]) for a in self.fin.accounts()])
        d = make_date()
        if simple_form(self, "Оплата счёта", [("Со счёта", acc), ("Дата оплаты", d)]):
            if guard(self, self.fin.pay_bill, bid, acc.currentData(), pd(d)) is not None:
                self.changed()


class GoalsPage(Page):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.summary)
        self.table = make_table(["Копилка", "Накоплено", "Цель", "Осталось", "Прогресс", "Срок", "В месяц"])
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        for text, fn, primary in (("Новая копилка…", self.new, True), ("Пополнить…", self.deposit, False),
                                  ("Снять…", self.withdraw, False), ("Изменить…", self.edit, False),
                                  ("В архив", self.archive, False)):
            b = QPushButton(text)
            if primary:
                b.setProperty("type", "primary")
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

    def refresh(self):
        cur = self.fin.currency
        goals = self.fin.goals()
        rows, ids, prog = [], [], []
        for g in goals:
            p = self.fin.goal_progress(g)
            prog.append(p)
            rows.append([g["name"], fmt(p["saved"], cur), fmt(p["target"], cur), fmt(p["left"], cur), "",
                         parse_date(g["deadline"]).strftime("%d.%m.%Y") if g["deadline"] else "—",
                         "достигнуто 🎉" if p["done"] else (fmt(p["monthly"], cur) if p["monthly"] is not None else "—")])
            ids.append(g["id"])
        fill(self.table, rows, ids, right=(1, 2, 3, 6))
        for i, p in enumerate(prog):
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(p["pct"])
            bar.setFormat(f"{p['pct']}%")
            self.table.setCellWidget(i, 4, bar)
        total = sum(p["saved"] for p in prog)
        self.summary.setText(f"<h3>Всего в копилках: {fmt(total, cur)}</h3>" if goals
                             else "<h3>Копилок пока нет</h3><p>Создайте цель — отпуск, ремонт, подушка безопасности — "
                                  "и откладывайте деньги со счетов. Накопленное остаётся в общем остатке.</p>")

    def _goal(self):
        gid = selected_id(self.table)
        if gid is None:
            QMessageBox.information(self, "Копилка", "Выберите копилку в таблице")
        return gid

    def new(self):
        name, target, dl = QLineEdit(), QLineEdit(), QLineEdit()
        dl.setPlaceholderText("дд.мм.гггг (необязательно)")
        if simple_form(self, "Новая копилка", [("Название", name), ("Цель, сумма", target), ("К какому сроку", dl)]):
            if guard(self, self.fin.add_goal, name.text(), target.text(), dl.text() or None) is not None:
                self.changed()

    def _move(self, title, fn, label):
        gid = self._goal()
        if gid is None:
            return
        acc = combo([(a["name"], a["id"]) for a in self.fin.accounts()])
        amount = QLineEdit()
        d = make_date()
        if simple_form(self, title, [(label, acc), ("Сумма", amount), ("Дата", d)]):
            if guard(self, fn, gid, acc.currentData(), amount.text(), pd(d)) is not None:
                self.changed()

    def deposit(self):
        self._move("Пополнить копилку", self.fin.deposit_to_goal, "Со счёта")

    def withdraw(self):
        self._move("Снять из копилки", self.fin.withdraw_from_goal, "На счёт")

    def edit(self):
        gid = self._goal()
        if gid is None:
            return
        g = self.fin.db.execute("SELECT * FROM accounts WHERE id=?", (gid,)).fetchone()
        name, target = QLineEdit(g["name"]), QLineEdit(f"{g['target_cents'] / 100:.2f}")
        dl = QLineEdit(parse_date(g["deadline"]).strftime("%d.%m.%Y") if g["deadline"] else "")
        if simple_form(self, "Копилка", [("Название", name), ("Цель", target), ("Срок", dl)]):
            if guard(self, self.fin.update_goal, gid, name.text(), target.text(), dl.text() or None) is not None:
                self.changed()

    def archive(self):
        gid = self._goal()
        if gid is None:
            return
        if self.fin.balance(gid) != 0:
            QMessageBox.warning(self, "Копилка", "Сначала снимите деньги из копилки — в архив можно убрать только пустую.")
            return
        self.fin.archive_account(gid)
        self.changed()


# ===================================================================== пароль
def _pw_field(placeholder="") -> QLineEdit:
    f = QLineEdit()
    f.setEchoMode(QLineEdit.EchoMode.Password)
    f.setPlaceholderText(placeholder)
    return f


class LockDialog(QDialog):
    """Окно ввода пароля при запуске и после блокировки. reject() = выход из программы."""

    def __init__(self, fin, parent=None):
        super().__init__(parent)
        self.fin, self.attempts = fin, 0
        self.setWindowTitle("Домашняя бухгалтерия")
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        self.setFixedWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(72))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Введите пароль")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size:18px;font-weight:600")
        self.field = _pw_field("Пароль")
        self.error = QLabel()
        self.error.setStyleSheet(f"color:{C['bad']}")
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ok, quit_ = QPushButton("Войти"), QPushButton("Выйти")
        ok.setProperty("type", "primary")
        ok.setDefault(True)
        ok.clicked.connect(self.try_login)
        quit_.clicked.connect(self.reject)
        for w in (logo, title, self.field, self.error, ok, quit_):
            lay.addWidget(w)
        self.field.returnPressed.connect(self.try_login)

    def try_login(self):
        if self.fin.check_password(self.field.text()):
            self.accept()
            return
        self.attempts += 1
        self.field.clear()
        self.error.setText(f"Неверный пароль (попытка {self.attempts})")
        if self.attempts >= 5:  # ничего не блокируем навсегда — просто закрываем программу
            self.reject()


def ask_password(fin, parent=None) -> bool:
    """True, если пароля нет или он введён верно."""
    return (not fin.has_password()) or LockDialog(fin, parent).exec() == QDialog.DialogCode.Accepted


class PasswordDialog(QDialog):
    """Установка, смена и снятие пароля."""

    def __init__(self, fin, parent=None):
        super().__init__(parent)
        self.fin = fin
        self.setWindowTitle("Пароль")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        has = fin.has_password()
        lay.addWidget(QLabel("Пароль запрашивается при запуске программы и после автоблокировки." if has else
                             "Пароль не задан. Программа открывается без ввода пароля."))
        self.cur = _pw_field("Текущий пароль")
        self.new = _pw_field("Новый пароль (не короче 4 символов)")
        self.rep = _pw_field("Повторите новый пароль")
        if has:
            lay.addWidget(self.cur)
        lay.addWidget(self.new)
        lay.addWidget(self.rep)
        warn = QLabel("Пароль нельзя восстановить: если забудете, доступ к данным через программу будет потерян. "
                      "Файл базы при этом не шифруется — пароль защищает вход в программу.")
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color:{C['muted']};font-size:12px")
        lay.addWidget(warn)
        row = QHBoxLayout()
        save = QPushButton("Сохранить пароль")
        save.setProperty("type", "primary")
        save.clicked.connect(self.save)
        row.addWidget(save)
        if has:
            rm = QPushButton("Снять пароль")
            rm.setProperty("type", "danger")
            rm.clicked.connect(self.remove)
            row.addWidget(rm)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay.addLayout(row)

    def save(self):
        if self.new.text() != self.rep.text():
            QMessageBox.warning(self, "Пароль", "Пароли не совпадают")
            return
        try:
            self.fin.set_password(self.new.text(), self.cur.text())
        except ValueError as e:
            QMessageBox.warning(self, "Пароль", str(e))
            return
        QMessageBox.information(self, "Пароль", "Пароль сохранён.")
        self.accept()

    def remove(self):
        try:
            self.fin.remove_password(self.cur.text())
        except ValueError as e:
            QMessageBox.warning(self, "Пароль", str(e))
            return
        QMessageBox.information(self, "Пароль", "Пароль снят.")
        self.accept()
