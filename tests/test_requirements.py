"""requirements.txt должен перечислять все сторонние библиотеки, которые импортирует программа (пустой или неполный файл ломает сборку и установку)."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_OF = {'PyQt6': 'pyqt6', 'pyqtgraph': 'pyqtgraph', 'pandas': 'pandas', 'openpyxl': 'openpyxl', 'docx': 'python-docx', 'reportlab': 'reportlab', 'cryptography': 'cryptography',
              'requests': 'requests', 'bs4': 'beautifulsoup4', 'lxml': 'lxml', 'pypdf': 'pypdf', 'pypdfium2': 'pypdfium2', 'PIL': 'pillow'}
OPTIONAL = {'qdarktheme', 'numpy', 'xlrd', 'win32crypt', 'win32com', 'pythoncom', 'pytesseract', 'fitz', 'pdf2image'}       # приходят вместе с другими или нужны только по возможности


def required_names():
    names = set()
    for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        line = line.split('#')[0].strip()
        if line:
            for sep in '<>=!~[;':
                line = line.split(sep)[0]
            names.add(line.strip().lower().replace('_', '-'))
    return names


def test_requirements_not_empty_and_cover_all_imports():
    declared = required_names()
    assert len(declared) >= 10, 'requirements.txt пуст или почти пуст'
    used = {}
    for path in list((ROOT / 'smetagaz').glob('*.py')) + [ROOT / 'run.py', ROOT / 'run_server.py']:
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module.split('.')[0]]
            for m in mods:
                if m not in sys.stdlib_module_names and m != 'smetagaz' and m not in OPTIONAL:
                    used.setdefault(m, path.name)
    unknown = {m: f for m, f in used.items() if m not in PACKAGE_OF}
    assert not unknown, f'сторонние модули без записи в таблице пакетов теста: {unknown}'
    missing = {m: PACKAGE_OF[m] for m in used if PACKAGE_OF[m] not in declared}
    assert not missing, f'не перечислены в requirements.txt: {missing}'
