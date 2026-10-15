import pytest
from datetime import date
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem
from smetagaz import print_ui as pu, numbering as nm
from smetagaz.database import DatabaseManager


def test_table_pdf_respects_hidden(tmp_path):
    t = QTableWidget(2, 3)
    t.setHorizontalHeaderLabels(['А', 'Б', 'В'])
    for r in range(2):
        for c in range(3):
            t.setItem(r, c, QTableWidgetItem(f'v{r}{c}' if c != 2 else '2026-03-01'))
    t.setColumnHidden(1, True)
    t.setRowHidden(1, True)
    markup, landscape = pu.table_html('Тест', t, 'поиск: x')
    assert 'v00' in markup and 'v01' not in markup and 'v10' not in markup and '01.03.2026' in markup and not landscape
    out = pu.write_pdf(str(tmp_path / 'a.pdf'), markup)
    assert open(out, 'rb').read(5) == b'%PDF-'


def test_cards_build_and_pdf(tmp_path):
    from smetagaz import gsn_domain as gn
    d = DatabaseManager(tmp_path / 'x.db')
    d.init_db()
    cid, _ = gn.save_card(d, dict(contract_number='ГСН-1', contract_date='2026-03-01', title='Дом', pe_length=10, steel_length=2, tie_in='steel', couplings=1),
                          dict(name='Иванов Иван', phone='375291112233'))
    markup, _l = pu.gsn_card(d, cid)
    assert 'ГСН-1' in markup and 'Иванов Иван' in markup and 'Материалы' in markup
    assert open(pu.write_pdf(str(tmp_path / 'c.pdf'), markup), 'rb').read(5) == b'%PDF-'
    rid = nm.reserve(d, 'contracts', 1, date(2026, 5, 1))[0][0]
    assert '01-02/26' in pu.gsvm_card(d, rid)[0]
    pid = nm.reserve(d, 'gsv_projects', 1, date(2026, 5, 1))[0][0]
    assert '01-26 ГСВ' in pu.gsv_project_card(d, pid)[0]
    d.close()
