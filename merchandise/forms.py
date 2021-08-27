from django import forms

from crispy_forms.bootstrap import InlineCheckboxes, AppendedText, PrependedText
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Button, Layout, Submit, Row, Column, Field, Fieldset, Hidden, HTML

from .models import ProductVariant


class ProductVariantModelChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        size_value = f"{obj.size} - " if obj.size else ""
        return f"{size_value}£{obj.cost}{' (out of stock)' if obj.out_of_stock else ''}"



class ProductPurchaseForm(forms.Form):

    def __init__(self, *args, **kwargs):
        product = kwargs.pop("product")
        super(ProductPurchaseForm, self).__init__(*args, **kwargs)
        self.fields["option"] = ProductVariantModelChoiceField(
            queryset=ProductVariant.objects.filter(product=product),
            label="Choose an option"
        )

        self.helper = FormHelper()
        self.helper.layout = Layout(
            "option",
            Submit('submit', 'Add to cart')
        )

    def clean_option(self):
        value = self.cleaned_data["option"]
        if value.out_of_stock:
            self.add_error("option", "out of stock")
        else:
            return value