import os,tempfile,time,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from smetagaz.database import DatabaseManager
from smetagaz.data_services import search
from smetagaz.backup import create_backup,restore_backup
with tempfile.TemporaryDirectory() as tmp:
 d=DatabaseManager(Path(tmp)/'smetagaz.db');d.init_db();start=time.perf_counter()
 with d.transaction():d.executemany('INSERT INTO materials(name,unit,price) VALUES(?,?,?)',((f'Труба газовая объект {i}','м',12.5) for i in range(100000)))
 inserted=time.perf_counter()-start;start=time.perf_counter()
 for _ in range(30):rows=search(d,'газовая 99999')
 search_ms=(time.perf_counter()-start)/30*1000
 start=time.perf_counter();page=d.fetchall('SELECT id,name FROM materials ORDER BY id DESC LIMIT 201');page_ms=(time.perf_counter()-start)*1000
 from smetagaz.file_jobs import import_files
 rid=d.execute('INSERT INTO estimates(title) VALUES("Файлы")').lastrowid
 paths=[]
 for i in range(1000):
  path=Path(tmp)/f'input_{i}.txt';path.write_bytes(b'a'*4096);paths.append(path)
 start=time.perf_counter();batch=import_files(d,rid,paths);file_s=time.perf_counter()-start
 assert batch['imported']==1000
 start=time.perf_counter();create_backup(d,Path(tmp)/'backup.zip');backup_s=time.perf_counter()-start
 start=time.perf_counter();restore_backup(Path(tmp)/'backup.zip',Path(tmp)/'restore');restore_s=time.perf_counter()-start
 assert len(rows)==1 and len(page)==201
 result=dict(records=100000,files_imported=1000,file_import_seconds=round(file_s,3),insert_seconds=round(inserted,3),search_avg_ms=round(search_ms,3),page_ms=round(page_ms,3),backup_seconds=round(backup_s,3),restore_seconds=round(restore_s,3),database_bytes=Path(d.db_name).stat().st_size)
 print(json.dumps(result,indent=2));d.close()
