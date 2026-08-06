from django import template

from core.date_fmt import format_display_date

register = template.Library()


@register.filter(name="date_letters")
def date_letters(value):
    """Format a date as ``10 jan 2026``."""
    return format_display_date(value)
