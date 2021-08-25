# -*- coding: utf-8 -*-
import pytz
from datetime import datetime

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.shortcuts import reverse

from crispy_forms.bootstrap import InlineCheckboxes, AppendedText, PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML

from booking.models import ProductCategory, Product, ProductPurchase, ProductStock, ProductVariant
from common.utils import full_name
from .form_utils import Formset


class ProductCategoryCreateUpdateForm(forms.ModelForm):

    class Meta:
        model = ProductCategory
        fields = ('name',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            "name",
            Submit('submit', 'Save')
        )


class ProductVariantForm(forms.Form):
    size = forms.CharField(max_length=50, required=False)
    cost = forms.DecimalField(decimal_places=2, max_digits=10)
    quantity_in_stock = forms.IntegerField()


class ProductCreateUpdateForm(forms.ModelForm):

    class Meta:
        model = Product
        fields = ('name', 'category', 'active')

    def __init__(self, *args, **kwargs):
        category_id = kwargs.pop("category_id", None)
        super().__init__(*args, **kwargs)
        if category_id:
            self.fields["category"].initial = category_id
        self.helper = FormHelper()
        self.helper.layout = Layout(
            "name",
            "category",
            "active",
            Fieldset(
                "Purchase Options",
                HTML("<span class='helptext'>Note: size must be unique; duplicate sizes will be overwritten. "
                     "Leave blank if size is not applicable.</span>"),
                Formset("product_variant_formset"),
                HTML("<span class='helptext'>Save to add more options</span>"),
            ),
            Submit('submit', 'Save')
        )


class ProductVariantModelChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        stock = ProductStock.objects.get(product_variant=obj)
        size_value = f"{obj.size} - " if obj.size else ""
        return f"{size_value}£{obj.cost} - {stock.quantity} in stock"


class UserModelChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return full_name(obj)


class ProductPurchaseCreateUpdateForm(forms.ModelForm):

    class Meta:
        model = ProductPurchase
        fields = ('product', 'user', 'paid', 'date_paid', 'received', 'date_received')

    def __init__(self, *args, **kwargs):
        product = kwargs.pop("product")
        super().__init__(*args, **kwargs)
        self.fields["option"] = ProductVariantModelChoiceField(
            queryset=ProductVariant.objects.filter(product=product)
        )
        if self.instance.id:
            try:
                matching_variant = ProductVariant.objects.get(
                    product=product, size=self.instance.size, cost=self.instance.cost
                )
                self.fields["option"].initial = matching_variant.id
            except ProductVariant.DoesNotExist:
                matching_variant = None
                self.fields["option"].required = False

        self.fields["user"] = UserModelChoiceField(
            queryset=User.objects.all().order_by("first_name"), required=True, label="Purchaser"
        )
        self.fields["date_paid"] = forms.DateField(
            widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d %b %Y'),
            input_formats=['%d %b %Y'],
            required=False
        )
        self.fields["date_received"] = forms.DateField(
            widget=forms.DateInput(attrs={"autocomplete": "off"}, format='%d %b %Y'),
            input_formats=['%d %b %Y'],
            required=False
        )

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Hidden("product", product.id),
            "user",
            "option",
            HTML(f"<p>NOTE: Original Size/Cost option is no longer available</p>") if self.instance.id and matching_variant is None else HTML(
                ""),
            HTML(f"<p>Original Size: {self.instance.size}</p>") if self.instance.id and matching_variant is None else HTML(""),
            HTML(f"<p>Original Cost: £{self.instance.cost}</p>") if self.instance.id and matching_variant is None else HTML(""),
            Row(
                Column("paid", css_class="col-2"),
                Column(
                    AppendedText(
                        'date_paid',
                        '<i id="id_date_paid" class="far fa-clock"></i>'
                    ), css_class="col-6"
                )
            ),
            Row(
                Column("received", css_class="col-2"),
                Column(
                    AppendedText(
                        'date_received',
                        '<i id="id_date_paid" class="far fa-clock"></i>'
                    ), css_class="col-6"
                )
            ),
            Submit('submit', 'Save')
        )
