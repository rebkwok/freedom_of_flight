from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator


def validate_confirm(value):
    if not value:
        raise ValidationError(
            'You must confirm that you accept the waiver terms'
        )


phone_number_validator = RegexValidator(r'^[0-9\s]+$', 'Enter a valid phone number (no dashes or brackets).')
