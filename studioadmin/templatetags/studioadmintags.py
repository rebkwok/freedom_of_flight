from django import template


register = template.Library()


def is_active(tab_index, tab):
    if tab:
        if str(tab_index) == tab:
            return True
    return False


@register.filter
def get_active_class(tab_index, tab):
    return 'active' if is_active(tab_index, tab) else ''


@register.filter
def get_active_in_class(tab_index, tab):
    return 'show active' if is_active(tab_index, tab) else ''
