"""Interactive Save As for generated documents. Call only from the GUI thread."""
from pathlib import Path

from PyQt6.QtCore import QStandardPaths
from PyQt6.QtWidgets import QFileDialog, QMessageBox

_last_directory = ''
LABELS = {'.docx': 'Word', '.xlsx': 'Excel', '.pdf': 'PDF', '.zip': 'ZIP'}


def choose_document_path(parent, suggested, *, title='Сохранить как', protected=()):
    """Return the selected absolute filename, or '' on cancellation.

    DefaultSuffix lets the native dialog confirm overwriting the actual output
    file, including when the user enters a name without an extension.
    """
    global _last_directory
    suggested = Path(suggested)
    suffix = suggested.suffix.lower()
    if not suffix:
        raise ValueError('Не указан формат документа')
    directory = suggested.parent if suggested.is_absolute() and suggested.parent.is_dir() else None
    if directory is None:
        directory = Path(_last_directory or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or Path.cwd())
    forbidden = {Path(p).resolve() for p in protected if p}
    dialog = QFileDialog(parent, title, str(directory))
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    dialog.setNameFilter(f'{LABELS.get(suffix, "Документ")} (*{suffix})')
    dialog.setDefaultSuffix(suffix.lstrip('.'))
    dialog.selectFile(suggested.name)
    while dialog.exec() == QFileDialog.DialogCode.Accepted:
        selected = dialog.selectedFiles()
        if not selected:
            return ''
        raw = Path(selected[0]).expanduser().absolute()
        path = raw if raw.suffix.lower() == suffix else Path(str(raw) + suffix)
        if path.resolve() in forbidden:
            QMessageBox.warning(parent, 'Выберите другое имя', 'Нельзя заменить исходный шаблон или документ. Выберите другое имя файла.')
            continue
        if path != raw and path.exists():
            answer = QMessageBox.question(parent, 'Заменить файл?', f'Файл уже существует:\n{path}\n\nЗаменить его?',
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                continue
        _last_directory = str(path.parent)
        return str(path)
    return ''


def choose_document_paths(parent, jobs):
    """jobs: [{key, path, source?}]. Collect ALL choices before writing any file."""
    jobs = list(jobs)
    protected = [job['source'] for job in jobs if job.get('source')]
    chosen = {}
    used = set()
    for job in jobs:
        while True:
            path = choose_document_path(parent, job['path'], protected=protected)
            if not path:
                return None
            key = str(Path(path).resolve()).casefold()
            if key not in used:
                break
            QMessageBox.warning(parent, 'Выберите другое имя', 'Этот путь уже выбран для другого документа комплекта.')
        used.add(key)
        chosen[job['key']] = path
    return chosen
