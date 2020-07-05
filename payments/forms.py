
from django.utils.html import format_html

from paypal.standard.forms import PayPalPaymentsForm


class PayPalPaymentsFormWithId(PayPalPaymentsForm):

    def render(self):
        return format_html("""<form id="go_to_paypal_form" action="{0}" method="post">
    {1}
    <input id="submit_paypal" type="image" src="#" name="submit" alt="Buy it Now" style="display:none"/>
    <span class="btn btn-sm btn-primary mb-1"><i class="fa fa-spinner fa-spin"></i> Redirecting to PayPal</span>
</form>""", self.get_endpoint(), self.as_p())
