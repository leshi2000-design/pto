"""Самопроверка собранной программы (PTO.exe --selftest): все ли нужные библиотеки на месте."""
import sys


def _has_server():
    from pathlib import Path
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
    return (base / 'PTO_Server.exe').exists() or (base / 'PTO_Server').exists()


def run():
    """Проверка собранной программы: импортирует всё, что нужно окну сервера и расшифровке накладных. Пишет результат в selftest.txt (у exe без консоли нет вывода)."""
    import importlib
    import traceback
    from pathlib import Path
    import os
    import tempfile
    tmp = tempfile.mkdtemp(prefix='pto_selftest_')              # самопроверка работает во временной папке и не трогает данные пользователя
    os.environ['SMETAGAZ_DATA_DIR'] = tmp
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    report, ok = [], True
    for name in ('PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.QtSvg', 'cryptography', 'openpyxl', 'docx', 'pypdf', 'pypdfium2', 'PIL', 'smetagaz.main_window', 'smetagaz.invoice_ui', 'smetagaz.material_groups_ui', 'smetagaz.section_codes_ui', 'smetagaz.edit_lock_ui', 'smetagaz.network_ui', 'smetagaz.staff_view', 'smetagaz.incoming_view') + (('smetagaz.server_app',) if _has_server() else ()):
        try:
            importlib.import_module(name)
            report.append(f'OK    {name}')
        except Exception:
            ok = False
            report.append(f'FAIL  {name}\n{traceback.format_exc()}')
    # запуск «как у пользователя»: пустая база во временной папке, миграции и построение главного окна (без показа)
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from smetagaz.database import DatabaseManager
        probe = DatabaseManager(os.path.join(tmp, 'probe.db'))
        probe.init_db()
        probe.close()
        report.append('OK    база данных: миграции на пустой базе')
        from smetagaz import main_window
        from smetagaz.database import db as main_db
        main_db.init_db()
        window = main_window.MainWindow()
        for i, button in enumerate(window.tabs_buttons):          # каждый раздел меню открывается без ошибок
            window.switch_tab(i, button)
        window.close()
        report.append(f'OK    главное окно: разделов меню — {len(window.tabs_buttons)}')
    except Exception:
        ok = False
        report.append('FAIL  запуск программы\n' + traceback.format_exc())
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
    (base / 'selftest.txt').write_text(('ВСЁ В ПОРЯДКЕ\n' if ok else 'ЕСТЬ ОШИБКИ\n') + '\n'.join(report), encoding='utf-8')
    return 0 if ok else 1
