"""Состояние резервных копий для окна «ПТО Сервер»: когда была последняя копия и нет ли причин для тревоги. Без Qt."""
from datetime import datetime, timedelta

OK, WARN, BAD = 'ok', 'warn', 'bad'
LOCAL_OK_H, LOCAL_BAD_H = 2, 24


def _parse(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _ago(delta):
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return 'только что'
    if minutes < 60:
        return f'{minutes} мин назад'
    hours = minutes // 60
    if hours < 48:
        return f'{hours} ч назад'
    return f'{hours // 24} дн. назад'


def report(db, now=None):
    """-> список (уровень, текст): строки для показа. Уровень 'ok' — всё хорошо, 'warn' — внимание, 'bad' — копий давно нет или они не получаются."""
    from . import offsite_backup
    now = now or datetime.now()
    rows = []
    last = _parse(db.get_setting('last_db_backup', ''))
    status = db.get_setting('backup_status', '')
    if last is None:
        rows.append((BAD, 'Автоматическая копия ещё ни разу не делалась'))
    else:
        age = now - last
        level = OK if age <= timedelta(hours=LOCAL_OK_H) else WARN if age <= timedelta(hours=LOCAL_BAD_H) else BAD
        text = f'Последняя автоматическая копия: {last:%d.%m.%Y %H:%M} ({_ago(age)})'
        if level == BAD:
            text += ' — больше суток без копии!'
        rows.append((level, text))
    if 'ошибка' in status.lower():
        rows.append((BAD, 'Ошибка автоматической копии: ' + status))
    s = offsite_backup.settings(db)
    if not offsite_backup.configured(db):
        rows.append((WARN, 'Копия вне компьютера не настроена: при поломке диска или краже компьютера данные пропадут вместе с автоматическими копиями. '
                           'Настройте её (программа в режиме клиента на 127.0.0.1 под администратором → Настройки → «Копии вне компьютера»).'))
    else:
        off = _parse(db.get_setting('last_offsite_backup', ''))
        offsite_status = db.get_setting('offsite_status', '')
        if off is None:
            rows.append((WARN, 'Копия вне компьютера настроена, но ещё не делалась'))
        else:
            age = now - off
            level = OK if age <= timedelta(hours=s['interval_h'] * 2) else BAD
            text = f'Последняя копия вне компьютера: {off:%d.%m.%Y %H:%M} ({_ago(age)})'
            if level == BAD:
                text += ' — пора была раньше, проверьте диск или облачную папку'
            rows.append((level, text))
        if 'ошибк' in offsite_status.lower():
            rows.append((BAD, offsite_status))
        verify = db.get_setting('offsite_verify_status', '')
        if 'ОШИБКА' in verify:
            rows.append((BAD, verify))
    return rows


def worst(rows):
    return BAD if any(r[0] == BAD for r in rows) else WARN if any(r[0] == WARN for r in rows) else OK


COLORS = {OK: '#15803D', WARN: '#B45309', BAD: '#DC2626'}
MARKS = {OK: '✔', WARN: '⚠', BAD: '✖'}


def html(rows):
    return ''.join(f'<div style="color:{COLORS[level]}">{MARKS[level]} {text}</div>' for level, text in rows)
