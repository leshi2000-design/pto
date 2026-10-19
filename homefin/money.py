"""Деньги хранятся целым числом копеек, чтобы не копить ошибки float."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def to_cents(value) -> int:
    """'12,50' / 12.5 / Decimal('12.5') -> 1250."""
    if isinstance(value, int):
        return value * 100
    text = str(value).strip().replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        d = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Некорректная сумма: {value!r}") from exc
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt(cents: int, currency: str = "") -> str:
    sign = "-" if cents < 0 else ""
    c = abs(int(cents))
    s = f"{c // 100:,}".replace(",", " ") + f",{c % 100:02d}"
    return f"{sign}{s} {currency}".rstrip()


def dec(value) -> Decimal:
    """Число из текста с запятой или точкой."""
    try:
        return Decimal(str(value).strip().replace(",", ".").replace(" ", ""))
    except InvalidOperation as exc:
        raise ValueError(f"Некорректное число: {value!r}") from exc
