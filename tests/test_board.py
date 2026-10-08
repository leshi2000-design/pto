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
