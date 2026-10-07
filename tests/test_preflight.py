import docx
import pytest
from smetagaz.database import DatabaseManager
from smetagaz import preflight as pf, gsv_project_domain as gd, gsvm_docs as dd, gsvm_domain as md


@pytest.fixture
def d(tmp_path, monkeypatch):
    for mod, attr, val in ((gd, 'PROJECTS_DIR', tmp_path / 'projects'), (gd, 'TEMPLATES_DIR', tmp_path / 'templates'), (dd, 'TEMPLATES_DIR', tmp_path / 'templates' / 'gsvm')):
        monkeypatch.setattr(mod, attr, val)
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    yield d
    d.close()


def texts(issues, level=None):
    return ' | '.join(i['text'] for i in issues if level in (None, i['level']))


def test_project_contract_with_empty_fields(d):
    cid = d.execute("INSERT INTO crm.clients(name) VALUES('Иванов Иван')").lastrowid
    pid = d.execute("INSERT INTO gsv_projects(pd_number,contract_number,client_id,client_name,cost) VALUES('01-26 ГСВ','01-03/26',?,'Иванов Иван',0)", (cid,)).lastrowid
    issues = pf.check_project(d, pid, 'contract')
    errors = texts(issues, 'error')
    for fragment in ('паспорт', 'кем выдан', 'дата выдачи паспорта', 'адрес клиента', 'стоимость', 'срок исполнения', 'дата заключения'):
        assert fragment in errors, (fragment, errors)
    assert 'В шаблоне есть теги без данных' in texts(issues, 'warn') and '{ПАСПОРТ}' in texts(issues, 'warn')


def test_project_clean_contract_has_no_issues(d):
    cid = d.execute("INSERT INTO crm.clients(name,phone,address,passport,passport_issuer,passport_date) VALUES('Иванов Иван','1','Минск','МР 1','РУВД','2015-01-01')").lastrowid
    pid = d.execute("INSERT INTO gsv_projects(pd_number,contract_number,client_id,client_name,phone,object_name,address,cost,contract_date,due_date) "
                    "VALUES('01-26 ГСВ','01-03/26',?,'Иванов Иван','1','Дом','д. Ключи',250,'2026-10-01','2026-10-31')", (cid,)).lastrowid
    assert pf.check_project(d, pid, 'contract') == []
    assert 'дата акта' in texts(pf.check_project(d, pid, 'act'), 'error')          # у акта своя обязательная дата


def test_unknown_and_empty_template_tags(d, tmp_path):
    cid = d.execute("INSERT INTO crm.clients(name) VALUES('Иванов')").lastrowid
    pid = d.execute("INSERT INTO gsv_projects(pd_number,contract_number,client_id,client_name,cost,contract_date) VALUES('01-26 ГСВ','01-03/26',?,'Иванов',100,'2026-10-01')", (cid,)).lastrowid
    tpl = tmp_path / 't.docx'
    doc = docx.Document()
    doc.add_paragraph('Паспорт {ПАСПОРТ}, {НЕТ_ТАКОГО}, {ПРИМЕЧАНИЕ}')
    doc.save(tpl)
    d.set_setting('gsvp_tpl_act', str(tpl))
    warn = texts(pf.check_project(d, pid, 'act'), 'warn')
    assert '{ПАСПОРТ}' in warn and '{НЕТ_ТАКОГО}' in warn and 'ПРИМЕЧАНИЕ' not in warn          # необязательные теги не считаются проблемой


def montage(d, **extra):
    cid = d.execute("INSERT INTO crm.clients(name,phone,address,passport,passport_issuer,passport_date) VALUES('Иванов Иван','1','Минск','МР 1','РУВД','2015-01-01')").lastrowid
    cols = dict(contract_number='01-02/26', contract_date='2026-10-01', object_name='Дом', object_address='д. Ключи', client_id=cid, client_name='Иванов Иван',
                work_end_date='2026-12-01', acceptance_act_date='2026-12-05', contract_amount=500)
    cols.update(extra)
    return d.execute(f"INSERT INTO contracts({','.join(cols)}) VALUES({','.join('?' for _ in cols)})", tuple(cols.values())).lastrowid


def test_montage_estimate_freshness_and_id_documents(d):
    cid = montage(d)
    assert pf.check_montage(d, cid, 'contract') == []
    eid = d.execute("INSERT INTO estimates(title,total) VALUES('Смета',0)").lastrowid
    d.execute('UPDATE estimates SET total=500 WHERE id=?', (eid,))
    md.link_estimate(d, cid, eid)
    assert 'ещё не получены' in texts(pf.check_montage(d, cid, 'contract'), 'warn')
    md.sync_estimate(d, cid)
    assert pf.check_montage(d, cid, 'contract') == []
    d.execute("INSERT INTO estimate_items(estimate_id,item_type,name,unit,quantity,price,sum) VALUES(?,?,?,?,?,?,?)", (eid, 'Материал', 'Труба', 'м', 1, 1, 1))
    assert 'Смета была изменена' in texts(pf.check_montage(d, cid, 'contract'), 'error')
    md.sync_estimate(d, cid)
    warn = texts(pf.check_montage(d, cid, 'hidden_works'), 'warn')
    assert 'трубопроводы' in warn                                                  # для исполнительных документов нужны трубы и стыки
    assert '{КОТЕЛ_МОДЕЛЬ}' not in warn and '{ТРУБА' not in warn                  # пустые теги оборудования и труб — норма


def test_montage_missing_passport_and_cost(d):
    cid = montage(d, contract_amount=0)
    cl = d.fetchone('SELECT client_id FROM contracts WHERE id=?', (cid,))[0]
    d.execute("UPDATE crm.clients SET passport='',address='' WHERE id=?", (cl,))
    errors = texts(pf.check_montage(d, cid, 'act'), 'error')
    assert 'паспорт' in errors and 'адрес клиента' in errors and 'стоимость' in errors
