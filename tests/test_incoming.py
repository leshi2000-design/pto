import pytest
from datetime import date
import docx
from smetagaz.database import DatabaseManager
from smetagaz import incoming_domain as inc


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setattr(inc, 'INBOX_DIR', tmp_path / 'inbox')
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    yield d
    d.close()


NAKL = 'Товарная накладная № 1245/А от 12 марта 2026\nПоставщик: ООО «Трубопласт» УНП 190123456\nПолучатель: Иванов Иван, объект ул. Центральная 25\nДоговор 07-02/26\nИтого к оплате: 1 250,50\n'


def write_docx(path, text):
    doc = docx.Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    doc.save(path)
    return str(path)


def test_requisites_from_text():
    assert inc.guess_kind(NAKL) == 'Накладная'
    assert inc.find_number(NAKL, 'Накладная') == '1245/А'
    assert inc.find_dates(NAKL)[0][1] == '2026-03-12' and inc.find_dates('Дата 05.04.26')[0][1] == '2026-04-05'
    assert inc.find_amount(NAKL) == 1250.5
    assert inc.find_counterparty(NAKL) == 'ООО «Трубопласт»'
    assert inc.guess_kind('Сертификат соответствия № RU-1') == 'Сертификат' and inc.guess_kind('Акт выполненных работ №3') == 'Акт'


def test_analyze_suggests_object_and_save_flow(d, tmp_path):
    good = d.execute("INSERT INTO contracts(contract_number,client_name,object_address) VALUES('07-02/26','Иванов Иван Иванович','Минск, Центральная 25')").lastrowid
    d.execute("INSERT INTO contracts(contract_number,client_name,object_address) VALUES('08-02/26','Петров Пётр','Гродно, Советская 1')")
    path = write_docx(tmp_path / 'nakl.docx', NAKL)
    r = inc.analyze(d, path)
    assert r['kind'] == 'Накладная' and r['number'] == '1245/А' and r['amount'] == 1250.5 and not r['warning']
    assert r['candidates'][0][:2] == ('contracts', good) and r['candidates'][0][3] >= 15
    assert len(r['candidates']) == 1
    did = inc.save(d, path, dict(kind='Накладная', number='1245/А', doc_date='2026-03-12', amount=1250.5, counterparty='ООО «Трубопласт»', owner_type='contracts', owner_id=good))
    row = inc.listing(d)[0]
    assert row['id'] == did and 'inbox' in row['path'] and row['object'].startswith('Монтаж ГСВ') and (tmp_path / 'nakl.docx').exists()
    assert inc.listing(d, 'трубопласт') and not inc.listing(d, 'нет такого')


def test_signed_act_marks_object_only_when_confirmed(d, tmp_path):
    c = d.execute("INSERT INTO contracts(contract_number,client_name) VALUES('01-02/26','А')").lastrowid
    g = d.execute("INSERT INTO gsn_projects(contract_number,title,client_name) VALUES('ГСН-1','Дом','Б')").lastrowid
    p = write_docx(tmp_path / 'akt.docx', 'Акт выполненных работ № 5')
    inc.save(d, p, dict(kind='Акт', doc_date='2026-04-01', owner_type='contracts', owner_id=c), mark_signed=False)
    assert d.fetchone('SELECT coalesce(act_signed,0),coalesce(acceptance_act_date,\'\') FROM contracts WHERE id=?', (c,)) == (0, '')
    inc.save(d, p, dict(kind='Акт', doc_date='2026-04-01', owner_type='contracts', owner_id=c), mark_signed=True)
    assert d.fetchone('SELECT act_signed,acceptance_act_date FROM contracts WHERE id=?', (c,)) == (1, '2026-04-01')
    inc.save(d, p, dict(kind='Акт', doc_date='2026-04-02', owner_type='gsn_projects', owner_id=g), mark_signed=True)
    assert d.fetchone('SELECT act_signed,act_date FROM gsn_projects WHERE id=?', (g,)) == (1, '2026-04-02')


def test_unreadable_files_warn_not_fail(d, tmp_path):
    f = tmp_path / 'scan.png'
    f.write_bytes(b'not a real image')
    r = inc.analyze(d, str(f))
    assert r['kind'] == 'Другое' and r['warning'] and r['candidates'] == []
    with pytest.raises(ValueError):
        inc.save(d, str(tmp_path / 'missing.pdf'), dict(kind='Акт'))


def test_view_and_dialog(d, tmp_path, monkeypatch):
    from smetagaz import incoming_view as iv, staff_view
    monkeypatch.setattr(iv, 'db', d)
    path = write_docx(tmp_path / 'n.docx', NAKL)
    dlg = iv.ReviewDialog(path)
    assert dlg.kind.currentText() == 'Накладная' and dlg.number.text() == '1245/А'
    dlg.save()
    assert dlg.saved
    v = iv.IncomingView()
    v.load_data()
    assert v.table.rowCount() == 1
