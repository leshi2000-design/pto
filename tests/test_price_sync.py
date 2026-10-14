import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import pytest
from smetagaz import price_sync as ps
from smetagaz.database import DatabaseManager

PAGES = {
    'https://shop.by/a': '<html><body><h1>Труба</h1><span class="price">12,50 руб.</span></body></html>',
    'https://shop.by/b': '<html><head><meta property="product:price:amount" content="99.90"></head></html>',
    'https://shop.by/c': '<span class="price">7000 руб.</span>',                        # резкий скачок
    'https://other.by/d': '<html>без цены</html>',
}


def fetcher(url, timeout=8):
    if url not in PAGES:
        raise ConnectionError('нет связи')
    return PAGES[url]


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def add(db, name, price, url, selector=''):
    return db.execute("INSERT INTO materials(name,unit,price,url,price_selector,item_type) VALUES(?,?,?,?,?,'Материал')", (name, 'шт', price, url, selector)).lastrowid


def test_check_apply_and_history(db):
    a = add(db, 'Труба', 10.0, 'https://shop.by/a', '.price')
    b = add(db, 'Муфта', 99.9, 'https://shop.by/b')          # без селектора: стандартная разметка; цена не изменилась
    c = add(db, 'Кран', 100.0, 'https://shop.by/c', '.price')
    d = add(db, 'Без цены', 5.0, 'https://other.by/d')
    e = add(db, 'Недоступно', 5.0, 'https://offline.by/x')
    results = {r['id']: r for r in ps.check_many(db, [a, b, c, d, e], fetcher=fetcher, pause=0)}
    assert results[a]['status'] == 'changed' and results[a]['new'] == 12.5
    assert results[b]['status'] == 'same'
    assert results[c]['status'] == 'suspicious'                  # скачок в 70 раз не применяется автоматически
    assert results[d]['status'] == 'error' and 'не найдена' in results[d]['message']
    assert results[e]['status'] == 'error' and 'нет связи' in results[e]['message']
    assert db.fetchone('SELECT price FROM materials WHERE id=?', (a,))[0] == 10.0          # проверка ничего не меняет
    assert ps.apply_prices(db, [(a, 12.5)]) == 1
    assert db.fetchone('SELECT price FROM materials WHERE id=?', (a,))[0] == 12.5
    assert [(h[1], h[2]) for h in ps.history(db, a)] == [(10.0, 12.5)]
    ps.mark_checked(db, list(results.values()))
    assert db.fetchone('SELECT price_status FROM materials WHERE id=?', (e,))[0].startswith('Ошибка')


def test_domain_selector_is_remembered(db):
    a = add(db, 'Труба', 10.0, 'https://shop.by/a')
    ps.remember_selector(db, a, 'https://shop.by/a', '.price')
    b = add(db, 'Другая труба', 10.0, 'https://www.shop.by/zzz')       # другой товар того же сайта получает селектор сайта
    assert ps.selector_for(db, b)[1] == '.price' and ps.domain_of('https://www.shop.by/zzz') == 'shop.by'


def test_dialog_applies_checked_rows(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: None)
    a = add(db, 'Труба', 10.0, 'https://shop.by/a', '.price')
    risky = add(db, 'Кран', 100.0, 'https://shop.by/c', '.price')
    import smetagaz.price_sync_view as pv
    dlg = pv.PriceUpdateDialog(None)
    assert dlg.ids == [a, risky]
    results = [dict(id=a, name='Труба', url='u', old=10.0, new=12.5, status='changed', message=''),
               dict(id=risky, name='Кран', url='u', old=100.0, new=7000.0, status='suspicious', message='скачок')]
    dlg.show_results(results)
    assert dlg.table.rowCount() == 2 and dlg.btn_apply.isEnabled() and dlg.table.item(0, 4).text() == '+25.0%'
    assert dlg.table.item(0, 0).checkState().name == 'Checked' and dlg.table.item(1, 0).checkState().name == 'Unchecked'     # резкое изменение не отмечено
    dlg.apply()
    assert db.fetchone('SELECT price FROM materials WHERE id=?', (a,))[0] == 12.5 and db.fetchone('SELECT price FROM materials WHERE id=?', (risky,))[0] == 100.0


def test_material_card_has_link_and_selector(db, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ps, 'fetch', fetcher)
    mid = add(db, 'Труба', 10.0, '')
    import smetagaz.material_card as mc
    card = mc.MaterialCardDialog(mid)
    card.input_url.setText('https://shop.by/a')
    card.input_price_selector.setText('.price')
    card.check_price_now()
    assert card.input_price.text() == '12.50'           # цена подставлена с сайта
    card.save_data()
    assert db.fetchone('SELECT price,price_selector,url FROM materials WHERE id=?', (mid,)) == (12.5, '.price', 'https://shop.by/a')
    assert db.fetchone('SELECT price_selector FROM price_sources WHERE domain=?', ('shop.by',))[0] == '.price'
