import pytest
from smetagaz.database import DatabaseManager
from smetagaz import integrity


@pytest.fixture
def d(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def texts(findings, category=None):
    return ' | '.join(f['text'] for f in findings if category in (None, f['category']))


def test_clean_database_has_no_problems(d):
    assert integrity.check(d) == []


def test_finds_links_files_and_folders(d, tmp_path):
    cid = d.execute("INSERT INTO crm.clients(name) VALUES('Иванов')").lastrowid
    d.execute("INSERT INTO crm.clients(name) VALUES(' иванов ')")                                    # дубль ФИО
    good = tmp_path / 'ok.pdf'
    good.write_bytes(b'x')
    d.execute("INSERT INTO contracts(contract_number,client_id,client_name) VALUES('1',999,'Призрак')")      # клиент удалён
    d.execute("INSERT INTO contracts(contract_number) VALUES('2')")                                          # вообще без клиента
    d.execute("INSERT INTO contracts(contract_number,client_id,client_name,act_signed,contract_folder) VALUES('2',?,'Иванов',1,?)", (cid, str(tmp_path / 'нет папки')))
    d.execute("INSERT INTO certificates(name,file_path) VALUES('Пропал',?)", (str(tmp_path / 'пропал.pdf'),))
    d.execute("INSERT INTO certificates(name,file_path) VALUES('Есть',?)", (str(good),))
    d.execute('PRAGMA foreign_keys=OFF')                               # в старых базах такие записи могли остаться
    d.execute("INSERT INTO payments(estimate_id,amount,date) VALUES(777,10,'2026-10-01')")
    d.execute("INSERT INTO payments(amount,date) VALUES(10,'2026-10-02')")
    d.execute("INSERT INTO payments(owner_type,owner_id,amount,date) VALUES('contracts',555,10,'2026-10-03')")
    d.set_setting('gsvm_tpl_contract', str(tmp_path / 'нет шаблона.docx'))
    found = integrity.check(d)
    assert 'удалённого клиента №999' in texts(found, 'Клиенты') and 'договор «2» без клиента' in texts(found, 'Клиенты') and 'Повторяющееся ФИО' in texts(found, 'Клиенты')
    assert 'смета №777 не существует' in texts(found, 'Оплаты') and 'не привязана' in texts(found, 'Оплаты') and 'contracts №555' in texts(found, 'Оплаты')
    assert 'Пропал' in texts(found, 'Файлы') and 'Есть' not in texts(found, 'Файлы')
    assert 'нет папки' in texts(found, 'Папки') and 'gsvm_tpl_contract' in texts(found, 'Шаблоны')
    assert 'дата акта не указана' in texts(found, 'Договоры') and 'повторяется' in texts(found, 'Договоры')
    assert 'ссылается на несуществующую запись' in texts(found, 'Связи')
    assert found[0]['level'] == 'error' and found[-1]['level'] in ('warn', 'info')                       # ошибки идут первыми


def test_fix_dangling_clients_is_safe(d):
    cid = d.execute("INSERT INTO crm.clients(name) VALUES('Иванов')").lastrowid
    d.execute("INSERT INTO contracts(contract_number,client_id,client_name) VALUES('1',999,'Призрак')")
    d.execute("INSERT INTO contracts(contract_number,client_id,client_name) VALUES('2',?,'Иванов')", (cid,))
    assert integrity.fix_dangling_clients(d) == 1
    assert d.fetchall('SELECT contract_number,client_id,client_name FROM contracts ORDER BY id') == [('1', None, 'Призрак'), ('2', cid, 'Иванов')]
    assert 'удалённого клиента' not in texts(integrity.check(d))
