import pytest
from datetime import date
from smetagaz import weld_register_view, welding_view, docs_register_domain as dr  # noqa: F401  (до подмены базы в тестах)
from smetagaz.database import DatabaseManager
from smetagaz import weld_register_domain as wr


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'w.db')
    d.init_db()
    yield d
    d.close()


def welder(db, name):
    return db.execute('INSERT INTO welders(name) VALUES(?)', (name,)).lastrowid


def test_add_month():
    assert wr.add_month(date(2026, 1, 31)) == date(2026, 2, 28) and wr.add_month(date(2026, 12, 15)) == date(2027, 1, 15)


def test_items_numbers_states_and_renew(db):
    a, b = welder(db, 'Иванов'), welder(db, 'Петров')
    z = wr.save_item(db, dict(kind=wr.ZAYAVKA, number='12', doc_date='2026-10-01', counterparty='Лаборатория', subject='Заявка на испытания'))
    l = wr.save_item(db, dict(kind=wr.LETTER, number='13', doc_date='2026-10-02', counterparty='Лаборатория', subject='Письмо о сроках', status='Отправлено'))
    with pytest.raises(ValueError, match='до какого'):
        wr.save_item(db, dict(kind=wr.PROTOCOL, number='П-1', doc_date='2026-10-05'))
    with pytest.raises(ValueError, match='раньше'):
        wr.save_item(db, dict(kind=wr.PROTOCOL, number='П-1', doc_date='2026-10-05', valid_to='2026-10-01'))
    with pytest.raises(ValueError, match='Статус'):
        wr.save_item(db, dict(kind=wr.ZAYAVKA, number='14', doc_date='2026-10-05', subject='x', status='Действует'))
    p = wr.save_item(db, dict(kind=wr.PROTOCOL, number='П-1', doc_date='2026-10-05', valid_to='2026-11-05', counterparty='Лаборатория', subject='Протокол МИ'), [a, b])
    with pytest.raises(ValueError, match='уже зарегистрирован'):
        wr.save_item(db, dict(kind=wr.PROTOCOL, number='П-1', doc_date='2026-10-20', valid_to='2026-11-20'))
    assert wr.get_item(db, p)['welders'] and len(wr.get_item(db, p)['welders']) == 2
    today = date(2026, 10, 30)
    assert wr.state(wr.PROTOCOL, 'Действует', '2026-11-05', today) == 'soon' and wr.state(wr.PROTOCOL, 'Действует', '2026-10-01', today) == 'expired'
    assert wr.state(wr.ZAYAVKA, 'Подана', '2020-01-01', today) == '' and wr.state(wr.PROTOCOL, 'Заменён', '2020-01-01', today) == ''
    assert wr.summary(db, today) == (1, 1, 0)
    assert [r[0] for r in wr.welder_protocols(db, a, today)] == [p] and wr.welder_protocols(db, a, date(2026, 12, 1)) == []
    # оформить протокол заново: на месяц от новой даты, прежний заменён
    new = wr.renew_protocol(db, p, date(2026, 11, 3))
    n = wr.get_item(db, new)
    assert n['valid_to'] == '2026-12-03' and n['status'] == 'Действует' and sorted(n['welders']) == sorted([a, b]) and n['renews_id'] == p and n['number'] == ''
    assert wr.get_item(db, p)['status'] == 'Заменён'
    with pytest.raises(ValueError):
        wr.renew_protocol(db, z)
    assert wr.listing(db, kind=wr.PROTOCOL, active_only=True, today=date(2026, 11, 10))[0] == 1
    assert wr.listing(db, search='иванов')[0] == 2 and wr.listing(db, kind=wr.ZAYAVKA)[0] == 1 and wr.listing(db)[0] == 4
    ev = wr.agenda_events(db, date(2026, 12, 1), date(2026, 12, 31), date(2026, 11, 10))
    assert len(ev) == 1 and ev[0][1] == 'permit'
    from smetagaz import agenda_domain
    assert any('протокол' in e['title'].lower() for e in agenda_domain.events_between(db, date(2026, 12, 1), date(2026, 12, 31), date(2026, 11, 10)))
    wr.delete_item(db, z)
    assert wr.get_item(db, z) is None


def test_move_from_outgoing(db):
    out1 = dr.save_doc(db, dict(register='out', reg_number='Исх-5', reg_date='2026-10-01', correspondent='Лаборатория', subject='Заявка на механические испытания', file_path='/tmp/z.pdf'))
    out2 = dr.save_doc(db, dict(register='out', reg_number='Исх-6', reg_date='2026-10-02', correspondent='Лаборатория', subject='Протокол испытаний', due_date='2026-11-02'))
    out3 = dr.save_doc(db, dict(register='out', reg_number='Исх-7', reg_date='2026-10-03', correspondent='Горгаз', subject='Письмо не про сварщиков'))
    assert wr.move_from_outgoing(db, [out1], wr.ZAYAVKA) == 1
    assert wr.move_from_outgoing(db, [out2], wr.PROTOCOL, remove=False) == 1
    assert dr.get_doc(db, out1) is None and dr.get_doc(db, out2) is not None and dr.get_doc(db, out3) is not None
    z = wr.listing(db, kind=wr.ZAYAVKA)[1][0]
    assert z['number'] == 'Исх-5' and z['file_path'] == '/tmp/z.pdf'
    p = wr.listing(db, kind=wr.PROTOCOL)[1][0]
    assert p['valid_to'] == '2026-11-02' and p['status'] == 'Действует'


def test_welders_view_has_register_tab(db, monkeypatch):
    import sys
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', db, raising=False)
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: 0)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: 0)
    v = welding_view.WeldersView()
    names = [v.tabs.tabText(i) for i in range(v.tabs.count())]
    assert 'Заявки, письма, протоколы' in names
    tab = v.tabs.widget(names.index('Заявки, письма, протоколы'))
    a = welder(db, 'Иванов')
    for kind in wr.KINDS:
        d = weld_register_view.WeldItemDialog(kind)
        d.number.setText('1')
        d.subject.setPlainText('Тест')
        d.save()
        assert d.rid
        weld_register_view.WeldItemDialog(None, d.rid)
    tab.load_data()
    assert tab.table.rowCount() == 3 and 'Действующих протоколов: 1' in tab.summary.text()
    m = weld_register_view.MoveFromOutgoingDialog()
    m.load()
