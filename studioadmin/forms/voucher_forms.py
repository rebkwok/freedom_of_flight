# -*- coding: utf-8 -*-
import pytz
from datetime import datetime

from django import forms
from django.core.exceptions import ValidationError

from crispy_forms.bootstrap import InlineCheckboxes, AppendedText, PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML

from booking.models import BlockConfig, BlockVoucher
from common.utils import start_of_day_in_utc, end_of_day_in_utc


def validate_discount(value):
    if value < 1 or value > 100:
        raise ValidationError('Discount must be between 1% and 100%')


def validate_greater_than_0(value):
    if value == 0:
        raise ValidationError('Must be greater than 0 (leave blank if no '
                              'maximum)')


def validate_code(code):
    if len(code.split()) > 1:
        raise ValidationError('Code must not contain spaces')


class BlockVoucherStudioadminForm(forms.ModelForm):

    class Meta:
        model = BlockVoucher
        fields = (
            'code', 'discount', 'discount_amount', 'start_date', 'expiry_date',
            'max_per_user',
            'max_vouchers',
            'block_configs',
            "activated",
            "is_gift_voucher",
            'name',
            'message',
            'purchaser_email'
        )
        widgets = {
            'start_date': forms.DateInput(format='%d-%b-%Y'),
            'expiry_date': forms.DateInput(format='%d-%b-%Y'),
            'block_configs': forms.SelectMultiple(attrs={"class": "form-control"}),
        }
        labels = {
            'discount': 'Discount (%)',
            'discount_amount': 'Discount amount (£)',
            'name': 'Name (optional, for gift vouchers)',
            'message': 'Message (optional, for gift vouchers)',
            'max_per_user': 'Maximum uses per user',
            'max_vouchers': 'Maximum total uses',
            'block_configs': 'Valid blocks'
        }
        help_texts = {
            'max_per_user': 'Optional: set a limit on the number of times '
                            'this voucher can be used by a single user (leave blank for unlimited)',
            'max_vouchers': 'Optional: set a limit on the number of times this '
                            'voucher can be used (across ALL users - leave blank for unlimited)',
            'start_date': 'Pick from calendar or enter in format e.g. 10 Jan 2016',
            'expiry_date': 'Optional: set an expiry date after which the '
                           'voucher will no longer be accepted',
            'block_configs': 'Choose block types that this voucher can be used for',
            'is_gift_voucher': 'For a standard, single use gift voucher, set max uses per user=1, max available vouchers=1, and discount=100%',
            'purchaser_email': 'Read only; purchaser email for gift voucher'
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = ['%d-%b-%Y']
        self.fields["expiry_date"].input_formats = ['%d-%b-%Y']
        self.fields['code'].validators = [validate_code]
        self.fields['discount'].validators = [validate_discount]
        self.fields['discount_amount'].validators = [validate_greater_than_0]
        self.fields['max_vouchers'].validators = [validate_greater_than_0]
        self.fields['block_configs'].queryset = BlockConfig.objects.filter(active=True)
        self.fields['purchaser_email'].disabled = True

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "Voucher details",
                "code",
                "block_configs",
                "activated",
                HTML("<p>Enter either a discount % or fixed discount amount"),
                Row(
                    Column(AppendedText("discount", "%")),
                    Column(PrependedText("discount_amount", "£")),
                ),
            ),
            Fieldset(
                "Voucher restrictions",
                Row(
                    Column(
                        AppendedText(
                            "start_date", "<i id='id_start_date_open' class='far fa-calendar'></i>", autocomplete="off",
                        ),
                    ),
                    Column(
                        AppendedText(
                            "expiry_date", "<i id='id_expiry_date_open' class='far fa-calendar'></i>", autocomplete="off",
                        )
                    )
                ),
            ),
            Row(
                Column(Field("max_vouchers", type="integer")),
                Column(Field("max_per_user", type="integer")),
            ),
            Fieldset(
                "Gift Voucher details",
                "is_gift_voucher",
                'name',
                Field("message", rows=10),
                'purchaser_email',
            ),
            Submit('submit', 'Save')
        )

    def get_uses(self):
        return self.instance.blocks.filter(paid=True).count()

    def clean(self):
        super().clean()
        discount = self.cleaned_data.get("discount")
        discount_amount = self.cleaned_data.get("discount_amount")
        if discount and discount_amount:
            self.add_error('__all__', 'Enter either a  discount % or discount amount (not both)')
        elif not (discount or discount_amount):
            self.add_error('discount', 'One of discount % or discount amount is required')
            self.add_error('discount_amount', 'One of discount % or discount amount is required')

        start_date = self.cleaned_data.get('start_date')
        expiry_date = self.cleaned_data.get('expiry_date')

        if expiry_date:
            expiry_date = end_of_day_in_utc(expiry_date)

        if start_date and expiry_date:
            if start_date > expiry_date:
                self.add_error('expiry_date', 'Expiry date must be after start date')

        max_uses = self.cleaned_data.get('max_vouchers')
        if self.instance.id and max_uses:
            times_used = self.get_uses()
            if times_used > max_uses:
                self.add_error(
                    'max_vouchers',
                    f'Voucher code has already been used {times_used} times in '
                    f'total; set max uses to {times_used} or greater'
                )
