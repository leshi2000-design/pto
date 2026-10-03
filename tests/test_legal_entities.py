import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sqlite3
import pytest
from smetagaz.database import DatabaseManager
from smetagaz.legal_entities_domain import DIRECTIONS, next_outgoing_number
from smetagaz.data_services import search


@pytest.fixture
def database(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def test_client_contract_act_chain(database):
    db = database
    cid = db.execute("INSERT INTO le_clients(name, unp, phone) VALUES('ООО Ромашка','123456789','+375291112233')").lastrowid

    for direction in DIRECTIONS:
        rid = db.execute(
            "INSERT INTO le_contracts(direction, contract_number, contract_date, client_id, object_name, amount, vat_included, status) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (direction, f'Д-{direction[:3]}', '2026-01-10', cid, 'Объект', 1000.0, 1, 'Действует')
        ).lastrowid
        assert db.fetchone("SELECT direction FROM le_contracts WHERE id=?", (rid,))[0] == direction

    contract_id = db.fetchone("SELECT id FROM le_contracts LIMIT 1")[0]
    act_id = db.execute(
        "INSERT INTO le_acts(contract_id, act_number, act_date, amount, vat_included, description) VALUES(?,?,?,?,?,?)",
        (contract_id, 'А-1', '2026-02-01', 500.0, 0, 'Выполнены работы')
    ).lastrowid
    assert db.fetchone("SELECT count(*) FROM le_acts WHERE contract_id=?", (contract_id,))[0] == 1

    # Deleting the contract cascades to its acts.
    db.execute("DELETE FROM le_contracts WHERE id=?", (contract_id,))
    assert db.fetchone("SELECT count(*) FROM le_acts WHERE id=?", (act_id,))[0] == 0

    # A client with remaining contracts can't be deleted outright (FK RESTRICT).
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM le_clients WHERE id=?", (cid,))


def test_outgoing_log_and_numbering(database):
    db = database
    assert next_outgoing_number(db) == '1'
    db.execute("INSERT INTO le_outgoing(reg_number, reg_date, recipient, subject) VALUES('1','2026-01-05','ООО Ромашка','Письмо о сроках')")
    assert next_outgoing_number(db) == '2'


def test_search_reaches_new_tables(database):
    db = database
    cid = db.execute("INSERT INTO le_clients(name, unp) VALUES('Уникальная Организация','987654321')").lastrowid
    db.execute("INSERT INTO le_contracts(direction, contract_number, client_id) VALUES(?, 'УНИК-42', ?)", (DIRECTIONS[0], cid))
    db.execute("INSERT INTO le_outgoing(reg_number, recipient, subject) VALUES('7','Куда-то','Уникальнейшая тема письма')")

    assert any(row[2] == 'Уникальная Организация' for row in search(db, 'Уникальная'))
    assert any(row[2] == 'УНИК-42' for row in search(db, 'УНИК-42'))
    assert any('Уникальнейшая' in row[3] for row in search(db, 'Уникальнейшая'))
