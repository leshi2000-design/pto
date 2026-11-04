"""Обновление программы из ZIP-файла — без замены файлов программы.

Как это работает. Обновление (ZIP с папкой smetagaz — тот же архив, что вы получаете) распаковывается в папку данных (…\\.smetagaz\\updates\\<версия>), проверяется
(безопасность архива, синтаксис, самопроверка в отдельном процессе) и включается записью в updates\\current.txt. При каждом запуске ЭТОТ небольшой модуль (он остаётся в сборке)
подключает пакет smetagaz из включённого обновления вместо встроенного. Файлы PTO.exe / _internal не изменяются, поэтому нет блокировок Windows и «полузамененных» файлов.
Если обновление не запускается, программа сама отключает его и стартует со встроенной версией; вернуться к встроенной версии можно и вручную (Справка → Обновить из ZIP).

Модуль работает до импорта пакета smetagaz и поэтому не использует ничего из него."""
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

PACKAGE = 'smetagaz'
MAX_FILES = 6000
MAX_BYTES = 300 * 1024 * 1024
KEEP = 3
FORBIDDEN_SUFFIXES = {'.exe', '.dll', '.bat', '.cmd', '.ps1', '.vbs', '.msi', '.scr', '.com', '.pyd', '.so', '.dylib', '.jar', '.js', '.lnk'}
ACTIVE = None          # сведения о подключённом обновлении (заполняется activate)
IGNORED = None         # причина, по которой обновление не подключено


class UpdateError(Exception):
    """Понятная пользователю причина, по которой архив нельзя установить."""


def data_dir():
    return Path(os.environ.get('SMETAGAZ_DATA_DIR') or (Path.home() / '.smetagaz'))


def updates_dir():
    return data_dir() / 'updates'


def parse_version(text):
    nums = re.findall(r'\d+', str(text or ''))[:3]
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums))


def version_of(source):
    m = re.search(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', source, re.M)
    return m.group(1) if m else ''


def _pointer():
    return updates_dir() / 'current.txt'


def current_name():
    try:
        return _pointer().read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def folder_of(name):
    if not name or '/' in name or '\\' in name or name in ('.', '..'):
        return None
    folder = updates_dir() / name
    return folder if (folder / PACKAGE / '__init__.py').is_file() else None


# --- ПОДКЛЮЧЕНИЕ ПРИ ЗАПУСКЕ -------------------------------------------------------------------------

class _Finder(importlib.abc.MetaPathFinder):
    """Пакет smetagaz и все его модули берутся только из обновления; отсутствующий в нём модуль не подменяется встроенным (иначе версии смешались бы)."""
    def __init__(self, root):
        self.root = str(root)

    def find_spec(self, fullname, path=None, target=None):
        if fullname != PACKAGE and not fullname.startswith(PACKAGE + '.'):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, [self.root] if fullname == PACKAGE else path, target)
        if spec is None:
            raise ModuleNotFoundError(f'{fullname}: в установленном обновлении нет этого модуля', name=fullname)
        return spec


def _purge():
    for name in [n for n in sys.modules if n == PACKAGE or n.startswith(PACKAGE + '.')]:
        del sys.modules[name]


def builtin_version():
    """Версия встроенной в программу (не из обновления) копии пакета."""
    try:
        import smetagaz as built_in
        version = built_in.__version__
    except Exception:
        version = ''
    _purge()
    return version


def activate():
    """Подключает включённое обновление, если оно новее встроенной версии. PTO_OVERLAY_DIR — проверка конкретной папки (самопроверка перед установкой);
    PTO_NO_OVERLAY=1 — запуск только со встроенной версией. Возвращает сведения об обновлении или None."""
    global ACTIVE, IGNORED
    ACTIVE = IGNORED = None
    if os.environ.get('PTO_NO_OVERLAY') == '1':
        return None
    explicit = os.environ.get('PTO_OVERLAY_DIR')
    if explicit:
        folder, name = Path(explicit), Path(explicit).name
        if not (folder / PACKAGE / '__init__.py').is_file():
            return None
    else:
        name = current_name()
        folder = folder_of(name)
        if not folder:
            if name:
                IGNORED = f'папка обновления «{name}» не найдена или повреждена'
            return None
    try:
        version = version_of((folder / PACKAGE / '__init__.py').read_text(encoding='utf-8'))
    except OSError:
        IGNORED = 'не удалось прочитать версию обновления'
        return None
    base = builtin_version()
    if not explicit and base and parse_version(version) <= parse_version(base):
        IGNORED = f'встроенная версия {base} не старее обновления {version} — обновление не нужно'
        return None
    sys.meta_path.insert(0, _Finder(folder))
    ACTIVE = dict(name=name, version=version, builtin=base, path=str(folder))
    return ACTIVE


def deactivate(reason=''):
    """Отключает включённое обновление (возврат к встроенной версии); причина сохраняется в updates\\last_failure.txt."""
    folder = updates_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if reason:
            (folder / 'last_failure.txt').write_text(f'{datetime.now():%d.%m.%Y %H:%M:%S}\n{reason}', encoding='utf-8')
        _pointer().unlink(missing_ok=True)
    except OSError:
        pass


def relaunch(extra_env=None):
    """Запускает программу заново (после отката на встроенную версию)."""
    env = dict(os.environ, **(extra_env or {}))
    args = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).with_name('run.py'))]
    subprocess.Popen(args + sys.argv[1:], env=env, close_fds=True)


# --- УСТАНОВКА ИЗ ZIP -------------------------------------------------------------------------------------

def _safe_name(raw):
    name = raw.replace('\\', '/')
    parts = [p for p in name.split('/') if p not in ('', '.')]
    if name.startswith('/') or re.match(r'^[A-Za-z]:', name) or '..' in parts:
        raise UpdateError(f'В архиве небезопасный путь: {raw}')
    return '/'.join(parts)


def inspect_zip(zip_path):
    """Проверяет архив и возвращает сведения: version, prefix, members [(имя в архиве, имя внутри папки обновления)], size, requirements (текст или '').
    Принимаются архивы вида PTO_x.y.z/smetagaz/… или smetagaz/… ; ничего не распаковывается."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        raise UpdateError(f'Не удалось открыть архив: {e}') from None
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES * 4:
            raise UpdateError('В архиве слишком много файлов')
        names = {}
        for info in infos:
            if info.is_dir():
                continue
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise UpdateError(f'В архиве символическая ссылка: {info.filename}')
            names[_safe_name(info.filename)] = info
        inits = [n for n in names if re.fullmatch(rf'(?:[^/]+/)?{PACKAGE}/__init__\.py', n)]
        if len(inits) != 1:
            raise UpdateError('Это не архив обновления ПТО: в нём нет папки smetagaz (нужен тот же ZIP, что и для установки программы).')
        prefix = inits[0][:-len(f'{PACKAGE}/__init__.py')]
        version = version_of(zf.read(names[inits[0]]).decode('utf-8', 'replace'))
        if not version:
            raise UpdateError('В архиве не найден номер версии (smetagaz/__init__.py).')
        members, size = [], 0
        for name, info in names.items():
            if not name.startswith(prefix + PACKAGE + '/') or '/__pycache__/' in name or name.endswith('.pyc'):
                continue
            if Path(name).suffix.lower() in FORBIDDEN_SUFFIXES:
                raise UpdateError(f'Обновление содержит недопустимый файл ({Path(name).name}): обновляются только Python-модули и данные программы.')
            members.append((info.filename, name[len(prefix):]))
            size += info.file_size
        if len(members) > MAX_FILES or size > MAX_BYTES:
            raise UpdateError('Архив слишком большой для обновления программы.')
        req = ''
        if prefix + 'requirements.txt' in names:
            req = zf.read(names[prefix + 'requirements.txt']).decode('utf-8', 'replace')
    return dict(version=version, prefix=prefix, members=members, size=size, requirements=req, zip=str(zip_path))


IMPORT_NAMES = {'python-docx': 'docx', 'beautifulsoup4': 'bs4', 'pillow': 'PIL', 'pyqt6': 'PyQt6', 'pypdf': 'pypdf', 'pypdfium2': 'pypdfium2', 'lxml': 'lxml',
                'reportlab': 'reportlab', 'cryptography': 'cryptography', 'requests': 'requests', 'openpyxl': 'openpyxl', 'pandas': 'pandas', 'pyqtgraph': 'pyqtgraph'}


def missing_requirements(text):
    """Библиотеки из requirements.txt обновления, которых нет в программе (для них обновление из ZIP не подходит — нужна пересборка программы)."""
    missing = []
    for line in str(text or '').splitlines():
        line = line.split('#')[0].strip()
        if not line:
            continue
        name = re.split(r'[<>=!~;\[ ]', line, maxsplit=1)[0].strip()
        module = IMPORT_NAMES.get(name.lower(), name.replace('-', '_'))
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(name)
    return missing


def extract(info, dest):
    """Распаковывает файлы пакета в dest (папка создаётся); пути проверены в inspect_zip, здесь — ещё раз относительно dest."""
    dest = Path(dest)
    root = dest.resolve()
    with zipfile.ZipFile(info['zip']) as zf:
        for original, rel in info['members']:
            target = (dest / rel).resolve()
            if not target.is_relative_to(root):
                raise UpdateError(f'Файл вне папки обновления: {rel}')
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(original) as src, open(target, 'wb') as out:
                shutil.copyfileobj(src, out, 1024 * 1024)


def compile_check(dest):
    """Синтаксис всех .py файлов обновления текущим интерпретатором (до запуска). Возвращает список ошибок."""
    errors = []
    for path in Path(dest).rglob('*.py'):
        try:
            compile(path.read_bytes(), str(path), 'exec', dont_inherit=True)
        except (SyntaxError, ValueError) as e:
            errors.append(f'{path.relative_to(dest).as_posix()}: {e}')
    return errors


def run_selftest(dest, timeout=240):
    """Самопроверка обновления в отдельном процессе (пустая база во временной папке): возвращает (успешно, текст отчёта)."""
    with tempfile.TemporaryDirectory(prefix='pto_update_check_') as tmp:
        out = Path(tmp) / 'selftest.txt'
        env = dict(os.environ, PTO_OVERLAY_DIR=str(dest), PTO_SELFTEST_OUT=str(out), SMETAGAZ_DATA_DIR=str(Path(tmp) / 'data'), QT_QPA_PLATFORM='offscreen')
        env.pop('PTO_NO_OVERLAY', None)
        args = [sys.executable, '--selftest'] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).with_name('run.py')), '--selftest']
        try:
            result = subprocess.run(args, env=env, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            return False, f'Самопроверка не завершилась за {timeout} с.'
        except OSError as e:
            return False, f'Не удалось запустить самопроверку: {e}'
        text = out.read_text(encoding='utf-8') if out.is_file() else (result.stderr or b'').decode('utf-8', 'replace')[-2000:]
        return result.returncode == 0 and text.startswith('ВСЁ В ПОРЯДКЕ'), text


def stage(zip_path):
    """Шаги 1–3: проверка архива, распаковка в новую папку updates\\<имя> и проверка синтаксиса. Возвращает (info, папка, предупреждения). При ошибке папка удаляется."""
    info = inspect_zip(zip_path)
    warnings = []
    missing = missing_requirements(info['requirements'])
    if missing:
        warnings.append('Обновлению нужны библиотеки, которых нет в этой сборке: ' + ', '.join(missing) + '. Для них потребуется пересборка программы (build_windows.bat).')
    name = f'v{info["version"]}_{datetime.now():%Y%m%d_%H%M%S}'
    dest = updates_dir() / name
    try:
        extract(info, dest)
        errors = compile_check(dest)
        if errors:
            raise UpdateError('В обновлении есть синтаксические ошибки:\n' + '\n'.join(errors[:5]))
        meta = dict(version=info['version'], installed=datetime.now().isoformat(timespec='seconds'), source=Path(zip_path).name, warnings=warnings)
        (dest / 'info.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return info, dest, warnings


def activate_folder(dest):
    """Включает проверенное обновление: со следующего запуска программа использует его."""
    updates_dir().mkdir(parents=True, exist_ok=True)
    tmp = _pointer().with_suffix('.tmp')
    tmp.write_text(Path(dest).name, encoding='utf-8')
    os.replace(tmp, _pointer())
    cleanup()


def installed():
    """Установленные обновления, новые сверху: [{name, version, installed, source, active}]."""
    out = []
    root = updates_dir()
    if root.is_dir():
        for folder in sorted((p for p in root.iterdir() if p.is_dir() and (p / PACKAGE / '__init__.py').is_file()), key=lambda p: p.name.split('_', 1)[-1], reverse=True):        # новые сверху (по времени установки в имени папки)
            try:
                meta = json.loads((folder / 'info.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                meta = {}
            out.append(dict(name=folder.name, version=meta.get('version') or version_of((folder / PACKAGE / '__init__.py').read_text(encoding='utf-8')), installed=meta.get('installed', ''),
                            source=meta.get('source', ''), active=folder.name == current_name()))
    return out


def cleanup(keep=KEEP):
    """Удаляет старые установленные обновления, кроме включённого и последних keep."""
    items = installed()
    keep_names = {i['name'] for i in items[:keep]} | {current_name()}
    for item in items:
        if item['name'] not in keep_names:
            shutil.rmtree(updates_dir() / item['name'], ignore_errors=True)
