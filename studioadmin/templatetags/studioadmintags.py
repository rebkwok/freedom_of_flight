from django import template


register = template.Library()


def is_active(tab_index, tab, requested_tab=None):
    # make sure everything is a string when we compare
    if requested_tab is not None:
        return str(tab_index) == str(requested_tab)
    elif tab:
        return str(tab_index) == str(tab)
    return False


@register.simple_tag(takes_context=True)
def get_active_tab_class(context, tab_index, tab):
    requested_tab = context.get("active_tab")
    return 'active' if is_active(tab_index, tab, requested_tab) else ''


@register.simple_tag(takes_context=True)
def get_active_pane_class(context, tab_index, tab):
    requested_tab = context.get("active_tab")
    return 'show active' if is_active(tab_index, tab, requested_tab) else ''
