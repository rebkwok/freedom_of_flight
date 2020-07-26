from django import template
from django.utils.html import format_html, mark_safe

from ..models import has_active_disclaimer, has_expired_disclaimer as has_expired_disclaimer_util


register = template.Library()


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


@register.filter
def full_name(user):
    return f"{user.first_name} {user.last_name}"


@register.filter
def format_health_questionnaire(questionnaire_responses):
    responses = []
    for question, response in questionnaire_responses.items():
        if isinstance(response, list):
            response = ", ".join(response)
        responses.append(f"<strong>{question}</strong><br/>{response}")
    return format_html(mark_safe("<br/>".join(responses)))
