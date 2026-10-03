"""
Формула стоимости работы в справочнике:
  ЗП = Трудозатраты (чел-час) × Часовая ставка
  ОХР и ОПР = % от ЗП (вводится)
  Плановая прибыль = % от ЗП (вводится)
  СоцСтрах = 34,6% от ЗП (фиксировано)
  Другие затраты = сумма за единицу (вводится)
  Налог на прибыль = 20% от (ЗП+ОХР/ОПР+Прибыль+СоцСтрах+Другие) (фиксировано)
  Итого = сумма выше + Налог
Любое поле можно оставить нулевым и ввести итоговую цену вручную напрямую в карточке.
"""
from decimal import Decimal
from .stock_domain import decimal

SOCIAL_PCT = Decimal('34.6')
PROFIT_TAX_PCT = Decimal('20')


def compute_work_price(labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs):
    wage = decimal(labor_hours or 0) * decimal(hourly_rate or 0)
    overhead = wage * decimal(overhead_pct or 0) / 100
    profit = wage * decimal(profit_pct or 0) / 100
    social = wage * SOCIAL_PCT / 100
    other = decimal(other_costs or 0)
    subtotal = wage + overhead + profit + social + other
    tax = subtotal * PROFIT_TAX_PCT / 100
    return dict(wage=wage, overhead=overhead, profit=profit, social=social, other=other, subtotal=subtotal, tax=tax, total=subtotal + tax)


def has_breakdown(labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs):
    """True when at least one formula input was filled in (vs. a plain manual price)."""
    return any(decimal(v or 0) != 0 for v in (labor_hours, hourly_rate, overhead_pct, profit_pct, other_costs))
