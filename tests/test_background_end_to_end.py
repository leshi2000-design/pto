"""Работа в фоне «по-настоящему»: запускается настоящая программа (main_window.main) с ключом --background, значок у часов подменён (в тестовой среде его нет).
Проверяется: окно при запуске не показывается, а веб-доступ уже работает; второй запуск программы открывает окно первой; крестик сворачивает окно, а веб-доступ продолжает отвечать;
«Выход» из значка завершает программу без зависания."""
import json
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

PROBE = textwrap.dedent('''
    import json, os, subprocess, sys, urllib.request
    from pathlib import Path
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon
    data, port, out = Path(os.environ['SMETAGAZ_DATA_DIR']), int(os.environ['PROBE_PORT']), Path(os.environ['PROBE_OUT'])
    sys.path.insert(0, os.environ['PROBE_REPO'])
    sys.argv = ['run.py', '--background']
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: True)       # в тестовой среде нет области уведомлений — подменяем
    QSystemTrayIcon.isVisible = lambda self: True
    QSystemTrayIcon.showMessage = lambda self, *a, **k: None
    results = {}

    def health():
        try:
            return urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2).read().decode()
        except Exception as e:
            return 'ERR ' + str(e)

    def window():
        return next(w for w in QApplication.topLevelWidgets() if isinstance(w, QMainWindow))
    second = {}

    def step1():
        w = window()
        results['start_visible'] = w.isVisible()
        results['start_web'] = health()
        results['tray_enabled'] = w.background.enabled()
        results['authenticated_at_start'] = w.background.authenticated
        env = dict(os.environ, PROBE_OUT='')
        second['p'] = subprocess.Popen([sys.executable, os.environ['PROBE_RUN']], env=env, cwd=os.environ['PROBE_REPO'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def step2():
        w = window()
        results['second_rc'] = second['p'].poll()
        results['after_second_visible'] = w.isVisible()
        results['authenticated_after'] = w.background.authenticated

    def step3():
        w = window()
        w.close()                                                         # нажали крестик
        results['closed_hidden'] = not w.isVisible()
        results['app_alive'] = True

    def step4():
        results['web_after_close'] = health()
        window().background.quit_app()                                    # «Выход» из значка

    orig = QApplication.exec

    def patched(*a):
        for delay, fn in ((2500, step1), (5500, step2), (6500, step3), (8500, step4)):
            QTimer.singleShot(delay, fn)
        code = orig()
        results['exit_code'] = code
        out.write_text(json.dumps(results), encoding='utf-8')
        return code
    QApplication.exec = staticmethod(patched)
    from smetagaz.main_window import main
    main()
''')


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_background_mode_end_to_end(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    port = free_port()
    setup = (f"import sys; sys.path.insert(0, {str(REPO)!r})\n"
             f"from pathlib import Path\nfrom smetagaz.database import DatabaseManager\nfrom smetagaz import web_gateway as wg\n"
             f"d = DatabaseManager(Path({str(data)!r}) / 'smetagaz.db'); d.init_db()\n"
             f"for k, v in (('web_enabled', '1'), ('web_https', '0'), ('web_port', '{port}'), ('background_mode', '1')): d.set_setting(k, v)\n"
             f"wg.add_user(d, 'user1', 'password123', 'editor'); d.close()\n")
    env = {'QT_QPA_PLATFORM': 'offscreen', 'SMETAGAZ_DATA_DIR': str(data), 'PATH': '/usr/bin:/bin:/usr/local/bin', 'HOME': str(tmp_path)}
    subprocess.run([sys.executable, '-c', setup], check=True, env=env, cwd=REPO, timeout=60)
    probe = tmp_path / 'probe.py'
    probe.write_text(PROBE, encoding='utf-8')
    out = tmp_path / 'result.json'
    env.update(PROBE_PORT=str(port), PROBE_OUT=str(out), PROBE_REPO=str(REPO), PROBE_RUN=str(REPO / 'run.py'))
    done = subprocess.run([sys.executable, str(probe)], env=env, cwd=REPO, timeout=90, capture_output=True, text=True)
    assert out.exists(), done.stderr[-2000:]
    r = json.loads(out.read_text(encoding='utf-8'))
    assert r['tray_enabled'] and r['authenticated_at_start'] is False
    assert r['start_visible'] is False and r['start_web'] == 'ok'                       # тихий запуск: окна нет, веб-доступ уже отвечает
    assert r['second_rc'] == 0 and r['after_second_visible'] is True and r['authenticated_after'] is True       # второй запуск открыл окно первой программы и сам завершился
    assert r['closed_hidden'] is True and r['web_after_close'] == 'ok'                  # крестик свернул окно, веб-доступ продолжает отвечать
    assert r['exit_code'] == 0                                                          # «Выход» из значка завершил программу без зависания
    # после выхода сайт больше не отвечает
    try:
        socket.create_connection(('127.0.0.1', port), timeout=1).close()
        reachable = True
    except OSError:
        reachable = False
    assert not reachable
