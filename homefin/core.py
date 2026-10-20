"""Ядро домашней бухгалтерии: SQLite + вся бизнес-логика без GUI."""
from __future__ import annotations

import calendar
import hashlib
import hmac
import os
import shutil
import sqlite3
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .money import dec, to_cents

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, kind TEXT NOT NULL DEFAULT 'card',
    initial_cents INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0,
    target_cents INTEGER NOT NULL DEFAULT 0, deadline TEXT);
CREATE TABLE IF NOT EXISTS categories(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN('income','expense')),
    archived INTEGER NOT NULL DEFAULT 0, UNIQUE(name, kind));
CREATE TABLE IF NOT EXISTS transactions(
    id INTEGER PRIMARY KEY, date TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN('income','expense','transfer')),
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    to_account_id INTEGER REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id),
    note TEXT NOT NULL DEFAULT '', recurring_id INTEGER);
CREATE INDEX IF NOT EXISTS ix_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS ix_tx_cat ON transactions(category_id);
CREATE TABLE IF NOT EXISTS budgets(
    category_id INTEGER PRIMARY KEY REFERENCES categories(id), limit_cents INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS services(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, unit TEXT NOT NULL DEFAULT '',
    metered INTEGER NOT NULL DEFAULT 1, fixed_cents INTEGER NOT NULL DEFAULT 0,
    account_number TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tariffs(
    id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    valid_from TEXT NOT NULL, rate TEXT NOT NULL, tier_limit TEXT, tier_rate TEXT);
CREATE TABLE IF NOT EXISTS readings(
    id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    date TEXT NOT NULL, value TEXT NOT NULL, UNIQUE(service_id, date));
CREATE TABLE IF NOT EXISTS bills(
    id INTEGER PRIMARY KEY, service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    period TEXT NOT NULL, consumption TEXT, amount_cents INTEGER NOT NULL, due_date TEXT,
    paid_date TEXT, transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    note TEXT NOT NULL DEFAULT '', UNIQUE(service_id, period));
CREATE TABLE IF NOT EXISTS recurring(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN('income','expense')),
    amount_cents INTEGER NOT NULL, account_id INTEGER NOT NULL REFERENCES accounts(id),
    category_id INTEGER REFERENCES categories(id), day INTEGER NOT NULL,
    start_date TEXT NOT NULL, end_date TEXT, last_period TEXT, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

DEFAULT_EXPENSE = ["Продукты", "Транспорт", "Здоровье", "Одежда", "Развлечения", "Связь и интернет",
                   "Образование", "Дом и ремонт", "Подарки", "Коммунальные платежи", "Прочее"]
DEFAULT_INCOME = ["Зарплата", "Подработка", "Подарки", "Проценты", "Прочее"]
DEFAULT_SERVICES = [("Электроэнергия", "кВт·ч", 1), ("Холодная вода", "м³", 1), ("Горячая вода", "м³", 1),
                    ("Газ", "м³", 1), ("Отопление", "Гкал", 0), ("Водоотведение", "м³", 0),
                    ("Вывоз мусора", "", 0), ("Квартплата / ЖКУ", "", 0), ("Домофон", "", 0)]
CASH_ACCOUNT = "Наличные"
UTILITY_CATEGORY = "Коммунальные платежи"


def iso(d) -> str:
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat() if isinstance(d, date) else str(d)


def parse_date(text) -> date:
    if isinstance(text, date):
        return text
    s = str(text).strip()
    for f in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            pass
    raise ValueError(f"Некорректная дата: {text!r} (ожидается дд.мм.гггг)")


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_bounds(period: str) -> tuple[str, str]:
    y, m = map(int, period.split("-"))
    return f"{y:04d}-{m:02d}-01", f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def exchange_kind(kind: str) -> str:
    return {"income": "Доход", "expense": "Расход"}.get(kind, kind)


def _q(x: Decimal, places="0.001") -> Decimal:
    return x.quantize(Decimal(places), rounding=ROUND_HALF_UP)


class Finance:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self._migrate()
        if not self.db.execute("SELECT 1 FROM accounts").fetchone():
            self._seed()

    # ---------------------------------------------------------------- базовое
    def _migrate(self):
        """Базы первой версии не имели полей копилки."""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(accounts)")}
        with self.db:
            if "target_cents" not in cols:
                self.db.execute("ALTER TABLE accounts ADD COLUMN target_cents INTEGER NOT NULL DEFAULT 0")
            if "deadline" not in cols:
                self.db.execute("ALTER TABLE accounts ADD COLUMN deadline TEXT")

    def _seed(self):
        with self.db:
            self.db.execute("INSERT INTO accounts(name,kind) VALUES(?,?)", (CASH_ACCOUNT, "cash"))
            for n in DEFAULT_EXPENSE:
                self.db.execute("INSERT INTO categories(name,kind) VALUES(?,'expense')", (n,))
            for n in DEFAULT_INCOME:
                self.db.execute("INSERT INTO categories(name,kind) VALUES(?,'income')", (n,))
            for n, u, m in DEFAULT_SERVICES:
                self.db.execute("INSERT INTO services(name,unit,metered) VALUES(?,?,?)", (n, u, m))
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('currency','BYN')")

    def close(self):
        self.db.close()

    def get_setting(self, key, default=""):
        r = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, str(value)))

    @property
    def currency(self) -> str:
        return self.get_setting("currency", "BYN")

    def backup(self, folder: str | Path, keep: int = 20) -> Path:
        """Копия базы по правилам sqlite (консистентная), хранятся последние `keep`."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / f"homefin_{datetime.now():%Y%m%d_%H%M%S}.db"
        out = sqlite3.connect(dst)
        with out:
            self.db.backup(out)
        out.close()
        for old in sorted(folder.glob("homefin_*.db"))[:-keep]:
            old.unlink()
        return dst

    def restore(self, src: str | Path):
        if self.path == ":memory:":
            raise RuntimeError("Восстановление недоступно для базы в памяти")
        self.db.close()
        shutil.copyfile(src, self.path)
        self.__init__(self.path)

    # ---------------------------------------------------------------- счета
    def accounts(self, include_archived=False, include_goals=False):
        """Счета; копилки (kind='goal') по умолчанию не входят — ими управляет вкладка «Копилка»."""
        sql = "SELECT * FROM accounts WHERE 1=1"
        if not include_archived:
            sql += " AND archived=0"
        if not include_goals:
            sql += " AND kind!='goal'"
        return self.db.execute(sql + " ORDER BY name").fetchall()

    def add_account(self, name, kind="card", initial="0") -> int:
        name = name.strip()
        if not name:
            raise ValueError("Укажите название счёта")
        with self.db:
            return self.db.execute("INSERT INTO accounts(name,kind,initial_cents) VALUES(?,?,?)",
                                   (name, kind, to_cents(initial))).lastrowid

    def update_account(self, acc_id, name, kind, initial):
        with self.db:
            self.db.execute("UPDATE accounts SET name=?,kind=?,initial_cents=? WHERE id=?",
                            (name.strip(), kind, to_cents(initial), acc_id))

    def archive_account(self, acc_id, archived=True):
        with self.db:
            self.db.execute("UPDATE accounts SET archived=? WHERE id=?", (int(archived), acc_id))

    def balance(self, acc_id, upto: str | None = None) -> int:
        a = self.db.execute("SELECT initial_cents FROM accounts WHERE id=?", (acc_id,)).fetchone()
        if not a:
            raise KeyError(acc_id)
        cond, args = ("AND date<=?", [upto]) if upto else ("", [])

        def total(where: str, col: str = "account_id") -> int:
            sql = f"SELECT COALESCE(SUM(amount_cents),0) FROM transactions WHERE {col}=? AND kind=? {cond}"
            return self.db.execute(sql, [acc_id, where, *args]).fetchone()[0]

        return (a["initial_cents"] + total("income") - total("expense") - total("transfer")
                + total("transfer", "to_account_id"))

    def balances(self):
        return [(a, self.balance(a["id"])) for a in self.accounts(include_goals=True)]

    def total_balance(self) -> int:
        return sum(b for _, b in self.balances())

    # ---------------------------------------------------------------- копилки
    # Копилка — особый счёт (kind='goal') с целевой суммой. Пополнение — перевод со счёта,
    # поэтому общий остаток не меняется, а доходы и расходы в отчётах не искажаются.
    def add_goal(self, name, target, deadline=None) -> int:
        name = name.strip()
        cents = to_cents(target)
        if not name:
            raise ValueError("Укажите название копилки")
        if cents <= 0:
            raise ValueError("Цель должна быть больше нуля")
        with self.db:
            return self.db.execute("INSERT INTO accounts(name,kind,target_cents,deadline) VALUES(?,'goal',?,?)",
                                   (name, cents, iso(parse_date(deadline)) if deadline else None)).lastrowid

    def update_goal(self, goal_id, name, target, deadline=None):
        cents = to_cents(target)
        if cents <= 0:
            raise ValueError("Цель должна быть больше нуля")
        with self.db:
            self.db.execute("UPDATE accounts SET name=?,target_cents=?,deadline=? WHERE id=? AND kind='goal'",
                            (name.strip(), cents, iso(parse_date(deadline)) if deadline else None, goal_id))

    def goals(self, include_archived=False):
        sql = "SELECT * FROM accounts WHERE kind='goal'" + ("" if include_archived else " AND archived=0")
        return self.db.execute(sql + " ORDER BY name").fetchall()

    def goal_progress(self, goal, today: date | None = None) -> dict:
        today = today or date.today()
        saved, target = self.balance(goal["id"]), goal["target_cents"]
        left = max(target - saved, 0)
        monthly = None
        if goal["deadline"] and left:
            d = parse_date(goal["deadline"])
            months = max((d.year - today.year) * 12 + d.month - today.month, 0) or (1 if d >= today else 0)
            monthly = -(-left // months) if months else left  # округление вверх; срок прошёл — нужна вся сумма
        return dict(saved=saved, target=target, left=left, pct=min(100, saved * 100 // target) if target else 0,
                    done=saved >= target, monthly=monthly)

    def deposit_to_goal(self, goal_id, from_account_id, amount, d=None) -> int:
        g = self._goal(goal_id)
        return self.add_transaction(d or date.today(), "transfer", amount, from_account_id,
                                    note=f"В копилку «{g['name']}»", to_account_id=goal_id)

    def withdraw_from_goal(self, goal_id, to_account_id, amount, d=None) -> int:
        g = self._goal(goal_id)
        if to_cents(amount) > self.balance(goal_id):
            raise ValueError("В копилке нет столько денег")
        return self.add_transaction(d or date.today(), "transfer", amount, goal_id,
                                    note=f"Из копилки «{g['name']}»", to_account_id=to_account_id)

    def _goal(self, goal_id):
        g = self.db.execute("SELECT * FROM accounts WHERE id=? AND kind='goal'", (goal_id,)).fetchone()
        if not g:
            raise ValueError("Копилка не найдена")
        return g

    # ---------------------------------------------------------------- пароль
    PBKDF2_ROUNDS = 200_000

    def has_password(self) -> bool:
        return bool(self.get_setting("pw_hash"))

    def _hash(self, password: str, salt: bytes, rounds: int) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds).hex()

    def check_password(self, password: str) -> bool:
        if not self.has_password():
            return True
        salt = bytes.fromhex(self.get_setting("pw_salt"))
        rounds = int(self.get_setting("pw_rounds", str(self.PBKDF2_ROUNDS)))
        return hmac.compare_digest(self._hash(password, salt, rounds), self.get_setting("pw_hash"))

    def set_password(self, new: str, current: str | None = None):
        if self.has_password() and not self.check_password(current or ""):
            raise ValueError("Текущий пароль неверный")
        if len(new) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")
        salt = os.urandom(16)
        self.set_setting("pw_salt", salt.hex())
        self.set_setting("pw_rounds", self.PBKDF2_ROUNDS)
        self.set_setting("pw_hash", self._hash(new, salt, self.PBKDF2_ROUNDS))

    def remove_password(self, current: str):
        if not self.check_password(current):
            raise ValueError("Пароль неверный")
        with self.db:
            self.db.execute("DELETE FROM settings WHERE key IN ('pw_salt','pw_rounds','pw_hash')")

    # ---------------------------------------------------------------- календарь
    def calendar_events(self, period: str, today: date | None = None) -> dict[str, list[dict]]:
        """События месяца по дням: факт (income/expense), счета к оплате (bill), плановые регулярные (planned)."""
        today = today or date.today()
        a, b = month_bounds(period)
        out: dict[str, list[dict]] = {}

        def put(d, **ev):
            out.setdefault(d, []).append(ev)

        for t in self.transactions(a, b):
            if t["kind"] != "transfer":
                put(t["date"], type=t["kind"], title=t["note"] or t["category"] or exchange_kind(t["kind"]),
                    cents=t["amount_cents"], category=t["category"] or "")
        for bl in self.bills("unpaid"):
            if bl["due_date"] and a <= bl["due_date"] <= b:
                put(bl["due_date"], type="bill", title=f"{bl['service']} за {bl['period']}", cents=bl["amount_cents"],
                    bill_id=bl["id"])
        y, m = map(int, period.split("-"))
        for r in self.db.execute("SELECT * FROM recurring WHERE active=1").fetchall():
            d = date(y, m, min(r["day"], calendar.monthrange(y, m)[1]))
            if d > today and d >= parse_date(r["start_date"]) and not (r["end_date"] and d > parse_date(r["end_date"])):
                put(iso(d), type="planned", title=f"{r['name']} (план)", cents=r["amount_cents"], kind=r["kind"])
        return out

    # ---------------------------------------------------------------- категории
    def categories(self, kind=None, include_archived=False):
        sql, args = "SELECT * FROM categories WHERE 1=1", []
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        if not include_archived:
            sql += " AND archived=0"
        return self.db.execute(sql + " ORDER BY name", args).fetchall()

    def category_id(self, name, kind="expense", create=True):
        r = self.db.execute("SELECT id FROM categories WHERE name=? AND kind=?", (name, kind)).fetchone()
        if r:
            return r["id"]
        if not create:
            return None
        with self.db:
            return self.db.execute("INSERT INTO categories(name,kind) VALUES(?,?)", (name, kind)).lastrowid

    def add_category(self, name, kind):
        return self.category_id(name.strip(), kind)

    def rename_category(self, cat_id, name):
        with self.db:
            self.db.execute("UPDATE categories SET name=? WHERE id=?", (name.strip(), cat_id))

    def archive_category(self, cat_id, archived=True):
        with self.db:
            self.db.execute("UPDATE categories SET archived=? WHERE id=?", (int(archived), cat_id))

    # ---------------------------------------------------------------- операции
    def add_transaction(self, d, kind, amount, account_id, category_id=None, note="", to_account_id=None,
                        recurring_id=None) -> int:
        cents = to_cents(amount)
        if cents <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        if kind == "transfer":
            if not to_account_id or to_account_id == account_id:
                raise ValueError("Для перевода выберите два разных счёта")
            category_id = None
        else:
            to_account_id = None
        with self.db:
            return self.db.execute(
                "INSERT INTO transactions(date,kind,amount_cents,account_id,to_account_id,category_id,note,recurring_id)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (iso(parse_date(d)), kind, cents, account_id, to_account_id, category_id, note.strip(),
                 recurring_id)).lastrowid

    def update_transaction(self, tx_id, d, kind, amount, account_id, category_id=None, note="", to_account_id=None):
        cents = to_cents(amount)
        if cents <= 0:
            raise ValueError("Сумма должна быть больше нуля")
        if kind == "transfer":
            if not to_account_id or to_account_id == account_id:
                raise ValueError("Для перевода выберите два разных счёта")
            category_id = None
        else:
            to_account_id = None
        with self.db:
            self.db.execute("UPDATE transactions SET date=?,kind=?,amount_cents=?,account_id=?,to_account_id=?,"
                            "category_id=?,note=? WHERE id=?",
                            (iso(parse_date(d)), kind, cents, account_id, to_account_id, category_id, note.strip(), tx_id))

    def delete_transaction(self, tx_id):
        with self.db:
            self.db.execute("UPDATE bills SET paid_date=NULL, transaction_id=NULL WHERE transaction_id=?", (tx_id,))
            self.db.execute("DELETE FROM transactions WHERE id=?", (tx_id,))

    def transactions(self, date_from=None, date_to=None, account_id=None, category_id=None, kind=None,
                     text="", limit=None):
        sql = ("SELECT t.*, a.name AS account, b.name AS to_account, c.name AS category FROM transactions t "
               "JOIN accounts a ON a.id=t.account_id LEFT JOIN accounts b ON b.id=t.to_account_id "
               "LEFT JOIN categories c ON c.id=t.category_id WHERE 1=1")
        args: list = []
        for cond, val in (("t.date>=?", date_from), ("t.date<=?", date_to), ("(t.account_id=? OR t.to_account_id=?)",
                          account_id), ("t.category_id=?", category_id), ("t.kind=?", kind)):
            if val not in (None, ""):
                sql += f" AND {cond}"
                args += [val, val] if cond.count("?") == 2 else [val]
        if text:
            sql += " AND (t.note LIKE ? OR c.name LIKE ?)"
            args += [f"%{text}%"] * 2
        sql += " ORDER BY t.date DESC, t.id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.db.execute(sql, args).fetchall()

    # ---------------------------------------------------------------- бюджеты
    def set_budget(self, category_id, limit):
        cents = to_cents(limit) if str(limit).strip() else 0
        with self.db:
            if cents <= 0:
                self.db.execute("DELETE FROM budgets WHERE category_id=?", (category_id,))
            else:
                self.db.execute("INSERT INTO budgets VALUES(?,?) ON CONFLICT(category_id) DO UPDATE SET "
                                "limit_cents=excluded.limit_cents", (category_id, cents))

    def budget_status(self, period: str):
        """[(категория, лимит, потрачено)] за месяц YYYY-MM."""
        a, b = month_bounds(period)
        rows = self.db.execute(
            "SELECT c.id, c.name, bu.limit_cents, COALESCE((SELECT SUM(amount_cents) FROM transactions t "
            "WHERE t.category_id=c.id AND t.kind='expense' AND t.date BETWEEN ? AND ?),0) AS spent "
            "FROM budgets bu JOIN categories c ON c.id=bu.category_id ORDER BY c.name", (a, b)).fetchall()
        return [(r["id"], r["name"], r["limit_cents"], r["spent"]) for r in rows]

    # ---------------------------------------------------------------- отчёты
    def totals(self, date_from, date_to):
        r = self.db.execute(
            "SELECT COALESCE(SUM(CASE WHEN kind='income' THEN amount_cents END),0) AS inc,"
            "COALESCE(SUM(CASE WHEN kind='expense' THEN amount_cents END),0) AS exp "
            "FROM transactions WHERE date BETWEEN ? AND ?", (date_from, date_to)).fetchone()
        return r["inc"], r["exp"]

    def by_category(self, date_from, date_to, kind="expense"):
        return [(r["name"] or "Без категории", r["s"]) for r in self.db.execute(
            "SELECT c.name, SUM(t.amount_cents) AS s FROM transactions t LEFT JOIN categories c ON c.id=t.category_id "
            "WHERE t.kind=? AND t.date BETWEEN ? AND ? GROUP BY c.name ORDER BY s DESC",
            (kind, date_from, date_to)).fetchall()]

    def monthly(self, months=12, end: date | None = None):
        """[(YYYY-MM, доходы, расходы)] за последние `months` месяцев."""
        end = end or date.today()
        out = []
        for i in range(months - 1, -1, -1):
            p = add_months(end.replace(day=1), -i).strftime("%Y-%m")
            inc, exp = self.totals(*month_bounds(p))
            out.append((p, inc, exp))
        return out

    # ---------------------------------------------------------------- регулярные операции
    def add_recurring(self, name, kind, amount, account_id, category_id, day, start, end=None) -> int:
        cents = to_cents(amount)
        if cents <= 0 or not 1 <= int(day) <= 31:
            raise ValueError("Проверьте сумму и день месяца (1-31)")
        with self.db:
            return self.db.execute(
                "INSERT INTO recurring(name,kind,amount_cents,account_id,category_id,day,start_date,end_date) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (name.strip(), kind, cents, account_id, category_id, int(day), iso(parse_date(start)),
                 iso(parse_date(end)) if end else None)).lastrowid

    def recurring(self):
        return self.db.execute("SELECT r.*, a.name AS account, c.name AS category FROM recurring r "
                               "JOIN accounts a ON a.id=r.account_id LEFT JOIN categories c ON c.id=r.category_id "
                               "ORDER BY r.name").fetchall()

    def set_recurring_active(self, rid, active):
        with self.db:
            self.db.execute("UPDATE recurring SET active=? WHERE id=?", (int(active), rid))

    def delete_recurring(self, rid):
        with self.db:
            self.db.execute("DELETE FROM recurring WHERE id=?", (rid,))

    def run_recurring(self, today: date | None = None) -> int:
        """Создаёт пропущенные операции до сегодняшнего дня. Возвращает число созданных."""
        today = today or date.today()
        created = 0
        for r in self.db.execute("SELECT * FROM recurring WHERE active=1").fetchall():
            cur = parse_date(r["start_date"]).replace(day=1)
            if r["last_period"]:
                cur = add_months(parse_date(r["last_period"] + "-01"), 1)
            last = r["last_period"]
            while True:
                d = cur.replace(day=min(r["day"], calendar.monthrange(cur.year, cur.month)[1]))
                if d > today or (r["end_date"] and d > parse_date(r["end_date"])):
                    break
                if d >= parse_date(r["start_date"]):
                    self.add_transaction(d, r["kind"], Decimal(r["amount_cents"]) / 100, r["account_id"],
                                         r["category_id"], r["name"], recurring_id=r["id"])
                    created += 1
                last = cur.strftime("%Y-%m")
                cur = add_months(cur, 1)
            if last != r["last_period"]:
                with self.db:
                    self.db.execute("UPDATE recurring SET last_period=? WHERE id=?", (last, r["id"]))
        return created

    # ---------------------------------------------------------------- коммуналка: услуги
    def services(self, include_archived=False):
        sql = "SELECT * FROM services" + ("" if include_archived else " WHERE archived=0") + " ORDER BY name"
        return self.db.execute(sql).fetchall()

    def add_service(self, name, unit="", metered=True, fixed="0", account_number="") -> int:
        if not name.strip():
            raise ValueError("Укажите название услуги")
        with self.db:
            return self.db.execute("INSERT INTO services(name,unit,metered,fixed_cents,account_number) VALUES(?,?,?,?,?)",
                                   (name.strip(), unit, int(metered), to_cents(fixed or 0), account_number)).lastrowid

    def update_service(self, sid, name, unit, metered, fixed, account_number):
        with self.db:
            self.db.execute("UPDATE services SET name=?,unit=?,metered=?,fixed_cents=?,account_number=? WHERE id=?",
                            (name.strip(), unit, int(metered), to_cents(fixed or 0), account_number, sid))

    def archive_service(self, sid, archived=True):
        with self.db:
            self.db.execute("UPDATE services SET archived=? WHERE id=?", (int(archived), sid))

    # тарифы
    def add_tariff(self, service_id, valid_from, rate, tier_limit=None, tier_rate=None) -> int:
        dec(rate)
        if tier_limit not in (None, ""):
            dec(tier_limit), dec(tier_rate)
        else:
            tier_limit = tier_rate = None
        with self.db:
            return self.db.execute("INSERT INTO tariffs(service_id,valid_from,rate,tier_limit,tier_rate) VALUES(?,?,?,?,?)",
                                   (service_id, iso(parse_date(valid_from)), str(dec(rate)),
                                    None if tier_limit is None else str(dec(tier_limit)),
                                    None if tier_rate is None else str(dec(tier_rate)))).lastrowid

    def tariffs(self, service_id):
        return self.db.execute("SELECT * FROM tariffs WHERE service_id=? ORDER BY valid_from DESC", (service_id,)).fetchall()

    def delete_tariff(self, tid):
        with self.db:
            self.db.execute("DELETE FROM tariffs WHERE id=?", (tid,))

    def tariff_at(self, service_id, on: str):
        return self.db.execute("SELECT * FROM tariffs WHERE service_id=? AND valid_from<=? "
                               "ORDER BY valid_from DESC LIMIT 1", (service_id, on)).fetchone()

    # показания счётчиков
    def add_reading(self, service_id, d, value):
        v = dec(value)
        d = iso(parse_date(d))
        prev = self.db.execute("SELECT value FROM readings WHERE service_id=? AND date<? ORDER BY date DESC LIMIT 1",
                               (service_id, d)).fetchone()
        if prev and v < dec(prev["value"]):
            raise ValueError(f"Показание {v} меньше предыдущего ({prev['value']})")
        with self.db:
            self.db.execute("INSERT INTO readings(service_id,date,value) VALUES(?,?,?) "
                            "ON CONFLICT(service_id,date) DO UPDATE SET value=excluded.value", (service_id, d, str(v)))

    def readings(self, service_id):
        rows = self.db.execute("SELECT * FROM readings WHERE service_id=? ORDER BY date", (service_id,)).fetchall()
        out, prev = [], None
        for r in rows:
            v = dec(r["value"])
            out.append((r["id"], r["date"], v, None if prev is None else v - prev))
            prev = v
        return list(reversed(out))

    def delete_reading(self, rid):
        with self.db:
            self.db.execute("DELETE FROM readings WHERE id=?", (rid,))

    # расчёт
    def calc_amount(self, service_id, consumption: Decimal, on: str) -> int:
        """Сумма к оплате в копейках: потребление × тариф (с порогом) + фиксированная часть."""
        s = self.db.execute("SELECT fixed_cents FROM services WHERE id=?", (service_id,)).fetchone()
        t = self.tariff_at(service_id, on)
        total = Decimal(s["fixed_cents"]) / 100
        if t and consumption:
            rate = dec(t["rate"])
            if t["tier_limit"] is not None and consumption > dec(t["tier_limit"]):
                lim = dec(t["tier_limit"])
                total += lim * rate + (consumption - lim) * dec(t["tier_rate"])
            else:
                total += consumption * rate
        return to_cents(_q(total, "0.01"))

    def consumption_for(self, service_id, period: str):
        """Расход за месяц = последнее показание в месяце − последнее показание до него."""
        a, b = month_bounds(period)
        cur = self.db.execute("SELECT value FROM readings WHERE service_id=? AND date BETWEEN ? AND ? "
                              "ORDER BY date DESC LIMIT 1", (service_id, a, b)).fetchone()
        prev = self.db.execute("SELECT value FROM readings WHERE service_id=? AND date<? ORDER BY date DESC LIMIT 1",
                               (service_id, a)).fetchone()
        if not cur or not prev:
            return None
        return dec(cur["value"]) - dec(prev["value"])

    # счета на оплату
    def create_bill(self, service_id, period, amount=None, due_date=None, consumption=None, note="") -> int:
        """Без amount сумма считается по показаниям и тарифу."""
        period = period.strip()
        month_bounds(period)  # валидация формата
        cons = None if consumption in (None, "") else dec(consumption)
        s = self.db.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
        if amount in (None, ""):
            if s["metered"] and cons is None:
                cons = self.consumption_for(service_id, period)
                if cons is None:
                    raise ValueError("Нет показаний за период и предыдущего показания — введите сумму вручную")
            cents = self.calc_amount(service_id, cons or Decimal(0), month_bounds(period)[1])
        else:
            cents = to_cents(amount)
        if cents <= 0:
            raise ValueError("Сумма должна быть больше нуля (проверьте тариф)")
        with self.db:
            return self.db.execute(
                "INSERT INTO bills(service_id,period,consumption,amount_cents,due_date,note) VALUES(?,?,?,?,?,?)",
                (service_id, period, None if cons is None else str(cons), cents,
                 iso(parse_date(due_date)) if due_date else None, note)).lastrowid

    def update_bill(self, bill_id, amount, due_date, note=""):
        with self.db:
            self.db.execute("UPDATE bills SET amount_cents=?,due_date=?,note=? WHERE id=?",
                            (to_cents(amount), iso(parse_date(due_date)) if due_date else None, note, bill_id))

    def bills(self, status=None, period=None, service_id=None):
        sql = ("SELECT b.*, s.name AS service, s.unit AS unit FROM bills b JOIN services s ON s.id=b.service_id WHERE 1=1")
        args: list = []
        if status == "paid":
            sql += " AND b.paid_date IS NOT NULL"
        elif status == "unpaid":
            sql += " AND b.paid_date IS NULL"
        if period:
            sql += " AND b.period=?"
            args.append(period)
        if service_id:
            sql += " AND b.service_id=?"
            args.append(service_id)
        return self.db.execute(sql + " ORDER BY b.period DESC, s.name", args).fetchall()

    def pay_bill(self, bill_id, account_id, paid_date=None) -> int:
        b = self.db.execute("SELECT b.*, s.name AS service FROM bills b JOIN services s ON s.id=b.service_id WHERE b.id=?",
                            (bill_id,)).fetchone()
        if b["paid_date"]:
            raise ValueError("Счёт уже оплачен")
        d = iso(parse_date(paid_date or date.today()))
        cat = self.category_id(UTILITY_CATEGORY)
        tx = self.add_transaction(d, "expense", Decimal(b["amount_cents"]) / 100, account_id, cat,
                                  f"{b['service']} за {b['period']}")
        with self.db:
            self.db.execute("UPDATE bills SET paid_date=?, transaction_id=? WHERE id=?", (d, tx, bill_id))
        return tx

    def unpay_bill(self, bill_id):
        b = self.db.execute("SELECT transaction_id FROM bills WHERE id=?", (bill_id,)).fetchone()
        if b and b["transaction_id"]:
            self.delete_transaction(b["transaction_id"])
        with self.db:
            self.db.execute("UPDATE bills SET paid_date=NULL, transaction_id=NULL WHERE id=?", (bill_id,))

    def delete_bill(self, bill_id):
        with self.db:
            self.db.execute("DELETE FROM bills WHERE id=?", (bill_id,))

    def reminders(self, today: date | None = None, days_ahead=5):
        """Неоплаченные счета: просроченные и подходящие по сроку. [(bill, дней до срока)]."""
        today = today or date.today()
        out = []
        for b in self.bills("unpaid"):
            if not b["due_date"]:
                continue
            left = (parse_date(b["due_date"]) - today).days
            if left <= days_ahead:
                out.append((b, left))
        return sorted(out, key=lambda x: x[1])

    def utility_stats(self, service_id=None, months=12, end: date | None = None):
        """[(YYYY-MM, сумма в копейках)] по оплаченным и неоплаченным счетам."""
        end = end or date.today()
        out = []
        for i in range(months - 1, -1, -1):
            p = add_months(end.replace(day=1), -i).strftime("%Y-%m")
            sql, args = "SELECT COALESCE(SUM(amount_cents),0) FROM bills WHERE period=?", [p]
            if service_id:
                sql += " AND service_id=?"
                args.append(service_id)
            out.append((p, self.db.execute(sql, args).fetchone()[0]))
        return out

    def prev_due_day(self, service_id) -> int | None:
        r = self.db.execute("SELECT due_date FROM bills WHERE service_id=? AND due_date IS NOT NULL "
                            "ORDER BY period DESC LIMIT 1", (service_id,)).fetchone()
        return parse_date(r["due_date"]).day if r else None

    def next_period_due(self, service_id, period) -> str | None:
        """Подсказка срока оплаты: тот же день месяца, что в прошлом счёте, в следующем за периодом месяце."""
        day = self.prev_due_day(service_id)
        if not day:
            return None
        y, m = map(int, period.split("-"))
        nxt = add_months(date(y, m, 1), 1)
        return iso(nxt.replace(day=min(day, calendar.monthrange(nxt.year, nxt.month)[1])))


def last_n_days(n: int) -> tuple[str, str]:
    today = date.today()
    return iso(today - timedelta(days=n)), iso(today)
