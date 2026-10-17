import os
# PyInstaller: сборка папки dist\ПТО\ (запуск: build_windows.bat)
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden = (collect_submodules('smetagaz') + collect_submodules('pyqtgraph') + collect_submodules('openpyxl') +
          ['pandas', 'bs4', 'lxml', 'lxml.etree', 'requests', 'docx', 'reportlab', 'cryptography', 'PyQt6.QtSvg', 'pypdfium2', 'PIL'])
datas = [('smetagaz/assets', 'smetagaz/assets')] + collect_data_files('PyQt6', includes=['Qt6/translations/qt_ru.qm', 'Qt6/translations/qtbase_ru.qm']) + collect_data_files('docx') + collect_data_files('reportlab') + collect_data_files('pyqtgraph') + collect_data_files('pypdfium2')

a = Analysis(['run.py'], pathex=['.'], datas=datas, hiddenimports=hidden, excludes=['tkinter', 'matplotlib', 'scipy', 'pytest'])
icon = 'smetagaz/assets/icon.ico' if os.path.exists('smetagaz/assets/icon.ico') else None
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PTO', console=False, icon=icon)
# второй исполняемый файл — ПТО Сервер для сетевой работы (общие библиотеки лежат рядом)
b = Analysis(['run_server.py'], pathex=['.'], datas=datas, hiddenimports=hidden, excludes=['tkinter', 'matplotlib', 'scipy', 'pytest'])
pyz_server = PYZ(b.pure)
exe_server = EXE(pyz_server, b.scripts, [], exclude_binaries=True, name='PTO_Server', console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, exe_server, b.binaries, b.datas, name='ПТО')
