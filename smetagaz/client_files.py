"""Файлы клиента: папки всех его договоров (проекты ГСВ, монтаж ГСВ, монтаж ГСН) в одном окне."""
import os
from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QPushButton, QLabel
from PyQt6.QtCore import Qt

from .database import db
from .platform_utils import open_local

SECTIONS = {'gsv_projects': 'Проекты ГСВ', 'contracts': 'Монтаж ГСВ', 'gsn_projects': 'Монтаж ГСН', 'smr_contracts': 'СМР', 'le_contracts': 'Юрлица'}
MAX_FILES = 500


def client_folders(db, cid):
    """[(раздел, подпись договора, папка)] по всем договорам клиента."""
    result = []
    for rid, number, obj, folder in db.fetchall('SELECT id,pd_number,object_name,project_folder FROM gsv_projects WHERE client_id=? ORDER BY id DESC', (cid,)):
        result.append((SECTIONS['gsv_projects'], f'{number} · {obj or ""}'.strip(' ·'), folder or ''))
    for rid, number, obj in db.fetchall('SELECT id,contract_number,object_name FROM contracts WHERE client_id=? ORDER BY id DESC', (cid,)):
        row = db.fetchone("SELECT contract_folder FROM contracts WHERE id=?", (rid,))
        result.append((SECTIONS['contracts'], f'№{number or rid} · {obj or ""}'.strip(' ·'), row[0] if row and row[0] else ''))
    for rid, number, title in db.fetchall('SELECT id,contract_number,title FROM gsn_projects WHERE client_id=? ORDER BY id DESC', (cid,)):
        row = db.fetchone("SELECT folder_path FROM executive_objects WHERE owner_type='gsn_projects' AND owner_id=?", (rid,))
        result.append((SECTIONS['gsn_projects'], f'№{number or rid} · {title or ""}'.strip(' ·'), row[0] if row else ''))
    for number, obj, folder in db.fetchall('SELECT contract_number,coalesce(nullif(object_address,\'\'),object_name),folder FROM smr_contracts WHERE person_id=? ORDER BY id DESC', (cid,)):
        result.append((SECTIONS['smr_contracts'], f'№{number} · {obj or ""}'.strip(' ·'), folder or ''))
    return result


def legal_folders(db, lid):
    """[(раздел, подпись договора, папка)] по договорам юрлица в «Юрлицах», «СМР» и карточках ГСВ, где оно заказчик."""
    result = []
    for number, obj, folder in db.fetchall('SELECT contract_number,coalesce(nullif(object_address,\'\'),object_name),folder FROM le_contracts WHERE client_id=? ORDER BY id DESC', (lid,)):
        result.append((SECTIONS['le_contracts'], f'№{number} · {obj or ""}'.strip(' ·'), folder or ''))
    for number, obj, folder in db.fetchall('SELECT contract_number,coalesce(nullif(object_address,\'\'),object_name),folder FROM smr_contracts WHERE legal_id=? ORDER BY id DESC', (lid,)):
        result.append((SECTIONS['smr_contracts'], f'№{number} · {obj or ""}'.strip(' ·'), folder or ''))
    for number, obj, folder in db.fetchall('SELECT pd_number,object_name,project_folder FROM gsv_projects WHERE le_client_id=? ORDER BY id DESC', (lid,)):
        result.append((SECTIONS['gsv_projects'], f'{number} · {obj or ""}'.strip(' ·'), folder or ''))
    for number, obj, folder in db.fetchall('SELECT contract_number,object_name,contract_folder FROM contracts WHERE le_client_id=? ORDER BY id DESC', (lid,)):
        result.append((SECTIONS['contracts'], f'№{number} · {obj or ""}'.strip(' ·'), folder or ''))
    return result


def list_files(folder, limit=MAX_FILES):
    base = Path(folder)
    files = []
    for path in sorted(base.rglob('*')):
        if path.is_file():
            files.append(path)
            if len(files) >= limit:
                break
    return files


class ClientFilesWidget(QWidget):
    """Дерево «раздел → договор → файлы»; двойной щелчок открывает файл или папку."""
    def __init__(self, cid, parent=None, kind='person'):
        super().__init__(parent)
        self.cid = cid
        self.kind = kind
        layout = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Файл', 'Размер, КБ', 'Путь'])
        self.tree.setColumnWidth(0, 360)
        self.tree.itemDoubleClicked.connect(self.open_item)
        layout.addWidget(self.tree, 1)
        bar = QHBoxLayout()
        refresh = QPushButton('Обновить')
        refresh.clicked.connect(self.load)
        bar.addWidget(refresh)
        bar.addStretch()
        layout.addLayout(bar)
        self.load()

    def load(self):
        self.tree.clear()
        if not self.cid:
            self.info.setText('Файлы появятся после сохранения клиента.')
            return
        folders = legal_folders(db, self.cid) if self.kind == 'legal' else client_folders(db, self.cid)
        total = 0
        for section, label, folder in folders:
            top = QTreeWidgetItem([f'{section} · {label}', '', folder])
            top.setData(0, Qt.ItemDataRole.UserRole, folder)
            top.setForeground(0, self.palette().link())
            self.tree.addTopLevelItem(top)
            if not folder or not os.path.isdir(folder):
                top.addChild(QTreeWidgetItem(['Папка не создана или недоступна', '', '']))
                continue
            for path in list_files(folder):
                total += 1
                child = QTreeWidgetItem([str(path.relative_to(folder)), f'{path.stat().st_size / 1024:.1f}', str(path)])
                child.setData(0, Qt.ItemDataRole.UserRole, str(path))
                top.addChild(child)
            top.setExpanded(True)
        self.info.setText(f'Договоров клиента: {len(folders)}, файлов: {total}. Двойной щелчок открывает файл или папку договора.' if folders else 'У клиента пока нет договоров.')

    def open_item(self, item, _column=0):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path and os.path.exists(path):
            open_local(os.path.abspath(path))
