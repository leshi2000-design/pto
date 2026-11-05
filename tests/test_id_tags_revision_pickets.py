"""Исполнительная документация: тег «Фамилия И.О.», акт ревизии тех. устройств (счётчик / сигнализатор / регулятор; пустая строка удаляется), пикеты ГСН и их теги."""
import docx
import pytest

from smetagaz import gsn_docs as gd_n, gsn_domain as gn, gsv_project_domain as gd, gsvm_docs as t, gsvm_domain as m
from smetagaz.database import DatabaseManager


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, 'PROJECTS_DIR', tmp_path / 'projects')
    monkeypatch.setattr(gd, 'TEMPLATES_DIR', tmp_path / 'templates')
    monkeypatch.setattr(t, 'TEMPLATES_DIR', tmp_path / 'templates' / 'gsvm')
    monkeypatch.setattr(gd_n, 'TEMPLATES_DIR', tmp_path / 'templates' / 'gsn')
    db = DatabaseManager(tmp_path / 'smetagaz.db')
    db.init_db()
    yield db
    db.close()


def gsv_contract(db, name='Иванов Иван Иванович'):
    cid = db.execute('INSERT INTO crm.clients(name,phone) VALUES(?,?)', (name, '375291112233')).lastrowid
    return db.execute("INSERT INTO contracts(contract_number,contract_date,object_name,object_address,client_id,client_name,seq_num,year_num) VALUES('01-02/26','2026-11-12','Дом','Минск',?,?,1,26)",
                      (cid, name)).lastrowid


def revision_template(path, table=False):
    doc = docx.Document()
    doc.add_paragraph('АКТ ревизии технических устройств')
    doc.add_paragraph('Заказчик: {КЛИЕНТ_ФАМИЛИЯ_ИО}')
    if table:
        tbl = doc.add_table(rows=3, cols=3)
        for i, (name, tag) in enumerate((('Счётчик', '{СЧЕТЧИК}'), ('Сигнализатор', '{СИГНАЛИЗАТОР}'), ('Регулятор', '{РЕГУЛЯТОР}')), 1):
            tbl.cell(i - 1, 0).text = str(i)
            tbl.cell(i - 1, 1).text = name
            tbl.cell(i - 1, 2).text = tag
    else:
        for i, (name, tag) in enumerate((('Счётчик', '{СЧЕТЧИК}'), ('Сигнализатор', '{СИГНАЛИЗАТОР}'), ('Регулятор', '{РЕГУЛЯТОР}')), 1):
            doc.add_paragraph(f'{i} {name} {tag}')
    doc.add_paragraph('Комиссия: __________')
    doc.save(path)


def use_template(db, kind, path):
    db.set_setting(t.template_setting(kind), str(path))


def test_initials_last_helper():
    assert gd.get_initials_last('Иванов Иван Иванович') == 'Иванов И.И.'
    assert gd.get_initials_last('Иванов Иван') == 'Иванов И.'
    assert gd.get_initials_last('Иванов') == 'Иванов' and gd.get_initials_first('Иванов Иван Иванович') == 'И.И. Иванов'


def test_client_surname_initials_tag_in_gsv_gsn_and_projects(d):
    cid = gsv_contract(d)
    tags = t.tag_map(d, cid)
    assert tags['КЛИЕНТ'] == 'Иванов Иван Иванович' and tags['КЛИЕНТ_СОКР'] == 'И.И. Иванов' and tags['КЛИЕНТ_ФАМИЛИЯ_ИО'] == 'Иванов И.И.'
    gid, _ = gn.save_card(d, dict(title='Газопровод', contract_date='2026-03-01'), dict(name='Петров Пётр Петрович', phone='1'))
    assert gd_n.tag_map(d, gid)['КЛИЕНТ_ФАМИЛИЯ_ИО'] == 'Петров П.П.'
    assert any(tag == 'КЛИЕНТ_ФАМИЛИЯ_ИО' for tag, _l in gd.PROJECT_TAGS) if hasattr(gd, 'PROJECT_TAGS') else True


def test_equipment_tags_are_combined_and_empty_when_missing(d):
    cid = gsv_contract(d)
    m.save_equipment(d, cid, [dict(kind='Счётчик газа', model='G4 ВК', serial='123'), dict(kind='Сигнализатор', model='СГБ-1', serial=''), dict(kind='Счётчик газа', model='G6', serial='9')])
    tags = t.tag_map(d, cid)
    assert tags['СЧЕТЧИК'] == 'G4 ВК, зав. № 123; G6, зав. № 9' and tags['СИГНАЛИЗАТОР'] == 'СГБ-1' and tags['РЕГУЛЯТОР'] == ''
    assert tags['СЧЁТЧИК_ГАЗА'] == tags['СЧЕТЧИК'] and tags['СЧЁТЧИК_ГАЗА_МОДЕЛЬ'] == 'G4 ВК; G6' and tags['РЕГУЛЯТОР_ДАВЛЕНИЯ_ГАЗА_СЕРИЙНЫЙ_НОМЕР'] == '' and tags['РЕГУЛЯТОР_ДАВЛЕНИЯ_ГАЗА'] == ''


def test_revision_act_removes_line_of_missing_equipment(d, tmp_path):
    cid = gsv_contract(d)
    m.link_folder(d, cid, tmp_path / 'obj', create=True)
    m.save_equipment(d, cid, [dict(kind='Счётчик газа', model='G4', serial='123'), dict(kind='Сигнализатор', model='СГБ-1', serial='55')])        # регулятора нет
    tpl = tmp_path / 'rev.docx'
    revision_template(tpl)
    use_template(d, 'device_revision', tpl)
    text = [p.text for p in docx.Document(t.generate(d, cid, 'device_revision')).paragraphs]
    assert '1 Счётчик G4, зав. № 123' in text and '2 Сигнализатор СГБ-1, зав. № 55' in text and 'Заказчик: Иванов И.И.' in text
    assert not any('Регулятор' in line or line.startswith('3') for line in text) and 'Комиссия: __________' in text and not any('{' in line for line in text)
    # нет и сигнализатора — исчезает и его строка; без оборудования вообще остаются только обычные строки
    m.save_equipment(d, cid, [dict(kind='Счётчик газа', model='G4', serial='123')])
    text = [p.text for p in docx.Document(t.generate(d, cid, 'device_revision')).paragraphs]
    assert '1 Счётчик G4, зав. № 123' in text and not any('Сигнализатор' in x or 'Регулятор' in x for x in text)
    m.save_equipment(d, cid, [])
    text = [p.text for p in docx.Document(t.generate(d, cid, 'device_revision')).paragraphs]
    assert text == ['АКТ ревизии технических устройств', 'Заказчик: Иванов И.И.', 'Комиссия: __________']
    # оборудование снова появилось — строка возвращается (сравнение по данным, а не по прошлому документу)
    m.save_equipment(d, cid, [dict(kind='Регулятор давления газа', model='РДНК', serial='77')])
    assert '3 Регулятор РДНК, зав. № 77' in [p.text for p in docx.Document(t.generate(d, cid, 'device_revision')).paragraphs]


def test_revision_act_table_rows_removed_whole(d, tmp_path):
    cid = gsv_contract(d)
    m.link_folder(d, cid, tmp_path / 'obj', create=True)
    m.save_equipment(d, cid, [dict(kind='Счётчик газа', model='G4', serial='123')])
    tpl = tmp_path / 'rev_table.docx'
    revision_template(tpl, table=True)
    use_template(d, 'device_revision', tpl)
    out = docx.Document(t.generate(d, cid, 'device_revision'))
    rows = [[c.text for c in r.cells] for r in out.tables[0].rows]
    assert rows == [['1', 'Счётчик', 'G4, зав. № 123']]                   # строки «2 Сигнализатор» и «3 Регулятор» удалены целиком, вместе с цифрой
    m.save_equipment(d, cid, [])
    out = docx.Document(t.generate(d, cid, 'device_revision'))
    assert not out.tables and not any('Счётчик' in p.text for p in out.paragraphs)                    # таблица пуста — убрана целиком


def test_line_is_kept_when_other_data_present_and_other_documents_unchanged(d, tmp_path):
    cid = gsv_contract(d)
    m.link_folder(d, cid, tmp_path / 'obj', create=True)
    m.save_equipment(d, cid, [dict(kind='Счётчик газа', model='G4', serial='')])
    tpl = tmp_path / 'rev2.docx'
    doc = docx.Document()
    doc.add_paragraph('Счётчик {СЧЁТЧИК_ГАЗА_МОДЕЛЬ}, № {СЧЁТЧИК_ГАЗА_СЕРИЙНЫЙ_НОМЕР}')         # один тег заполнен, другой пуст — строка остаётся (данные есть)
    doc.add_paragraph('Регулятор {РЕГУЛЯТОР_ДАВЛЕНИЯ_ГАЗА_МОДЕЛЬ}, № {РЕГУЛЯТОР_ДАВЛЕНИЯ_ГАЗА_СЕРИЙНЫЙ_НОМЕР}')      # оба пусты — строка удаляется
    doc.add_paragraph('Объект {ОБЪЕКТ}, регулятор {РЕГУЛЯТОР}')                        # смешанная строка: рядом заполненный тег — строка остаётся, на месте пустого тега пусто
    doc.save(tpl)
    use_template(d, 'device_revision', tpl)
    text = [p.text for p in docx.Document(t.generate(d, cid, 'device_revision')).paragraphs]
    assert text == ['Счётчик G4, № ', 'Объект Дом, регулятор ']
    # в других документах (не акты ревизии) строки с пустым тегом не удаляются
    doc = docx.Document()
    doc.add_paragraph('Регулятор: {РЕГУЛЯТОР}')
    warranty = tmp_path / 'warranty.docx'
    doc.save(warranty)
    use_template(d, 'warranty', warranty)
    assert [p.text for p in docx.Document(t.generate(d, cid, 'warranty')).paragraphs] == ['Регулятор: ']


def test_drop_lines_with_tag_split_across_runs(tmp_path):
    doc = docx.Document()
    p = doc.add_paragraph()
    p.add_run('3 Регуля')
    p.add_run('тор {РЕГУЛЯ')
    p.add_run('ТОР}')
    doc.add_paragraph('Остаётся')
    removed = gd.drop_empty_lines(doc, {'РЕГУЛЯТОР': ''}, {'РЕГУЛЯТОР'})
    assert removed == 1 and [x.text for x in doc.paragraphs] == ['Остаётся']
    assert gd.drop_empty_lines(doc, {'РЕГУЛЯТОР': 'x'}, {'РЕГУЛЯТОР'}) == 0 and gd.drop_empty_lines(doc, {}, set()) == 0


# --- пикеты ГСН ---------------------------------------------------------------------------------------------------

def gsn_card(db):
    cid, _ = gn.save_card(db, dict(title='Газопровод', contract_date='2026-03-01', contract_number='ГСН-1/26'), dict(name='Петров Пётр Петрович', phone='1'))
    return cid


def test_pickets_domain_validation_and_order(d):
    cid = gsn_card(d)
    gn.save_pickets(d, cid, [dict(name='ПК0', distance='0'), dict(name='ПК1+50', distance='150,5', note='угол'), dict(name='', distance='', note=''), dict(name='ПК2', distance=None)])
    assert gn.pickets(d, cid) == [dict(id=gn.pickets(d, cid)[0]['id'], name='ПК0', distance=0.0, note=''), dict(id=gn.pickets(d, cid)[1]['id'], name='ПК1+50', distance=150.5, note='угол'),
                                  dict(id=gn.pickets(d, cid)[2]['id'], name='ПК2', distance=None, note='')]
    for rows, text in (([dict(name='', distance='5')], 'название'), ([dict(name='ПК1', distance='abc')], 'не число'), ([dict(name='ПК1', distance='-1')], 'отрицательным')):
        with pytest.raises(ValueError, match=text):
            gn.save_pickets(d, cid, rows)
    assert len(gn.pickets(d, cid)) == 3                                                             # при ошибке прежние пикеты не потеряны
    d.execute('DELETE FROM gsn_projects WHERE id=?', (cid,))
    assert d.fetchone('SELECT count(*) FROM gsn_pickets')[0] == 0                                    # вместе с договором удаляются и пикеты


def test_picket_tags_and_documents_drop_unused_lines(d, tmp_path):
    cid = gsn_card(d)
    gn.save_pickets(d, cid, [dict(name='ПК0', distance='0'), dict(name='ПК1', distance='100', note='поворот')])
    tags = gd_n.tag_map(d, cid)
    assert tags['ПИКЕТ_1'] == 'ПК0' and tags['ПИКЕТ_2'] == 'ПК1' and tags['ПИКЕТ_2_РАССТОЯНИЕ'] == '100' and tags['ПИКЕТ_1_РАССТОЯНИЕ'] == '0' and tags['ПИКЕТ_2_ПРИМЕЧАНИЕ'] == 'поворот'
    assert tags['ПИКЕТ_3'] == '' and tags['ПИКЕТ_40'] == '' and tags['ПИКЕТЫ'] == 'ПК0\nПК1' and tags['ПИКЕТОВ_ВСЕГО'] == '2'
    assert 'ПИКЕТ_41' not in tags
    gn.save_pickets(d, cid, [dict(name=f'ПК{i}') for i in range(45)])
    assert gd_n.tag_map(d, cid)['ПИКЕТ_45'] == 'ПК44'                                                # тегов столько, сколько введено пикетов
    gn.save_pickets(d, cid, [dict(name='ПК0', distance='0'), dict(name='ПК1', distance='100', note='поворот')])
    gn.link_folder(d, cid, str(tmp_path / 'obj'), create=True)
    tpl = tmp_path / 'pickets.docx'
    doc = docx.Document()
    doc.add_paragraph('Трасса')
    for i in range(1, 5):
        doc.add_paragraph(f'Пикет {i}: {{ПИКЕТ_{i}}} — {{ПИКЕТ_{i}_РАССТОЯНИЕ}} м')
    doc.add_paragraph('Всего пикетов: {ПИКЕТОВ_ВСЕГО}')
    doc.save(tpl)
    d.set_setting(gd_n.template_setting('registry'), str(tpl))
    text = [p.text for p in docx.Document(gd_n.generate(d, cid, 'registry')).paragraphs]
    assert text == ['Трасса', 'Пикет 1: ПК0 — 0 м', 'Пикет 2: ПК1 — 100 м', 'Всего пикетов: 2']
    assert gd_n.doc_state(d, cid, 'registry') == 'fresh'
    gn.save_pickets(d, cid, [dict(name='ПК0', distance='0')])
    assert gd_n.doc_state(d, cid, 'registry') == 'stale'                                              # изменили пикеты — документ устарел


def test_pickets_tab_widget(d, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from smetagaz import gsn_pickets_ui as ui
    monkeypatch.setattr(ui, 'db', d)

    class Dialog:
        pass
    tab = ui.GsnPicketsTab(Dialog())
    cid = gsn_card(d)
    gn.save_pickets(d, cid, [dict(name='ПК0', distance='0'), dict(name='ПК1', distance='100,5')])
    tab.load(cid)
    assert tab.table.rowCount() == 2 and tab.rows()[1] == dict(name='ПК1', distance=100.5, note='') and 'Пикетов: 2' in tab.count.text()
    tab.append('ПК2', 'x')
    with pytest.raises(ValueError, match='не число'):
        tab.rows()
    tab.table.item(2, 1).setText('250')
    tab.table.setCurrentCell(2, 0)
    tab.move(-1)
    assert [r['name'] for r in tab.rows()] == ['ПК0', 'ПК2', 'ПК1']
    tab.set_enabled_inputs(False)
    assert not tab.buttons[0].isEnabled()
    tab.load(None)
    assert tab.table.rowCount() == 0
