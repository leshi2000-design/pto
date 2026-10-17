"""Номера разделов договоров: в номере «07-02/26» число «02» — номер раздела (вида договора), «07» — порядковый номер в году, «26» — год.
Каждый вид договора имеет свой раздел; номер раздела вводится вручную в «Настройки → Номера разделов договоров». Новые договоры получают новый номер раздела,
уже созданные номера не меняются (прежние номера раздела запоминаются, чтобы такие договоры по-прежнему узнавались при обмене номерами и выборе следующего номера). Без Qt."""
import re

KINDS = {          # ключ -> (название, номер раздела по умолчанию, описание)
    'contracts': ('Договор на монтаж ГСВ', '02', 'раздел «Монтаж ГСВ»'),
    'gsv_projects': ('Договор на проект ГСВ', '03', 'раздел «Проекты ГСВ»'),
    'le': ('Прочие договоры юрлиц', '04', 'раздел «Справочник юрлиц» (договоры без вида)'),
    'smr': ('Договор на СМР (юр. лица)', '05', 'раздел «СМР (юрлица)»'),
    'to': ('Договор на ТО (юр. лица)', '06', 'раздел «ТО (юрлица)»'),
    'ip': ('Договор на СМР (физ. лица)', '07', 'раздел «СМР (ИП)»'),
}
CODE_RE = re.compile(r'^[0-9A-Za-zА-Яа-я]{1,4}$')


def _default(key):
    return KINDS[key][1]


def code(db, key):
    """Текущий номер раздела для вида договора."""
    value = str(db.get_setting(f'section_code_{key}', '') or '').strip()
    return value if CODE_RE.match(value) else _default(key)


def history(db, key):
    return [c for c in str(db.get_setting(f'section_code_old_{key}', '') or '').split(',') if c and CODE_RE.match(c)]


def all_codes(db, key):
    """Текущий номер раздела и все прежние (в таком порядке)."""
    now = code(db, key)
    return [now] + [c for c in history(db, key) if c != now]


def regex(db, key, tail=r'/(\d{2})'):
    """Регулярное выражение номера «NN-<раздел>/YY» с любым из номеров раздела вида договора; группы: порядковый номер, год."""
    alternatives = '|'.join(re.escape(c) for c in all_codes(db, key))
    return re.compile(rf'^\s*(\d+)-(?:{alternatives}){tail}\s*$')


def like_clauses(db, key):
    """(SQL-условие, параметры) для выбора номеров этого вида: contract_number LIKE '%-02/%' OR …"""
    codes = all_codes(db, key)
    return '(' + ' OR '.join("contract_number LIKE ?" for _ in codes) + ')', tuple(f'%-{c}/%' for c in codes)


def format_number(db, key, seq, year):
    return f'{seq:02}-{code(db, key)}/{year:02}'


def used(db, key):
    """Сколько договоров уже создано с текущим номером раздела (для подсказки в настройках)."""
    table = {'contracts': 'contracts', 'gsv_projects': 'gsv_projects', 'le': 'le_contracts', 'smr': 'smr_contracts', 'to': 'to_contracts', 'ip': 'ip_contracts'}[key]
    try:
        clause, params = like_clauses(db, key)
        return db.fetchone(f'SELECT count(*) FROM {table} WHERE {clause}', params)[0]
    except Exception:
        return 0


def set_code(db, key, value):
    """Задаёт номер раздела вручную. Номера разделов разных видов договоров не должны совпадать (иначе по номеру нельзя понять вид договора)."""
    if key not in KINDS:
        raise ValueError('Неизвестный вид договора')
    value = str(value or '').strip()
    if not CODE_RE.match(value):
        raise ValueError('Номер раздела — от 1 до 4 знаков: цифры или буквы, без пробелов, дефиса и косой черты')
    for other, (title, _d, _x) in KINDS.items():
        if other != key and value in all_codes(db, other):
            raise ValueError(f'Номер раздела {value} уже используется для вида «{title}» (в том числе в прежних номерах). Выберите другой.')
    old = code(db, key)
    if value == old:
        return
    hist = [c for c in history(db, key) if c != value]
    if old not in hist:
        hist.append(old)
    db.set_setting(f'section_code_old_{key}', ','.join(hist))
    db.set_setting(f'section_code_{key}', value)


def save_all(db, values):
    """values: {ключ: номер раздела}. Проверяет всё сразу (в том числе обмен номерами между видами) и сохраняет одной операцией."""
    cleaned = {}
    for key in KINDS:
        v = str(values.get(key, code(db, key)) or '').strip()
        if not CODE_RE.match(v):
            raise ValueError(f'«{KINDS[key][0]}»: номер раздела — от 1 до 4 знаков (цифры или буквы)')
        cleaned[key] = v
    seen = {}
    for key, v in cleaned.items():
        if v in seen:
            raise ValueError(f'Номер раздела {v} указан дважды: «{KINDS[seen[v]][0]}» и «{KINDS[key][0]}»')
        seen[v] = key
    for key, v in cleaned.items():                                # новый номер не должен совпасть с прежними номерами чужого вида
        for other in KINDS:
            if other != key and v in history(db, other) and cleaned[other] != v and v != code(db, other):
                raise ValueError(f'Номер раздела {v} раньше использовался для вида «{KINDS[other][0]}», по нему уже созданы договоры. Выберите другой.')
    with db.transaction():
        for key, v in cleaned.items():
            old = code(db, key)
            if v != old:
                hist = [c for c in history(db, key) if c != v]
                if old not in hist:
                    hist.append(old)
                db.set_setting(f'section_code_old_{key}', ','.join(hist))
                db.set_setting(f'section_code_{key}', v)
