from django import template

register = template.Library()

@register.filter
def percentage(value, total):
    """Calculate percentage of value out of total"""
    if not total or total == 0:
        return 0
    try:
        return round((float(value) / float(total)) * 100)
    except (ValueError, TypeError):
        return 0

@register.filter 
def multiply(value, multiplier):
    """Multiply two numbers"""
    try:
        return float(value) * float(multiplier)
    except (ValueError, TypeError):
        return 0

@register.filter
def divide(value, divisor):
    """Divide two numbers"""
    if not divisor or divisor == 0:
        return 0
    try:
        return float(value) / float(divisor)
    except (ValueError, TypeError):
        return 0
