import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import QObject,QTimer
from .database import db
from .backup import create_backup
from .contracts_excel_export import export_registries,EXPORT_FILENAME

CONTRACTS_EXPORT_INTERVAL=3600  # раз в час, пока программа запущена; файлы перезаписываются

class AutoBackupService(QObject):
    def __init__(self):
        super().__init__()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='backup')
        self.future=None
        self.contracts_future=None
        self.projects_future=None
        self.timer=QTimer(self);self.timer.timeout.connect(self.run_checks);self.timer.start(60000)
        QTimer.singleShot(5000,self.run_checks)
    def run_checks(self):
        if not (self.future and not self.future.done()):
            try:last=datetime.fromisoformat(db.get_setting('last_db_backup',''))
            except ValueError:last=datetime.min
            if (datetime.now()-last).total_seconds()>3600:self.future=self.pool.submit(self.backup_db,datetime.now())
        if not (self.contracts_future and not self.contracts_future.done()):
            try:last=datetime.fromisoformat(db.get_setting('last_contracts_excel',''))
            except ValueError:last=datetime.min
            if (datetime.now()-last).total_seconds()>CONTRACTS_EXPORT_INTERVAL:self.contracts_future=self.pool.submit(self.export_contracts_excel,datetime.now())
        if not (self.projects_future and not self.projects_future.done()):
            try:last=datetime.fromisoformat(db.get_setting('last_projects_excel',''))
            except ValueError:last=datetime.min
            if (datetime.now()-last).total_seconds()>CONTRACTS_EXPORT_INTERVAL:self.projects_future=self.pool.submit(self.export_projects_excel,datetime.now())
    def export_projects_excel(self,now):
        try:
            from .gsv_project_domain import export_cards,EXPORT_FILENAME
            path=Path(db.db_name).parent/'excel_reports'/EXPORT_FILENAME
            count=export_cards(db,path)
            db.set_setting('last_projects_excel',now.isoformat())
            db.set_setting('projects_excel_status',f'{now:%d.%m.%Y %H:%M}: проекты ГСВ, карточек {count} — {path}')
        except Exception as e:
            logging.exception('Projects Excel export failed')
            db.set_setting('projects_excel_status',f'{now:%d.%m.%Y %H:%M}: ошибка экспорта — {e}')
    def backup_db(self,now):
        try:
            folder=Path(db.db_name).parent/'backups';folder.mkdir(exist_ok=True)
            result=create_backup(db,folder/f'auto_{now:%Y%m%d_%H%M%S_%f}.zip')
            db.set_setting('last_db_backup',now.isoformat())
            db.set_setting('backup_status',f'{now:%d.%m.%Y %H:%M}: пропущенных файлов: {len(result["missing"])}')
            for old in sorted(folder.glob('auto_*.zip'))[:-24]:old.unlink()
        except Exception as e:
            logging.exception('Backup failed')
            db.set_setting('backup_status',f'{now:%d.%m.%Y %H:%M}: ошибка резервного копирования — {e}')
    def export_contracts_excel(self,now):
        try:
            folder=Path(db.db_name).parent/'excel_reports';path=folder/EXPORT_FILENAME
            gsv_count,gsn_count=export_registries(db,path)
            db.set_setting('last_contracts_excel',now.isoformat())
            db.set_setting('contracts_excel_status',f'{now:%d.%m.%Y %H:%M}: ГСВ {gsv_count}, ГСН {gsn_count} строк — {path}')
        except Exception as e:
            logging.exception('Contracts Excel export failed')
            db.set_setting('contracts_excel_status',f'{now:%d.%m.%Y %H:%M}: ошибка экспорта — {e}')
    def close(self):
        self.timer.stop();self.pool.shutdown(wait=True)
