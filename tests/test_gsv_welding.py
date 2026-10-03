from pathlib import Path
import json,zipfile
import pytest
from smetagaz.database import DatabaseManager
from smetagaz.gsv_domain import (save_client,get_client,save_equipment,save_pipelines,dossier,add_document,link_documents,save_job,set_work_day)
from smetagaz.backup import create_backup,restore_backup
from smetagaz.data_services import search

@pytest.fixture
def d(tmp_path):
    db=DatabaseManager(tmp_path/'smetagaz.db');db.init_db();yield db;db.close()

def contract(d):
    cid=save_client(d,dict(name='Иван Петров',phone='123',address='Адрес клиента',passport='AB123'))
    rid=d.execute('INSERT INTO contracts(contract_number,object_name,client_id,client_name,client_phone) VALUES(?,?,?,?,?)',('ГСВ-1','Дом',cid,'Иван Петров','123')).lastrowid
    return rid,cid

def test_clients_atomic_and_stable(d):
    rid,cid=contract(d)
    assert get_client(d,cid)['passport']=='AB123'
    save_client(d,dict(name='Иван Петров',phone='555',address='Новый адрес'),cid)
    assert d.fetchone('SELECT client_phone FROM contracts WHERE id=?',(rid,))[0]=='555'
    assert d.fetchone('SELECT count(*) FROM crm.clients')[0]==1
    with pytest.raises(ValueError):
        with d.transaction():
            save_client(d,dict(name='Не должен сохраниться'))
            save_equipment(d,'contracts',rid,[dict(equipment_kind='Неизвестный вид')])
    assert d.fetchone('SELECT count(*) FROM crm.clients')[0]==1

def test_equipment_pipelines_automatic_dossier(d,tmp_path):
    rid,_=contract(d);file=tmp_path/'pipe25.pdf';file.write_bytes(b'certificate')
    cert=d.execute('INSERT INTO certificates(name,cert_number,file_path) VALUES(?,?,?)',('Труба 25','25-C',str(file))).lastrowid
    pipeline=d.execute('INSERT INTO gsv_pipelines(name,certificate_id) VALUES(?,?)',('Труба 25',cert)).lastrowid
    save_equipment(d,'contracts',rid,[dict(equipment_kind='Котел',equipment_model='BAXI 24',certificate_number='P-100')])
    save_pipelines(d,'contracts',rid,[(pipeline,10.5,'Сталь')])
    rows=dossier(d,'contracts',rid)
    assert rows[0]['number']=='P-100'
    assert rows[1]['path']==str(file) and rows[1]['number']=='25-C'
    d.execute('UPDATE certificates SET cert_number=? WHERE id=?',('25-NEW',cert));assert dossier(d,'contracts',rid)[1]['number']=='25-NEW'
    with pytest.raises(Exception):d.execute('DELETE FROM gsv_pipelines WHERE id=?',(pipeline,))
    save_pipelines(d,'contracts',rid,[]);assert len(dossier(d,'contracts',rid))==1

def test_external_docs_shared_and_no_file_copy(d,tmp_path):
    rid,_=contract(d);w=d.execute('INSERT INTO welders(name,birth_date,stamp) VALUES(?,?,?)',('Сварщик','1990-03-15','ABC')).lastrowid
    source=tmp_path/'outside';source.mkdir();file=source/'protocol.pdf';file.write_bytes(b'protocol')
    doc=add_document(d,dict(title='Протокол 12',category='welder',document_type='Протокол',file_path=str(file),welder_id=w,number='12',document_date='2026-09-16',note=''))
    link_documents(d,'contracts',rid,[doc,doc]);assert d.fetchone('SELECT count(*) FROM object_welding_documents')[0]==1
    assert dossier(d,'contracts',rid)[0]['path']==str(file)
    other=source/'renamed.pdf';file.rename(other)
    add_document(d,dict(title='Протокол 12',category='contract_act',document_type='Протокол',file_path=str(other),welder_id=w,number='12',document_date='',note=''),doc)
    assert dossier(d,'contracts',rid)[0]['path']==str(other)
    archive=tmp_path/'backup.zip';result=create_backup(d,archive)
    assert result['external_welding_references'][0]['path']==str(other)
    with zipfile.ZipFile(archive) as z:assert not any(name.endswith('renamed.pdf') for name in z.namelist())
    restored=tmp_path/'restored';restore_backup(archive,restored)
    new=DatabaseManager(restored/'smetagaz.db');new.init_db();assert dossier(new,'contracts',rid)[0]['path']==str(other);new.close()
    d.execute('DELETE FROM welding_documents WHERE id=?',(doc,));assert other.exists();assert not dossier(d,'contracts',rid)

def test_schedule_days_objects_and_delete(d):
    rid,_=contract(d)
    est=d.execute('INSERT INTO estimates(title) VALUES("Смета работ")').lastrowid
    d.execute('UPDATE contracts SET estimate_id=? WHERE id=?',(est,rid))
    item=d.execute('INSERT INTO estimate_items(estimate_id,item_type,name) VALUES(?,?,?)',(est,'Работа','Сварка стыка')).lastrowid
    job=save_job(d,'Сварка стыка','contracts',rid,item_id=item)
    custom=save_job(d,'Пользовательская работа')
    for day in ['2026-09-01','2026-09-03']:set_work_day(d,job,day,True)
    set_work_day(d,job,'2026-09-01',True);assert d.fetchone('SELECT count(*) FROM welding_days')[0]==2
    assert search(d,'сварка')
    set_work_day(d,job,'2026-09-01',False);assert d.fetchone('SELECT count(*) FROM welding_days')[0]==1
    d.execute('DELETE FROM contracts WHERE id=?',(rid,));assert d.fetchone('SELECT owner_type,owner_id FROM welding_jobs WHERE id=?',(job,))==(None,None)
    d.execute('DELETE FROM welding_jobs WHERE id=?',(job,));assert d.fetchone('SELECT count(*) FROM welding_days')[0]==0
    assert d.fetchone('SELECT id FROM welding_jobs WHERE id=?',(custom,))

def test_project_dossier_and_schema_idempotence(d):
    rid=d.execute('INSERT INTO gsv_projects(pd_number,client_name) VALUES("01 ГСВ","Клиент")').lastrowid
    save_equipment(d,'gsv_projects',rid,[dict(equipment_kind='Счетчик',equipment_model='G4',certificate_number='001')])
    assert dossier(d,'gsv_projects',rid)[0]['number']=='001'
    d.init_db();d.init_db();assert d.fetchone('SELECT count(*) FROM gsv_equipment')[0]==1
    assert d.get_setting('schema_version')=='8'
    with pytest.raises(Exception):d.execute("INSERT INTO object_pipelines(owner_type,owner_id,pipeline_id) VALUES('contracts',99999,99999)")

def test_upgrade_existing_v2_database(tmp_path):
    """Recreate a v2 schema using only its supported columns; never discard legacy rows."""
    from smetagaz.database import DatabaseManager
    import sqlite3
    path=tmp_path/'legacy.db'
    # The v2 app used these same baseline tables. No new domain schema is present yet.
    old=DatabaseManager(path);old._init_schema()
    old.execute('CREATE TABLE welders(id INTEGER PRIMARY KEY,name TEXT,certificate TEXT,notes TEXT)')
    old.execute('INSERT INTO welders(name,certificate,notes) VALUES(?,?,?)',('Старый сварщик','Старое удостоверение','Сохранить'))
    old.execute('INSERT INTO estimates(title,client_name,client_phone) VALUES(?,?,?)',('Старая смета','Старый клиент','555'))
    old.execute('INSERT INTO contracts(estimate_id,contract_number,passport_series_number,client_address) VALUES(1,"OLD-1","OLD-PASSPORT","OLD-ADDRESS")')
    old.execute('INSERT INTO contract_equipment(contract_id,equipment_name,certificate_number,note) VALUES(1,"Котёл старой модели","OLD-CERT","Не терять")')
    old.set_setting('schema_version','2');old.close()
    d=DatabaseManager(path);d.init_db()
    assert d.fetchone('SELECT name,certificate,notes FROM welders')==('Старый сварщик','Старое удостоверение','Сохранить')
    assert d.fetchone('SELECT equipment_name,certificate_number,note FROM contract_equipment')==('Котёл старой модели','OLD-CERT','Не терять')
    assert d.fetchone('SELECT client_id FROM contracts')[0] is not None
    assert d.fetchone('SELECT passport,address FROM crm.clients')==('OLD-PASSPORT','OLD-ADDRESS')
    assert d.fetchone('SELECT client_name FROM contracts')[0]=='Старый клиент'
    assert list((tmp_path/'backups').glob('before_upgrade_*/smetagaz.db'))
    d.init_db();assert d.fetchone('SELECT count(*) FROM contract_equipment')[0]==1
    d.close()
