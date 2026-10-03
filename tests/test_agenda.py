from datetime import date
import sqlite3
import pytest
from smetagaz.database import DatabaseManager
from smetagaz import agenda_domain as a

TODAY = date(2026, 10, 3)


@pytest.fixture
def d(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def kinds(d, day):
    return [(e['kind'], e['title']) for e in a.events_between(d, day, day, TODAY)]


def test_due_labels():
    assert a.due_label('2026-10-03', TODAY) == 'Срок сегодня'
    assert a.due_label('2026-10-04', TODAY) == 'Срок завтра'
    assert a.due_label('2026-10-12', TODAY) == 'Срок 12.10.2026'
    assert a.due_label('2026-10-02', TODAY) == 'Просрочено на 1 день'
    assert a.due_label('2026-09-30', TODAY) == 'Просрочено на 3 дня'
    assert a.due_label('2026-09-20', TODAY) == 'Просрочено на 13 дней'
    assert a.due_label('2026-09-20', TODAY, done=True) == 'Срок 20.09.2026'
    assert a.due_label('', TODAY) == '' and a.due_label('мусор', TODAY) == ''
    assert a.norm_date('05.03.2026') == '2026-03-05' and a.norm_date('2026-03-05 10:00') == '2026-03-05'


def test_recurring_clamps_and_weekend_shift():
    assert a.occurrence(31, 'none', 2026, 2) == date(2026, 2, 28)
    assert a.occurrence(0, 'none', 2028, 2) == date(2028, 2, 29)
    assert a.occurrence(10, 'none', 2026, 10) == date(2026, 10, 10)          # суббота
    assert a.occurrence(10, 'prev', 2026, 10) == date(2026, 10, 9)
    assert a.occurrence(10, 'next', 2026, 10) == date(2026, 10, 12)


def test_recurring_in_calendar_range_and_start_month(d):
    d.execute("INSERT INTO recurring_dates(title,day_of_month,shift) VALUES('Зарплата',5,'none')")
    d.execute("INSERT INTO recurring_dates(title,day_of_month,start_month) VALUES('Аванс',20,'2026-12')")
    d.execute("INSERT INTO recurring_dates(title,day_of_month,active) VALUES('Выключено',7,0)")
    found = [(e['date'], e['title']) for e in a.events_between(d, date(2026, 10, 1), date(2027, 1, 31), TODAY)]
    assert (date(2026, 10, 5), 'Зарплата') in found and (date(2027, 1, 5), 'Зарплата') in found
    assert [t for dt, t in found if t == 'Аванс'] == ['Аванс', 'Аванс']          # декабрь и январь
    assert not any(t == 'Выключено' for _, t in found)


def test_tasks_due_overdue_and_done(d):
    d.execute("INSERT INTO kanban_tasks(title,status,is_archived,urgency,due_date) VALUES('Позвонить','todo',0,'Высокая','2026-10-03')")
    d.execute("INSERT INTO kanban_tasks(title,status,is_archived,urgency,due_date) VALUES('Старая','in_progress',0,'Обычная','2026-09-30')")
    d.execute("INSERT INTO kanban_tasks(title,status,is_archived,urgency,due_date) VALUES('Закрытая','done',0,'Обычная','2026-09-01')")
    d.execute("INSERT INTO kanban_tasks(title,status,is_archived,urgency,due_date) VALUES('В архиве','todo',1,'Обычная','2026-10-03')")
    assert kinds(d, TODAY) == [('task', 'Позвонить')]
    assert kinds(d, date(2026, 9, 30)) == [('overdue', 'Старая')]
    assert [r[1] for r in a.overdue_tasks(d, TODAY)] == ['Старая']          # завершённая и архивная не считаются
    # завершающий пользовательский статус тоже снимает просрочку
    d.execute("INSERT INTO task_statuses(code,name,is_done) VALUES('paid','Оплачено',1)")
    d.execute("UPDATE kanban_tasks SET status='paid' WHERE title='Старая'")
    assert a.overdue_tasks(d, TODAY) == []


def test_business_events_are_marked(d):
    est = d.execute("INSERT INTO estimates(title,total) VALUES('Смета дом',1000)").lastrowid
    d.execute("INSERT INTO contracts(estimate_id,contract_number,contract_date,object_name,acceptance_act_date,work_start_date,work_end_date) "
              "VALUES(?,?,?,?,?,?,?)", (est, '7/26', '2026-10-01', 'Дом Иванова', '2026-10-20', '2026-10-05', '2026-10-15'))
    d.execute("INSERT INTO gsv_projects(pd_number,contract_number,contract_date,object_name,act_date,due_date) VALUES('ПД-1','12','2026-10-01','Проект',  '2026-10-21','2026-10-10')")
    d.execute("INSERT INTO gsn_projects(title,contract_number,contract_date) VALUES('ГСН объект','ГСН-3','02.10.2026')")
    d.execute("INSERT INTO payments(estimate_id,amount,date) VALUES(?,?,?)", (est, 250.5, '2026-10-02'))
    wj = d.execute("INSERT INTO welding_jobs(title,object_text) VALUES('Сварка ввода','ул. Лесная')").lastrowid
    d.execute("INSERT INTO welding_days(job_id,work_date) VALUES(?,?)", (wj, '2026-10-02'))
    d.execute("INSERT INTO calendar_events(title,event_date,event_time) VALUES('Встреча','2026-10-02','09:30')")
    day1 = kinds(d, date(2026, 10, 1))
    assert sorted(k for k, _ in day1) == ['contract', 'contract']
    day2 = {k for k, _ in kinds(d, date(2026, 10, 2))}
    assert day2 == {'contract', 'payment', 'work', 'event'}                     # договор ГСН за 02.10 в формате ДД.ММ.ГГГГ
    assert {k for k, _ in kinds(d, date(2026, 10, 20))} == {'act'}
    assert {k for k, _ in kinds(d, date(2026, 10, 21))} == {'act'}
    assert {k for k, _ in kinds(d, date(2026, 10, 5))} == {'work'}
    assert {k for k, _ in kinds(d, date(2026, 10, 10))} == {'project'}
    marks = a.month_summary(a.events_between(d, date(2026, 10, 1), date(2026, 10, 31), TODAY))
    assert marks['2026-10-02']['payment'] == 1 and 'work' in marks['2026-10-02']


def test_upgrade_of_old_database_keeps_tasks(tmp_path):
    path = tmp_path / 'smetagaz.db'
    old = DatabaseManager(path)
    old.init_db()
    old.execute('DROP TABLE recurring_dates')
    old.close()
    again = DatabaseManager(path)
    again.init_db()
    cols = {r[1] for r in again.fetchall('PRAGMA table_info(kanban_tasks)')}
    assert 'due_date' in cols
    assert [r[0] for r in again.fetchall('SELECT code FROM task_statuses ORDER BY sort_order,id')][:3] == ['todo', 'in_progress', 'done']
    assert again.fetchone("SELECT is_done FROM task_statuses WHERE code='done'")[0] == 1
    again.close()
