import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import pytest
from smetagaz import gsvm_statuses as gs
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_own_editable_statuses(db):
    work = [n for _i, n, _c in gs.catalog(db, 'work')]
    assert 'Монтаж' in work and 'Договор подписан' in [n for _i, n, _c in gs.catalog(db, 'client')]
    # независимы от проектов ГСВ
    assert db.fetchone('SELECT count(*) FROM gsv_status_catalog')[0] > 0 and db.fetchone('SELECT count(*) FROM gsvm_status_catalog')[0] == 10
    sid = gs.save_status(db, 'work', 'Ожидание материалов', '#7C3AED')
    cid = db.execute("INSERT INTO contracts(contract_number,client_name) VALUES('01-02/26','Иванов')").lastrowid
    gs.set_contract_statuses(db, cid, [sid, gs.catalog(db, 'client')[0][0]])
    assert 'Ожидание материалов' in db.fetchone('SELECT statuses_text FROM contracts WHERE id=?', (cid,))[0]
    gs.save_status(db, 'work', 'Ждём материалы', '#7C3AED', sid)               # переименование обновляет текст у договоров
    assert 'Ждём материалы' in db.fetchone('SELECT statuses_text FROM contracts WHERE id=?', (cid,))[0]
    with pytest.raises(ValueError):
        gs.delete_status(db, sid)                                               # используется
    with pytest.raises(ValueError):
        gs.save_status(db, 'work', 'Ждём материалы', '#000000')                 # дубликат
    gs.set_contract_statuses(db, cid, [])
    gs.delete_status(db, sid)
    order = [r[0] for r in gs.catalog(db, 'work')]
    gs.move_status(db, 'work', order[1], -1)
    assert [r[0] for r in gs.catalog(db, 'work')][0] == order[1]


def test_card_registry_statuses_and_id_transfer(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: print('WARN', a[2:]))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.No)
    import smetagaz.contract_card as cc
    import smetagaz.contracts_registry as cr
    card = cc.ContractCardDialog()
    card.client_form.name.setText('Иванов Иван')
    card.inp_object_address.setText('г. Минск, ул. Мира 5')
    card.inp_amount.setValue(1500)
    first = [s for s in card.status_picker.lists['client'].findItems('Договор подписан', __import__('PyQt6.QtCore', fromlist=['Qt']).Qt.MatchFlag.MatchExactly)][0]
    first.setCheckState(__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.CheckState.Checked)
    card.id_transfer.done.setChecked(True)                       # дата подставляется сегодняшняя
    assert card.id_transfer.day.value()
    card.id_transfer.recipient.setCurrentIndex(card.id_transfer.recipient.findData('Напрямую в ГорГАЗ'))
    assert card.save_data()
    row = db.fetchone('SELECT id_transferred,id_recipient,id_transfer_date,statuses_text FROM contracts')
    assert row[0] == 1 and row[1] == 'Напрямую в ГорГАЗ' and row[2] and 'Договор подписан' in row[3]
    reopened = cc.ContractCardDialog(contract_id=db.fetchone('SELECT id FROM contracts')[0])
    assert reopened.id_transfer.done.isChecked() and reopened.id_transfer.recipient.currentData() == 'Напрямую в ГорГАЗ'
    assert any(reopened.status_picker.ids())
    view = cr.ContractsRegistryView()
    view.load_data()
    headers = [view.table.horizontalHeaderItem(c).text() for c in range(view.table.columnCount())]
    assert headers == ['№ договора', 'Дата заключения', 'Объект / Адрес', 'Клиент', 'Стоимость, BYN', 'Статусы', 'Примечание'] and not view.table.verticalHeader().isVisible()
    assert view.table.item(0, 3).text() == 'Иванов Иван' and 'Договор подписан' in view.table.item(0, 5).text()
