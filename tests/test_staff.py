import pytest
from datetime import date
from smetagaz.database import DatabaseManager
from smetagaz import staff_domain as sd, agenda_domain as ag


@pytest.fixture
def d(tmp_path):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


def person(d, name, role='Монтажник'):
    return sd.save_staff(d, dict(name=name, role=role, phone='375291112233'))


def test_deadlines_states_and_welder_license(d):
    a = person(d, 'Иванов')
    sd.save_doc(d, a, dict(kind='Аттестат', title='Аттестат монтажника', valid_to='2026-03-10'))
    sd.save_doc(d, a, dict(title='Медосмотр', valid_to='2026-12-31'))
    sd.save_doc(d, a, dict(title='Без срока'))
    d.execute("INSERT INTO welders(name,valid_until,grade) VALUES('Сидоров','2026-02-01','5 разряд')")
    assert sd.sync_welders(d) == 1 and sd.sync_welders(d) == 0
    rows = {r['title']: r for r in sd.all_deadlines(d, date(2026, 3, 1))}
    assert rows['Аттестат монтажника']['state'] == 'soon' and rows['Аттестат монтажника']['left'] == 9
    assert rows['Медосмотр']['state'] == 'ok' and 'Без срока' not in rows
    assert rows['Удостоверение сварщика (5 разряд)']['state'] == 'expired'
    assert sd.expired_for(d, rows['Удостоверение сварщика (5 разряд)']['staff_id'], date(2026, 3, 1)) == ['Удостоверение сварщика (5 разряд)']


def test_crews_assignments_conflicts_and_schedule(d):
    a, b, c = person(d, 'А'), person(d, 'Б'), person(d, 'В')
    crew = sd.save_crew(d, 'Бригада 1', a, [b])
    assert sorted(sd.crew_members(d, crew)) == sorted([a, b])
    with pytest.raises(ValueError):
        sd.save_crew(d, 'бригада 1')
    obj = d.execute("INSERT INTO gsn_projects(contract_number,title,client_name) VALUES('ГСН-1','Дом','Петров')").lastrowid
    first = sd.add_assignment(d, '2026-03-02', '2026-03-06', crew_id=crew, owner_type='gsn_projects', owner_id=obj)
    assert sd.conflicts(d, c, None, '2026-03-01', '2026-03-31') == []
    clash = sd.conflicts(d, b, None, '2026-03-05', '2026-03-09')
    assert clash and clash[0][0] == 'Б' and 'ГСН-1' in clash[0][1]
    assert not sd.conflicts(d, b, None, '2026-03-05', '2026-03-09', exclude=first) and not sd.conflicts(d, None, crew, '2026-03-02', '2026-03-06', exclude=first)
    with pytest.raises(ValueError):
        sd.add_assignment(d, '2026-03-06', '2026-03-02', staff_id=a, object_text='x')
    with pytest.raises(ValueError):
        sd.add_assignment(d, '2026-03-02', '2026-03-03', staff_id=a, crew_id=crew, object_text='x')
    grid, names = sd.schedule(d, date(2026, 3, 1), date(2026, 3, 31))
    assert set(grid) == {a, b} and len(grid[a]) == 5 and names[a] == 'А'
    team = sd.object_team(d, 'gsn_projects', obj, date(2026, 3, 3))
    assert {n for n, _ in team} == {'А', 'Б'}
    assert len(sd.assignments(d, 'gsn_projects', obj)) == 1


def test_agenda_shows_permits_and_crew(d):
    a = person(d, 'Иванов')
    sd.save_doc(d, a, dict(title='Допуск', valid_to='2026-03-10'))
    sd.add_assignment(d, '2026-03-12', '2026-03-13', staff_id=a, object_text='Объект X')
    events = ag.events_between(d, date(2026, 3, 1), date(2026, 3, 31), date(2026, 3, 1))
    kinds = {e['kind'] for e in events}
    assert {'permit', 'crew'} <= kinds


def test_delete_staff_cleans_links(d):
    a = person(d, 'А')
    crew = sd.save_crew(d, 'Б1', a, [a])
    sd.add_assignment(d, '2026-03-02', '2026-03-03', staff_id=a, object_text='X')
    sd.delete_staff(d, a)
    assert d.fetchone('SELECT leader_id FROM crews WHERE id=?', (crew,))[0] is None
    assert d.fetchone('SELECT count(*) FROM staff_assign')[0] == 0 and d.fetchone('SELECT count(*) FROM crew_members')[0] == 0
