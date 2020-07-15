from django.contrib.auth.models import User


def full_name(user):
    return f"{user.first_name} {user.last_name}"
