"""Позиция из справочника добавляется в смету без количества по умолчанию: поле пустое, вводят сами (пусто = 0)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QTableWidget, QWidget

from smetagaz.database import DatabaseManager


@pytest.fixture
def editor_env(tmp_path, monkeypatch):
    import sys
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    from smetagaz import estimate_editor as ee, estimates_domain as ed
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', d, raising=False)
    app = QApplication.instance() or QApplication([])

    class Fake(QWidget):
        estimate_id = ed.create_estimate(d, 'Смета')
        table = QTableWidget(0, 3)

        def section_of_row(self, row):
            return None
    yield ee, Fake()
    del app
    d.close()


def ask(ee, fake, typed, monkeypatch):
    seen = {}

    def fake_exec(dialog):
        edit = dialog.findChild(QLineEdit)
        seen['initial'] = edit.text()
        seen['placeholder'] = edit.placeholderText()
        edit.setText(typed)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(QDialog, 'exec', fake_exec)
    return ee.EstimateEditorDialog.ask_quantity(fake, 'Количество', 'Укажите объем (м):'), seen


def test_quantity_field_is_empty_by_default(editor_env, monkeypatch):
    ee, fake = editor_env
    (qty, section, ok), seen = ask(ee, fake, '', monkeypatch)
    assert seen['initial'] == '' and 'количество' in seen['placeholder'] and ok and qty == 0.0 and section is None            # ничего не подставлено, пусто = 0
    assert ask(ee, fake, '12,5', monkeypatch)[0][0] == 12.5
    assert ask(ee, fake, '3.250', monkeypatch)[0][0] == 3.25
    assert ask(ee, fake, '.', monkeypatch)[0][0] == 0.0
