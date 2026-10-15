import pytest
from datetime import date
from smetagaz.database import DatabaseManager
from smetagaz import numbering as nm


@pytest.fixture
def d(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_reserve_continues_numbering_both_sections(d):
    a = nm.reserve(d, 'contracts', 3, date(2026, 5, 1))
    assert [n for _i, n in a] == ['01-02/26', '02-02/26', '03-02/26']
    p = nm.reserve(d, 'gsv_projects', 2, date(2026, 5, 1))
    assert [n for _i, n in p] == ['01-26 ГСВ', '02-26 ГСВ']
    assert d.fetchone('SELECT contract_number,reserved FROM gsv_projects WHERE id=?', (p[0][0],)) == ('01-03/26', 1)
    again = nm.reserve(d, 'contracts', 1, date(2026, 6, 1))
    assert again[0][1] == '04-02/26'
    with pytest.raises(ValueError):
        nm.reserve(d, 'contracts', 0)


def test_change_number_and_taken(d):
    a, b = [i for i, _ in nm.reserve(d, 'gsv_projects', 2, date(2026, 5, 1))]
    assert nm.change_number(d, 'gsv_projects', a, '7-26') == '07-26 ГСВ'
    assert d.fetchone('SELECT contract_number,seq_num FROM gsv_projects WHERE id=?', (a,)) == ('07-03/26', 7)
    with pytest.raises(nm.NumberTaken) as e:
        nm.change_number(d, 'gsv_projects', a, '02-26')
    assert e.value.other_id == b
    with pytest.raises(ValueError):
        nm.change_number(d, 'gsv_projects', a, 'abc')
    c = nm.reserve(d, 'contracts', 1, date(2026, 5, 1))[0][0]
    assert nm.change_number(d, 'contracts', c, 'Старый №5') == 'Старый №5'


def test_swap_keeps_clients_with_cards(d):
    a = d.execute("INSERT INTO gsv_projects(pd_number,seq_num,year_num,contract_number,client_name) VALUES('01-26 ГСВ',1,26,'01-03/26','Иванов')").lastrowid
    b = d.execute("INSERT INTO gsv_projects(pd_number,seq_num,year_num,contract_number,client_name) VALUES('02-26 ГСВ',2,26,'02-03/26','Петров')").lastrowid
    nm.swap_numbers(d, 'gsv_projects', a, b)
    assert d.fetchone('SELECT pd_number,client_name FROM gsv_projects WHERE id=?', (a,)) == ('02-26 ГСВ', 'Иванов')
    assert d.fetchone('SELECT pd_number,contract_number,client_name FROM gsv_projects WHERE id=?', (b,)) == ('01-26 ГСВ', '01-03/26', 'Петров')
    x = d.execute("INSERT INTO contracts(contract_number,seq_num,year_num,client_name) VALUES('01-02/26',1,26,'А')").lastrowid
    y = d.execute("INSERT INTO contracts(contract_number,seq_num,year_num,client_name) VALUES('02-02/26',2,26,'Б')").lastrowid
    nm.swap_numbers(d, 'contracts', x, y)
    assert d.fetchone('SELECT contract_number FROM contracts WHERE id=?', (x,))[0] == '02-02/26'


def test_release_when_filled(d):
    rid = nm.reserve(d, 'contracts', 1, date(2026, 5, 1))[0][0]
    nm.release_if_filled(d, 'contracts', rid)
    assert d.fetchone('SELECT reserved FROM contracts WHERE id=?', (rid,))[0] == 1
    d.execute("UPDATE contracts SET client_name='Иванов' WHERE id=?", (rid,))
    nm.release_if_filled(d, 'contracts', rid)
    assert d.fetchone('SELECT reserved FROM contracts WHERE id=?', (rid,))[0] == 0
