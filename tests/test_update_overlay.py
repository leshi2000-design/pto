import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import pto_overlay as po  # noqa: E402
from smetagaz import services, backup, update_ui  # noqa: E402,F401


def make_zip(tmp_path, version='9.9.9', prefix='PTO_9.9.9/', mutate=None, extra=None, name='update.zip'):
    """Архив обновления из текущих исходников с другим номером версии."""
    src = tmp_path / ('src_' + name)
    shutil.copytree(ROOT / 'smetagaz', src / 'smetagaz', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    init = src / 'smetagaz' / '__init__.py'
    text = init.read_text(encoding='utf-8')
    import re
    init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', text), encoding='utf-8')
    if mutate:
        mutate(src)
    (src / 'requirements.txt').write_text('PyQt6>=6.6\nopenpyxl>=3.1\n', encoding='utf-8')
    out = tmp_path / name
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in src.rglob('*'):
            if f.is_file():
                z.write(f, prefix + f.relative_to(src).as_posix())
        for n, data in (extra or {}).items():
            z.writestr(n, data)
    return out


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / 'data'
    d.mkdir()
    monkeypatch.setenv('SMETAGAZ_DATA_DIR', str(d))
    return d


def run_program(args, data, extra_env=None, timeout=240):
    env = dict(os.environ, SMETAGAZ_DATA_DIR=str(data), QT_QPA_PLATFORM='offscreen')
    env.pop('PTO_NO_OVERLAY', None)
    env.pop('PTO_OVERLAY_DIR', None)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(ROOT / 'run.py'), *args], cwd=data, env=env, capture_output=True, text=True, timeout=timeout)


def test_inspect_accepts_good_archive_and_rejects_bad(tmp_path):
    good = make_zip(tmp_path)
    info = po.inspect_zip(good)
    assert info['version'] == '9.9.9' and info['prefix'] == 'PTO_9.9.9/' and any(rel == 'smetagaz/__init__.py' for _o, rel in info['members'])
    assert not any('tests' in rel for _o, rel in info['members'])
    flat = make_zip(tmp_path, prefix='', name='flat.zip')
    assert po.inspect_zip(flat)['prefix'] == ''
    with pytest.raises(po.UpdateError, match='небезопасный путь'):
        po.inspect_zip(make_zip(tmp_path, extra={'PTO_9.9.9/../evil.py': 'x'}, name='t1.zip'))
    with pytest.raises(po.UpdateError, match='недопустимый файл'):
        po.inspect_zip(make_zip(tmp_path, extra={'PTO_9.9.9/smetagaz/run.exe': 'MZ'}, name='t2.zip'))
    notpto = tmp_path / 'other.zip'
    with zipfile.ZipFile(notpto, 'w') as z:
        z.writestr('readme.txt', 'x')
    with pytest.raises(po.UpdateError, match='нет папки smetagaz'):
        po.inspect_zip(notpto)
    broken = tmp_path / 'broken.zip'
    broken.write_bytes(b'not a zip')
    with pytest.raises(po.UpdateError, match='Не удалось открыть'):
        po.inspect_zip(broken)


def test_stage_rejects_syntax_error_and_cleans_up(tmp_path, data_dir):
    def break_module(src):
        (src / 'smetagaz' / 'lazy.py').write_text('def broken(:\n', encoding='utf-8')
    with pytest.raises(po.UpdateError, match='синтаксические ошибки'):
        po.stage(make_zip(tmp_path, mutate=break_module))
    assert po.installed() == [] and not any((data_dir / 'updates').glob('v*')) if (data_dir / 'updates').exists() else True


def test_stage_activate_list_cleanup(tmp_path, data_dir):
    info, dest, warnings = po.stage(make_zip(tmp_path, version='9.9.9'))
    assert (dest / 'smetagaz' / '__init__.py').is_file() and (dest / 'info.json').is_file() and warnings == []
    po.activate_folder(dest)
    items = po.installed()
    assert po.current_name() == dest.name and items[0]['active'] and items[0]['version'] == '9.9.9' and items[0]['source'] == 'update.zip'
    for v in ('9.9.10', '9.9.11', '9.9.12', '9.9.13'):
        time.sleep(1.1)
        i, d, _w = po.stage(make_zip(tmp_path, version=v, name=f'{v}.zip'))
        po.activate_folder(d)
    names = [i['version'] for i in po.installed()]
    assert len(names) == po.KEEP and names[0] == '9.9.13'              # старые удаляются, включённое остаётся
    po.deactivate('вручную')
    assert po.current_name() == '' and 'вручную' in (data_dir / 'updates' / 'last_failure.txt').read_text(encoding='utf-8')


def test_requirements_warning(tmp_path, data_dir):
    assert po.missing_requirements('PyQt6>=6.6\npython-docx\nnonexistent-lib-xyz==1.0\n# комментарий\n') == ['nonexistent-lib-xyz']


def test_program_starts_from_update_and_ignores_older(tmp_path, data_dir):
    info, dest, _w = po.stage(make_zip(tmp_path, version='9.9.9'))
    po.activate_folder(dest)
    r = run_program(['--selftest'], data_dir)
    report = (data_dir / 'selftest.txt').read_text(encoding='utf-8')
    assert r.returncode == 0 and 'Версия: 9.9.9' in report and str(dest) in report and report.startswith('ВСЁ В ПОРЯДКЕ'), report[:600]
    # встроенная версия новее обновления — обновление не применяется
    po.deactivate()
    info, old, _w = po.stage(make_zip(tmp_path, version='0.0.1', name='old.zip'))
    po.activate_folder(old)
    r = run_program(['--selftest'], data_dir)
    report = (data_dir / 'selftest.txt').read_text(encoding='utf-8')
    assert 'Версия: 0.0.1' not in report and 'Версия: 4.' in report


def test_module_missing_in_update_is_not_taken_from_builtin(tmp_path, data_dir):
    def drop(src):
        (src / 'smetagaz' / 'lazy.py').unlink()
    info, dest, _w = po.stage(make_zip(tmp_path, mutate=drop))
    code = "import sys; sys.path.insert(0, %r); import pto_overlay as po; po.activate(); import smetagaz.lazy" % str(ROOT)
    r = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, PTO_OVERLAY_DIR=str(dest), SMETAGAZ_DATA_DIR=str(data_dir)), capture_output=True, text=True)
    assert r.returncode != 0 and 'в установленном обновлении нет этого модуля' in r.stderr


def test_selftest_of_candidate_and_failure_detected(tmp_path, data_dir):
    info, dest, _w = po.stage(make_zip(tmp_path))
    ok, report = po.run_selftest(dest)
    assert ok and 'Версия: 9.9.9' in report, report[:500]

    def break_import(src):
        (src / 'smetagaz' / 'main_window.py').write_text('raise RuntimeError("boom")\n', encoding='utf-8')
    info2, dest2, _w = po.stage(make_zip(tmp_path, version='9.9.8', mutate=break_import, name='bad.zip'))
    ok2, report2 = po.run_selftest(dest2)
    assert not ok2 and 'boom' in report2


def test_broken_update_falls_back_to_builtin(tmp_path, data_dir):
    def break_main(src):
        (src / 'smetagaz' / 'main_window.py').write_text('raise RuntimeError("boom-fallback")\n', encoding='utf-8')
    info, dest, _w = po.stage(make_zip(tmp_path, mutate=break_main))
    po.activate_folder(dest)
    assert po.current_name() == dest.name
    r = run_program([], data_dir, {'PTO_EXIT_AFTER_MS': '1500'})
    assert r.returncode == 0                                              # родительский процесс отключил обновление и перезапустил программу
    assert po.current_name() == '' and 'boom-fallback' in (data_dir / 'updates' / 'last_failure.txt').read_text(encoding='utf-8')
    end = time.time() + 40                                               # перезапущенная встроенная версия стартует и закрывается сама
    while time.time() < end and not (data_dir / 'smetagaz.db').exists():
        time.sleep(0.5)
    assert (data_dir / 'smetagaz.db').exists()
    time.sleep(4)


def test_zip_update_dialog(tmp_path, data_dir, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from PyQt6.QtTest import QTest
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: 0)
    monkeypatch.setattr(po, 'run_selftest', lambda dest, timeout=240: (True, 'ВСЁ В ПОРЯДКЕ'))
    monkeypatch.setattr(update_ui.db, 'safety_backup', lambda reason: None)
    d = update_ui.ZipUpdateDialog()
    d.choose(str(make_zip(tmp_path)))
    end = time.time() + 30
    while d.worker is not None and d.worker.isRunning() and time.time() < end:
        QTest.qWait(50)
    QTest.qWait(200)
    assert po.current_name() and d.installed_version == '9.9.9' and not d.quit_button.isHidden() and d.items.count() == 1
    d.roll_back()
    assert po.current_name() == '' and d.items.count() == 1 and not d.rollback.isEnabled()
    # неверный архив — понятное сообщение, ничего не установлено
    shown = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a, **k: shown.append(a[2]) or 0)
    bad = tmp_path / 'bad.zip'
    bad.write_bytes(b'x')
    d.choose(str(bad))
    assert shown and 'Не удалось открыть' in shown[0]


def test_close_does_not_wait_for_long_backup(tmp_path, monkeypatch):
    """Закрытие программы не ждёт долгую копию: идущая прерывается, ожидание ограничено."""
    from datetime import datetime
    from smetagaz.database import DatabaseManager
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    monkeypatch.setattr(services, 'db', d)
    svc = services.AutoBackupService()
    started = []

    def slow_create(db, dest, progress=None, include_files=True):
        started.append(1)
        for _ in range(600):                      # «гигабайты файлов»: копия вызывает progress на каждом файле
            time.sleep(0.05)
            progress(0, 0, 'Копирование')
    monkeypatch.setattr(services, 'create_backup', slow_create)
    svc.future = svc.pool.submit(svc.backup_db, datetime.now())
    time.sleep(0.4)
    assert started
    t0 = time.monotonic()
    svc.close()
    assert time.monotonic() - t0 < 5 and svc.future.done()
    d.close()


def test_create_backup_can_be_cancelled(tmp_path):
    from smetagaz.database import DatabaseManager
    d = DatabaseManager(tmp_path / 'smetagaz.db')
    d.init_db()
    out = tmp_path / 'b.zip'

    def stop(*_):
        raise services.BackupCancelled()
    with pytest.raises(services.BackupCancelled):
        backup.create_backup(d, out, stop, include_files=False)
    assert not out.exists() and not list(tmp_path.glob('tmp*'))
    d.close()
