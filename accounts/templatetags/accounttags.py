from django import template

from ..models import has_active_disclaimer, has_expired_disclaimer

register = template.Library()


@register.simple_tag
def modify_redirect_field_value(ret_url):
    if ret_url and ret_url in ['/accounts/password/change/', '/accounts/password/set/']:
        return '/accounts/profile'
    return ret_url


@register.filter
def has_disclaimer(user):
    return has_active_disclaimer(user)


@register.filter
def has_expired_disclaimer(user):
    return has_expired_disclaimer(user)
