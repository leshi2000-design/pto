import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import pytest
from smetagaz import security, backup
from smetagaz.database import DatabaseManager, parse_tabs_config, safe_font_size


def test_decrypt_wrong_password_keeps_existing_file(tmp_path):
    src = tmp_path / 'a.zip'; src.write_bytes(b'data' * 1000)
    enc = tmp_path / 'a.sgb'
    security.encrypt_backup(src, enc, 'correct-password-1')
    assert not list(tmp_path.glob('*.tmp'))
    target = tmp_path / 'out.zip'; target.write_bytes(b'precious')
    with pytest.raises(ValueError):
        security.decrypt_backup(enc, target, 'wrong-password-12')
    assert target.read_bytes() == b'precious' and not list(tmp_path.glob('*.tmp'))
    security.decrypt_backup(enc, target, 'correct-password-1')
    assert target.read_bytes() == b'data' * 1000


def test_encrypt_failure_keeps_old_file(tmp_path):
    enc = tmp_path / 'x.sgb'; enc.write_bytes(b'old')
    with pytest.raises(Exception):
        security.encrypt_backup(tmp_path / 'missing.zip', enc, 'correct-password-1')
    assert enc.read_bytes() == b'old' and not list(tmp_path.glob('*.tmp'))


def test_backup_hides_offsite_password_and_posix_manifest(tmp_path):
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    d.set_setting('offsite_password', 'super-secret-password'); d.set_setting('offsite_enabled', '1')
    (tmp_path / 'attachments' / 'sub').mkdir(parents=True); (tmp_path / 'attachments' / 'sub' / 'f.txt').write_text('x')
    manifest = backup.create_backup(d, tmp_path / 'b.zip')
    assert all('\\' not in name for name in manifest['files']) and 'attachments/sub/f.txt' in manifest['files']
    assert d.get_setting('offsite_password') == 'super-secret-password' and d.get_setting('offsite_enabled') == '1'
    restored = tmp_path / 'restored'
    backup.restore_backup(tmp_path / 'b.zip', restored)
    r = DatabaseManager(restored / 'smetagaz.db')
    assert r.get_setting('offsite_password') == '' and r.get_setting('offsite_enabled') == '0'
    r.close(); d.close()


def test_tabs_config_and_font_size_are_safe():
    assert parse_tabs_config('null') == [] and parse_tabs_config('{"a":1}') == [] and parse_tabs_config('not json') == []
    tabs = parse_tabs_config(json.dumps([1, None, {'id': 'a', 'name': 'A', 'visible': 'x'}, {'id': 'a'}, {'id': 5}, {'id': 'b'}]))
    assert [t['id'] for t in tabs] == ['a', 'b'] and tabs[0]['visible'] == 1
    assert safe_font_size('abc') == 10 and safe_font_size('99') == 20 and safe_font_size('11.5') == 11


def test_dark_theme_fix_is_reversible():
    from PyQt6.QtWidgets import QApplication, QLabel
    from smetagaz import theme
    app = QApplication.instance() or QApplication([])
    label = QLabel('x'); label.setStyleSheet('color: #605E5C;')
    theme._fix_widget(label, True)
    assert '#C8C6C4' in label.styleSheet()
    theme._fix_widget(label, False)
    assert label.styleSheet() == 'color: #605E5C;'
    a, b = theme._arrow_files('#123456'), theme._arrow_files('#123456')
    assert a == b and 'smetagaz-theme-' in a['down']


def test_backup_leaves_no_open_database_files(tmp_path):
    """Windows не удаляет открытые файлы (WinError 32): после копирования не должно остаться открытых временных баз."""
    from smetagaz import sqlite_util
    with sqlite_util.connect(tmp_path / 'x.db') as con:
        con.execute('CREATE TABLE t(a)')
    with pytest.raises(Exception):
        con.execute('SELECT 1')              # соединение закрыто
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    backup.create_backup(d, tmp_path / 'b.zip')
    backup.restore_backup(tmp_path / 'b.zip', tmp_path / 'restored')
    d.safety_backup('test')
    held = [os.readlink(f'/proc/self/fd/{n}') for n in os.listdir('/proc/self/fd') if os.path.exists(f'/proc/self/fd/{n}')]
    assert not [p for p in held if p.endswith(('.db', '.db (deleted)')) and 'restored' in p or '(deleted)' in p and '.db' in p]
    d.close()


def test_excel_history_one_version_per_day(tmp_path):
    from smetagaz.contracts_excel_export import keep_version
    f = tmp_path / 'excel_reports' / 'Реестры.xlsx'; f.parent.mkdir()
    f.write_bytes(b'v1')
    assert keep_version(f) is not None and keep_version(f) is None      # в тот же день вторая версия не создаётся
    assert len(list((f.parent / 'history').glob('Реестры_*.xlsx'))) == 1
    for day in range(10):
        (f.parent / 'history' / f'Реестры_2020010{day % 10}_000000.xlsx').write_bytes(b'x')
    (f.parent / 'history' / 'Реестры_20200109_000001.xlsx').write_bytes(b'x')
    for p in (f.parent / 'history').glob('*_00000*.xlsx'): pass
    f2 = tmp_path / 'excel_reports' / 'Другой.xlsx'; f2.write_bytes(b'v1')
    assert keep_version(f2) is not None


def test_backup_on_exit_runs_when_last_copy_is_old(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from smetagaz import services
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    monkeypatch.setattr(services, 'db', d)
    svc = services.AutoBackupService()
    svc.backup_on_exit()
    assert list((tmp_path / 'backups').glob('auto_*.zip')) and d.get_setting('last_db_backup')
    before = len(list((tmp_path / 'backups').glob('auto_*.zip')))
    svc2 = services.AutoBackupService(); svc2.backup_on_exit()       # свежая копия уже есть — повторно не создаётся
    assert len(list((tmp_path / 'backups').glob('auto_*.zip'))) == before
    d.close()


def test_offsite_password_is_not_stored_in_plain_text(tmp_path):
    from smetagaz import secret_store, offsite_backup
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    d.set_setting('offsite_password', 'old-plain-password')          # старый формат
    secret_store.migrate(d)
    stored = d.get_setting('offsite_password')
    assert stored.startswith(('key:', 'dpapi:')) and 'old-plain-password' not in stored
    assert offsite_backup.settings(d)['password'] == 'old-plain-password'
    secret_store.set_secret(d, 'offsite_password', 'new-secret-123')
    assert offsite_backup.settings(d)['password'] == 'new-secret-123' and 'new-secret' not in d.get_setting('offsite_password')
    (tmp_path / 'secret.key').unlink()                               # база без ключа пароль не раскрывает
    assert secret_store.reveal(stored, tmp_path) != 'old-plain-password'
    d.close()


def test_background_job_progress_cancel_and_errors(tmp_path):
    import time
    from PyQt6.QtWidgets import QApplication, QWidget
    from smetagaz import background
    app = QApplication.instance() or QApplication([])
    host = QWidget()

    def pump(job, timeout=10):
        end = time.time() + timeout
        while job in background._ACTIVE and time.time() < end:       # до вызова обработчиков в основном потоке
            app.processEvents(); time.sleep(0.01)

    out = {}
    job = background.run(host, 'Тест', lambda ctx: (ctx.progress(1, 2, 'шаг'), 42)[1], done=lambda r: out.update(result=r))
    pump(job)
    assert out == {'result': 42}
    # ошибка доходит до обработчика
    job = background.run(host, 'Тест', lambda ctx: 1 / 0, error=lambda e: out.update(error=type(e).__name__))
    pump(job)
    assert out['error'] == 'ZeroDivisionError'

    # отмена: цикл прерывается на ближайшей проверке
    steps = []

    def long_work(ctx):
        for n in range(1000):
            ctx.progress(n, 1000, 'работа'); steps.append(n); time.sleep(0.005)
    job = background.run(host, 'Тест', long_work, cancelled=lambda: out.update(cancelled=True))
    time.sleep(0.05); job.ctx.cancel()
    pump(job)
    assert out.get('cancelled') and len(steps) < 1000


def test_backup_cancel_keeps_destination_untouched(tmp_path):
    from smetagaz import backup, background
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    (tmp_path / 'attachments').mkdir(); (tmp_path / 'attachments' / 'a.txt').write_text('x')
    target = tmp_path / 'b.zip'; target.write_bytes(b'previous')
    ctx = background.Context(); ctx.cancel()
    with pytest.raises(background.Cancelled):
        backup.create_backup(d, target, ctx.progress)
    assert target.read_bytes() == b'previous' and not [p for p in tmp_path.iterdir() if p.name.startswith('tmp')]
    d.close()


def test_import_cancel_returns_partial_report(tmp_path):
    from smetagaz import gsvm_import as imp, background
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    rows = [dict(row=n, data=dict(client_name=f'Клиент {n}', contract_date='2026-03-01', address=f'ул. {n}'), status='new', messages=[]) for n in range(1, 6)]
    ctx = background.Context()
    original = ctx.progress

    def stop_after_two(done, total, text=''):
        if done == 3:
            ctx.cancel()
        return original(done, total, text)
    ctx.progress = stop_after_two
    report = imp.import_rows(d, rows, 'skip', ctx)
    assert report['created'] == 2 and report['cancelled'] == 3
    d.close()


def test_backup_survives_fsync_errors(tmp_path, monkeypatch):
    """В Windows fsync на файле, открытом для чтения, даёт [Errno 9]; копия не должна из-за этого падать."""
    import errno
    from smetagaz import backup, security

    def bad_fsync(fd):
        raise OSError(errno.EBADF, 'Bad file descriptor')
    monkeypatch.setattr(os, 'fsync', bad_fsync)
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    backup.create_backup(d, tmp_path / 'b.zip')
    assert (tmp_path / 'b.zip').stat().st_size > 0
    security.encrypt_backup(tmp_path / 'b.zip', tmp_path / 'b.sgb', 'correct-password-1')
    security.decrypt_backup(tmp_path / 'b.sgb', tmp_path / 'out.zip', 'correct-password-1')
    assert (tmp_path / 'out.zip').read_bytes() == (tmp_path / 'b.zip').read_bytes()
    d.close()


def test_close_hides_window_at_once_and_backs_up_in_background(tmp_path, monkeypatch):
    import sys, time
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    for name, mod in list(sys.modules.items()):
        if name.startswith('smetagaz') and isinstance(getattr(mod, 'db', None), DatabaseManager) and mod.db is not d:
            monkeypatch.setattr(mod, 'db', d)
    import smetagaz.main_window as mw
    monkeypatch.setattr(mw.QApplication, 'quit', staticmethod(lambda: None))
    w = mw.MainWindow(); w.show(); app.processEvents()
    w.backup_service.timer.stop()
    started = time.perf_counter()
    w.close()
    assert not w.isVisible() and time.perf_counter() - started < 0.5      # окно скрылось сразу, копия идёт в фоне
    end = time.time() + 20
    while not getattr(w, '_exit_ready', False) and time.time() < end:
        app.processEvents(); time.sleep(0.02)
    assert w._exit_ready and list((tmp_path / 'backups').glob('auto_*.zip'))
    d.close()


def test_section_folder_root_is_user_defined(tmp_path, monkeypatch):
    import smetagaz.database as database
    from smetagaz import gsv_project_domain as gd, contracts_core as cc, folder_ui
    d = DatabaseManager(tmp_path / 'smetagaz.db'); d.init_db()
    monkeypatch.setattr(database, 'db', d)
    assert gd.section_root('contracts') == gd.PROJECTS_DIR / 'Монтаж ГСВ'          # по умолчанию — внутри данных программы
    mine = tmp_path / 'Мои договоры' / 'Монтаж'
    d.set_setting('folder_root_contracts', str(mine))
    assert gd.section_root('contracts') == mine and cc.section_root('smr') == gd.PROJECTS_DIR / 'СМР'
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'exec', lambda self: 0)
    box = {}

    def fake_clicked(self):
        return next(b for b in self.buttons() if b.text() == 'Создать новую')
    monkeypatch.setattr(QMessageBox, 'clickedButton', fake_clicked)
    path, create = folder_ui.choose_folder(None, 'contracts', '01-02-26 - ул. Мира')
    assert create and path == str(mine / '01-02-26 - ул. Мира') and mine.is_dir()       # без лишних вопросов — в выбранной папке
    d.close()


def test_dates_are_shown_as_dd_mm_yyyy():
    from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem
    from PyQt6.QtCore import QDate
    from smetagaz.dates import display_date
    from smetagaz.date_widgets import DateEdit, install_display_patch
    from smetagaz.domain_widgets import OptionalDate
    app = QApplication.instance() or QApplication([])
    assert display_date('2026-03-05') == '05.03.2026' and display_date('2026-03-05 14:30:00') == '05.03.2026 14:30:00' and display_date('текст') == 'текст'
    install_display_patch()
    table = QTableWidget(1, 1)
    table.setItem(0, 0, QTableWidgetItem('2026-03-05'))
    assert table.item(0, 0).text() == '05.03.2026'
    edit = DateEdit(QDate(2026, 3, 5))
    assert edit.displayFormat() == 'dd.MM.yyyy' and edit.text() == '05.03.2026'
    optional = OptionalDate()
    assert optional.value() == '' and optional.is_empty()
    optional.set_value('2026-03-05')
    assert optional.value() == '2026-03-05' and not optional.is_empty()
    assert OptionalDate(default_today=True).value() == QDate.currentDate().toString('yyyy-MM-dd')
    cal = edit.calendarWidget()
    assert cal.firstDayOfWeek().name == 'Monday' and cal.locale().language().name == 'Russian'
