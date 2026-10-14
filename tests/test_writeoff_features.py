import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import pytest
from smetagaz import stock_domain as sd, audit_domain as ad
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def material(db):
    return db.fetchone('SELECT id FROM stock_materials ORDER BY id LIMIT 1')[0]


def defect(db, number='ДА-1'):
    data = dict(number=number, act_date='2026-02-01', object_name='Здание', organization='ООО', approved_by='', commission='', reason='', conditions='', notes='')
    return sd.save_defect(db, data, [dict(defect='течь', work='замена', unit='м', quantity='2')])


def test_copy_and_delete_defect_and_acts(db):
    mid = material(db)
    sd.receive(db, mid, '10', '2026-01-01')
    did = defect(db)
    new = sd.copy_defect(db, did)
    assert new != did and db.fetchone('SELECT organization FROM defect_acts WHERE id=?', (new,))[0] == 'ООО'
    assert db.fetchone('SELECT count(*) FROM defect_lines WHERE act_id=?', (new,))[0] == 1
    sd.delete_defect(db, new)
    assert db.fetchone('SELECT count(*) FROM defect_acts')[0] == 1
    aid = sd.save_act(db, dict(number='СП-1', act_date='2026-02-02', object_name='Здание'), [dict(material_id=mid, norm_qty=None, actual_qty=2000000)])
    sd.post_act(db, aid)
    assert sd.balance(db, mid) == 8000000
    sd.delete_act(db, aid)                                               # проведённый акт удаляется, материал возвращается на остаток
    assert sd.balance(db, mid) == 10000000 and db.fetchone('SELECT count(*) FROM stock_acts')[0] == 0
    # дефектный акт с действующим списанием удалить нельзя
    sd.receive(db, mid, '1', '2026-01-02')
    did2 = defect(db, 'ДА-9')
    stock = sd.from_defect(db, did2)
    with pytest.raises(ValueError):
        sd.delete_defect(db, did2)
    sd.delete_act(db, stock)
    sd.delete_defect(db, did2)                                           # после удаления списания — можно


def test_material_delete_archive_and_history(db):
    mid = material(db)
    sd.receive(db, mid, '10', '2026-01-01', 'накладная 1')
    aid = sd.save_act(db, dict(number='СП-2', act_date='2026-02-02', object_name='Здание'), [dict(material_id=mid, norm_qty=None, actual_qty=3000000)])
    sd.post_act(db, aid)
    history = sd.material_history(db, mid)
    assert [(h['kind'], h['balance']) for h in history] == [('Поступление', 10000000), ('Списание', 7000000)] and history[1]['act'] == 'СП-2'
    with pytest.raises(ValueError):
        sd.delete_material(db, mid)                                       # есть в актах
    assert sd.delete_material(db, mid, True) == 'archived'
    assert db.fetchone('SELECT active FROM stock_materials WHERE id=?', (mid,))[0] == 0
    free = db.execute("INSERT INTO stock_materials(name,category,unit) VALUES('Тест','Прочее','шт')").lastrowid
    sd.receive(db, free, '5', '2026-01-01')
    assert sd.delete_material(db, free) == 'deleted' and not db.fetchone('SELECT 1 FROM stock_moves WHERE material_id=?', (free,))
    deleted = next(e for e in ad.entries(db, action='D') if e['table'] == 'stock_materials')      # материал можно вернуть из «Журнала и корзины»
    assert ad.restore(db, deleted['id']) >= 1 and db.fetchone('SELECT name FROM stock_materials WHERE id=?', (free,))[0] == 'Тест'


def test_objects_and_defaults(db):
    own = sd.save_object(db, 'Моё здание', address='ул. Садовая 1', commission='Петров')
    linked_contract = db.execute("INSERT INTO contracts(contract_number,object_name) VALUES('01-02/26','Дом')").lastrowid
    linked = sd.save_object(db, 'Дом на Мира', owner_type='contracts', owner_id=linked_contract)
    with pytest.raises(ValueError):
        sd.save_object(db, 'Моё здание')                                  # название уникально
    sd.set_defaults(db, dict(organization='ООО Газ', approved_by='Директор Иванов', commission='Сидоров, Орлов'))
    assert sd.object_defaults(db)['approved_by'] == 'Директор Иванов'
    assert sd.object_defaults(db, own)['commission'] == 'Петров' and sd.object_defaults(db, own)['organization'] == 'ООО Газ'   # поле объекта заменяет общее
    assert [r[1] for r in sd.objects(db)] == ['Дом на Мира', 'Моё здание']


def test_ui_new_documents_use_defaults_and_registries(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: print('WARN', a[2:]))
    import smetagaz.stock_view as sv
    own = sd.save_object(db, 'Моё здание', commission='Петров')
    sd.set_defaults(db, dict(organization='ООО Газ', approved_by='Директор Иванов', commission='Сидоров'))
    dlg = sv.DefectDialog()
    assert dlg.header.inputs['organization'].text() == 'ООО Газ' and dlg.header.inputs['approved_by'].text() == 'Директор Иванов'
    dlg.header.listed.setCurrentIndex(dlg.header.listed.findData(own))        # выбор объекта подставляет его реквизиты
    assert dlg.header.object_name.text() == 'Моё здание' and dlg.header.inputs['commission'].text() == 'Петров'
    mid = material(db)
    sd.receive(db, mid, '10', '2026-01-01')
    did = defect(db)
    reg = sv.Registry('defects'); reg.load_data(); reg.table.selectRow(0)
    reg.copy_defect.__func__  # метод существует
    sd_before = db.fetchone('SELECT count(*) FROM defect_acts')[0]
    monkeypatch.setattr(sv.DefectDialog, 'exec', lambda self: 0)
    reg.copy_defect()
    assert db.fetchone('SELECT count(*) FROM defect_acts')[0] == sd_before + 1
    mats = sv.Registry('materials'); mats.load_data()
    mats.table.selectRow(next(r for r in range(mats.table.rowCount()) if mats.table.item(r, 0).data(sv.Qt.ItemDataRole.UserRole) == mid))
    hist = []
    monkeypatch.setattr(sv.MaterialHistoryDialog, 'exec', lambda self: hist.append(self.table.rowCount()) or 0)
    mats.history()
    assert hist == [1]
    objects = sv.ObjectsView()
    assert objects.table.rowCount() == 1 and objects.defaults['organization'].text() == 'ООО Газ'
