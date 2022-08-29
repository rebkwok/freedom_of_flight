# -*- coding: utf-8 -*-
from django import forms
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.shortcuts import reverse

from crispy_forms.bootstrap import InlineCheckboxes, AppendedText, PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML

from booking.models import BlockConfig, BlockVoucher, GiftVoucherConfig, TotalVoucher
from common.utils import end_of_day_in_utc


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
            'item_count',
            'max_per_user',
            'max_vouchers',
            'block_configs',
            "activated",
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
            'name': 'Recipient Name',
            'message': 'Message',
            'item_count': "Require multiple item purchase",
            'max_per_user': 'Maximum uses per user',
            'max_vouchers': 'Maximum total uses',
            'block_configs': ''
        }
        help_texts = {
            'max_per_user': 'Optional: set a limit on the number of times '
                            'this voucher can be used by a single user (leave blank for unlimited)',
            'max_vouchers': 'Optional: set a limit on the number of times this '
                            'voucher can be used (across ALL users - leave blank for unlimited)',
            'start_date': 'Pick from calendar or enter in format e.g. 10 Jan 2016',
            'expiry_date': 'Optional: set an expiry date after which the '
                           'voucher will no longer be accepted',
            'block_configs': '',
            'purchaser_email': 'Purchaser email for gift voucher',
            'activated': 'Tick to make voucher active and usable'
        }

    def __init__(self, *args, **kwargs):
        is_gift_voucher = kwargs.pop("is_gift_voucher", False)
        super().__init__(*args, **kwargs)
        self.fields["start_date"].input_formats = ['%d-%b-%Y']
        self.fields["expiry_date"].input_formats = ['%d-%b-%Y']
        self.fields['code'].validators = [validate_code]
        self.fields['discount'].validators = [validate_discount]
        self.fields['discount_amount'].validators = [validate_greater_than_0]
        self.fields['max_vouchers'].validators = [validate_greater_than_0]
        self.fields['block_configs'].queryset = BlockConfig.objects.filter(active=True)
        self.fields['block_configs'].required = False
        self.fields['total_voucher'] = forms.BooleanField(
            required=False, label="Applied to total",
            help_text="Discount applied to total checkout value, irrespective of items/block purchases"
        )
        self.child_instance = None
        used = False
        if self.instance.id:
            if TotalVoucher.objects.filter(id=self.instance.id).exists():
                self.child_instance = TotalVoucher.objects.get(id=self.instance.id)
            else:
                self.child_instance = BlockVoucher.objects.get(id=self.instance.id)
            self.fields['total_voucher'].initial = isinstance(self.child_instance, TotalVoucher)
            if isinstance(self.child_instance, BlockVoucher):
                self.fields['block_configs'].initial = self.child_instance.block_configs.values_list("id", flat=True)
                self.fields['item_count'].initial = self.child_instance.item_count
            if self.child_instance.gift_voucher.exists():
                is_gift_voucher = True
            if self.child_instance.uses() > 0:
                used = True
                for field in ["item_count", "discount", "discount_amount", "total_voucher"]:
                    self.fields[field].disabled = True
                if isinstance(self.child_instance, TotalVoucher):
                    self.fields['block_configs'].disabled = True
        self.fields['purchaser_email'].disabled = True

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                "Voucher details",
                "code",
                "activated",
                HTML(
                    "<p>Enter either a discount % or fixed discount amount"
                    "<br/><small class='text-muted'>(If the voucher requires purchase of multiple items, the discount will "
                    "be applied to EACH item)</small></p>"
                ),
                HTML(
                    "<p><strong>Note: voucher discounts and item number cannot be updated as the voucher has already been used</strong></p>"
                ) if used else HTML(""),
                Row(
                    Column(AppendedText("discount", "%")),
                    Column(PrependedText("discount_amount", "£")),
                    Column("item_count"),
                ),
            ),
            Fieldset(
                "Valid Items",
                HTML("<p>Select valid block types OR tick to create a voucher applied to checkout total</>"),
                HTML(
                    "<p><strong>Note: voucher type cannot be updated as the voucher has already been used</strong></p>"
                ) if used else HTML(""),
                Row(
                    Column("block_configs"),
                    Column("total_voucher"),
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
                'name',
                Field("message", rows=10),
                'purchaser_email',
            ) if is_gift_voucher else Fieldset(
                '',
                Hidden('name', self.instance.name if self.instance.id else ''),
                Hidden('name', self.instance.message if self.instance.id else ''),
                Hidden('name', self.instance.purchaser_email if self.instance.id else '')
            ),
            Submit('submit', 'Save')
        )

    def clean(self):
        super().clean()

        total_voucher = self.cleaned_data.get("total_voucher")
        if self.child_instance:
            if self.child_instance.uses() > 0:
                # Is the voucher type being changed?
                if (
                        (isinstance(self.child_instance,
                                    BlockVoucher) and total_voucher) or
                        (isinstance(self.child_instance,
                                    TotalVoucher) and not total_voucher)
                ):
                    self.add_error('__all__', "Voucher has already been used, can't change voucher type")
                    return
                # Did block configs get added to a TotalVoucher?
                if isinstance(self.child_instance, TotalVoucher) and self.cleaned_data.get("block_configs"):
                    self.add_error('__all__', "Can't add block types to a total voucher")
                    return

        block_configs = self.cleaned_data.get("block_configs")
        # Don't allow change from total to block type voucher if it's already been used
        discount = self.cleaned_data.get("discount")
        discount_amount = self.cleaned_data.get("discount_amount")
        if discount and discount_amount:
            self.add_error('__all__', 'Enter either a discount % or discount amount (not both)')
        elif not (discount or discount_amount):
            self.add_error('discount', 'One of discount % or discount amount is required')
            self.add_error('discount_amount', 'One of discount % or discount amount is required')

        if block_configs and total_voucher:
            self.add_error('__all__', 'Either add blocks for voucher or select total voucher')
        elif not (block_configs or total_voucher):
            self.add_error('block_configs', 'One of block types or total voucher is required')
            self.add_error('total_voucher', 'One of block types or total voucher required')

        start_date = self.cleaned_data.get('start_date')
        expiry_date = self.cleaned_data.get('expiry_date')

        if expiry_date:
            expiry_date = end_of_day_in_utc(expiry_date)

        if start_date and expiry_date:
            if start_date > expiry_date:
                self.add_error('expiry_date', 'Expiry date must be after start date')

        max_uses = self.cleaned_data.get('max_vouchers')
        if self.child_instance and max_uses:
            times_used = self.child_instance.uses()
            if times_used > max_uses:
                self.add_error(
                    'max_vouchers',
                    f'Voucher code has already been used {int(times_used)} times in '
                    f'total; set max uses to {int(times_used)} or greater'
                )

    def full_clean(self):
        super().full_clean()
        if self.errors.get("__all__"):
            errorlist = [*self.errors["__all__"]]
            for error in self.errors["__all__"]:
                # remove the default credit discount %/discount amount message, we should have added a nicer one already
                if error.startswith("Only one of") and len(self.errors["__all__"]) >= 2:
                    errorlist.remove(error)
            if errorlist != self.errors["__all__"]:
                self.errors["__all__"] = errorlist

    def save(self, commit=True):
        """
        Save this form's self.instance object if commit=True. Otherwise, add
        a save_m2m() method to the form which can be called after the instance
        is saved manually at a later time. Return the model instance.
        """
        if self.errors:
            raise ValueError(
                "The %s could not be %s because the data didn't validate." % (
                    self.instance._meta.object_name,
                    'created' if self.instance._state.adding else 'changed',
                )
            )
        models = {
            "total": TotalVoucher,
            "block": BlockVoucher
        }
        opts = self._meta
        fields = list(opts.fields)
        if self.cleaned_data["total_voucher"]:
            new_type = "total"
        else:
            new_type = "block"

        if new_type == "total":
            fields.remove("block_configs")

        if self.child_instance:
            if isinstance(self.child_instance, TotalVoucher):
                old_type = "total"
            else:
                old_type = "block"

            if new_type != old_type:
                self.instance = models[new_type]()
                self.child_instance.delete()
            else:
                self.instance = self.child_instance
        else:
            self.instance = models[new_type]()

        try:
            self.instance = forms.models.construct_instance(self, self.instance, opts.fields, opts.exclude)
        except ValidationError as e:
            self._update_errors(e)

        return super().save(commit=commit)


class BlockConfigModelChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj}{' (inactive)' if not obj.active else ''}"


class GiftVoucherConfigForm(forms.ModelForm):
    class Meta:
        model = GiftVoucherConfig
        fields = ("block_config", "discount_amount", "duration", "active")
        labels = {
            "block_config": "Credit block",
            "discount_amount": "Voucher value",
            "active": "Available for purchase on site"
        }
        help_texts = {
            "duration": "Number of months until voucher expires (from completion of payment); defaults to 6 months",
            "active": "Uncheck to remove this option from the gift voucher purchase options available to users"
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False
        self.fields["block_config"] = BlockConfigModelChoiceField(
            queryset=BlockConfig.objects.order_by("-active"), required=False
        )

        self.helper = FormHelper()
        back_url = reverse('studioadmin:gift_voucher_configs')
        self.helper.layout = Layout(
            HTML("<p>A gift voucher can be valid for either a single credit block <strong>OR</strong> a "
                 "fixed value (valid as a discount on a users total shopping basket value)</p>"),
            Row(
                Column("block_config"),
                Column(PrependedText("discount_amount", "£")),
            ),
            "duration",
            "active",
            Submit('submit', f'Save', css_class="btn btn-success"),
            HTML(f'<a class="btn btn-outline-dark" href="{back_url}">Back</a>')
        )
