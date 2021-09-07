from django.core.validators import RegexValidator

phone_number_validator = RegexValidator(r'^[0-9\s]+$', 'Enter a valid phone number (no dashes or brackets).')
