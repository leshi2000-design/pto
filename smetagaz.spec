# PyInstaller: сборка папки dist\СМЕТА-ГАЗ\ (запуск: build_windows.bat)
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hidden = (collect_submodules('smetagaz') + collect_submodules('pyqtgraph') + collect_submodules('openpyxl') +
          ['pandas', 'bs4', 'lxml', 'lxml.etree', 'requests', 'docx', 'reportlab', 'cryptography', 'PyQt6.QtSvg'])
datas = [('smetagaz/assets', 'smetagaz/assets')] + collect_data_files('docx') + collect_data_files('reportlab') + collect_data_files('pyqtgraph')

a = Analysis(['run.py'], pathex=['.'], datas=datas, hiddenimports=hidden, excludes=['tkinter', 'matplotlib', 'scipy', 'pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SmetaGaz', console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name='СМЕТА-ГАЗ')
