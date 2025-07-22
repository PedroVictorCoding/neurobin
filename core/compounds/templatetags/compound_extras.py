from django import template
from django.utils.html import escape
import html

register = template.Library()

@register.filter
def smiles_safe(value):
    """
    Safely escape SMILES strings for use in HTML attributes
    while preserving chemical notation characters
    """
    if not value:
        return ""
    
    # Only escape quotes and ampersands to prevent XSS
    # but preserve chemical characters like =, <, >, [], (), etc.
    safe_value = value.replace('"', '&quot;').replace("'", '&#x27;').replace('&', '&amp;')
    return safe_value


@register.filter
def get_item(dictionary, key):
    """Get an item from a dictionary by key"""
    if dictionary and hasattr(dictionary, 'get'):
        return dictionary.get(key)
    return None
