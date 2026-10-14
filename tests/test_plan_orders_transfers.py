import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from datetime import date, timedelta
import pytest
from smetagaz import stock_registers as reg, agenda_domain, audit_domain as ad
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


@pytest.fixture
def ui(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: print('WARN', a[2:]))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    return db


def test_planned_work_shows_in_calendar_and_can_be_marked_done(ui):
    db = ui
    import smetagaz.welding_view as wv
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    dlg = wv.JobDialog(planned=True)
    assert dlg.status.currentData() == 'planned' and dlg.work_date.value() >= tomorrow          # новое планирование — на будущую дату
    dlg.work_date.set_value((date.today() + timedelta(days=3)).isoformat())
    dlg.title.setText('Сварка ввода'); dlg.object_text.setText('г. Минск, ул. Мира 5'); dlg.work_time.setText('9:30')
    dlg.save()
    job = db.fetchone('SELECT id,status,work_time FROM welding_jobs')
    assert job[1] == 'planned' and job[2] == '9:30'
    day = date.today() + timedelta(days=3)
    events = [e for e in agenda_domain.events_between(db, day, day) if e['ref'] == ('welding_jobs', job[0])]
    assert events and events[0]['kind'] == 'weld_plan' and events[0]['title'].startswith('План:') and events[0]['time'] == '9:30' and 'ул. Мира 5' in events[0]['detail']
    # уже сделанная работа записывается как выполненная, неверное время отклоняется
    bad = wv.JobDialog(); bad.title.setText('Х'); bad.object_text.setText('Y'); bad.work_time.setText('25:99'); bad.save()
    assert db.fetchone('SELECT count(*) FROM welding_jobs')[0] == 1
    done = wv.JobDialog(); done.title.setText('Сварка стыка'); done.object_text.setText('ул. Ленина 1'); done.save()
    assert db.fetchone("SELECT status FROM welding_jobs WHERE title='Сварка стыка'")[0] == 'done'
    # реестр: фильтр и отметка выполненным
    view = wv.ScheduleView()
    assert view.table.rowCount() == 2
    view.status_filter.setCurrentIndex(view.status_filter.findData('planned'))
    assert view.table.rowCount() == 1 and view.table.item(0, 2).text() == 'Запланировано'
    view.table.selectRow(0); view.mark_done()
    assert db.fetchone("SELECT status FROM welding_jobs WHERE id=?", (job[0],))[0] == 'done'
    after = [e for e in agenda_domain.events_between(db, day, day) if e['ref'] == ('welding_jobs', job[0])]
    assert after[0]['kind'] == 'work'


def test_missed_plan_is_highlighted(db):
    jid = db.execute("INSERT INTO welding_jobs(title,object_text,status) VALUES('Сварка','Адрес','planned')").lastrowid
    past = date.today() - timedelta(days=2)
    db.execute('INSERT INTO welding_days(job_id,work_date) VALUES(?,?)', (jid, past.isoformat()))
    event = [e for e in agenda_domain.events_between(db, past, past) if e['ref'] == ('welding_jobs', jid)][0]
    assert event['color'] == '#DC2626' and 'не отмечено выполненным' in event['detail']


def test_orders_registry(db):
    oid = reg.save_order(db, dict(number='1/26', order_date='2026-03-01', title='О комиссии по списанию', content='Создать комиссию', issued_by='Директор'))
    assert reg.next_order_number(db, '2026-05-01') == '2/26'
    with pytest.raises(ValueError):
        reg.save_order(db, dict(number='1/26', order_date='2026-04-01', title='Дубль'))              # номер уникален в пределах года
    reg.save_order(db, dict(number='1/27', order_date='2027-01-10', title='Другой год'))
    with pytest.raises(ValueError):
        reg.save_order(db, dict(number='2/26', order_date='2026-03-01', title='X', valid_until='2026-01-01'))
    with pytest.raises(ValueError):
        reg.save_order(db, dict(number='', order_date='2026-03-01', title='X'))
    reg.save_order(db, dict(number='1/26', order_date='2026-03-01', title='Новое название', issued_by='Директор'), oid)
    assert db.fetchone('SELECT title FROM stock_orders WHERE id=?', (oid,))[0] == 'Новое название'
    reg.delete_order(db, oid)
    deleted = next(e for e in ad.entries(db, action='D') if e['table'] == 'stock_orders')
    ad.restore(db, deleted['id'])                                                                     # приказ можно вернуть из корзины
    assert db.fetchone('SELECT title FROM stock_orders WHERE id=?', (oid,))[0] == 'Новое название'


def test_transfer_acts(db):
    mid = db.fetchone('SELECT id FROM stock_materials ORDER BY id LIMIT 1')[0]
    before = db.fetchone('SELECT coalesce(sum(qty),0) FROM stock_moves')[0]
    data = dict(number='АП-1', transfer_date='2026-03-02', from_place='Склад', to_place='Объект Мира 5', reason='Приказ 1/26', approved_by='Директор')
    tid = reg.save_transfer(db, data, [dict(material_id=mid, material_name='Ацетилен', unit='м³', quantity='2,5'), dict(material_id=None, material_name='Свой материал', unit='шт', quantity='4')])
    assert [(l[1], l[3]) for l in reg.transfer_lines(db, tid)] == [('Ацетилен', '2.5'), ('Свой материал', '4')]
    assert db.fetchone('SELECT coalesce(sum(qty),0) FROM stock_moves')[0] == before                  # остатки не меняются
    for bad in (dict(data, to_place='склад'), dict(data, from_place=''), dict(data, number='')):
        with pytest.raises(ValueError):
            reg.save_transfer(db, bad, [dict(material_name='М', quantity='1')])
    with pytest.raises(ValueError):
        reg.save_transfer(db, dict(data, number='АП-2'), [dict(material_name='М', quantity='0')])
    with pytest.raises(ValueError):
        reg.save_transfer(db, dict(data, number='АП-2'), [])
    with pytest.raises(ValueError):
        reg.save_transfer(db, data, [dict(material_name='М', quantity='1')])                         # номер занят
    copy = reg.copy_transfer(db, tid)
    assert copy != tid and len(reg.transfer_lines(db, copy)) == 2 and db.fetchone('SELECT transfer_date FROM stock_transfers WHERE id=?', (copy,))[0] == date.today().isoformat()
    reg.delete_transfer(db, copy)
    assert db.fetchone('SELECT count(*) FROM stock_transfer_lines')[0] == 2


def test_register_views(ui):
    db = ui
    import smetagaz.stock_view as sv
    from smetagaz.date_widgets import install_display_patch
    install_display_patch()                      # в программе включается при оформлении окна
    reg.save_order(db, dict(number='5/26', order_date='2026-03-01', title='О материалах'))
    tid = reg.save_transfer(db, dict(number='АП-5', transfer_date='2026-03-02', from_place='Склад', to_place='Объект'), [dict(material_name='Труба', unit='м', quantity='3')])
    orders = sv.RegisterView('orders')
    assert orders.table.rowCount() == 1 and orders.table.item(0, 1).text() == '5/26' and orders.table.item(0, 0).text() == '01.03.2026'
    transfers = sv.RegisterView('transfers')
    assert transfers.table.rowCount() == 1 and 'Труба — 3 м' in transfers.table.item(0, 4).text()
    transfers.search.setText('труба'); assert transfers.table.rowCount() == 1
    transfers.search.setText('нет такого'); assert transfers.table.rowCount() == 0
    transfers.search.clear(); transfers.table.selectRow(0); transfers.delete()
    assert transfers.table.rowCount() == 0
    module = sv.WriteoffView()
    titles = [module.tabs.tabText(i) for i in range(module.tabs.count())]
    assert 'Приказы' in titles and 'Акты перевода материалов' in titles
    dlg = sv.TransferDialog()
    assert dlg.number.text().startswith('АП-') and dlg.lines.rowCount() == 1
