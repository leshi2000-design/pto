"""Справочник: цена материала = закупка + НДС + надбавка; НДС по галочке; надбавка вычисляется или вводится вручную; цены закупки и продажи обязательны."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from decimal import Decimal

import pytest

from smetagaz import material_pricing as mp
from smetagaz.database import DatabaseManager


def test_calc_auto_and_manual():
    r = mp.calc(100, True, 20, 'auto', price=150)
    assert (r['vat'], r['markup'], r['markup_pct'], r['price']) == (Decimal('20.00'), Decimal('30.00'), Decimal('30.00'), Decimal('150.00'))        # 100 + 20 НДС + 30 надбавка = 150
    r = mp.calc(100, False, 20, 'auto', price=150)
    assert r['vat'] == 0 and r['markup'] == Decimal('50.00')
    r = mp.calc(100, True, 20, 'manual', markup=30)
    assert r['price'] == Decimal('150.00') and r['markup_pct'] == Decimal('30.00')
    assert mp.calc(80, True, 20, 'auto', price=90)['markup'] == Decimal('-6.00')                         # ниже закупки с НДС — отрицательная надбавка
    assert mp.calc(0, True, 20, 'auto', price=10)['markup_pct'] == 0
    assert mp.markup_from_percent(200, 15) == Decimal('30.00')
    with pytest.raises(ValueError):
        mp.calc(1, False, 20, 'x')


def test_required_prices_for_material_only():
    mp.validate('Работа', 0, 0)
    mp.validate('Материал', 5, 7)
    for p, s, text in ((0, 7, 'закупки'), (5, 0, 'продажи'), ('', 7, 'закупки')):
        with pytest.raises(ValueError, match=text):
            mp.validate('Материал', p, s)


@pytest.fixture
def card_env(tmp_path, monkeypatch):
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    import smetagaz.material_card as mc
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and getattr(mod, 'db', None) is not None and mod.db.__class__.__name__ == 'DatabaseManager':
            monkeypatch.setattr(mod, 'db', d, raising=False)
    from PyQt6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    seen = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: seen.append(a[2]))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    yield d, mc, seen
    d.close()


def new_card(d, mc, **cols):
    mid = d.execute("INSERT INTO materials(name,unit,price,purchase_price,item_type) VALUES('Кран','шт',?,?,?)", (cols.get('price', 0), cols.get('purchase', 0), cols.get('type', 'Материал'))).lastrowid
    return mid, mc.MaterialCardDialog(mid)


def test_card_auto_mode_computes_markup_and_saves(card_env):
    d, mc, seen = card_env
    mid, card = new_card(d, mc)
    card.input_purchase.setText('100')
    card.input_purchase.textEdited.emit('100')
    card.input_price.setText('150')
    card.input_price.textEdited.emit('150')
    card.chk_vat.setChecked(True)                                                       # НДС 20 % от закупки
    assert card.lbl_vat.text() == 'НДС: 20.00 руб.' and card.input_markup.text() == '30.00' and card.input_markup_pct.text() == '30.00' and '= продажа 150.00' in card.lbl_formula.text()
    assert card.input_price.isReadOnly() is False and card.input_markup.isReadOnly() is True
    card.save_data()
    assert d.fetchone('SELECT price,purchase_price,vat_on,vat_pct,markup_mode,markup FROM materials WHERE id=?', (mid,)) == (150.0, 100.0, 1, 20.0, 'auto', 30.0)
    card.chk_vat.setChecked(False)                                                      # без НДС надбавка вся разница
    assert card.input_markup.text() == '50.00'


def test_card_manual_mode_computes_price_from_markup_rub_or_percent(card_env):
    d, mc, seen = card_env
    mid, card = new_card(d, mc)
    card.input_purchase.setText('200')
    card.input_purchase.textEdited.emit('200')
    card.chk_vat.setChecked(True)
    card.combo_markup.setCurrentIndex(card.combo_markup.findData('manual'))
    assert card.input_price.isReadOnly() and not card.input_markup.isReadOnly()
    card.input_markup.setText('50')
    card.input_markup.textEdited.emit('50')                                             # 200 + 40 НДС + 50 = 290
    assert card.input_price.text() == '290.00' and card.input_markup_pct.text() == '25.00'
    card.input_markup_pct.setText('10')
    card.input_markup_pct.textEdited.emit('10')                                         # 10 % от закупки = 20 руб → 260
    assert card.input_markup.text() == '20.00' and card.input_price.text() == '260.00'
    card.save_data()
    assert d.fetchone('SELECT price,vat_on,markup_mode,markup FROM materials WHERE id=?', (mid,)) == (260.0, 1, 'manual', 20.0)
    again = mc.MaterialCardDialog(mid)                                                  # при повторном открытии режим и надбавка сохранены
    assert again.combo_markup.currentData() == 'manual' and again.input_markup.text() == '20.00' and again.input_price.text() == '260.00' and again.chk_vat.isChecked()
    d.execute('UPDATE materials SET price=300 WHERE id=?', (mid,))                      # цену изменили в обход карточки (обновление с сайта) — надбавка считается заново
    third = mc.MaterialCardDialog(mid)
    assert third.combo_markup.currentData() == 'auto' and third.input_markup.text() == '60.00'


def test_card_requires_purchase_and_price_for_material_and_warns_on_loss(card_env):
    d, mc, seen = card_env
    mid, card = new_card(d, mc)
    card.input_name.setText('Кран')
    card.input_price.setText('10')
    card.input_price.textEdited.emit('10')
    card.save_data()
    assert any('закупки' in str(x) for x in seen) and d.fetchone('SELECT price FROM materials WHERE id=?', (mid,))[0] == 0              # без закупки не сохраняется
    card.input_purchase.setText('8')
    card.input_purchase.textEdited.emit('8')
    card.input_price.setText('0')
    card.input_price.textEdited.emit('0')
    card.save_data()
    assert any('продажи' in str(x) for x in seen)
    card.chk_vat.setChecked(True)
    card.input_price.setText('9')
    card.input_price.textEdited.emit('9')                                               # 8 + 1,60 НДС > 9 — убыток, подтверждение (в тесте «Да»)
    assert 'убыток' in card.lbl_formula.text()
    card.save_data()
    assert d.fetchone('SELECT price,markup FROM materials WHERE id=?', (mid,)) == (9.0, -0.6)
    work_id, work = new_card(d, mc, type='Работа')                                      # у работы цены закупки/продажи не обязательны, блок цены скрыт
    assert work.grp_price.isHidden() or not work.grp_price.isVisibleTo(work)
    work.input_name.setText('Монтаж')
    work.save_data()
    assert d.fetchone('SELECT name FROM materials WHERE id=?', (work_id,))[0] == 'Монтаж'
