import logging
import time
import threading
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


class BackupCancelled(Exception):
    """Копия прервана при закрытии программы (итоговый файл не тронут, временные файлы удалены)."""


class AutoBackupService(QObject):
    def __init__(self):
        super().__init__()
        self._abort=threading.Event()          # установлен при закрытии: долгие копии останавливаются на ближайшем файле
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='backup')
        self.future=None
        self.full_future=None
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
        if not (self.full_future and not self.full_future.done()):
            try:last=datetime.fromisoformat(db.get_setting('last_full_backup',''))
            except ValueError:last=datetime.min
            if db.get_setting('backup_full_daily','1')=='1' and (datetime.now()-last).total_seconds()>86400:self.full_future=self.pool.submit(self.backup_db,datetime.now(),True)
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
    def _checker(self):
        """Функция для create_backup: прерывает копию, запущенную до закрытия программы. Каждая копия держит свой флажок, поэтому копия при закрытии не затрагивается."""
        flag=self._abort
        def check(*_):
            if flag.is_set():raise BackupCancelled()
        return check
    def abort_running(self):
        """Останавливает идущие и отменяет ожидающие фоновые копии (при закрытии программы); новые копии получают новый флажок."""
        self._abort.set();self._abort=threading.Event()
    def backup_db(self,now,full=False):
        """Каждый час — копия только баз данных (db_*.zip); раз в сутки — полная копия с вложениями и папками договоров (full_*.zip), если хватает места."""
        from . import backup_policy
        try:
            folder=Path(db.db_name).parent/'backups';folder.mkdir(exist_ok=True)
            note='';check=self._checker()
            if full:
                ok,reason=backup_policy.full_backup_allowed(db,folder)
                if not ok:
                    db.set_setting('last_full_backup',now.isoformat())      # повторная попытка — через сутки
                    db.set_setting('backup_full_status',f'{now:%d.%m.%Y %H:%M}: полная копия с файлами пропущена — {reason}. Базы данных копируются каждый час.')
                    return
                result=create_backup(db,folder/f'full_{now:%Y%m%d_%H%M%S_%f}.zip',check,include_files=True)
                db.set_setting('last_full_backup',now.isoformat())
                db.set_setting('backup_full_status',f'{now:%d.%m.%Y %H:%M}: полная копия с файлами создана, пропущенных файлов: {len(result["missing"])}')
            else:
                result=create_backup(db,folder/f'db_{now:%Y%m%d_%H%M%S_%f}.zip',check,include_files=False)
                db.set_setting('last_db_backup',now.isoformat())
                db.set_setting('backup_status',f'{now:%d.%m.%Y %H:%M}: копия баз данных создана')
            removed=backup_policy.prune(folder,backup_policy.cap_bytes(db))
            if removed:note=f' · удалено старых копий: {len(removed)}'
            size=backup_policy.summary(folder)['total']
            db.set_setting('backup_folder_status',f'Автоматические копии занимают {size/1024**3:.2f} ГБ{note}')
        except BackupCancelled:
            logging.info('Backup cancelled on exit')
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
        self.abort_running();self._stopped=True;self.timer.stop()
        self.pool.shutdown(wait=False,cancel_futures=True)
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='backup-exit')       # копия при закрытии не стоит в очереди за долгой полной копией
        try:return self.pool.submit(work)
        except RuntimeError:           # пул уже остановлен предыдущим закрытием
            self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='backup');return self.pool.submit(work)
    def backup_on_exit(self,min_age=None):
        """Синхронный вариант (тесты и закрытие без окна): дожидается и делает копии при необходимости."""
        self.abort_running();self._stopped=True;self.timer.stop();self.pool.shutdown(wait=True)
        if self.exit_backup_needed():
            self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='backup');self.start_exit_backup().result()
    def close(self):
        """Остановка без ожидания долгих копий: идущая копия прерывается на ближайшем файле, ожидание — не дольше нескольких секунд."""
        self.abort_running();self._stopped=True;self.timer.stop()
        self.pool.shutdown(wait=False,cancel_futures=True)
        deadline=time.monotonic()+8
        for f in (self.future,self.full_future,self.contracts_future,self.projects_future,self.offsite_future,self.integrity_future):
            if f is not None and not f.done():
                try:f.result(timeout=max(0.1,deadline-time.monotonic()))
                except Exception:pass


def arm_exit_watchdog(seconds=15):
    """Страховка от «зависшего» завершения: если через seconds секунд после начала выхода процесс всё ещё жив (поток копии, сеть), он завершается принудительно.
    Данные не страдают: базы SQLite записываются транзакциями, незавершённая копия удаляется как временная."""
    import os
    if os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('PTO_NO_WATCHDOG'):
        return
    def kill():
        time.sleep(seconds)
        os._exit(0)
    threading.Thread(target=kill,daemon=True,name='exit-watchdog').start()
