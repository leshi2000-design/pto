"""Bounded-memory batch attachment ingestion with cancellation and per-file results."""
import os
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QFileDialog
from PyQt6.QtCore import QTimer
from .database import db


def import_files(database,estimate_id,paths,cancel=None):
    cancel=cancel or Event();folder=Path(database.db_name).parent/'attachments';folder.mkdir(exist_ok=True)
    result={'imported':0,'failed':[],'cancelled':False}
    for value in paths:
        if cancel.is_set():result['cancelled']=True;break
        src=Path(value);target=folder/(uuid.uuid4().hex+'_'+src.name);temp=target.with_suffix(target.suffix+'.part')
        try:
            before=src.stat()
            with src.open('rb') as source,temp.open('xb') as dest:
                for block in iter(lambda:source.read(1024*1024),b''):
                    if cancel.is_set():raise InterruptedError('Отменено')
                    dest.write(block)
                dest.flush();os.fsync(dest.fileno())
            after=src.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Файл изменился во время копирования')
            os.replace(temp,target)
            try:database.execute('INSERT INTO attachments(estimate_id,file_name,file_path) VALUES(?,?,?)',(estimate_id,src.name,str(target)))
            except Exception:target.unlink(missing_ok=True);raise
            result['imported']+=1
        except InterruptedError:result['cancelled']=True;break
        except Exception as e:result['failed'].append((src.name,str(e)))
        finally:temp.unlink(missing_ok=True)
    return result

class FileImportDialog(QDialog):
    def __init__(self,estimate_id,paths,parent=None):
        super().__init__(parent);self.setWindowTitle('Добавление файлов');self.resize(550,180)
        layout=QVBoxLayout(self);self.label=QLabel(f'Копирование {len(paths)} файлов…');self.label.setWordWrap(True);layout.addWidget(self.label)
        self.cancel=Event();self.button=QPushButton('Отменить');layout.addWidget(self.button);self.button.clicked.connect(self.stop)
        self.pool=ThreadPoolExecutor(max_workers=1);self.future=self.pool.submit(import_files,db,estimate_id,paths,self.cancel)
        self.timer=QTimer(self);self.timer.timeout.connect(self.poll);self.timer.start(100)
    def stop(self):
        if self.future.done():self.accept()
        else:self.cancel.set();self.label.setText('Завершаю текущую операцию…')
    def poll(self):
        if not self.future.done():return
        self.timer.stop();self.pool.shutdown(wait=False)
        try:
            r=self.future.result();self.label.setText(f'Добавлено: {r["imported"]}. Ошибок: {len(r["failed"])}. '+('Операция отменена.' if r['cancelled'] else '')+'\n'+'\n'.join(f'{a}: {b}' for a,b in r['failed'][:10]))
        except Exception as e:self.label.setText(str(e))
        self.button.setText('Закрыть')
    def reject(self):
        if not self.future.done():self.stop();return
        super().reject()

def attach_files(parent):
    paths,_=QFileDialog.getOpenFileNames(parent,'Выберите файлы','','Все файлы (*)')
    if paths:FileImportDialog(parent.estimate_id,paths,parent).exec();parent.load_files_combo()
