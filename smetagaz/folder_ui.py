"""Привязка папки договора по кнопке: выбрать существующую или создать новую с понятным именем."""
import os

from PyQt6.QtWidgets import QMessageBox, QFileDialog

from . import gsv_project_domain as gd


def choose_folder(parent, section, suggested_name, current=''):
    """Спрашивает, привязать существующую папку или создать новую. Возвращает (путь, создана_ли_новая) или (None, False)."""
    box = QMessageBox(parent)
    box.setWindowTitle('Папка договора')
    box.setIcon(QMessageBox.Icon.Question)
    box.setText('Папка договора ещё не привязана.' if not current else f'Сейчас привязана папка:\n{current}')
    box.setInformativeText('Привязать существующую папку или создать новую?\n\nИмя новой папки:\n' + suggested_name)
    new_button = box.addButton('Создать новую', QMessageBox.ButtonRole.AcceptRole)
    existing_button = box.addButton('Привязать существующую…', QMessageBox.ButtonRole.ActionRole)
    box.addButton('Отмена', QMessageBox.ButtonRole.RejectRole)
    box.exec()
    clicked = box.clickedButton()
    if clicked is existing_button:
        start = current or str(gd.section_root(section)) if os.path.isdir(current or str(gd.section_root(section))) else ''
        path = QFileDialog.getExistingDirectory(parent, 'Выберите существующую папку договора', start)
        return (path, False) if path else (None, False)
    if clicked is new_button:
        root = gd.section_root(section)
        root.mkdir(parents=True, exist_ok=True)
        place = QFileDialog.getExistingDirectory(parent, 'Где создать новую папку?', str(root))
        if not place:
            return None, False
        return os.path.join(place, suggested_name), True
    return None, False


def ensure_project_folder(parent, db, pid):
    """Папка проекта: возвращает путь, при необходимости спрашивая пользователя; '' если отказался."""
    current = gd.project_folder(db, pid)
    if current:
        return current
    path, create = choose_folder(parent, 'gsv_projects', gd.project_folder_name(db, pid))
    if not path:
        return ''
    try:
        return gd.link_folder(db, pid, path, create=create)
    except (ValueError, OSError) as e:
        QMessageBox.warning(parent, 'Папка договора', str(e))
        return ''


def change_project_folder(parent, db, pid):
    current = gd.project_folder(db, pid)
    path, create = choose_folder(parent, 'gsv_projects', gd.project_folder_name(db, pid), current)
    if not path:
        return ''
    try:
        return gd.link_folder(db, pid, path, create=create)
    except (ValueError, OSError) as e:
        QMessageBox.warning(parent, 'Папка договора', str(e))
        return ''
