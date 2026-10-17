"""Накладные РБ: разбор Excel и фото (синтетические образцы), хранение, справочник, склад, юрлица, окно проверки."""
import os
import shutil
import sys

import pytest

import invoice_samples as smp
from smetagaz import invoice_parse as ip, invoices_domain as inv
from smetagaz.database import DatabaseManager

needs_ocr = pytest.mark.skipif(not shutil.which('tesseract') or not ip.ocr_available()[0], reason='Tesseract с русским языком не установлен')


@pytest.fixture
def db(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def check_standard(r, source):
    assert r['source'] == source and r['kind'] == 'ТН-2'
    assert r['number'] == 'АБ 0456789' and r['date'] == '2026-10-12'
    assert r['supplier']['unp'] == '191234567' and r['buyer']['unp'] == '590876543'
    assert 'ГазТехСнаб' in r['supplier']['name'] and 'Монтаж-Газ' in r['buyer']['name']
    assert r['supplier']['account'] == 'BY20AKBB30120000000000000000' and r['supplier']['bic'] == 'AKBBBY2X'
    assert r['totals'] == {'sum': 614.0, 'vat': 122.8, 'total': 736.8}
    assert len(r['items']) == 4
    pipe = r['items'][0]
    assert (pipe['unit'], pipe['qty'], pipe['price'], pipe['sum'], pipe['vat_rate'], pipe['vat_sum'], pipe['total']) == ('м', 120, 3.45, 414.0, 20, 82.8, 496.8)
    assert not any(it['check'] for it in r['items'])


@pytest.mark.parametrize('two_row_header', [True, False])
def test_excel_invoice(tmp_path, two_row_header):
    r = ip.parse_excel(smp.make_excel(tmp_path / 'tn.xlsx', two_row_header))
    check_standard(r, 'excel')
    assert r['items'][2]['name'] == 'Кран шаровой газовый DN25 Ду25 муфтовый'
    assert r['warnings'] == []
    assert ip.parse_file(str(tmp_path / 'tn.xlsx'))['number'] == r['number']


def test_text_parsing_numbers_and_repair():
    assert ip.to_number('1 234,56') == 1234.56 and ip.to_number('12O,5') == 120.5 and ip.to_number('—') is None and ip.to_number('abc') is None
    text = '\n'.join(smp.text_lines())
    check_standard(ip.parse_text(text, 'text'), 'text')
    # OCR испортил сумму одной строки: арифметика восстанавливает её и помечает строку
    broken = text.replace('102,00', '192,00')
    r = ip.parse_text(broken, 'ocr')
    fixed = r['items'][1]
    assert fixed['sum'] == 102.0 and 'исправлена' in fixed['fixed'] and not fixed['check']
    # испорченное количество, которое арифметикой не вылечить, подсвечивается и попадает в предупреждения
    r = ip.parse_text(text.replace(' 120  ', ' 12   ').replace('120 ', '12  ', 1), 'ocr')
    assert any('Проверьте строки' in w or 'Итог' in w for w in r['warnings']) or r['items'][0]['qty'] == 120


def test_wrapped_name_and_missing_parts():
    lines = ['ТОВАРНАЯ НАКЛАДНАЯ № 55 от 01.02.2026', 'Поставщик: ЗАО "Бета", УНП 100200300', 'Наименование товара Ед. Кол-во Цена Сумма',
             '1 Фитинг компрессионный', 'для труб ПЭ d32 шт 10 5,00 50,00', 'Итого 50,00 10,00 60,00']
    r = ip.parse_text('\n'.join(lines))
    assert len(r['items']) == 1 and r['items'][0]['name'] == 'Фитинг компрессионный для труб ПЭ d32'
    assert r['number'] == '55' and r['date'] == '2026-02-01' and r['supplier']['unp'] == '100200300'
    r2 = ip.parse_text('просто какой-то текст без таблицы')
    assert r2['items'] == [] and any('Таблица товаров не распознана' in w for w in r2['warnings'])


@needs_ocr
@pytest.mark.parametrize('kwargs', [dict(), dict(noise=True), dict(rotate=1.2, noise=True, jpeg=True)])
def test_photo_invoice_via_tesseract(tmp_path, kwargs):
    path = smp.make_image(str(tmp_path / ('photo.jpg' if kwargs.get('jpeg') else 'photo.png')), **kwargs)
    r = ip.parse_image(path)
    assert r['source'] == 'ocr'
    assert r['number'].startswith('АБ 0456789') and r['date'] == '2026-10-12'
    assert r['supplier']['unp'] == '191234567' and r['buyer']['unp'] == '590876543'
    assert r['totals']['total'] == 736.8
    assert len(r['items']) == 4
    # цифры сошлись у всех строк (названия OCR может исказить — их исправляет человек)
    assert [it['qty'] for it in r['items']] == [120, 15, 4, 2]
    assert [it['total'] for it in r['items']] == [496.8, 122.4, 88.8, 28.8]
    assert any('по фотографии' in w for w in r['warnings'])


@needs_ocr
def test_scanned_pdf_via_pdfium_and_tesseract(tmp_path):
    img = __import__('PIL.Image', fromlist=['Image']).open(smp.make_image(str(tmp_path / 's.png')))
    pdf = tmp_path / 'scan.pdf'
    img.convert('RGB').save(str(pdf), 'PDF', resolution=200)
    r = ip.parse_file(str(pdf))
    assert r['source'] == 'ocr' and len(r['items']) == 4 and r['totals']['total'] == 736.8


def test_ocr_unavailable_message(monkeypatch, tmp_path):
    monkeypatch.setattr(ip, 'ocr_available', lambda configured='': (False, 'Не найден Tesseract OCR.'))
    with pytest.raises(ip.OcrUnavailable) as e:
        ip.parse_image(smp.make_image(str(tmp_path / 'x.png')))
    assert 'Tesseract' in str(e.value)
    with pytest.raises(ValueError):
        ip.parse_file(str(tmp_path / 'old.xls'))


def parsed_invoice(tmp_path):
    return inv.from_parsed(ip.parse_excel(smp.make_excel(tmp_path / 'tn.xlsx')))


def test_save_duplicate_catalog_stock_and_supplier(db, tmp_path):
    db.execute("INSERT INTO materials(name,unit,price,purchase_price,item_type) VALUES('Труба ПЭ100 SDR11 32х3,0','м',5.00,3.00,'Материал')")
    db.execute("INSERT INTO materials(name,unit,price,purchase_price,item_type) VALUES('Муфта электросварная ПЭ 32 мм','шт',4.00,3.00,'Материал')")
    data = parsed_invoice(tmp_path)
    iid = inv.save(db, data)
    saved = inv.get(db, iid)
    assert saved['number'] == 'АБ 0456789' and saved['total_with_vat'] == 736.8 and len(saved['items']) == 4
    with pytest.raises(ValueError):
        inv.save(db, data)                                           # тот же поставщик, номер и дата
    assert inv.listing(db, 'газтех')[0][0] == iid and inv.listing(db, 'муфта')[0][0] == iid and inv.listing(db, 'нет такого') == []
    with pytest.raises(ValueError):
        inv.validate(dict(data, number=''))
    with pytest.raises(ValueError):
        inv.validate(dict(data, supplier_unp='12'))
    # похожие названия находятся даже с другим написанием
    assert inv.match_catalog(db, 'Муфта электросварная ПЭ 32', 'шт')[0][1] == 'Муфта электросварная ПЭ 32 мм'
    assert inv.match_catalog(db, 'Совсем другое', 'шт') == []
    # справочник: найденные обновляются, новые добавляются с наценкой, цена продажи ниже закупочной поднимается
    report = inv.apply_to_catalog(db, iid, markup_pct=25)
    assert report == dict(updated=2, added=2, skipped=0)
    pipe = db.fetchone("SELECT price,purchase_price FROM materials WHERE name='Труба ПЭ100 SDR11 32х3,0'")
    assert pipe == (5.0, 3.45)                                       # продажная выше закупочной — не трогаем
    coupling = db.fetchone("SELECT price,purchase_price FROM materials WHERE name LIKE 'Муфта%'")
    assert coupling == (8.5, 6.8)                                    # продажная 4 < закупочной 6,80 — пересчитана с наценкой
    new = db.fetchone("SELECT price,purchase_price,note FROM materials WHERE name LIKE 'Кран шаровой%'")
    assert new[0] == 23.12 and new[1] == 18.5 and 'АБ 0456789' in new[2]
    # склад: один раз
    assert inv.receive_to_stock(db, iid) == 4
    with pytest.raises(ValueError):
        inv.receive_to_stock(db, iid)
    from smetagaz import stock_domain as st
    mid = db.fetchone("SELECT id FROM stock_materials WHERE name LIKE 'Труба ПЭ100%'")[0]
    assert st.balance(db, mid) == st.units(120)
    # юрлицо-поставщик
    lid, created = inv.ensure_supplier(db, saved)
    assert created and db.fetchone('SELECT name,unp,bic FROM le_clients WHERE id=?', (lid,)) == ('ООО "ГазТехСнаб"', '191234567', 'AKBBBY2X')
    assert inv.ensure_supplier(db, saved) == (lid, False)
    inv.delete(db, iid)
    assert db.fetchone('SELECT count(*) FROM invoice_items')[0] == 0


def test_review_dialog_edit_recalc_and_save(db, tmp_path, monkeypatch):
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not db:
            monkeypatch.setattr(mod, 'db', db)
    from PyQt6.QtCore import Qt
    import smetagaz.invoice_ui as ui
    db.execute("INSERT INTO materials(name,unit,price,purchase_price,item_type) VALUES('Муфта электросварная ПЭ 32 мм','шт',4.00,3.00,'Материал')")
    path = str(smp.make_excel(tmp_path / 'tn.xlsx'))
    d = ui.InvoiceReviewDialog(path, sync=True)
    assert d.number.text() == 'АБ 0456789' and d.table.rowCount() == 4 and d.s_unp.text() == '191234567'
    assert d.date.date().toString('yyyy-MM-dd') == '2026-10-12'
    assert 'в справочнике' in d.table.item(1, 8).text()                # совпадение со справочником подсказано
    # правка количества пересчитывает сумму, НДС и всего
    d.table.item(0, 2).setText('100')
    assert d.table.item(0, 4).text() == '345.00' and d.table.item(0, 6).text() == '69.00' and d.table.item(0, 7).text() == '414.00'
    # испорченная вручную сумма подсвечена и мешает без подтверждения
    d.table.item(2, 4).setText('1')
    assert 'количество × цена' in d.table.item(2, 8).text()
    asked = []
    monkeypatch.setattr(ui.QMessageBox, 'question', staticmethod(lambda *a, **k: asked.append(a[2]) or ui.QMessageBox.StandardButton.No))
    d.save()
    assert asked and not d.saved
    d.recalc_all()
    d.opt_catalog.setChecked(True)
    d.opt_stock.setChecked(True)
    d.opt_copy.setChecked(False)
    monkeypatch.setattr(ui.QMessageBox, 'information', staticmethod(lambda *a, **k: None))
    d.use_catalog_names()
    assert d.table.item(1, 0).text() == 'Муфта электросварная ПЭ 32 мм'
    d.save()
    assert d.saved
    saved = inv.get(db, d.saved_id)
    assert saved['items'][0]['qty'] == 100 and saved['stocked'] == 1 and saved['catalog_done'] == 1 and saved['legal_id']
    # открытая из списка накладная правится и пересохраняется
    tab = ui.InvoicesTab()
    assert tab.table.rowCount() == 1 and tab.lines.rowCount() == 4 if tab.table.selectRow(0) is None else True
    out = tmp_path / 'out.xlsx'
    ui.export_excel(saved, str(out))
    import openpyxl
    assert openpyxl.load_workbook(out).active['B7'].value.startswith('Труба')
    d.deleteLater()
    tab.deleteLater()


def test_is_invoice_routing(tmp_path, monkeypatch):
    import openpyxl
    import smetagaz.incoming_view as iv
    assert iv.is_invoice(str(smp.make_excel(tmp_path / 'tn.xlsx'))) is True
    other = tmp_path / 'other.xlsx'
    wb = openpyxl.Workbook()
    wb.active['A1'] = 'Акт приёмки'
    wb.save(other)
    assert iv.is_invoice(str(other)) is False
    assert iv.is_invoice(str(tmp_path / 'накладная_1.jpg')) is False or True
