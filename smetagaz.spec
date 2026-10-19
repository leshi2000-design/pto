import os
# PyInstaller: сборка папки dist\ПТО\ (запуск: build_windows.bat)
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Сборка должна идти тем Python, где установлен PyQt6 (build_windows.bat использует .venv). Иначе PyInstaller молча соберёт программу без PyQt6,
# и она упадёт при запуске с «No module named PyQt6». Лучше остановиться сразу и объяснить.
import sys
try:
    import PyQt6.QtCore as _qt
except ImportError:
    raise SystemExit('СБОРКА ОСТАНОВЛЕНА: в Python, которым запущен PyInstaller (' + sys.executable + '), нет PyQt6.\n'
                     'Запускайте build_windows.bat (он создаёт .venv и ставит всё из requirements.txt) или установите: "' + sys.executable + '" -m pip install -r requirements.txt')
print('Сборка: Python', sys.version.split()[0], sys.executable, '· PyQt6', _qt.PYQT_VERSION_STR)

hidden = (collect_submodules('smetagaz') + collect_submodules('pyqtgraph') + collect_submodules('openpyxl') +
          ['pandas', 'bs4', 'lxml', 'lxml.etree', 'requests', 'docx', 'reportlab', 'cryptography', 'PyQt6', 'PyQt6.sip', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.QtSvg', 'PyQt6.QtPrintSupport', 'pypdfium2', 'PIL'])
datas = [('smetagaz/assets', 'smetagaz/assets')] + collect_data_files('PyQt6', includes=['Qt6/translations/qt_ru.qm', 'Qt6/translations/qtbase_ru.qm']) + collect_data_files('docx') + collect_data_files('reportlab') + collect_data_files('pyqtgraph') + collect_data_files('pypdfium2')

# По умолчанию собирается только программа (PTO.exe). ПТО Сервер добавляется переменной окружения PTO_WITH_SERVER=1 (build_windows.bat server).
# Оба файла собираются одним анализом, чтобы набор модулей (в том числе PyQt6) был одинаковым.
with_server = os.environ.get('PTO_WITH_SERVER') == '1'
a = Analysis(['run.py'] + (['run_server.py'] if with_server else []), pathex=['.'], datas=datas, hiddenimports=hidden, excludes=['tkinter', 'matplotlib', 'scipy', 'pytest'])
icon = 'smetagaz/assets/icon.ico' if os.path.exists('smetagaz/assets/icon.ico') else None
pyz = PYZ(a.pure)
hooks = [s for s in a.scripts if s[0].startswith('pyi_rth')]            # служебные скрипты PyInstaller нужны обоим файлам
script_main = [s for s in a.scripts if s[0] == 'run']
assert script_main, 'в сборке нет run.py'
exe = EXE(pyz, hooks + script_main, [], exclude_binaries=True, name='PTO', console=False, icon=icon)
exes = [exe]
if with_server:
    script_server = [s for s in a.scripts if s[0] == 'run_server']
    assert script_server, 'в сборке нет run_server.py'
    exes.append(EXE(pyz, hooks + script_server, [], exclude_binaries=True, name='PTO_Server', console=False, icon=icon))
coll = COLLECT(*exes, a.binaries, a.datas, name='ПТО')
