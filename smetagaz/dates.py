"""Формат дат программы — дд.мм.гггг. Модуль без Qt: используется и в таблицах, и в выгрузках Excel."""
import re

ISO = re.compile(r'^(\d{4})-(\d{2})-(\d{2})(?=$|[ T])')


def display_date(value):
    """'2026-03-05' (или '2026-03-05 14:30') -> '05.03.2026' (+ время); всё остальное возвращается без изменений."""
    text = str(value if value is not None else '')
    match = ISO.match(text)
    if not match:
        return text
    return f'{match.group(3)}.{match.group(2)}.{match.group(1)}' + text[10:]


def localize_workbook(wb):
    """Даты ГГГГ-ММ-ДД в ячейках книги openpyxl заменяются на дд.мм.гггг (текстом: Excel не должен переинтерпретировать формат)."""
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and ISO.match(cell.value):
                    cell.value = display_date(cell.value)
    return wb
