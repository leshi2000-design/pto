from datetime import date
import pytest
from smetagaz import board_domain as bd, contracts_core as cc
from smetagaz.database import DatabaseManager


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_parse_quick():
    today = date(2026, 10, 8)   # четверг
    assert bd.parse_quick('Сдать акт Иванова завтра #акт', today) == ('Сдать акт Иванова', '2026-10-09', ['акт'], 'Обычная')
    assert bd.parse_quick('позвонить в пятницу !', today)[1:] == ('2026-10-09', [], 'Высокая')
    assert bd.parse_quick('Сдать ведомость до 10-го !!', today) == ('Сдать ведомость', '2026-10-10', [], 'Критическая')
    assert bd.parse_quick('отчёт через 3 дня #налоги #срочное_дело', today)[1:3] == ('2026-10-11', ['налоги', 'срочное дело'])
    assert bd.parse_quick('оплатить 15.10', today)[:2] == ('оплатить', '2026-10-15')
    assert bd.parse_quick('просто задача', today) == ('просто задача', '', [], 'Обычная')
    assert bd.parse_quick('1.10 акт', today)[1] == '2027-10-01'


def test_quick_add_link_and_suggestions(db):
    t = bd.add_quick(db, 'Позвонить клиенту завтра #звонок')
    row = db.fetchone('SELECT status,due_date,tags FROM kanban_tasks WHERE id=?', (t['id'],))
    assert row[0] == 'todo' and row[2] == 'звонок'
    lid = cc.save_legal(db, dict(name='ООО Ромашка'))
    cid = cc.save_contract(db, 'le', dict(client_id=lid, direction='Монтажные работы', contract_date='2026-09-01', amount=10))
    cc.save_act(db, 'le', dict(contract_id=cid, act_date='2026-09-20', amount=10))
    assert bd.link_label(db, 'le_contracts', cid).startswith('Юрлица · 01-04/26')
    title, due = bd.default_task_for(db, 'le_contracts', cid, date(2026, 10, 8))
    assert title.startswith('Сдать акт по договору') and due == '2026-10-10'
    sug = bd.suggestions(db, date(2026, 10, 8))
    keys = {s['key'] for s in sug}
    assert f'sign_contract:le_contracts:{cid}' in keys and any(k.startswith('sign_act:le_acts') for k in keys)
    first = sug[0]
    bd.create_from_suggestion(db, first)
    bd.dismiss(db, sug[1]['key'])
    left = {s['key'] for s in bd.suggestions(db, date(2026, 10, 8))}
    assert first['key'] not in left and sug[1]['key'] not in left
    s = bd.summary(db, date(2026, 10, 8))
    assert s['acts'] == 1 and '1 акт к подписанию' in s['text']
    with pytest.raises(ValueError):
        bd.add_task(db, 'x', link=('bad', 1))


def test_cache_invalidates_on_change(db):
    from smetagaz import cache_domain
    calls = []
    compute = lambda: calls.append(1) or {'v': len(calls)}
    first = cache_domain.cached(db, 'k', compute)
    assert cache_domain.cached(db, 'k', compute) == first and len(calls) == 1
    first['v'] = 99                                   # изменение копии не портит кэш
    assert cache_domain.cached(db, 'k', compute) == {'v': 1}
    db.execute("INSERT INTO notes(title,body,note_date) VALUES('x','y','2026-10-01')")
    assert cache_domain.cached(db, 'k', compute) == {'v': 2} and len(calls) == 2
    cache_domain.invalidate()
    assert cache_domain.cached(db, 'k', compute) == {'v': 3}
    assert db.fetchone("SELECT 1 FROM sqlite_master WHERE name='idx_perf_le_acts_date'")


def test_summary_updates_after_change(db):
    from datetime import date
    s1 = bd.summary(db, date(2026, 10, 8))
    bd.add_quick(db, 'Просрочено давно 01.10.2026')
    s2 = bd.summary(db, date(2026, 10, 8))
    assert s2['overdue'] == s1['overdue'] + 1


def test_manual_order_move_task(tmp_path):
    from smetagaz.database import DatabaseManager
    from smetagaz import board_domain as b
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    ids = [d.execute("INSERT INTO kanban_tasks(title,status,is_archived) VALUES(?,?,0)", (f'T{i}', 'todo')).lastrowid for i in range(4)]
    order = lambda s='todo': [r[0] for r in d.fetchall(f'SELECT id FROM kanban_tasks WHERE status=? AND is_archived=0 {b.MANUAL_ORDER}', (s,))]
    assert order() == ids[::-1]                        # новые сверху, пока порядок не задан
    b.move_task(d, ids[0], 'todo', after_id=ids[3])    # самую старую — под самую новую
    assert order() == [ids[3], ids[0], ids[2], ids[1]]
    b.move_task(d, ids[1], 'todo', before_id=ids[3])   # наверх
    assert order() == [ids[1], ids[3], ids[0], ids[2]]
    b.move_task(d, ids[2], 'doing', None, None)        # в другую колонку
    assert order('doing') == [ids[2]] and ids[2] not in order()
    new = d.execute("INSERT INTO kanban_tasks(title,status,is_archived) VALUES('N','todo',0)").lastrowid
    assert order()[0] == new
    d.close()
