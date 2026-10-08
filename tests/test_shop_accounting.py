from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import json
import sqlite3
import threading
import pytest
from shop.core import Store
from shop import backup, documents
from shop.network import RemoteStore
from run_shop_server import make_server


@pytest.fixture
def store(tmp_path):
    with closing(Store(tmp_path / 'data')) as store:
        yield store


def inventory(store, quantity='10', price='5', day='2026-01-01'):
    pid = store.product('A', 'Товар')
    party = store.party('company', 'Покупатель', '123456789')
    receipt = store.document('receipt', party, [dict(product_id=pid, quantity=quantity, price=price)], day=day)
    store.post(receipt)
    return pid, party, receipt


def invoice(store, pid, party, quantity='2', price='10', day='2026-01-02'):
    inv = store.document('invoice', party, [dict(product_id=pid, quantity=quantity, price=price, tax='20')], day=day, due_day=day[:7]+'-28')
    store.post(inv)
    return inv


def test_full_workflow_reserve_debt_delivery_calendar(store):
    pid, party, _ = inventory(store)
    store.set_retail(pid, '10', '20', day='2026-01-01')
    inv = invoice(store, pid, party)
    assert store.stock(pid) == 10000
    assert store.reserved(pid) == 2000
    assert store.available(pid) == 8000
    assert store.debts()[0]['debt'] == 2400
    payment = store.payment(inv, '10', '2026-01-03')
    assert store.debts()[0]['debt'] == 1400
    shipment = store.shipment_from_invoice(inv, '2026-01-04')
    store.post(shipment)
    assert store.stock(pid) == 8000 and store.reserved(pid) == 0
    assert store.debts()[0]['shipped']
    sale = store.statistics('2026-01')['sales'][0]
    assert sale['party_name'] == 'Покупатель'
    assert sale['gross'] == 2400 and sale['cost'] == 1000 and sale['margin'] == 1000
    store.payment(inv, '14', '2026-01-05')
    assert not store.debts()
    store.cancel_payment(payment, '2026-01-06')
    assert store.debts()[0]['debt'] == 1000
    assert {r['kind'] for r in store.calendar()} >= {'receipt', 'invoice', 'payment', 'shipment', 'retail', 'payment_cancel', 'due'}
    assert store.calendar('2026-01-04')[0]['kind'] == 'shipment'


def test_fifo_cost_and_month_and_units(store):
    pid, party, _ = inventory(store, quantity='1', price='5')
    second = store.document('receipt', party, [dict(product_id=pid, quantity='2', price='7')], day='2026-01-02')
    store.post(second)
    inv = invoice(store, pid, party, quantity='2', price='10', day='2026-02-01')
    shipment = store.shipment_from_invoice(inv, '2026-02-02')
    store.post(shipment)
    report = store.statistics('2026-02')
    assert report['sales'][0]['cost'] == 1200
    assert report['sales'][0]['margin'] == 800
    assert report['quantities'] == {'шт': 2000}
    assert not store.sales('2026-01')
    with pytest.raises(ValueError):
        store.cancel(second)
    store.cancel(shipment)
    assert not store.sales('2026-02')
    assert store.reserved(pid) == 2000
    with pytest.raises(ValueError):
        store.cancel(second)
    store.cancel(inv)
    store.cancel(second)
    assert store.stock(pid) == 1000


def test_retail_date_history_and_invoice_snapshot(store):
    pid, party, _ = inventory(store)
    store.set_retail(pid, '10', '20', day='2026-01-01')
    store.set_retail(pid, '12', '20', day='2026-02-01')
    assert store.retail(pid, day='2026-01-15')['price'] == 1000
    assert store.retail(pid, day='2026-02-15')['price'] == 1200
    assert store.retail(pid, day='2025-12-01') is None
    inv = invoice(store, pid, party)
    store.set_retail(pid, '99', '20')
    assert store.total(inv) == 2400
    with pytest.raises(ValueError):
        store.payment(inv, '1', '2025-12-31')


def test_paid_or_delivered_invoice_cannot_cancel(store):
    pid, party, _ = inventory(store)
    inv = invoice(store, pid, party)
    payment = store.payment(inv, '1', '2026-01-03')
    with pytest.raises(ValueError, match='оплаты'):
        store.cancel(inv)
    store.cancel_payment(payment, '2026-01-04')
    ship = store.shipment_from_invoice(inv, '2026-01-05')
    store.post(ship)
    with pytest.raises(ValueError, match='передачу'):
        store.cancel(inv)


def test_belarus_requisites_and_seller_snapshot(store):
    pid, party, _ = inventory(store)
    values = dict(seller='ООО Пример', seller_unp='123456789', seller_address='Минск', seller_bank='Банк',
                  seller_bic='AKBBBY2X', seller_iban='BY46AKBB36000100000000000000')
    store.save_organization(values)
    inv = invoice(store, pid, party)
    store.save_organization({**values, 'seller': 'Новое имя'})
    _, context, _ = documents.context(store, inv)
    assert context['seller'] == 'ООО Пример'
    assert context['seller_unp'] == '123456789'
    with pytest.raises(ValueError, match='УНП'):
        store.save_organization({**values, 'seller_unp': '123'})
    with pytest.raises(ValueError, match='Контрольные'):
        store.save_organization({**values, 'seller_iban': 'BY00AKBB36000100000000000000'})


def test_backup_connections_are_closed(store, tmp_path, monkeypatch):
    inventory(store)
    original = sqlite3.connect
    opened = []
    class Tracked(sqlite3.Connection):
        closed = False
        def close(self):
            self.closed = True
            super().close()
    def connect(*args, **kwargs):
        conn = original(*args, factory=Tracked, **kwargs)
        opened.append(conn)
        return conn
    monkeypatch.setattr(backup.sqlite3, 'connect', connect)
    archive = backup.create(store)
    backup.restore(archive, tmp_path / 'restored')
    assert opened and all(c.closed for c in opened)


def test_upgrade_keeps_existing_data_and_creates_backup(store):
    pid, party, _ = inventory(store)
    inv = invoice(store, pid, party)
    ship = store.shipment_from_invoice(inv, '2026-01-03')
    store.post(ship)
    # Simulate the legacy version without accounting tables.
    with store.conn:
        for table in ('events', 'reservations', 'payments', 'cost_allocations', 'retail_prices'):
            store.conn.execute('DROP TABLE ' + table)
        store.conn.execute('PRAGMA user_version=0')
    root = store.root
    store.close()
    with closing(Store(root)) as upgraded:
        assert upgraded.stock(pid) == 8000
        assert upgraded.sales('2026-01')[0]['cost'] == 1000
        assert upgraded.total(inv) == 2400
        assert upgraded.calendar()
        assert list((root / 'backups').glob('*.zip'))


def test_server_two_clients_last_item_and_payment(tmp_path):
    root = tmp_path / 'server'
    with closing(Store(root)) as store:
        pid, party, _ = inventory(store, quantity='1')
    server = make_server(root, 'test-secret', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    first = second = None
    try:
        with pytest.raises(ValueError, match='ключ'):
            RemoteStore(tmp_path / 'bad', url, 'wrong')
        first = RemoteStore(tmp_path / 'client1', url, 'test-secret')
        second = RemoteStore(tmp_path / 'client2', url, 'test-secret')
        docs = [client.document('invoice', party, [dict(product_id=pid, quantity='1', price='10')], day='2026-01-02') for client in (first, second)]
        def issue(pair):
            client, doc = pair
            try:
                client.post(doc)
                return doc
            except ValueError:
                return None
        with ThreadPoolExecutor(2) as executor:
            results = list(executor.map(issue, zip((first, second), docs)))
        successful = [r for r in results if r]
        assert len(successful) == 1
        assert second.available(pid) == 0
        first.payment(successful[0], '5', '2026-01-03')
        assert second.debts()[0]['debt'] == 500
        ship = second.shipment_from_invoice(successful[0], '2026-01-04')
        second.post(ship)
        assert first.stock(pid) == 0
        assert first.debts()[0]['shipped']
        assert first.create_backup().exists()
        with pytest.raises(ValueError):
            first.rows('DELETE FROM products')
        assert len(second.catalog()) == 1
        with pytest.raises(ValueError):
            first.call('upload', '../escape.txt', 'eA==')
        with pytest.raises(ValueError):
            first.call('upload', 'templates/../shop.db', 'eA==')
        assert len(second.catalog()) == 1
    finally:
        if first:
            first.close()
        if second:
            second.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
