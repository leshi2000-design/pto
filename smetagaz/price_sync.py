"""Автоматическое обновление цен справочника материалов по ссылкам на страницы поставщиков.
Цена читается со страницы: по CSS-селектору (общему для сайта или своему у позиции), а если он не задан или не сработал — из стандартной разметки
(schema.org / Open Graph / JSON-LD). Новая цена не применяется автоматически: пользователь видит «было → стало» и подтверждает. Модуль не зависит от Qt."""
import json
import re
import time
from datetime import datetime
from urllib.parse import urlparse

from .lazy import LazyModule

requests = LazyModule('requests')
_bs4 = LazyModule('bs4')

SUSPICIOUS_RATIO = 3.0           # цена изменилась более чем в 3 раза — требует проверки
MAX_PAGE_BYTES = 3 * 1024 * 1024
STATUS_TEXT = {'changed': 'Цена изменилась', 'same': 'Без изменений', 'suspicious': 'Проверьте: резкое изменение', 'error': 'Ошибка'}


def migrate(db):
    cols = {r[1] for r in db.fetchall('PRAGMA table_info(materials)')}
    for name, ddl in (('price_selector', "TEXT DEFAULT ''"), ('price_checked_at', "TEXT DEFAULT ''"), ('price_status', "TEXT DEFAULT ''")):
        if name not in cols:
            db.execute(f'ALTER TABLE materials ADD COLUMN {name} {ddl}')
    db.execute("""CREATE TABLE IF NOT EXISTS price_history(id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
                  checked_at TEXT NOT NULL, old_price REAL, new_price REAL, source TEXT DEFAULT '')""")
    db.execute('CREATE INDEX IF NOT EXISTS idx_price_history_material ON price_history(material_id,checked_at)')
    db.execute("""CREATE TABLE IF NOT EXISTS price_sources(domain TEXT PRIMARY KEY, price_selector TEXT DEFAULT '', note TEXT DEFAULT '')""")


def domain_of(url):
    host = urlparse(str(url or '').strip()).netloc.lower()
    return host[4:] if host.startswith('www.') else host


def parse_price(text):
    """'1 250,50 руб.' / 'BYN 12.30' / '1.250,50' -> float или None."""
    raw = str(text or '').replace('\xa0', ' ').replace(' ', ' ')
    match = re.search(r'\d(?:[\d\s.,]*\d)?', raw)
    if not match:
        return None
    number = match.group(0).replace(' ', '')
    if ',' in number and '.' in number:                 # «1.250,50» или «1,250.50»: последний разделитель — десятичный
        number = number.replace('.', '').replace(',', '.') if number.rfind(',') > number.rfind('.') else number.replace(',', '')
    else:
        number = number.replace(',', '.')
    try:
        value = float(number)
    except ValueError:
        return None
    return value if value > 0 else None


def _from_node(node):
    if node is None:
        return None
    for attr in ('content', 'value', 'data-price'):
        if node.get(attr):
            price = parse_price(node.get(attr))
            if price:
                return price
    return parse_price(node.get_text(' ', strip=True))


def _json_ld_prices(soup):
    prices = []

    def walk(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in ('price', 'lowPrice') and isinstance(value, (str, int, float)):
                    price = parse_price(value)
                    if price:
                        prices.append(price)
                else:
                    walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            walk(json.loads(script.string or script.get_text() or ''))
        except ValueError:
            continue
    return prices


def extract_price(html, selector=''):
    """(цена, способ) или (None, причина)."""
    soup = _bs4.BeautifulSoup(html or '', 'html.parser')
    selector = str(selector or '').strip()
    if selector:
        try:
            found = soup.select_one(selector)
        except Exception:
            return None, 'Некорректный селектор цены'
        price = _from_node(found)
        if price:
            return price, 'селектор'
    for sel in ("[itemprop='price']", "meta[property='product:price:amount']", "meta[property='og:price:amount']", "meta[name='twitter:data1']"):
        price = _from_node(soup.select_one(sel))
        if price:
            return price, 'разметка страницы'
    ld = _json_ld_prices(soup)
    if ld:
        return ld[0], 'JSON-LD'
    return None, ('Цена по селектору не найдена' if selector else 'Цена на странице не найдена: укажите селектор цены')


def fetch(url, timeout=8):
    """Загружает страницу (с ограничением размера). Бросает исключение при ошибке сети или кода ответа."""
    if not str(url).lower().startswith(('http://', 'https://')):
        raise ValueError('Ссылка должна начинаться с http:// или https://')
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (PTO price check)', 'Accept-Language': 'ru,en;q=0.8'}, timeout=timeout, stream=True)
    response.raise_for_status()
    body = response.raw.read(MAX_PAGE_BYTES + 1, decode_content=True)
    if len(body) > MAX_PAGE_BYTES:
        raise ValueError('Страница слишком большая')
    encoding = response.encoding or response.apparent_encoding or 'utf-8'
    return body.decode(encoding, 'replace')


def selector_for(db, mid):
    row = db.fetchone('SELECT url,coalesce(price_selector,\'\') FROM materials WHERE id=?', (mid,))
    if not row:
        return '', ''
    if row[1]:
        return row[0] or '', row[1]
    source = db.fetchone('SELECT price_selector FROM price_sources WHERE domain=?', (domain_of(row[0]),))
    return row[0] or '', (source[0] if source else '')


def remember_selector(db, mid, url, selector):
    """Запоминает селектор цены для позиции и как умолчание для сайта."""
    selector = str(selector or '').strip()
    if not selector:
        return
    db.execute('UPDATE materials SET price_selector=? WHERE id=?', (selector, mid))
    if domain_of(url):
        db.execute('INSERT INTO price_sources(domain,price_selector) VALUES(?,?) ON CONFLICT(domain) DO UPDATE SET price_selector=excluded.price_selector', (domain_of(url), selector))


def check_material(db, mid, fetcher=fetch):
    """Проверяет одну позицию, ничего не записывая: dict(id,name,url,old,new,status,message)."""
    row = db.fetchone('SELECT name,coalesce(price,0) FROM materials WHERE id=?', (mid,))
    url, selector = selector_for(db, mid)
    result = dict(id=mid, name=row[0] if row else '', url=url, old=float(row[1]) if row else 0.0, new=None, status='error', message='')
    if not row or not url:
        result['message'] = 'Не указана ссылка'
        return result
    try:
        price, how = extract_price(fetcher(url), selector)
    except Exception as e:
        result['message'] = str(e)[:200]
        return result
    if price is None:
        result['message'] = how
        return result
    result['new'] = round(price, 2)
    old = result['old']
    if abs(result['new'] - old) < 0.005:
        result.update(status='same', message='Цена та же')
    elif old > 0 and (result['new'] / old > SUSPICIOUS_RATIO or result['new'] / old < 1 / SUSPICIOUS_RATIO):
        result.update(status='suspicious', message=f'Цена изменилась более чем в {SUSPICIOUS_RATIO:g} раза ({how}) — проверьте ссылку и селектор')
    else:
        result.update(status='changed', message=f'Источник: {how}')
    return result


def check_many(db, ids, ctx=None, fetcher=fetch, pause=0.6):
    """Проверка набора позиций с прогрессом; между запросами к одному сайту пауза. ctx — background.Context (необязательно)."""
    results, last_request = [], {}
    ids = list(ids)
    for n, mid in enumerate(ids, 1):
        row = db.fetchone('SELECT name FROM materials WHERE id=?', (mid,))
        if ctx:
            ctx.progress(n - 1, len(ids), f'{n} из {len(ids)}: {row[0] if row else mid}')
        url, _selector = selector_for(db, mid)
        host = domain_of(url)
        if host in last_request and pause:
            wait = pause - (time.monotonic() - last_request[host])
            if wait > 0:
                time.sleep(wait)
        results.append(check_material(db, mid, fetcher))
        last_request[host] = time.monotonic()
    if ctx:
        ctx.progress(len(ids), len(ids), 'Готово')
    return results


def apply_prices(db, changes, now=None):
    """changes: [(material_id, новая_цена)]. Записывает цену, историю и время проверки; возвращает число обновлённых позиций."""
    now = (now or datetime.now()).isoformat(timespec='seconds')
    count = 0
    with db.transaction():
        for mid, new in changes:
            row = db.fetchone('SELECT coalesce(price,0),url FROM materials WHERE id=?', (mid,))
            if not row or not new or float(new) <= 0:
                continue
            db.execute('INSERT INTO price_history(material_id,checked_at,old_price,new_price,source) VALUES(?,?,?,?,?)', (mid, now, row[0], float(new), row[1] or ''))
            db.execute("UPDATE materials SET price=?,price_checked_at=?,price_status='обновлено' WHERE id=?", (round(float(new), 2), now, mid))
            count += 1
    return count


def mark_checked(db, results, now=None):
    """Запоминает время и итог проверки для всех проверенных позиций (в том числе без изменений и с ошибками)."""
    now = (now or datetime.now()).isoformat(timespec='seconds')
    with db.transaction():
        for r in results:
            db.execute('UPDATE materials SET price_checked_at=?,price_status=? WHERE id=?', (now, STATUS_TEXT.get(r['status'], '') if r['status'] != 'error' else 'Ошибка: ' + r['message'][:80], r['id']))


def history(db, mid, limit=50):
    return db.fetchall('SELECT checked_at,old_price,new_price,source FROM price_history WHERE material_id=? ORDER BY checked_at DESC,id DESC LIMIT ?', (mid, limit))


def linked_material_ids(db, category_id=None):
    sql = "SELECT id FROM materials WHERE coalesce(url,'')<>''" + (' AND category_id=?' if category_id else '') + ' ORDER BY id'
    return [r[0] for r in db.fetchall(sql, (category_id,) if category_id else ())]
