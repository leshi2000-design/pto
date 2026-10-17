import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from PyQt6.QtCore import QObject,QTimer
from .database import db
from .backup import create_backup
from .contracts_excel_export import export_registries,EXPORT_FILENAME

INTEGRITY_INTERVAL_DAYS=7
CONTRACTS_EXPORT_INTERVAL=3600  # раз в час, пока программа запущена; файлы перезаписываются

class NoBackupService:
    """В сетевом клиенте копии и выгрузки делает ПТО Сервер: здесь ничего не запускается."""
    def exit_backup_needed(self):
        return False

    def start_exit_backup(self):
        return None

    def close(self):
        pass


class AutoBackupService(QObject):
    def __init__(self):
        super().__init__()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='backup')
        self.future=None
        self.contracts_future=None
        self.projects_future=None
        self.offsite_future=None
        self.integrity_future=None
        self.timer=QTimer(self);self.timer.timeout.connect(self.run_checks);self.timer.start(60000)
        QTimer.singleShot(5000,self.run_checks)
    def run_checks(self):
        if getattr(self,'_stopped',False):return          # после закрытия пул остановлен: отложенный запуск (singleShot) ничего не делает
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
        if not (self.integrity_future and not self.integrity_future.done()):
            try:last=datetime.fromisoformat(db.get_setting('last_integrity_check',''))
            except ValueError:last=datetime.min
            if (datetime.now()-last).days>=INTEGRITY_INTERVAL_DAYS:self.integrity_future=self.pool.submit(self.integrity_check,datetime.now())
        if not (self.offsite_future and not self.offsite_future.done()):
            from . import offsite_backup
            if any(offsite_backup.due(db)):self.offsite_future=self.pool.submit(self.offsite_backup,datetime.now())
    def integrity_check(self,now):
        """Раз в неделю: целостность файлов баз SQLite и логические связи (раздел «Проверка данных»). Результат виден в блоке копий окна сервера."""
        try:
            from . import integrity
            counts=integrity.summary(integrity.check(db))
            db.set_setting('last_integrity_check',now.isoformat())
            db.set_setting('integrity_counts',f"{counts['error']},{counts['warn']},{counts['info']}")
            if counts['error']:text=f"{now:%d.%m.%Y %H:%M}: найдено ошибок {counts['error']}, предупреждений {counts['warn']} — откройте «Настройки → Проверка данных»"
            elif counts['warn']:text=f"{now:%d.%m.%Y %H:%M}: ошибок нет, предупреждений {counts['warn']}"
            else:text=f"{now:%d.%m.%Y %H:%M}: проблем не найдено"
            db.set_setting('integrity_status',text)
        except Exception as e:
            logging.exception('Integrity check failed')
            db.set_setting('integrity_status',f'{now:%d.%m.%Y %H:%M}: проверка не выполнена — {e}')
    def offsite_backup(self,now):
        try:
            from . import offsite_backup
            offsite_backup.run_scheduled(db,now)
        except Exception as e:
            logging.exception('Offsite backup failed')
            db.set_setting('offsite_status',f'{now:%d.%m.%Y %H:%M}: ошибка — {e}')
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
    EXIT_MIN_AGE=1800        # копия при закрытии — только если последней больше 30 минут

    def exit_backup_needed(self,now=None):
        now=now or datetime.now()
        try:last=datetime.fromisoformat(db.get_setting('last_db_backup',''))
        except ValueError:last=datetime.min
        if (now-last).total_seconds()>self.EXIT_MIN_AGE:return True
        try:
            from . import offsite_backup
            return bool(offsite_backup.configured(db) and offsite_backup.due(db)[0])
        except Exception:
            return False
    def start_exit_backup(self):
        """Копия при закрытии выполняется в фоне (окно программы уже скрыто); возвращает Future."""
        def work():
            now=datetime.now()
            try:last=datetime.fromisoformat(db.get_setting('last_db_backup',''))
            except ValueError:last=datetime.min
            if (now-last).total_seconds()>self.EXIT_MIN_AGE:self.backup_db(now)
            try:
                from . import offsite_backup
                if offsite_backup.configured(db) and offsite_backup.due(db)[0]:self.offsite_backup(now)
            except Exception:
                logging.exception('Exit offsite backup failed')
        self._stopped=True;self.timer.stop()
        try:return self.pool.submit(work)
        except RuntimeError:           # пул уже остановлен предыдущим закрытием
            self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='backup');return self.pool.submit(work)
    def backup_on_exit(self,min_age=None):
        """Синхронный вариант (тесты и закрытие без окна): дожидается и делает копии при необходимости."""
        self._stopped=True;self.timer.stop();self.pool.shutdown(wait=True)
        if self.exit_backup_needed():
            self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='backup');self.start_exit_backup().result()
    def close(self):
        self._stopped=True;self.timer.stop();self.pool.shutdown(wait=True)
