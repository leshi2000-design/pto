"""Price import and bounded supplier category crawls; never changes stock."""
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urldefrag
from decimal import Decimal
import csv
import hashlib
import json
import re
import time
import requests
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from .core import scaled


def read_price(path):
    path = Path(path)
    if path.suffix.lower() == '.xlsx':
        book = load_workbook(path, read_only=True, data_only=True)
        try:
            rows = list(book.active.values)
        finally:
            book.close()
    elif path.suffix.lower() == '.csv':
        text = path.read_text(encoding='utf-8-sig')
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(text.splitlines(), dialect))
    else:
        raise ValueError('Поддерживаются XLSX и CSV (UTF-8)')
    if len(rows) < 2:
        raise ValueError('Прайс пуст: нужны заголовок и товары')
    return [str(v or '').strip() for v in rows[0]], rows[1:]


def import_price(store, path, mapping, supplier, currency='BYN'):
    headers, rows = read_price(path)
    prepared = []
    errors = []
    for number, row in enumerate(rows, 2):
        if not any(v is not None and str(v).strip() for v in row):
            continue
        try:
            def value(key, default=''):
                index = mapping.get(key)
                return str(row[index]).strip() if index is not None and index < len(row) and row[index] is not None else default
            name, sku = value('name'), value('sku')
            if not name or not sku:
                raise ValueError('Нужны название и артикул')
            cents = scaled(value('price'), 100)
            prepared.append((sku, name, value('unit', 'шт') or 'шт', cents))
        except (ValueError, IndexError) as exc:
            errors.append(f'Строка {number}: {exc}')
    if errors:
        raise ValueError('Импорт не выполнен.\n' + '\n'.join(errors[:20]))
    if not prepared or not supplier.strip() or not currency.strip():
        raise ValueError('Укажите поставщика, валюту и непустой прайс')
    # One transaction: no partial catalog on malformed input.
    source = 'file:' + Path(path).name
    with store.conn:
        for sku, name, unit, cents in prepared:
            store.conn.execute('INSERT INTO products(sku,name,unit) VALUES(?,?,?) ON CONFLICT(sku) DO NOTHING', (sku, name, unit))
            pid = store.conn.execute('SELECT id FROM products WHERE sku=?', (sku,)).fetchone()[0]
            store.conn.execute('''INSERT INTO offers(product_id,supplier,price,currency,source) VALUES(?,?,?,?,?)
                ON CONFLICT(product_id,supplier,currency,source) DO UPDATE SET price=excluded.price,updated=CURRENT_TIMESTAMP''',
                (pid, supplier, cents, currency, source))
    return len(prepared)


def price_text(text):
    cleaned = str(text).replace('\xa0', '').replace(' ', '').replace(',', '.')
    match = re.search(r'\d+(?:\.\d+)?', cleaned)
    if not match:
        raise ValueError('Цена не распознана')
    return Decimal(scaled(match.group(), 100)) / 100


def products_from_html(text, url, config):
    soup = BeautifulSoup(text, 'html.parser')
    results = []
    def walk(node):
        if isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, dict):
            typ = node.get('@type', '')
            if typ == 'Product' or isinstance(typ, list) and 'Product' in typ:
                offers = node.get('offers', {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                raw_price = offers.get('price')
                if node.get('name') and raw_price is not None:
                    results.append({'name': str(node['name']), 'sku': str(node.get('sku') or node.get('productID') or ''),
                                    'price': str(price_text(raw_price)), 'currency': offers.get('priceCurrency') or config['currency'],
                                    'url': urljoin(url, node.get('url') or url), 'unit': 'шт'})
            for value in node.values():
                if isinstance(value, (list, dict)):
                    walk(value)
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            walk(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError):
            continue
    if not results:
        selector = config.get('card_selector', '')
        cards = soup.select(selector) if selector else [soup]
        for card in cards:
            name = card.select_one(config.get('name_selector') or 'h1, [itemprop="name"]')
            price = card.select_one(config.get('price_selector') or '[itemprop="price"], .price')
            if name is None or price is None:
                continue
            sku_node = card.select_one(config['sku_selector']) if config.get('sku_selector') else None
            link = card.select_one('a[href]') if selector else None
            try:
                results.append({'name': name.get_text(' ', strip=True),
                                'sku': sku_node.get_text(strip=True) if sku_node else '',
                                'price': str(price_text(price.get('content') or price.get_text(' ', strip=True))),
                                'currency': config['currency'], 'url': urljoin(url, link['href']) if link else url,
                                'unit': config.get('unit', 'шт')})
            except ValueError:
                continue
    return results, soup


def crawl(config, progress=lambda text: None):
    starts = [line.strip() for line in config['categories'].splitlines() if line.strip()]
    if not starts or not config['supplier'].strip():
        raise ValueError('Нужны поставщик и адреса категорий')
    origin = urlsplit(config['url'])
    if origin.scheme not in ('http', 'https') or not origin.hostname or origin.username:
        raise ValueError('Укажите HTTP/HTTPS адрес сайта без пароля')
    prefixes = []
    for start in starts:
        parsed = urlsplit(start)
        if parsed.hostname != origin.hostname or parsed.scheme not in ('http', 'https'):
            raise ValueError('Категории должны быть на том же сайте')
        prefixes.append(parsed.path.rstrip('/'))
    queue = deque(starts)
    seen = set()
    found = {}
    errors = []
    max_pages = min(max(int(config.get('max_pages', 30)), 1), 300)
    session = requests.Session()
    session.headers['User-Agent'] = 'MagazinPriceReader/1.0'
    try:
        while queue and len(seen) < max_pages:
            url = urldefrag(queue.popleft())[0]
            if url in seen:
                continue
            seen.add(url)
            progress(f'Страница {len(seen)}/{max_pages}: {url}')
            try:
                # Validate every redirect: category crawl stays on its configured host.
                current = url
                for _ in range(6):
                    response = session.get(current, timeout=(10, 20), allow_redirects=False)
                    if response.is_redirect:
                        current = urljoin(current, response.headers['Location'])
                        if urlsplit(current).hostname != origin.hostname:
                            raise ValueError('Перенаправление на другой сайт')
                    else:
                        break
                else:
                    raise ValueError('Слишком много перенаправлений')
                response.raise_for_status()
                if len(response.content) > 5 * 1024**2:
                    raise ValueError('Страница слишком большая')
                products, soup = products_from_html(response.text, current, config)
                for product in products:
                    key = product['sku'] or product['url']
                    found[key] = product
                links = soup.select(config['link_selector']) if config.get('link_selector') else soup.select('a[href]')
                product_links = {urljoin(current, link['href']) for link in soup.select(
                    'a[itemprop="url"][href], [itemtype*="Product"] a[href], .product a[href], .product-card a[href], .product-item a[href]')}
                if config.get('card_selector'):
                    for card in soup.select(config['card_selector']):
                        product_links.update(urljoin(current, link['href']) for link in card.select('a[href]'))
                for link in links:
                    if not link.get('href'):
                        continue
                    target = urldefrag(urljoin(current, link['href']))[0]
                    parsed = urlsplit(target)
                    within = any(parsed.path == p or parsed.path.startswith(p + '/') for p in prefixes)
                    if parsed.hostname == origin.hostname and parsed.scheme in ('http', 'https') and (within or target in product_links or config.get('link_selector')):
                        if target not in seen and len(queue) < max_pages * 10:
                            queue.append(target)
            except (requests.RequestException, ValueError, KeyError) as exc:
                errors.append(f'{url}: {exc}')
            time.sleep(0.3)
    finally:
        session.close()
    if not found:
        raise ValueError('Товары не найдены. Проверьте категории и селекторы. Сайт может требовать JavaScript или вход.\n' + '\n'.join(errors[:5]))
    return list(found.values()), errors, bool(queue)


def apply_web_prices(store, config, products):
    count = 0
    with store.conn:
        for product in products:
            # No fuzzy merging: supplier IDs may collide with IDs in other suppliers.
            source = product['url']
            existing = store.conn.execute('SELECT product_id FROM offers WHERE supplier=? AND source=?',
                                          (config['supplier'], source)).fetchone()
            pid = existing[0] if existing else None
            if pid is None:
                sku = 'WEB-' + hashlib.sha256((config['supplier'] + ':' + (product['sku'] or source)).encode()).hexdigest()[:16]
                store.conn.execute('INSERT INTO products(sku,name,unit,category) VALUES(?,?,?,?) ON CONFLICT(sku) DO NOTHING',
                                   (sku, product['name'], product['unit'], config.get('category_name', 'Из интернета')))
                pid = store.conn.execute('SELECT id FROM products WHERE sku=?', (sku,)).fetchone()[0]
            cents = scaled(product['price'], 100)
            store.conn.execute('''INSERT INTO offers(product_id,supplier,price,currency,source) VALUES(?,?,?,?,?)
                ON CONFLICT(product_id,supplier,currency,source) DO UPDATE SET price=excluded.price,updated=CURRENT_TIMESTAMP''',
                (pid, config['supplier'], cents, product['currency'], source))
            count += 1
    return count
