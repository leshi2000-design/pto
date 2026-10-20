import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from homefin.core import Finance  # noqa: E402
from homefin.gui import MainWindow  # noqa: E402
from homefin.theme import apply  # noqa: E402


def test_window_smoke(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply(app)
    fin = Finance(":memory:")
    acc = fin.accounts()[0]["id"]
    fin.add_transaction("01.10.2026", "income", "500", acc, fin.category_id("Зарплата", "income"))
    sid = next(s["id"] for s in fin.services() if s["name"] == "Газ")
    fin.create_bill(sid, "2026-09", amount="10", due_date="2026-10-01")
    fin.set_budget(fin.category_id("Продукты"), "100")
    win = MainWindow(fin, backup_dir=str(tmp_path))
    for i in range(len(win.pages)):
        win.go(i)
    page = {title: p for p, title in win.pages}
    assert page["Коммунальные платежи"].table.rowCount() == 1
    assert page["Операции"].table.rowCount() == 1
    win.close()
    assert list(tmp_path.glob("homefin_*.db"))


def test_calendar_goals_and_lock(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply(app)
    fin = Finance(":memory:")
    acc = fin.accounts()[0]["id"]
    today = __import__("datetime").date.today()
    fin.add_transaction(today, "income", "100", acc, None, "Аванс")
    goal = fin.add_goal("Отпуск", "500")
    fin.deposit_to_goal(goal, acc, "50")
    win = MainWindow(fin, backup_dir=str(tmp_path))
    page = {title: p for p, title in win.pages}
    win.go([t for _, t in win.pages].index("Календарь"))
    cal = page["Календарь"]
    from PyQt6.QtCore import QDate
    cal.cal.setSelectedDate(QDate(today.year, today.month, today.day))
    cal.refresh()
    assert cal.cal.marks[today.isoformat()] == {"income"} and cal.table.rowCount() == 1
    win.go([t for _, t in win.pages].index("Копилка"))
    assert page["Копилка"].table.rowCount() == 1
    fin.set_password("1234")
    win.refresh_all()
    assert not win.lock_btn.isHidden()
    from homefin.gui_extra import LockDialog
    dlg = LockDialog(fin)
    dlg.field.setText("не тот")
    dlg.try_login()
    assert dlg.result() != 1 and "Неверный" in dlg.error.text()
    dlg.field.setText("1234")
    dlg.try_login()
    assert dlg.result() == 1
    win.close()
