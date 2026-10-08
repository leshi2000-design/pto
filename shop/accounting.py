"""Reservations, settlements, FIFO cost and a dated business event ledger."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import json
import re


def rounded(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def amounts(line):
    net = rounded(Decimal(line['quantity']) * line['price'] / 1000)
    tax = rounded(Decimal(net) * line['tax_bp'] / 10000)
    return net, tax


EVENTS = {'receipt': 'Поступление товара', 'invoice': 'Выставлен счёт', 'shipment': 'Передача товара',
          'payment': 'Получена оплата', 'payment_cancel': 'Оплата отменена', 'cancel': 'Документ отменён',
          'retail': 'Установлена розничная цена', 'draft': 'Создан черновик', 'due': 'Срок оплаты',
          'price_import': 'Импортирован прайс', 'web_update': 'Обновлены цены сайта'}


class Accounting:
    def init_accounting(self):
        migrating = self.conn.execute('PRAGMA user_version').fetchone()[0] < 2
        self.conn.executescript('''
        CREATE TABLE IF NOT EXISTS retail_prices(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
          day TEXT NOT NULL, price INTEGER NOT NULL CHECK(price>=0), tax_bp INTEGER NOT NULL CHECK(tax_bp BETWEEN 0 AND 10000),
          currency TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS reservations(invoice_id INTEGER NOT NULL REFERENCES documents(id),
          product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL CHECK(quantity>0),
          PRIMARY KEY(invoice_id,product_id));
        CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES documents(id),
          day TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0), method TEXT NOT NULL, reference TEXT NOT NULL,
          cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0,1)));
        CREATE TABLE IF NOT EXISTS cost_allocations(id INTEGER PRIMARY KEY, shipment_line_id INTEGER NOT NULL REFERENCES lines(id),
          receipt_line_id INTEGER NOT NULL REFERENCES lines(id), quantity INTEGER NOT NULL CHECK(quantity>0), cost INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, day TEXT NOT NULL, kind TEXT NOT NULL,
          document_id INTEGER REFERENCES documents(id), payment_id INTEGER REFERENCES payments(id),
          product_id INTEGER REFERENCES products(id), details TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS events_day ON events(day);
        CREATE INDEX IF NOT EXISTS payments_invoice ON payments(invoice_id);
        CREATE INDEX IF NOT EXISTS costs_receipt ON cost_allocations(receipt_line_id);
        CREATE INDEX IF NOT EXISTS lines_document ON lines(document_id);
        CREATE INDEX IF NOT EXISTS movements_product ON movements(product_id);
        CREATE INDEX IF NOT EXISTS retail_product_day ON retail_prices(product_id,currency,day);
        ''')
        columns = {r[1] for r in self.conn.execute('PRAGMA table_info(documents)')}
        with self.conn:
            for name, declaration in [('due_day', "TEXT NOT NULL DEFAULT ''"), ('seller_snapshot', "TEXT NOT NULL DEFAULT ''")]:
                if name not in columns:
                    self.conn.execute(f'ALTER TABLE documents ADD COLUMN {name} {declaration}')
            # Old invoices did not reserve stock. Preserve them without inventing reservations.
            for doc in self.rows("SELECT * FROM documents WHERE status='posted' ORDER BY day,id") if migrating else []:
                if not self.conn.execute('SELECT 1 FROM events WHERE document_id=? AND kind=?', (doc['id'], doc['kind'])).fetchone():
                    self.event(doc['day'], doc['kind'], doc['id'], details='Перенесено из предыдущей версии')
                if doc['kind'] == 'shipment' and not self.conn.execute(
                    'SELECT 1 FROM cost_allocations c JOIN lines l ON l.id=c.shipment_line_id WHERE l.document_id=?', (doc['id'],)).fetchone():
                    self.allocate_cost(doc, legacy=True)
            self.conn.execute('PRAGMA user_version=2')

    def set_settings(self, values):
        if set(values) - {'web_sources'}:
            raise ValueError('Эти настройки изменяются через реквизиты организации')
        with self.conn:
            for key, value in values.items():
                self.conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def reschedule_shipment(self, doc_id, day):
        date.fromisoformat(day)
        with self.conn:
            doc = self.conn.execute("SELECT * FROM documents WHERE id=? AND kind='shipment' AND status='draft'", (doc_id,)).fetchone()
            if not doc:
                raise ValueError('Изменить дату можно только в черновике отгрузки')
            self.conn.execute('UPDATE documents SET day=? WHERE id=?', (day, doc_id))

    def event(self, day, kind, document_id=None, payment_id=None, product_id=None, details=''):
        date.fromisoformat(day)
        self.conn.execute('INSERT INTO events(day,kind,document_id,payment_id,product_id,details) VALUES(?,?,?,?,?,?)',
                          (day, kind, document_id, payment_id, product_id, details))

    def reserved(self, product_id, except_invoice=None):
        return self.conn.execute('SELECT COALESCE(SUM(quantity),0) FROM reservations WHERE product_id=? AND invoice_id<>?',
                                 (product_id, except_invoice or -1)).fetchone()[0]

    def available(self, product_id, except_invoice=None):
        return self.stock(product_id) - self.reserved(product_id, except_invoice)

    def set_retail(self, product_id, price, tax='0', day=None, currency='BYN', note=''):
        from .core import scaled
        day = day or date.today().isoformat()
        date.fromisoformat(day)
        cents, tax_bp = scaled(price, 100), scaled(tax, 100)
        if tax_bp > 10000 or not currency.strip():
            raise ValueError('Некорректная ставка НДС или валюта')
        with self.conn:
            self.conn.execute('INSERT INTO retail_prices(product_id,day,price,tax_bp,currency,note) VALUES(?,?,?,?,?,?)',
                              (product_id, day, cents, tax_bp, currency, note))
            self.event(day, 'retail', product_id=product_id, details=f'{Decimal(cents)/100:.2f} {currency} без НДС')

    def retail(self, product_id, currency='BYN', day=None):
        rows = self.rows('SELECT * FROM retail_prices WHERE product_id=? AND currency=? AND day<=? ORDER BY day DESC,id DESC LIMIT 1',
                         (product_id, currency, day or date.today().isoformat()))
        return rows[0] if rows else None

    def total(self, doc_id):
        return sum(sum(amounts(row)) for row in self.rows('SELECT * FROM lines WHERE document_id=?', (doc_id,)))

    def invoices(self):
        result = []
        for doc in self.rows("SELECT * FROM documents WHERE kind='invoice' ORDER BY day DESC,id DESC"):
            doc['total'] = self.total(doc['id'])
            doc['paid'] = self.conn.execute('SELECT COALESCE(SUM(amount),0) FROM payments WHERE invoice_id=? AND cancelled=0', (doc['id'],)).fetchone()[0]
            doc['debt'] = max(0, doc['total'] - doc['paid'])
            doc['overpaid'] = max(0, doc['paid'] - doc['total'])
            doc['shipped'] = bool(self.conn.execute("SELECT 1 FROM documents WHERE invoice_id=? AND status='posted'", (doc['id'],)).fetchone())
            doc['payment_status'] = 'Переплата' if doc['overpaid'] else 'Оплачен' if not doc['debt'] else 'Частично оплачен' if doc['paid'] else 'Не оплачен'
            result.append(doc)
        return result

    def debts(self):
        return [d for d in self.invoices() if d['status'] == 'posted' and d['debt'] > 0]

    def payment(self, invoice_id, amount, day=None, method='Банк', reference=''):
        from .core import scaled
        cents = scaled(amount, 100)
        day = day or date.today().isoformat()
        date.fromisoformat(day)
        if cents <= 0 or not method.strip():
            raise ValueError('Укажите положительную сумму и способ оплаты')
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            doc = self.conn.execute("SELECT * FROM documents WHERE id=? AND kind='invoice' AND status='posted'", (invoice_id,)).fetchone()
            if not doc:
                raise ValueError('Оплату можно записать только к выставленному счёту')
            if day < doc['day']:
                raise ValueError('Дата оплаты не может быть раньше даты счёта')
            pid = self.conn.execute('INSERT INTO payments(invoice_id,day,amount,method,reference) VALUES(?,?,?,?,?)',
                                     (invoice_id, day, cents, method, reference)).lastrowid
            self.event(day, 'payment', invoice_id, pid, details=f'{Decimal(cents)/100:.2f} {doc["currency"]} · {method} · {reference}')
            self.conn.commit()
            return pid
        except BaseException:
            self.conn.rollback()
            raise

    def cancel_payment(self, payment_id, day=None):
        day = day or date.today().isoformat()
        date.fromisoformat(day)
        with self.conn:
            payment = self.conn.execute('SELECT * FROM payments WHERE id=? AND cancelled=0', (payment_id,)).fetchone()
            if not payment:
                raise ValueError('Оплата не найдена или уже отменена')
            if day < payment['day']:
                raise ValueError('Дата отмены раньше оплаты')
            self.conn.execute('UPDATE payments SET cancelled=1 WHERE id=?', (payment_id,))
            self.event(day, 'payment_cancel', payment['invoice_id'], payment_id, details='Отмена оплаты')

    def allocate_cost(self, doc, legacy=False):
        for line in self.rows('SELECT * FROM lines WHERE document_id=? ORDER BY id', (doc['id'],)):
            remaining = line['quantity']
            lots = self.rows('''SELECT l.*,d.day FROM lines l JOIN documents d ON d.id=l.document_id
              WHERE l.product_id=? AND d.kind='receipt' AND d.status='posted' AND d.currency=? AND d.day<=?
              ORDER BY d.day,d.id,l.id''', (line['product_id'], doc['currency'], doc['day']))
            for lot in lots:
                used = self.conn.execute('SELECT COALESCE(SUM(quantity),0) FROM cost_allocations WHERE receipt_line_id=?', (lot['id'],)).fetchone()[0]
                qty = min(remaining, lot['quantity'] - used)
                if qty <= 0:
                    continue
                # Allocate differences of cumulative rounded cost to avoid rounding drift across sales.
                cost = rounded(Decimal(used + qty) * lot['price'] / 1000) - rounded(Decimal(used) * lot['price'] / 1000)
                self.conn.execute('INSERT INTO cost_allocations(shipment_line_id,receipt_line_id,quantity,cost) VALUES(?,?,?,?)',
                                  (line['id'], lot['id'], qty, cost))
                remaining -= qty
                if remaining == 0:
                    break
            if remaining and not legacy:
                raise ValueError('Нет подходящего поступления для себестоимости: проверьте дату и валюту накладной')

    def sales(self, month=None, product_id=None):
        if month:
            date.fromisoformat(month + '-01')
        result = []
        for row in self.rows('''SELECT l.*,d.number,d.day,d.party_name,d.currency,d.invoice_id FROM lines l
            JOIN documents d ON d.id=l.document_id WHERE d.kind='shipment' AND d.status='posted'
            ORDER BY d.day DESC,d.id DESC'''):
            if month and not row['day'].startswith(month) or product_id and row['product_id'] != product_id:
                continue
            net, tax = amounts(row)
            allocations = self.conn.execute('SELECT COALESCE(SUM(quantity),0),COALESCE(SUM(cost),0) FROM cost_allocations WHERE shipment_line_id=?', (row['id'],)).fetchone()
            row.update(net=net, tax=tax, gross=net+tax, cost=allocations[1] if allocations[0] == row['quantity'] else None)
            row['margin'] = net - row['cost'] if row['cost'] is not None else None
            result.append(row)
        return result

    def statistics(self, month):
        sales = self.sales(month)
        totals = {}
        for row in sales:
            group = totals.setdefault(row['currency'], dict(revenue=0, net=0, cost=0, margin=0, unknown_cost=0))
            group['revenue'] += row['gross']
            group['net'] += row['net']
            if row['cost'] is None:
                group['unknown_cost'] += 1
            else:
                group['cost'] += row['cost']
                group['margin'] += row['margin']
        # Pieces and metres are not added together.
        quantities = {}
        for row in sales:
            quantities[row['unit']] = quantities.get(row['unit'], 0) + row['quantity']
        return {'sales': sales, 'totals': totals, 'quantities': quantities}

    def calendar(self, day=None):
        sql = '''SELECT e.*,d.number,d.party_name,p.name product_name FROM events e
          LEFT JOIN documents d ON d.id=e.document_id LEFT JOIN products p ON p.id=e.product_id'''
        return self.rows(sql + (' WHERE e.day=?' if day else '') + ' ORDER BY e.day DESC,e.id DESC', (day,) if day else ())

    def save_organization(self, values):
        required = ('seller', 'seller_unp', 'seller_address', 'seller_bank', 'seller_bic', 'seller_iban')
        if not all(values.get(k, '').strip() for k in required):
            raise ValueError('Заполните наименование, УНП, адрес, банк, БИК и IBAN')
        unp = values['seller_unp'].strip()
        bic = values['seller_bic'].strip().upper()
        iban = values['seller_iban'].replace(' ', '').upper()
        if not re.fullmatch(r'\d{9}', unp):
            raise ValueError('УНП должен содержать 9 цифр')
        if not re.fullmatch(r'[A-Z]{4}BY[A-Z0-9]{2}([A-Z0-9]{3})?', bic):
            raise ValueError('БИК банка Беларуси: 8 или 11 символов, код страны BY')
        if not re.fullmatch(r'BY\d{2}[A-Z0-9]{24}', iban):
            raise ValueError('Белорусский IBAN: BY и всего 28 символов')
        rearranged = iban[4:] + iban[:4]
        numeric = ''.join(str(ord(c)-55) if c.isalpha() else c for c in rearranged)
        if int(numeric) % 97 != 1:
            raise ValueError('Контрольные цифры IBAN не совпадают')
        values = {**values, 'seller_unp': unp, 'seller_bic': bic, 'seller_iban': iban}
        values['seller_details'] = '\n'.join(filter(None, [f'УНП {unp}', values['seller_address'],
            values['seller_bank'], f'БИК {bic}', f'IBAN {iban}', values.get('seller_director', ''),
            values.get('seller_phone', ''), values.get('seller_email', '')]))
        with self.conn:
            for key, value in values.items():
                self.conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))
