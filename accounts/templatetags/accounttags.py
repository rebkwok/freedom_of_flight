from django import template

from ..models import has_active_disclaimer, has_expired_disclaimer as has_expired_disclaimer_util

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
    return has_expired_disclaimer_util(user)


@register.filter
def latest_disclaimer(user):
    # return latest disclaimer, regardless of whether it's expired or not
    # (for emergency contact details)
    if user.online_disclaimer.exists():
        return user.online_disclaimer.latest("id")
