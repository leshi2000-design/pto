"""Разбор товарных накладных Республики Беларусь (ТН-2, ТТН-1, накладные из 1С и других программ): номер, дата, поставщик и получатель (УНП, адрес, счёт, банк),
таблица товаров с количеством, ценой, суммой и НДС, итоги. Источники: Excel (.xlsx), PDF с текстом, фотографии и сканы (OCR Tesseract). Без Qt.

Разбор — только предложение: пользователь проверяет и исправляет результат до сохранения. Каждая строка товаров проверяется арифметикой
(количество × цена = сумма, сумма + НДС = всего), расхождения помечаются, итоги сверяются с суммой по строкам.

Результат — словарь:
    kind, number, date (ГГГГ-ММ-ДД), currency, source ('excel' | 'text' | 'ocr'),
    supplier / buyer: {name, unp, address, account, bank, bic},
    items: [{name, unit, qty, price, sum, vat_rate, vat_sum, total, check}], totals: {sum, vat, total},
    warnings: [текст], text (распознанный текст для показа)."""
import os
import re
import shutil
from datetime import date

UNITS = {'шт', 'шт.', 'м', 'м.', 'п.м', 'пог.м', 'м2', 'м²', 'м3', 'м³', 'кг', 'кг.', 'г', 'т', 'л', 'л.', 'уп', 'уп.', 'упак', 'компл', 'компл.', 'к-т', 'ком', 'комп', 'пар', 'пара', 'рул', 'рул.',
         'бух', 'меш', 'меш.', 'лист', 'лис.', 'пач', 'пач.', 'бан', 'бан.', 'ведро', 'тн', 'услуга', 'усл', 'усл.', 'час', 'ч', 'ед', 'ед.', 'мп', 'см', 'мм', 'рулон', 'коробка', 'кор', 'кор.', 'набор', 'наб', 'наб.'}
VAT_RATES = {0, 9, 10, 18, 20, 25}
MONTHS = {'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6, 'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12}
TOTAL_WORDS = ('итого', 'всего по накладной', 'всего к оплате', 'всего:')
PARTY_LABELS = {
    'supplier': ('грузоотправитель', 'поставщик', 'продавец', 'отправитель', 'исполнитель'),
    'buyer': ('грузополучатель', 'покупатель', 'получатель', 'плательщик', 'заказчик'),
}
NUMBER = r'[-+]?\d{1,3}(?:[  ]\d{3})+(?:[.,]\d+)?|[-+]?\d+(?:[.,]\d+)?'


class OcrUnavailable(Exception):
    """Нет Tesseract или русского языка; сообщение пользователю объясняет, что установить."""


# --- числа и даты --------------------------------------------------------------------------------

def to_number(value):
    """'1 234,56' / '1234.56' / 12 / None -> float или None. Устойчиво к буквам O/О, принятым OCR за ноль."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace('\u00a0', ' ').replace('\u202f', ' ')
    if not text or text in ('-', '—', '–'):
        return None
    cleaned = re.sub(r'(?<=\d)[OoОо](?=[\d.,]|$)|^[OoОо](?=[\d.,])', '0', text)
    cleaned = cleaned.replace(' ', '')
    m = re.fullmatch(r'[-+]?\d+(?:[.,]\d+)?', cleaned)
    if not m:
        return None
    return float(cleaned.replace(',', '.'))


def norm_date(day, month, year):
    year = int(year)
    if year < 100:
        year += 2000
    try:
        return date(year, int(month), int(day)).isoformat()
    except ValueError:
        return ''


def find_dates(text):
    found = []
    for m in re.finditer(r'(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4}|\d{2})(?!\d)', text):
        d = norm_date(*m.groups())
        if d:
            found.append((m.start(), d))
    for m in re.finditer(r'(\d{1,2})\s+(' + '|'.join(MONTHS) + r')\s+(\d{4})', text, re.I):
        d = norm_date(m.group(1), MONTHS[m.group(2).lower()], m.group(3))
        if d:
            found.append((m.start(), d))
    return sorted(found)


# --- реквизиты -----------------------------------------------------------------------------------

def find_iban(text):
    m = re.search(r'\bBY\s?\d{2}\s?[A-Z0-9]{4}\s?\d{4}\s?[A-Z0-9]{4}\s?[A-Z0-9]{4}\s?[A-Z0-9]{4}\s?[A-Z0-9]{4}\b', text.replace('\u00a0', ' '), re.I)
    return re.sub(r'\s+', '', m.group(0)).upper() if m else ''


def find_bic(text):
    m = re.search(r'(?:BIC|БИК|SWIFT|код банка)\s*[:№]?\s*([A-Z]{4}BY[A-Z0-9]{2,5})', text, re.I)
    return m.group(1).upper() if m else ''


def find_unps(text):
    """[(позиция, УНП)]: девять цифр после «УНП» (допускаются буквы старого образца)."""
    return [(m.start(), m.group(1)) for m in re.finditer(r'(?:УНП|УНН)\s*[:№]?\s*(\d{9})(?!\d)', text, re.I)]


def _clean_name(chunk):
    chunk = re.sub(r'(?:УНП|УНН)\s*[:№]?\s*\d{9}', ' ', chunk, flags=re.I)
    chunk = re.split(r'\b(?:адрес|р/с|расч|счет|счёт|IBAN|тел|банк|БИК|BIC|e-mail|email)\b', chunk, maxsplit=1, flags=re.I)[0]
    chunk = re.sub(r'\([^)]*\)', ' ', chunk)                       # подписи под линией: (наименование, адрес…)
    return re.sub(r'\s+', ' ', chunk).strip(' ,;:.-–—')


def _party(chunk):
    party = dict(name='', unp='', address='', account='', bank='', bic='')
    unps = find_unps(chunk)
    party['unp'] = unps[0][1] if unps else ''
    party['account'] = find_iban(chunk)
    party['bic'] = find_bic(chunk)
    party['name'] = _clean_name(chunk.split('\n')[0] if '\n' in chunk.strip() and len(chunk.strip().split('\n')[0]) > 6 else chunk)
    m = re.search(r'адрес[^:\n]{0,20}[:\s]\s*([^\n]+?)(?=\s+(?:тел|р/с|расч|счет|счёт|IBAN|банк|УНП|БИК|BIC)\b|$)', chunk, re.I | re.M)
    if m:
        party['address'] = re.sub(r'\s+', ' ', m.group(1)).strip(' ,;')
    m = re.search(r'(?:(?:ОАО|ЗАО|РУП|ЧУП|ООО)\s*)?["«]([^"»\n]*банк[^"»\n]*)["»]', chunk, re.I)
    if m:
        party['bank'] = re.sub(r'\s+', ' ', m.group(1)).strip(' ,;')
    return party


def split_parties(text):
    """Разбивает «шапку» накладной на блоки по подписям (Грузоотправитель / Грузополучатель / Поставщик / Плательщик…). -> (поставщик, получатель)."""
    head = text
    cut = re.search(r'наименование\s+(?:товара|продукции|груза)|№\s*п/п', text, re.I)
    if cut:
        head = text[:cut.start()]
    marks = []
    for role, labels in PARTY_LABELS.items():
        for label in labels:
            for m in re.finditer(label + r'\s*(?:\([^)]*\))?\s*[:\-–—]?', head, re.I):
                marks.append((m.start(), m.end(), role))
    marks.sort()
    filtered = []
    for mk in marks:                                              # слова внутри одного блока (например, «Грузополучатель (покупатель)») не дублируем
        if not filtered or mk[0] >= filtered[-1][1]:
            filtered.append(mk)
    blocks = {}
    for i, (_start, end, role) in enumerate(filtered):
        stop = filtered[i + 1][0] if i + 1 < len(filtered) else len(head)
        chunk = head[end:stop]
        if role not in blocks and len(chunk.strip()) > 3:
            blocks[role] = _party(chunk)
    supplier = blocks.get('supplier') or dict(name='', unp='', address='', account='', bank='', bic='')
    buyer = blocks.get('buyer') or dict(name='', unp='', address='', account='', bank='', bic='')
    if not supplier['unp'] and not buyer['unp']:                  # подписей нет — берём первые УНП по порядку
        unps = find_unps(head)
        if unps:
            supplier['unp'] = unps[0][1]
        if len(unps) > 1:
            buyer['unp'] = unps[1][1]
    if not supplier['account']:
        supplier['account'] = find_iban(head)
    if not supplier['bic']:
        supplier['bic'] = find_bic(head)
    return supplier, buyer


def find_kind_and_number(text):
    head = text[:3000]
    kind = 'Накладная'
    if re.search(r'товарно[-\s]?транспортная|ттн', head, re.I):
        kind = 'ТТН'
    elif re.search(r'тн[-\s]?2|товарная\s+накладная', head, re.I):
        kind = 'ТН-2'
    elif re.search(r'накладная', head, re.I):
        kind = 'Накладная'
    number = ''
    m = re.search(r'(?:накладная|ттн[-\s]?1?|тн[-\s]?2)[^\n№N]{0,50}?(?:серия\s*([A-ZА-Я]{2})\s*)?[№N#]\s*([\w][\w\-/.]*)', head, re.I)
    if m:
        number = ((m.group(1) + ' ') if m.group(1) else '') + m.group(2).strip('.,;-')
    if not number:
        m = re.search(r'серия\s*([A-ZА-Я]{2})\s*[№N#]?\s*(\d{4,})', head, re.I)
        if m:
            number = f'{m.group(1).upper()} {m.group(2)}'
    if not number:
        m = re.search(r'[№N#]\s*([\w]*\d[\w\-/.]*)', head)
        number = m.group(1).strip('.,;') if m else ''
    dates = find_dates(head)
    day = ''
    m = re.search(r'(?:накладная|ттн|тн-?2)[^\n]{0,80}', head, re.I)
    if m:
        local = find_dates(m.group(0))
        if local:
            day = local[0][1]
    if not day and dates:
        day = dates[0][1]
    return kind, number, day


def find_currency(text):
    low = text.casefold()
    if 'byn' in low or 'бел. руб' in low or 'белорусск' in low or 'руб' in low:
        return 'BYN'
    return 'BYN'


# --- строки товаров -------------------------------------------------------------------------------

def _is_unit(token):
    t = token.strip().casefold().rstrip(',;')
    return t in UNITS or (re.fullmatch(r'[а-яa-z]{1,5}\.?', t) is not None and t.rstrip('.') in {u.rstrip('.') for u in UNITS})


def _close(a, b, tol=0.02):
    return abs(a - b) <= max(tol, abs(b) * 0.005)


def _check_row(it):
    """Арифметика строки. Возвращает текст замечания или ''."""
    q, p, s = it.get('qty'), it.get('price'), it.get('sum')
    notes = []
    if q is not None and p is not None and s is not None and not _close(q * p, s):
        # цена могла быть указана с НДС; допускаем и это
        notes.append(f'количество × цена = {q * p:,.2f}, а сумма {s:,.2f}'.replace(',', ' '))
    if s is not None and it.get('vat_sum') is not None and it.get('total') is not None and not _close(s + it['vat_sum'], it['total']):
        notes.append('сумма + НДС ≠ всего с НДС')
    return '; '.join(notes)


def assign_tail(it, tail):
    """Числа после суммы — ставка НДС, сумма НДС, всего с НДС. Раскладываем по арифметике, а не по порядку: OCR часто теряет или портит одно из чисел."""
    s = it['sum']
    if not tail or s is None:
        return
    for rate in sorted(VAT_RATES, reverse=True):
        expected_vat = round(s * rate / 100, 2)
        vat = next((v for v in tail if _close(v, expected_vat, 0.03) and v not in (rate,)), None) if rate else None
        if vat is not None:
            total = next((v for v in tail if _close(v, s + vat, 0.03)), None)
            it['vat_rate'], it['vat_sum'], it['total'] = rate, vat, total
            return
    if tail and tail[0] in VAT_RATES:                               # НДС 0 % или не удалось сопоставить: берём по порядку
        it['vat_rate'] = tail[0]
        tail = tail[1:]
    if tail:
        it['vat_sum'] = tail[0]
    if len(tail) > 1:
        it['total'] = tail[1]


def repair_item(it):
    """Одна цифра, испорченная OCR, ломает арифметику строки. Если два других соотношения сходятся, исправляем значение и помечаем строку (it['fixed'])."""
    q, p, s, vs, t, r = (it.get(k) for k in ('qty', 'price', 'sum', 'vat_sum', 'total', 'vat_rate'))
    notes = []
    if None not in (q, p, s) and not _close(q * p, s):
        other = None
        if t is not None and r is not None:
            other = t / (1 + r / 100)
        elif t is not None and vs is not None:
            other = t - vs
        if other is not None and _close(q * p, other, 0.05):
            it['sum'] = round(q * p, 2)
            notes.append(f'сумма исправлена с {s:,.2f} на {it["sum"]:,.2f}'.replace(',', ' '))
    s = it.get('sum')
    if s is not None and r is not None and vs is not None and t is not None:
        if not _close(s + vs, t):
            if _close(round(s * r / 100, 2), vs, 0.03):
                notes.append(f'«всего с НДС» исправлено с {t:,.2f} на {s + vs:,.2f}'.replace(',', ' '))
                it['total'] = round(s + vs, 2)
    if notes:
        it['fixed'] = '; '.join(notes)
    return it


def finish_item(it):
    repair_item(it)
    it['check'] = _check_row(it)
    if it.get('sum') is None and it.get('qty') is not None and it.get('price') is not None:
        it['sum'] = round(it['qty'] * it['price'], 2)
    if it.get('vat_sum') is None and it.get('sum') is not None and it.get('vat_rate') not in (None, 0):
        it['vat_sum'] = round(it['sum'] * it['vat_rate'] / 100, 2)
    if it.get('total') is None and it.get('sum') is not None:
        it['total'] = round(it['sum'] + (it.get('vat_sum') or 0), 2)
    return it


def parse_item_line(line):
    """Строка таблицы, распознанная как текст: «1 Труба ПЭ100 SDR11 32х3,0 м 120 3,45 414,00 20 82,80 496,80». -> словарь или None."""
    tokens = line.replace('\u00a0', ' ').split()
    if len(tokens) < 4:
        return None
    # отделяем числа справа
    nums, i = [], len(tokens)
    while i > 0:
        value = to_number(tokens[i - 1])
        if value is None and tokens[i - 1] in ('%', 'руб.', 'руб', 'коп.'):
            i -= 1
            continue
        if value is None:
            break
        nums.append(value)
        i -= 1
    nums.reverse()
    if len(nums) < 3:
        return None
    rest = tokens[:i]
    while rest and rest[-1] in ('%',):
        rest.pop()
    unit = ''
    if rest and _is_unit(rest[-1]):
        unit = rest.pop().rstrip(',;')
    elif len(rest) > 2 and _is_unit(rest[-2]) and len(rest[-1]) <= 4 and not re.search(r'\d', rest[-1]):
        unit = rest[-2].rstrip(',;')                                # после единицы остался мусор распознавания
        rest = rest[:-2]
    if rest and re.fullmatch(r'\d{1,3}[.)]?', rest[0]) and len(rest) > 1:
        rest = rest[1:]                                           # номер строки
    name = ' '.join(rest).strip(' ,;')
    if len(re.findall(r'[A-Za-zА-Яа-я]', name)) < 3:
        return None
    # ищем тройку количество × цена = сумма
    best = None
    for k in range(len(nums) - 2):
        q, p, s = nums[k], nums[k + 1], nums[k + 2]
        if q > 0 and p >= 0 and _close(q * p, s):
            best = k
            break
    it = dict(name=name, unit=unit.lower(), qty=None, price=None, sum=None, vat_rate=None, vat_sum=None, total=None)
    k = best if best is not None else 0
    it['qty'], it['price'], it['sum'] = nums[k], nums[k + 1], nums[k + 2]
    assign_tail(it, nums[k + 3:])
    return finish_item(it)


def _is_total_line(low):
    return any(low.lstrip(' |').startswith(w) for w in TOTAL_WORDS) or low.startswith('всего')


def parse_items_text(text):
    lines = [l.strip() for l in text.replace('\r', '').split('\n')]
    start = 0
    for i, line in enumerate(lines):                              # начало таблицы — строка заголовка
        low = line.casefold()
        if 'наименование' in low and any(w in low for w in ('количество', 'кол', 'цена', 'ед')):
            start = i + 1
            break
    items = []
    prefix = ''                                                  # начало названия, перенесённое на строку выше цифр
    for line in lines[start:]:
        low = line.casefold()
        if not line:
            continue
        if _is_total_line(low):
            break
        item = parse_item_line(line)
        if item:
            if prefix:
                item['name'] = (prefix + ' ' + item['name']).strip()
                prefix = ''
            items.append(item)
        elif re.match(r'^\d{1,3}[.)]?\s+\S', line) and not re.search(r'\d[.,]\d', line) and len(line) < 100 and not prefix:
            prefix = re.sub(r'^\d{1,3}[.)]?\s+', '', line).strip()        # «1 Фитинг компрессионный» — цифры будут на следующей строке
        elif items and not re.search(r'\d', line) and 2 < len(line) < 80 and not re.search(r'отпуск|принял|сдал|подпись|водитель|груз', low):
            items[-1]['name'] = (items[-1]['name'] + ' ' + line).strip()      # перенос длинного названия на следующую строку
    return items


def find_totals(text, items):
    totals = dict(sum=None, vat=None, total=None)
    m = None
    for m in re.finditer(r'(?:^|\n)\s*(?:итого|всего(?:\s+по\s+накладной)?)[^\n]*', text, re.I):
        pass                                                      # берём последнюю строку «Итого»
    if m:
        nums = [to_number(t) for t in m.group(0).split()]
        nums = [n for n in nums if n is not None]
        if len(nums) >= 3:
            totals['sum'], totals['vat'], totals['total'] = nums[-3], nums[-2], nums[-1]
        elif len(nums) == 2:
            totals['vat'], totals['total'] = nums[0], nums[1]
        elif len(nums) == 1:
            totals['total'] = nums[0]
    pat = rf'({NUMBER})'
    mv = re.search(r'(?:сумма\s+ндс|в\s+том\s+числе\s+ндс|ндс\s*[:=])[^\d\n]{0,30}' + pat, text, re.I)
    if mv and totals['vat'] is None:
        totals['vat'] = to_number(mv.group(1))
    mt = re.search(r'(?:всего\s+стоимость\s+с\s+ндс|всего\s+с\s+ндс|к\s+оплате|стоимость\s+с\s+ндс)[^\d\n]{0,30}' + pat, text, re.I)
    if mt and totals['total'] is None:
        totals['total'] = to_number(mt.group(1))
    return totals


# --- сборка результата ------------------------------------------------------------------------------

def build(text, items, source, extra_warnings=()):
    supplier, buyer = split_parties(text)
    kind, number, day = find_kind_and_number(text)
    totals = find_totals(text, items)
    warnings = list(extra_warnings)
    result = dict(kind=kind, number=number, date=day, currency=find_currency(text), source=source, supplier=supplier, buyer=buyer, items=items, totals=totals, warnings=warnings, text=text[:20000])
    validate(result)
    return result


def validate(result):
    """Сверка итогов и обязательных полей; дополняет result['warnings']."""
    warnings = [w for w in result['warnings'] if not w.startswith('⚠')]
    items, totals = result['items'], result['totals']
    if not items:
        warnings.append('⚠ Таблица товаров не распознана — добавьте строки вручную.')
    bad = [i + 1 for i, it in enumerate(items) if it.get('check')]
    if bad:
        warnings.append(f'⚠ Проверьте строки: {", ".join(map(str, bad[:15]))} — не сходится арифметика (подсвечены).')
    line_sum = round(sum(it.get('sum') or 0 for it in items), 2)
    line_total = round(sum(it.get('total') or it.get('sum') or 0 for it in items), 2)
    if items and totals.get('total') is not None and not (_close(line_total, totals['total'], 0.05) or _close(line_sum, totals['total'], 0.05)):
        warnings.append(f'⚠ Итог в документе {totals["total"]:,.2f}, а по строкам {line_total:,.2f} — возможно, пропущена или неверно распознана строка.'.replace(',', ' '))
    if not result['supplier'].get('unp'):
        warnings.append('⚠ УНП поставщика не найден.')
    if not result['number']:
        warnings.append('⚠ Номер накладной не найден.')
    if not result['date']:
        warnings.append('⚠ Дата накладной не найдена.')
    result['warnings'] = warnings
    if totals.get('total') is None and items:
        totals['sum'] = line_sum
        totals['total'] = line_total
        totals['vat'] = round(line_total - line_sum, 2)
    return result


def parse_text(text, source='text'):
    return build(text, parse_items_text(text), source)


# --- Excel ---------------------------------------------------------------------------------------

def _vat_incl(h):
    return 'с ндс' in h and 'без ндс' not in h


COLUMN_RULES = [          # (роль, подходит ли заголовок) — порядок важен: более конкретные роли раньше
    ('vat_sum', lambda h: 'ндс' in h and 'сумм' in h and not _vat_incl(h) and 'без ндс' not in h),
    ('vat_rate', lambda h: 'ндс' in h and ('ставк' in h or '%' in h) and 'сумм' not in h),
    ('total', lambda h: (_vat_incl(h) and ('стоим' in h or 'сумм' in h or 'всего' in h)) or h.startswith('всего')),
    ('price', lambda h: 'цена' in h and not _vat_incl(h)),
    ('sum', lambda h: ('стоим' in h or 'сумм' in h) and not _vat_incl(h) and ('ндс' not in h or 'без ндс' in h)),
    ('qty', lambda h: 'колич' in h or 'кол-во' in h or h.startswith('кол')),
    ('unit', lambda h: ('ед' in h and ('изм' in h or h.strip(' .') == 'ед')) or 'единица' in h),
    ('name', lambda h: 'наименование' in h or 'номенклатур' in h or h.startswith('товар')),
]


def _cell_text(v):
    if v is None:
        return ''
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def read_excel_rows(path, max_rows=600):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = max(wb.worksheets[:4], key=lambda w: w.max_row * w.max_column)       # лист с самым большим содержимым
    rows = [list(r) for r in ws.iter_rows(max_row=max_rows, values_only=True)]
    for merged in ws.merged_cells.ranges:                                    # значение объединённой ячейки видно во всех её клетках (общий заголовок «НДС» над «ставка» и «сумма»)
        value = ws.cell(merged.min_row, merged.min_col).value
        for r in range(merged.min_row, min(merged.max_row, max_rows) + 1):
            for c in range(merged.min_col, merged.max_col + 1):
                if r - 1 < len(rows) and c - 1 < len(rows[r - 1]) and rows[r - 1][c - 1] is None:
                    rows[r - 1][c - 1] = value
    wb.close()
    return rows


def find_header(rows):
    """Индекс строки заголовка таблицы и сопоставление колонок. Заголовок может занимать две строки (общая и подзаголовки)."""
    for i, row in enumerate(rows):
        cells = [_cell_text(c).casefold() for c in row]
        joined = ' '.join(cells)
        if 'наименование' not in joined and 'номенклатур' not in joined and 'товар' not in joined:
            continue
        if not any(k in joined for k in ('колич', 'кол-во')) or not any(k in joined for k in ('цена', 'сумм', 'стоим')):
            continue
        best = None
        for span in (1, 2, 3):                                    # объединяем заголовок из нескольких строк; берём вариант, где опознано больше колонок
            heads = []
            for c in range(len(row)):
                parts = [_cell_text(rows[j][c]).casefold() for j in range(i, min(i + span, len(rows))) if c < len(rows[j])]
                heads.append(' '.join(p for p in parts if p))
            mapping = {}
            for c, h in enumerate(heads):
                if not h:
                    continue
                for role, rule in COLUMN_RULES:
                    if role not in mapping and rule(h):
                        mapping[role] = c
                        break
            if {'name', 'qty'} <= set(mapping) and ({'price', 'sum'} & set(mapping)) and (best is None or len(mapping) > len(best[1])):
                best = (i + span - 1, mapping)
        if best:
            return best
    return None, {}


def parse_excel(path):
    rows = read_excel_rows(path)
    head_row, mapping = find_header(rows)
    head_text = '\n'.join(' '.join(_cell_text(c) for c in row if _cell_text(c)) for row in rows[:head_row if head_row is not None else 40])
    items, tail_lines = [], []
    warnings = []
    if head_row is None:
        warnings.append('⚠ Не найден заголовок таблицы товаров (Наименование, Количество, Цена…). Проверьте файл.')
        text = '\n'.join(' '.join(_cell_text(c) for c in row if _cell_text(c)) for row in rows)
        result = build(text, parse_items_text(text), 'excel', warnings)
        return result
    numbering = 0
    for row in rows[head_row + 1:]:
        cells = [_cell_text(c) for c in row]
        line = ' '.join(c for c in cells if c)
        low = line.casefold()
        if not line:
            continue
        if _is_total_line(low) or low.startswith('итого'):
            tail_lines.append(line)
            break
        name = cells[mapping['name']] if mapping['name'] < len(cells) else ''
        values = {role: to_number(row[col]) if col < len(row) else None for role, col in mapping.items() if role != 'name' and role != 'unit'}
        if not name or re.fullmatch(r'[\d\s.,]+', name):          # строка нумерации колонок «1 2 3 4…» и пустые строки
            continue
        if all(v is None for v in values.values()):
            if items and not any(re.search(r'\d', c) for c in cells if c != name):
                items[-1]['name'] += ' ' + name                   # продолжение названия
            continue
        unit = cells[mapping['unit']] if 'unit' in mapping and mapping['unit'] < len(cells) else ''
        items.append(finish_item(dict(name=re.sub(r'\s+', ' ', name), unit=unit, qty=values.get('qty'), price=values.get('price'), sum=values.get('sum'),
                                      vat_rate=values.get('vat_rate'), vat_sum=values.get('vat_sum'), total=values.get('total'))))
        numbering += 1
    # хвост (итого, подписи) нужен для итогов
    rest = rows[head_row + 1:]
    tail_text = '\n'.join(' '.join(_cell_text(c) for c in row if _cell_text(c)) for row in rest[-25:])
    text = head_text + '\n' + 'Наименование товара\n' + tail_text
    result = build(head_text + '\n' + tail_text, items, 'excel', warnings)
    result['totals'] = find_totals(tail_text, items)
    validate(result)
    result['text'] = head_text[:20000]
    return result


# --- OCR -----------------------------------------------------------------------------------------

def find_tesseract(configured=''):
    candidates = [configured, shutil.which('tesseract') or '',
                  r'C:\Program Files\Tesseract-OCR\tesseract.exe', r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                  os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Tesseract-OCR', 'tesseract.exe')]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return ''


def _popen_kwargs():
    import subprocess
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if os.name == 'nt':
        kwargs['creationflags'] = 0x08000000              # CREATE_NO_WINDOW: без мигающего чёрного окна
    return kwargs


def _tesseract(exe, args, timeout=180):
    """Запуск tesseract.exe напрямую, без дополнительных Python-модулей. -> (код возврата, stdout, stderr)."""
    import subprocess
    proc = subprocess.run([exe] + list(args), timeout=timeout, **_popen_kwargs())
    return proc.returncode, proc.stdout.decode('utf-8', errors='replace'), proc.stderr.decode('utf-8', errors='replace')


def ocr_available(configured=''):
    """(можно ли читать фото, путь к tesseract или объяснение, что установить)."""
    exe = find_tesseract(configured)
    if not exe:
        return False, ('Не найден Tesseract OCR. Установите его (Windows: сборка UB Mannheim, при установке отметьте язык Russian) '
                       'или укажите путь к tesseract.exe в «Настройки → Распознавание накладных по фотографии».')
    try:
        code, out, err = _tesseract(exe, ['--list-langs'], 30)
    except Exception as e:
        return False, f'Tesseract не запускается: {e}'
    langs = {line.strip() for line in (out + '\n' + err).splitlines()}
    if code != 0 and not langs:
        return False, 'Tesseract не запускается: ' + err.strip()[:200]
    if 'rus' not in langs:
        return False, 'В Tesseract нет русского языка (файл rus.traineddata). Переустановите Tesseract и отметьте язык Russian.'
    return True, exe


def prepare_image(path, scale_to=2400):
    """Фото с телефона -> картинка, удобная для распознавания: поворот по EXIF, серый, увеличение, контраст, резкость."""
    from PIL import Image, ImageFilter, ImageOps
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert('L')
    width = img.size[0]
    if width < scale_to:
        factor = scale_to / width
        img = img.resize((int(img.size[0] * factor), int(img.size[1] * factor)), Image.LANCZOS)
    elif width > scale_to * 1.6:
        factor = scale_to * 1.6 / width
        img = img.resize((int(img.size[0] * factor), int(img.size[1] * factor)), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    return img.filter(ImageFilter.SHARPEN)


def _save_temp(img):
    import tempfile
    handle, path = tempfile.mkstemp(suffix='.png', prefix='pto_ocr_')
    os.close(handle)
    img.save(path)
    return path


def _auto_rotate(img, exe):
    """Если фото снято боком или вверх ногами — поворачиваем по определению ориентации Tesseract (режим --psm 0)."""
    path = _save_temp(img)
    try:
        code, out, err = _tesseract(exe, [path, 'stdout', '--psm', '0'], 60)
        m = re.search(r'Rotate:\s*(\d+)', out)
        conf = re.search(r'Orientation confidence:\s*([\d.]+)', out)
        angle = int(m.group(1)) if m else 0
        if angle and conf and float(conf.group(1)) > 2:
            return img.rotate(-angle, expand=True, fillcolor=255)
    except Exception:
        pass
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return img


def ocr_text(img, exe, psm=6):
    path = _save_temp(img)
    try:
        code, out, err = _tesseract(exe, [path, 'stdout', '-l', 'rus+eng', '--oem', '1', '--psm', str(psm), '-c', 'preserve_interword_spaces=1'])
        if code != 0 and not out.strip():
            raise OcrUnavailable('Tesseract не смог прочитать изображение: ' + err.strip()[:300])
        return out
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _score(result):
    items = result['items']
    good = sum(1 for it in items if not it.get('check'))
    return good * 3 + len(items) + (2 if result['supplier'].get('unp') else 0) + (2 if result['number'] else 0) + (2 if result['date'] else 0)


def parse_image(path, configured='', pages=None):
    """Фото или скан -> результат. Пробуются несколько режимов разбивки страницы, выбирается лучший по числу сошедшихся строк."""
    ok, info = ocr_available(configured)
    if not ok:
        raise OcrUnavailable(info)
    exe = info
    img = prepare_image(path)
    img = _auto_rotate(img, exe)
    best = None
    for psm in (6, 4, 11):
        text = ocr_text(img, exe, psm)
        result = parse_text(text, 'ocr')
        if best is None or _score(result) > _score(best):
            best = result
        if result['items'] and not any(it.get('check') for it in result['items']) and result['supplier'].get('unp'):
            break                                                 # хороший результат — дальше не пробуем
    best['warnings'].insert(0, 'Распознано по фотографии: внимательно проверьте названия, количества и суммы — OCR мог ошибиться.')
    return best


def render_pdf_pages(path, limit=6):
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise OcrUnavailable('Для чтения PDF-сканов нужен модуль pypdfium2 (pip install pypdfium2). Либо сфотографируйте или сохраните страницу как картинку (JPG/PNG).')
    pdf = pdfium.PdfDocument(path)
    pages = []
    for index in range(min(len(pdf), limit)):
        pages.append(pdf[index].render(scale=3).to_pil())
    return pages


def parse_pdf(path, configured=''):
    from pypdf import PdfReader
    text = '\n'.join((p.extract_text() or '') for p in PdfReader(path).pages[:10])
    if len(text.strip()) > 80:
        result = parse_text(text, 'text')
        if result['items']:
            return result
    ok, info = ocr_available(configured)
    if not ok:
        raise OcrUnavailable('В PDF нет текста (это скан). ' + info)
    exe = info
    texts = []
    for page in render_pdf_pages(path):
        gray = page.convert('L')
        texts.append(ocr_text(_auto_rotate(gray, exe), exe, 6))
    result = parse_text('\n'.join(texts), 'ocr')
    result['warnings'].insert(0, 'Распознано по скану: внимательно проверьте названия, количества и суммы.')
    return result


def parse_file(path, configured=''):
    """Главная функция: по расширению выбирает способ. Бросает OcrUnavailable, если для фото/скана нет Tesseract."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xlsm'):
        return parse_excel(path)
    if ext == '.pdf':
        return parse_pdf(path, configured)
    if ext in ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp', '.heic'):
        return parse_image(path, configured)
    if ext in ('.txt', '.csv'):
        with open(path, encoding='utf-8', errors='replace') as f:
            return parse_text(f.read())
    if ext == '.xls':
        raise ValueError('Старый формат .xls не поддерживается: откройте файл в Excel и сохраните как .xlsx.')
    raise ValueError('Этот тип файла не поддерживается для накладных (нужны .xlsx, .pdf или фото).')


def looks_like_invoice(path):
    """Быстрая проверка по имени и типу файла: стоит ли сразу открывать окно накладной."""
    ext = os.path.splitext(path)[1].lower()
    name = os.path.basename(path).casefold()
    if ext in ('.xlsx', '.xlsm'):
        return True
    return any(k in name for k in ('накладн', 'ттн', 'тн-2', 'tn2', 'invoice', 'nakl'))
