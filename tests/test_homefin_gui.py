import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from homefin.core import Finance  # noqa: E402
from homefin.gui import MainWindow  # noqa: E402


def test_window_smoke(tmp_path):
    app = QApplication.instance() or QApplication([])
    fin = Finance(":memory:")
    acc = fin.accounts()[0]["id"]
    fin.add_transaction("01.10.2026", "income", "500", acc, fin.category_id("Зарплата", "income"))
    sid = next(s["id"] for s in fin.services() if s["name"] == "Газ")
    fin.create_bill(sid, "2026-09", amount="10", due_date="2026-10-01")
    fin.set_budget(fin.category_id("Продукты"), "100")
    win = MainWindow(fin, backup_dir=str(tmp_path))
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        win.pages[i][0].refresh()
    assert win.pages[2][0].table.rowCount() == 1
    assert win.pages[1][0].table.rowCount() == 1
    win.close()
    assert list(tmp_path.glob("homefin_*.db"))
