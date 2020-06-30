from django import template

from ..utils import has_available_block as has_available_block_util

register = template.Library()

@register.filter
def has_available_block(user, event):
    return has_available_block_util(user, event)
