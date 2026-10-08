"""Package only Магазин, excluding data, credentials and virtual environments."""
from pathlib import Path
import hashlib
import shutil
import tempfile
import zipfile

repo = Path(__file__).resolve().parents[1]
output = repo / 'downloads'
output.mkdir(exist_ok=True)
files = ['run_shop.py', 'run_shop_server.py', 'start_shop_windows.bat', 'start_shop_server_windows.bat',
    'start_shop_client_windows.bat', 'docs/MAGAZIN_GUIDE_RU.md', 'tests/test_shop.py',
    'tests/test_shop_accounting.py', 'tests/smoke_shop.py', 'tests/smoke_shop_network.py']
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / 'Magazin'
    root.mkdir()
    for name in files + [p.relative_to(repo).as_posix() for p in (repo / 'shop').glob('*.py')]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / name, target)
    packages = {'PyQt6', 'openpyxl', 'python-docx', 'requests', 'beautifulsoup4', 'lxml'}
    lines = [line for line in (repo / 'requirements-tested.txt').read_text().splitlines() if line.split('==')[0] in packages]
    (root / 'requirements-tested.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    (root / 'README.txt').write_text('''МАГАЗИН 2 — СКЛАД, СЧЕТА, ОПЛАТЫ И ЛОКАЛЬНАЯ СЕТЬ

Нужен Python 3.12 с Python Launcher. Это исходники, не Windows EXE.
Распакуйте архив целиком. Первый запуск требует интернет для зависимостей.

ОДИН КОМПЬЮТЕР: start_shop_windows.bat
СЕРВЕР СЕТИ: start_shop_server_windows.bat (оставьте окно открытым)
КЛИЕНТ СЕТИ: start_shop_client_windows.bat (адрес http://IP:8765 и ключ)
Ключ создаётся на сервере: %USERPROFILE%\\.magazin\\server-key.txt

Инструкция: docs/MAGAZIN_GUIDE_RU.md
Пример с демонстрационными данными: interface-preview.png
Старые данные не удаляйте. Перед миграцией создаётся резервная копия.
Ошибки: error.log в папке данных; сервер: server-error.log.

Склад показывает остаток, резерв и доступное количество.
Счёт резервирует товар. Передача списывает его со склада.
Есть розничные цены, оплаты, долги, статистика и календарь.

Сетевая база находится только на сервере. Общий ключ, без ролей.
HTTP не шифрует данные: доверенная сеть/VPN или HTTPS по инструкции.
Не публикуйте ключ. Сервер не открывайте в публичный интернет.

Шаблоны — образцы, не утверждённые ТН-2/ТТН-1.
Сайты могут требовать селекторов или отдельных адаптеров.
На реальной Windows-сети сборка ещё не проверена.
''', encoding='utf-8-sig')
    (root / 'start_shop_linux.sh').write_text('''#!/usr/bin/env bash
set -eu
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then python3.12 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements-tested.txt
exec .venv/bin/python run_shop.py "$@"
''', encoding='utf-8')
    preview = output / 'Magazin-interface.png'
    if preview.exists():
        shutil.copy2(preview, root / 'interface-preview.png')
    checksums = [hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(root).as_posix() for p in sorted(root.rglob('*')) if p.is_file()]
    (root / 'SHA256SUMS.txt').write_text('\n'.join(checksums)+'\n', encoding='utf-8')
    with zipfile.ZipFile(output / 'Magazin.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(root.parent))
    with zipfile.ZipFile(output / 'Magazin.zip') as archive:
        assert archive.testzip() is None
print('Magazin.zip created with current source, guide, launch scripts and checksums')
