"""Сверка перед формированием документов: пустые поля карточки, несвежая смета и теги шаблона, которые подставятся пустыми.

Возвращает список замечаний {'level': 'error'|'warn', 'text': ...}; решение о формировании принимает пользователь.
"""
import re
import zipfile

from . import gsv_project_domain as gd
from . import gsvm_domain as md
from . import gsvm_docs as dd

TAG_RE = gd.TAG_RE
# теги, которые вправе быть пустыми
OPTIONAL = {'ПРИМЕЧАНИЕ', 'ТУ', 'СТАТУС_РАБОТЫ', 'СТАТУС_КЛИЕНТА', 'ДАТА_ОПЛАТЫ', 'СУММА_ОПЛАТЫ', 'ПРИМЕЧАНИЕ_ОПЛАТЫ', 'ПРОЕКТИРОВЩИК', 'НОМЕР_ПРОЕКТА', 'ДАТА_ПРОЕКТА',
            'ПРИМЕЧАНИЕ_ОПЛАТЫ', 'ОПЛАЧЕНО', 'ДАТА_АКТА_П', 'ДАТА_АКТА_С', 'ДАТА_АКТА'}


def template_tags(path):
    """Имена тегов {…}, встречающиеся в шаблоне Word / Excel (в тексте, таблицах, колонтитулах, ячейках)."""
    found = set()
    try:
        if str(path).lower().endswith('.xlsx'):
            import openpyxl
            wb = openpyxl.load_workbook(path)
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str):
                            found.update(TAG_RE.findall(cell.value))
        else:
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    if name.startswith('word/') and name.endswith('.xml'):
                        xml = z.read(name).decode('utf-8', 'ignore')
                        text = re.sub(r'<[^>]+>', '', xml)           # теги Word могут быть разбиты на несколько фрагментов
                        found.update(TAG_RE.findall(text))
    except Exception:
        return set()
    return found


def _issue(level, text):
    return {'level': level, 'text': text}


def _template_issues(path, tags, normalize, ignore=()):
    issues = []
    empty, unknown = [], []
    for raw in sorted(template_tags(path)):
        key = normalize(raw)
        if key not in tags:
            unknown.append('{' + raw + '}')
        elif tags[key] == '' and key not in OPTIONAL and key not in ignore:
            empty.append('{' + raw + '}')
    if empty:
        issues.append(_issue('warn', 'В шаблоне есть теги без данных (подставится пустое место): ' + ', '.join(empty[:12]) + (' …' if len(empty) > 12 else '')))
    if unknown:
        issues.append(_issue('warn', 'В шаблоне есть неизвестные теги (останутся в тексте как есть): ' + ', '.join(unknown[:12])))
    return issues


def _need(tags, key, label, issues, level='error'):
    if not str(tags.get(key, '')).strip():
        issues.append(_issue(level, f'Не заполнено: {label}'))


def check_project(db, pid, kind):
    """Проекты ГСВ: поля, нужные документу, и пустые теги шаблона."""
    tags = gd.project_tags(db, pid)
    issues = []
    _need(tags, 'КЛИЕНТ', 'ФИО клиента', issues)
    _need(tags, 'ОБЪЕКТ', 'наименование объекта', issues)
    _need(tags, 'ДАТА_ЗАКЛЮЧЕНИЯ_С', 'дата заключения договора', issues)
    if kind in ('contract', 'act'):
        if tags.get('СТОИМОСТЬ') in ('', '0,00'):
            issues.append(_issue('error', 'Не указана стоимость'))
    if kind == 'contract':
        _need(tags, 'ПАСПОРТ', 'паспорт (серия, номер)', issues)
        _need(tags, 'КЕМ_ВЫДАН', 'кем выдан паспорт', issues)
        _need(tags, 'ДАТА_ВЫДАЧИ', 'дата выдачи паспорта', issues)
        _need(tags, 'АДРЕС_КЛИЕНТА', 'адрес клиента', issues)
        _need(tags, 'СРОК_ИСПОЛНЕНИЯ_С', 'срок исполнения', issues)
        _need(tags, 'АДРЕС_ОБЪЕКТА', 'адрес объекта', issues, 'warn')
    if kind == 'act':
        _need(tags, 'ДАТА_АКТА_С', 'дата акта', issues)
        _need(tags, 'НОМЕР_ДОГОВОРА', 'номер договора', issues)
    if kind == 'card':
        _need(tags, 'ТЕЛЕФОН', 'телефон клиента', issues, 'warn')
    return issues + _template_issues(gd.template_path(db, kind), tags, gd.tag_key)


def check_montage(db, cid, kind):
    """Монтаж ГСВ: поля, актуальность сметы, оборудование / трубы для исполнительных документов и пустые теги шаблона."""
    tags = dd.tag_map(db, cid)
    issues = []
    _need(tags, 'КЛИЕНТ', 'ФИО клиента', issues)
    _need(tags, 'ОБЪЕКТ', 'наименование объекта', issues)
    _need(tags, 'АДРЕС', 'адрес объекта', issues)
    _need(tags, 'ДАТА_ДОГОВОРА_С', 'дата заключения договора', issues)
    if kind in ('contract', 'act', 'card'):
        _need(tags, 'ПАСПОРТ', 'паспорт (серия, номер)', issues)
        _need(tags, 'КЕМ_ВЫДАН', 'кем выдан паспорт', issues, 'warn')
        _need(tags, 'ДАТА_ВЫДАЧИ', 'дата выдачи паспорта', issues, 'warn')
        _need(tags, 'АДРЕС_КЛИЕНТА', 'адрес клиента', issues)
        if tags.get('СТОИМОСТЬ') in ('', '0,00'):
            issues.append(_issue('error', 'Не указана стоимость работ'))
    if kind in ('contract', 'act'):
        _need(tags, 'ОКОНЧАНИЕ_РАБОТ', 'окончание работ', issues)
    if kind in ('act', 'accept') or kind in dd.ID_KINDS:
        _need(tags, 'ДАТА_АКТА_С', 'дата акта', issues)
    state = md.estimate_state(db, cid)
    if state == 'stale':
        issues.append(_issue('error', 'Смета была изменена — обновите данные («Получить стоимость из сметы»), иначе стоимость в документе может быть устаревшей'))
    elif state == 'unsynced':
        issues.append(_issue('warn', 'Данные из привязанной сметы ещё не получены — стоимость введена вручную'))
    if kind in dd.ID_KINDS:
        if not md.pipelines(db, cid):
            issues.append(_issue('warn', 'Не указаны трубопроводы'))
        elif not md.joints_total(db, cid):
            issues.append(_issue('warn', 'Не указано количество стыков'))
        if not md.equipment(db, cid) and kind in ('equipment_revision', 'device_revision', 'warranty'):
            issues.append(_issue('warn', 'Не указано оборудование'))
    ignore = {name for (name,) in db.fetchall("SELECT name FROM gsvm_tags WHERE coalesce(auto_key,'') LIKE 'e:%' OR coalesce(auto_key,'') LIKE 'p:%'")}
    issues += _template_issues(dd.template_path(db, kind), tags, dd.norm_tag, ignore)
    # одинаковые замечания не повторяются
    seen, unique = set(), []
    for i in issues:
        if i['text'] not in seen:
            seen.add(i['text'])
            unique.append(i)
    return unique
