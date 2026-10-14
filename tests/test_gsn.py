import pytest
import docx
from smetagaz.database import DatabaseManager
from smetagaz import gsn_domain as gn, gsn_docs as dd, gsv_project_domain as gd


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, 'TEMPLATES_DIR', tmp_path / 'templates')
    monkeypatch.setattr(dd, 'TEMPLATES_DIR', tmp_path / 'templates' / 'gsn')
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def item(d, role, name, unit='шт', cert=None):
    i = d.execute('INSERT INTO gsn_items(category,name,unit,active,role) VALUES(?,?,?,1,?)', ('Трубопроводы', name, unit, role)).lastrowid
    if cert:
        d.execute('INSERT INTO gsn_item_certs(item_id,cert_id) VALUES(?,?)', (i, cert))
    return i


def cert(d, name, always=0):
    return d.execute('INSERT INTO gsn_certificates(name,number,always) VALUES(?,?,?)', (name, 'N-' + name, always)).lastrowid


def card(d, **extra):
    v = dict(contract_number='ГСН-1/26', contract_date='2026-03-01', title='Газоснабжение дома', address='д. Ключи, 12', pe_length=12.5, steel_length=3,
             pressure_type='low', tie_in='steel', couplings=2, work_end_date='2026-04-30')
    v.update(extra)
    return gn.save_card(d, v, dict(name='Иванов Иван Иванович', phone='375291112233', address='Минск', passport='МР 1234567'))


def test_save_creates_client_and_tags(d):
    cid, client_id = card(d)
    assert d.fetchone('SELECT count(*) FROM crm.clients')[0] == 1 and client_id
    tags = dd.tag_map(d, cid)
    assert tags['МАТЕРИАЛЫ'].splitlines()[:2] == ['ПЭ труба — 12,5 м', 'Стальная труба — 3 м']
    assert len(tags) > 50


def test_materials_depend_on_tie_in(d):
    cid, _ = card(d)
    roles = [m['role'] for m in gn.materials(d, cid)]
    assert roles == ['pe_pipe', 'steel_pipe', 'transition', 'coupling']
    cid2, _ = card(d, tie_in='pe', couplings=0, contract_number='2')
    assert [m['role'] for m in gn.materials(d, cid2)] == ['pe_pipe', 'steel_pipe', 'plug']


def test_certificates_default_and_dependent(d):
    base = cert(d, 'общий', always=1)
    own = cert(d, 'соединение')
    other = cert(d, 'заглушка')
    t = item(d, 'transition', 'Соединение ПЭ/сталь', cert=own)
    item(d, 'plug', 'Заглушка', cert=other)
    cid, _ = card(d)
    gn.set_chosen_items(d, cid, {'transition': t})
    found = {c['id']: c['kind'] for c in gn.certificates(d, cid)}
    assert found == {base: 'default', own: 'dependent'}


def test_attestation_rules(d):
    w = d.execute("INSERT INTO welding_documents(title,category,document_type,file_path) VALUES('Общий','attestation','Аттестат','/x')").lastrowid
    m = d.execute("INSERT INTO welding_documents(title,category,document_type,file_path) VALUES('Металл','attestation','Аттестат','/y')").lastrowid
    gn.set_attestation_mode(d, w, 'always')
    gn.set_attestation_mode(d, m, 'steel')
    steel, _ = card(d)
    pe, _ = card(d, tie_in='pe', couplings=0, contract_number='2')
    assert {a['title'] for a in gn.attestations(d, steel)} == {'Общий', 'Металл'}
    assert {a['title'] for a in gn.attestations(d, pe)} == {'Общий'}


def test_default_end_and_validation():
    assert gn.default_end('2026-03-01').isoformat() == '2026-04-30'
    with pytest.raises(ValueError):
        gn.validate(dict(contract_date='мусор'))


def test_estimate_states_and_sync(d):
    cid, client_id = card(d)
    assert gn.estimate_state(d, cid) == 'none'
    eid = d.execute("INSERT INTO estimates(title,date,total,paid) VALUES('Смета','2026-03-01',100,0)").lastrowid
    gn.link_estimate(d, cid, eid)
    assert gn.estimate_state(d, cid) == 'unsynced'
    gn.sync_estimate(d, cid)
    assert gn.estimate_state(d, cid) == 'fresh'


def test_all_fourteen_documents_generate(d, tmp_path):
    assert len(dd.DOC_KINDS) == 14
    cid, _ = card(d)
    folder = tmp_path / 'obj'
    gn.link_folder(d, cid, str(folder), create=True)
    for kind in dd.DOC_KINDS:
        path = dd.generate(d, cid, kind)
        assert docx.Document(path).paragraphs
        assert dd.doc_state(d, cid, kind) == 'fresh'
    d.execute("UPDATE gsn_projects SET title='Другой объект' WHERE id=?", (cid,))
    assert dd.doc_state(d, cid, 'contract') == 'stale'


def test_custom_tag_in_editor(d):
    cid, _ = card(d)
    dd.sync_tags(d)
    assert any(t for t in dd.list_tags(d))
