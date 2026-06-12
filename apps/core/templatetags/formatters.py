import re
from decimal import Decimal

from django import template

register = template.Library()


def _br_number(value, decimals=2):
    """Formata número no padrão brasileiro: 1.234.567,89"""
    try:
        value = Decimal(str(value))
    except Exception:
        return '—'
    formatted = f'{value:,.{decimals}f}'          # 1,234,567.89
    return formatted.replace(',', 'X').replace('.', ',').replace('X', '.')


@register.filter
def brl_moeda(value):
    """1.234.567,89  (sem prefixo R$)"""
    if value is None:
        return '—'
    return _br_number(value, 2)


@register.filter
def brl_area(value, decimals=4):
    """1.234,5678 m²  (padrão 4 casas; aceita argumento: valor|brl_area:2)"""
    if value is None:
        return '—'
    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        decimals = 4
    return _br_number(value, decimals)


def _digits(value):
    return re.sub(r'\D', '', str(value or ''))


@register.filter
def format_cnpj(value):
    d = _digits(value)
    if len(d) != 14:
        return value or '—'
    return f'{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}'


@register.filter
def format_cpf(value):
    d = _digits(value)
    if len(d) != 11:
        return value or '—'
    return f'{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}'


@register.filter
def format_phone(value):
    d = _digits(value)
    if len(d) == 11:
        return f'({d[:2]}) {d[2:7]}-{d[7:]}'
    if len(d) == 10:
        return f'({d[:2]}) {d[2:6]}-{d[6:]}'
    return value or '—'


@register.filter
def format_cep(value):
    d = _digits(value)
    if len(d) != 8:
        return value or '—'
    return f'{d[:5]}-{d[5:]}'
