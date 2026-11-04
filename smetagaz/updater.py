"""Проверка новой версии. Адрес файла версий задаётся пользователем (JSON {"version": "3.5.0", "url": "...", "notes": "..."} или просто текст с номером версии).
Программа сама ничего не скачивает: она показывает, что есть новая версия; установка — из скачанного ZIP-файла (Справка → Обновить программу из ZIP)."""
import json
import re
import urllib.request
from datetime import datetime

from . import __version__

HOW_TO = ("Как обновиться без потери данных:\n"
          "1. Получите ZIP-архив новой версии (тот же файл, что присылается для установки).\n"
          "2. В программе: Справка (F1) → «Обновить программу из ZIP…» → «Выбрать ZIP…».\n"
          "3. Программа сама проверит архив, сделает снимок баз данных (папка backups) и установит обновление в папку данных — файлы программы не заменяются.\n"
          "4. Закройте программу и откройте снова: запустится новая версия, база обновится сама.\n"
          "5. Если новая версия не запустится, программа вернётся к предыдущей сама; вручную — кнопка «Вернуться к встроенной версии» в том же окне.\n"
          "Заменять файлы программы вручную больше не нужно (только если обновлению нужны новые библиотеки — тогда программа сообщит и потребуется пересборка).")


def parse_version(text):
    nums = re.findall(r'\d+', str(text or ''))[:3]
    return tuple(int(n) for n in nums) + (0,) * (3 - len(nums))


def is_newer(remote, local=__version__):
    return parse_version(remote) > parse_version(local)


def fetch(url, timeout=8):
    """-> dict(version, url, notes). Бросает исключение при недоступности адреса или неверном формате."""
    if not str(url).lower().startswith(('https://', 'http://')):
        raise ValueError('Адрес должен начинаться с https://')
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'PTO-updater'}), timeout=timeout) as response:
        raw = response.read(65536).decode('utf-8', 'replace').strip()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        data = {'version': (re.search(r'\d+(?:\.\d+){1,2}', raw) or [''])[0]}
    if not data.get('version'):
        raise ValueError('В ответе нет номера версии')
    return dict(version=str(data['version']), url=str(data.get('url') or ''), notes=str(data.get('notes') or ''))


def check(db, force=False, now=None):
    """Раз в 7 дней (или по требованию) запрашивает адрес. Возвращает (есть_новая, сведения|None, сообщение)."""
    url = db.get_setting('update_url', '').strip()
    if not url:
        return False, None, 'Адрес проверки обновлений не задан.'
    now = now or datetime.now()
    if not force:
        try:
            if (now - datetime.fromisoformat(db.get_setting('last_update_check', ''))).days < 7:
                return False, None, 'Проверка уже выполнялась на этой неделе.'
        except ValueError:
            pass
    info = fetch(url)
    db.set_setting('last_update_check', now.isoformat(timespec='seconds'))
    if is_newer(info['version']):
        return True, info, f'Доступна версия {info["version"]} (у вас {__version__}).'
    return False, info, f'Установлена актуальная версия {__version__}.'
