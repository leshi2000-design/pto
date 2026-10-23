import pytest
from pathlib import Path


def test_startup_error_is_written_and_shown(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from smetagaz import startup
    shown = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a, **k: shown.append(a[2]) or 0)
    monkeypatch.setenv('SMETAGAZ_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(startup, '_folders', lambda: [tmp_path / 'exe', tmp_path / 'data'])

    def boom():
        raise RuntimeError('тестовая ошибка запуска')
    with pytest.raises(SystemExit) as e:
        startup.guarded(boom)
    assert e.value.code == 1
    for folder in ('exe', 'data'):
        text = (tmp_path / folder / 'startup_error.txt').read_text(encoding='utf-8')
        assert 'тестовая ошибка запуска' in text and 'Traceback' in text and 'Python' in text
    assert shown and 'startup_error.txt' in shown[0] and 'тестовая ошибка запуска' in shown[0]


def test_guarded_passes_result_and_system_exit(monkeypatch):
    from smetagaz import startup
    assert startup.guarded(lambda: 7) == 7
    with pytest.raises(SystemExit) as e:
        startup.guarded(lambda: (_ for _ in ()).throw(SystemExit(3)))
    assert e.value.code == 3


def test_selftest_starts_program_like_user(tmp_path, monkeypatch):
    """Самопроверка собранной программы: пустая база во временной папке, миграции, все разделы меню открываются."""
    import os, subprocess, sys
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    run = Path(__file__).resolve().parent.parent / 'run.py'
    out = subprocess.run([sys.executable, str(run), '--selftest'], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=240)
    report = (tmp_path / 'selftest.txt').read_text(encoding='utf-8')
    assert out.returncode == 0 and report.startswith('ВСЁ В ПОРЯДКЕ'), report
    assert 'главное окно: разделов меню' in report and 'миграции на пустой базе' in report
