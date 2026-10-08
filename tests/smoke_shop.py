"""Exercise the shop UI with disposable data and offscreen Qt."""
import os
import sys
import tempfile
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from shop.ui import Window, DocumentDialog
from shop import backup, documents

app = QApplication([])
with tempfile.TemporaryDirectory() as tmp:
    window = Window(tmp)
    pid = window.store.product('TEST', 'Товар', 'шт')
    party = window.store.party('company', 'Организация', '123456789')
    receipt = window.store.document('receipt', party, [dict(product_id=pid, quantity='5', price='10', tax='20')])
    window.store.post(receipt)
    dialog = DocumentDialog(window.store, window)
    dialog.kind.setCurrentIndex(1)
    dialog.table.item(0, 1).setText('2')
    dialog.table.item(0, 2).setText('15.00')
    dialog.table.item(0, 3).setText('20')
    dialog.save()
    assert dialog.result() == dialog.DialogCode.Accepted, dialog.error.text()
    invoice = window.store.rows("SELECT id FROM documents WHERE kind='invoice'")[0]['id']
    window.store.post(invoice)
    shipment = window.store.shipment_from_invoice(invoice)
    window.store.post(shipment)
    assert window.store.stock(pid) == 3000
    window.refresh()
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        app.processEvents()
    assert window.tables['products'].item(0, 4).text() == '3'
    output = Path(tmp) / 'documents/test.html'
    documents.export(window.store, invoice, Path(tmp) / 'templates/invoice.html', output)
    assert '36.00' in output.read_text()
    window.show()
    app.processEvents()
    assert window.isVisible()
    if os.environ.get('MAGAZIN_SCREENSHOT'):
        window.tabs.setCurrentIndex(0)
        window.grab().save(os.environ['MAGAZIN_SCREENSHOT'])
    window.close()
    assert list((Path(tmp) / 'backups').glob('*.zip'))
print('Магазин GUI OK: 6 tabs; invoice from UI; receipt/shipment; template; automatic backup')
