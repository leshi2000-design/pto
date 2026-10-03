import os
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

def open_local(path, verb=None):
    if verb == 'print' and os.name == 'nt':
        return os.startfile(os.path.abspath(path), 'print')
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(path))):
        raise OSError('Не удалось открыть файл в системном приложении')
