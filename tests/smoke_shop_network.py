"""Two desktop clients share the server ledger without opening local SQLite."""
import os
import sys
import tempfile
import threading
from pathlib import Path
from contextlib import closing
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from shop.core import Store
from shop.network import RemoteStore
from shop.ui import Window
from run_shop_server import make_server

app = QApplication([])
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    with closing(Store(root / 'server')) as store:
        pid = store.product('NET', 'Сетевой товар')
        party = store.party('company', 'Покупатель', '123456789')
        receipt = store.document('receipt', party, [dict(product_id=pid, quantity='5', price='5')])
        store.post(receipt)
        store.set_retail(pid, '10', '20')
    server = make_server(root / 'server', 'test-key', port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        first = Window(root / 'first', RemoteStore(root / 'first', url, 'test-key'))
        second = Window(root / 'second', RemoteStore(root / 'second', url, 'test-key'))
        invoice = first.store.document('invoice', party, [dict(product_id=pid, quantity='2', price='10', tax='20')])
        first.store.post(invoice)
        second.refresh()
        assert second.tables['stock'].item(0, 4).text() == '2'
        second.store.payment(invoice, '12')
        first.refresh()
        assert first.tables['debts'].item(0, 5).text() == '12.00'
        shipment = second.store.shipment_from_invoice(invoice)
        second.store.post(shipment)
        first.refresh()
        assert first.tables['stock'].item(0, 3).text() == '3'
        assert not (root / 'first/shop.db').exists()
        assert not (root / 'second/shop.db').exists()
        first.close()
        second.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
print('Магазин network GUI OK: 2 clients; shared reserve/payment/delivery; server-only SQLite; backup/close')
