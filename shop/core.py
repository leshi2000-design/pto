"""SQLite ledger; prices and quantities use integers, never binary floats."""
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3


def scaled(value, scale):
    try:
        number = Decimal(str(value).replace(' ', '').replace('\xa0', '').replace(',', '.'))
        if not number.is_finite() or number < 0 or number * scale != (number * scale).to_integral_value():
            raise ValueError('Некорректное число или слишком много знаков после запятой')
        return int(number * scale)
    except InvalidOperation as exc:
        raise ValueError('Некорректное число') from exc


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ('templates', 'documents', 'sources', 'backups'):
            (self.root / folder).mkdir(exist_ok=True)
        self.conn = sqlite3.connect(self.root / 'shop.db', timeout=15)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS products (
          id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
          unit TEXT NOT NULL, category TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS parties (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('person','company')),
          name TEXT NOT NULL, tax_id TEXT NOT NULL DEFAULT '', details TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS offers (
          id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
          supplier TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>=0), currency TEXT NOT NULL,
          source TEXT NOT NULL, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(product_id,supplier,currency,source));
        CREATE TABLE IF NOT EXISTS documents (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('receipt','invoice','shipment')),
          number TEXT NOT NULL UNIQUE, day TEXT NOT NULL, party_id INTEGER NOT NULL REFERENCES parties(id),
          party_name TEXT NOT NULL, party_details TEXT NOT NULL, currency TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','posted','cancelled')),
          invoice_id INTEGER UNIQUE REFERENCES documents(id), reference TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS lines (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
          product_id INTEGER NOT NULL REFERENCES products(id), sku TEXT NOT NULL, name TEXT NOT NULL,
          unit TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>0),
          price INTEGER NOT NULL CHECK(price>=0), tax_bp INTEGER NOT NULL CHECK(tax_bp BETWEEN 0 AND 10000));
        CREATE TABLE IF NOT EXISTS movements (
          id INTEGER PRIMARY KEY, document_id INTEGER NOT NULL REFERENCES documents(id),
          product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL,
          UNIQUE(document_id,product_id));
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        if 'reference' not in {r[1] for r in self.conn.execute('PRAGMA table_info(documents)')}:
            self.conn.execute("ALTER TABLE documents ADD COLUMN reference TEXT NOT NULL DEFAULT ''")
            self.conn.commit()

    def rows(self, sql, args=()):
        return [dict(row) for row in self.conn.execute(sql, args)]

    def product(self, sku, name, unit='шт', category=''):
        if not sku.strip() or not name.strip() or not unit.strip():
            raise ValueError('Заполните артикул, название и единицу')
        with self.conn:
            return self.conn.execute('INSERT INTO products(sku,name,unit,category) VALUES(?,?,?,?)',
                                     (sku.strip(), name.strip(), unit.strip(), category.strip())).lastrowid

    def party(self, kind, name, tax_id='', details=''):
        if not name.strip() or kind not in ('person', 'company'):
            raise ValueError('Укажите контрагента')
        with self.conn:
            return self.conn.execute('INSERT INTO parties(kind,name,tax_id,details) VALUES(?,?,?,?)',
                                     (kind, name.strip(), tax_id, details)).lastrowid

    def catalog(self):
        return self.rows('''SELECT p.*, COALESCE((SELECT SUM(quantity) FROM movements m
          WHERE m.product_id=p.id),0) stock,
          (SELECT COUNT(*) FROM offers o WHERE o.product_id=p.id) offer_count FROM products p ORDER BY p.name''')

    def stock(self, product_id):
        return self.conn.execute('SELECT COALESCE(SUM(quantity),0) FROM movements WHERE product_id=?',
                                 (product_id,)).fetchone()[0]

    def offer(self, product_id, supplier, price, currency, source):
        if not supplier.strip() or not currency.strip() or not source.strip():
            raise ValueError('Укажите поставщика, валюту и источник')
        cents = scaled(price, 100)
        with self.conn:
            self.conn.execute('''INSERT INTO offers(product_id,supplier,price,currency,source) VALUES(?,?,?,?,?)
              ON CONFLICT(product_id,supplier,currency,source) DO UPDATE SET
              price=excluded.price, updated=CURRENT_TIMESTAMP''',
                              (product_id, supplier, cents, currency, source))

    def document(self, kind, party_id, items, currency='BYN', day=None, reference=''):
        if kind not in ('receipt', 'invoice', 'shipment') or not items or not currency.strip():
            raise ValueError('Укажите вид документа, валюту и позиции')
        day = day or date.today().isoformat()
        date.fromisoformat(day)
        with self.conn:
            party = self.conn.execute('SELECT * FROM parties WHERE id=?', (party_id,)).fetchone()
            if not party:
                raise ValueError('Контрагент не найден')
            # Serial allocation occurs inside the write transaction and never reuses a number.
            cursor = self.conn.execute('''INSERT INTO documents(kind,number,day,party_id,party_name,party_details,currency)
               VALUES(?,?,?,?,?,?,?)''', (kind, 'pending', day, party_id, party['name'],
                                          '\n'.join(filter(None, (party['tax_id'], party['details']))), currency))
            doc_id = cursor.lastrowid
            prefix = {'receipt': 'ПР', 'invoice': 'СЧ', 'shipment': 'РН'}[kind]
            self.conn.execute('UPDATE documents SET number=? WHERE id=?', (f'{prefix}-{doc_id:06d}', doc_id))
            self.conn.execute('UPDATE documents SET reference=? WHERE id=?', (reference, doc_id))
            for item in items:
                product = self.conn.execute('SELECT * FROM products WHERE id=?', (item['product_id'],)).fetchone()
                if not product:
                    raise ValueError('Товар не найден')
                quantity = scaled(item['quantity'], 1000)
                if quantity == 0:
                    raise ValueError('Количество должно быть положительным')
                self.conn.execute('''INSERT INTO lines(document_id,product_id,sku,name,unit,quantity,price,tax_bp)
                    VALUES(?,?,?,?,?,?,?,?)''', (doc_id, product['id'], product['sku'], product['name'],
                                               product['unit'], quantity, scaled(item['price'], 100),
                                               scaled(item.get('tax', 0), 100)))
            return doc_id

    def post(self, doc_id):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            doc = self.conn.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
            if not doc or doc['status'] != 'draft':
                raise ValueError('Провести можно только черновик')
            totals = Counter()
            for row in self.conn.execute('SELECT * FROM lines WHERE document_id=?', (doc_id,)):
                totals[row['product_id']] += row['quantity']
            if not totals:
                raise ValueError('Документ пуст')
            if doc['kind'] == 'shipment':
                for pid, quantity in totals.items():
                    if self.stock(pid) < quantity:
                        raise ValueError('Недостаточно товара на складе; документ не проведён')
            if doc['kind'] != 'invoice':
                sign = 1 if doc['kind'] == 'receipt' else -1
                self.conn.executemany('INSERT INTO movements(document_id,product_id,quantity) VALUES(?,?,?)',
                                      ((doc_id, pid, sign * qty) for pid, qty in totals.items()))
            self.conn.execute("UPDATE documents SET status='posted' WHERE id=?", (doc_id,))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def cancel(self, doc_id):
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            doc = self.conn.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
            if not doc or doc['status'] == 'cancelled':
                raise ValueError('Документ не найден или уже отменён')
            for move in self.conn.execute('SELECT * FROM movements WHERE document_id=?', (doc_id,)):
                if self.stock(move['product_id']) - move['quantity'] < 0:
                    raise ValueError('Нельзя отменить поступление: товар уже отгружен')
            self.conn.execute('DELETE FROM movements WHERE document_id=?', (doc_id,))
            self.conn.execute("UPDATE documents SET status='cancelled' WHERE id=?", (doc_id,))
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise

    def shipment_from_invoice(self, doc_id):
        doc = self.conn.execute('SELECT * FROM documents WHERE id=?', (doc_id,)).fetchone()
        if not doc or doc['kind'] != 'invoice' or doc['status'] != 'posted':
            raise ValueError('Выберите проведённый счёт')
        if self.conn.execute('SELECT 1 FROM documents WHERE invoice_id=?', (doc_id,)).fetchone():
            raise ValueError('Накладная по этому счёту уже создана')
        # Copy snapshots verbatim, including party and historical prices.
        with self.conn:
            cursor = self.conn.execute('''INSERT INTO documents(kind,number,day,party_id,party_name,party_details,currency,invoice_id)
                VALUES('shipment','pending',?,?,?,?,?,?)''',
                (date.today().isoformat(), doc['party_id'], doc['party_name'], doc['party_details'], doc['currency'], doc_id))
            new_id = cursor.lastrowid
            self.conn.execute('UPDATE documents SET number=? WHERE id=?', (f'РН-{new_id:06d}', new_id))
            self.conn.execute('''INSERT INTO lines(document_id,product_id,sku,name,unit,quantity,price,tax_bp)
                SELECT ?,product_id,sku,name,unit,quantity,price,tax_bp FROM lines WHERE document_id=?''', (new_id, doc_id))
            return new_id

    def close(self):
        self.conn.close()
