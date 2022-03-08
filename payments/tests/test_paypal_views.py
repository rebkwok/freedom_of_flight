from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase, override_settings

from model_bakery import baker

from paypal.standard.pdt.models import PayPalPDT

from booking.models import Block, Subscription, GiftVoucher
from common.test_utils import TestUsersMixin
from merchandise.tests.utils import make_purchase
from ..models import Invoice


class PaypalCancelReturnViewTests(TestCase):

    def test_get(self):
        resp = self.client.get(reverse("payments:paypal_cancel"))
        assert resp.status_code == 200


class PaypalTestViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.url = reverse("payments:paypal_test")

    def test_get_anonymous_user(self):
        assert Invoice.objects.exists() is False
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        form = resp.context["form"]
        assert form.initial["item_name_1"] == "paypal_test"
        assert Invoice.objects.exists() is True
        assert Invoice.objects.first().username == "paypal_test"

    def test_get_logged_in_user(self):
        assert Invoice.objects.exists() is False
        self.client.login(username=self.student_user.username, password="test")
        resp = self.client.get(self.url)
        assert resp.status_code == 200
        form = resp.context["form"]
        assert form.initial["item_name_1"] == "paypal_test"
        assert Invoice.objects.exists() is True
        assert Invoice.objects.first().username == self.student_user.username


@override_settings(SEND_ALL_STUDIO_EMAILS=True)
class PaypalReturnViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        self.url = reverse("payments:paypal_return")

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_no_matching_invoice(self, process_pdt):
        pdt_obj = baker.make(PayPalPDT, invoice="unknown")
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Error Processing Payment" in resp.content.decode("utf-8")

        # No invoice matching PDT value, send failed emails
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == "WARNING: Something went wrong with a payment!"
        assert "No invoice on PDT on return from paypal" in mail.outbox[0].body

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_and_block(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        block = baker.make_recipe(
            'booking.dropin_block', paid=False, invoice=invoice, user=self.student_user
        )
        pdt_obj = baker.make(
            PayPalPDT, invoice="foo", custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", mc_gross=10,
            mc_currency="GBP", receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        block.refresh_from_db()
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()

        assert block.paid is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_and_subscription(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        subscription = baker.make(Subscription, paid=False, invoice=invoice, user=self.student_user)
        pdt_obj = baker.make(
            PayPalPDT, invoice="foo", custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", mc_gross=10,
            mc_currency="GBP", receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        subscription.refresh_from_db()
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()

        assert subscription.paid is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_and_gift_voucher(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        gift_voucher = baker.make(
            GiftVoucher, gift_voucher_config__discount_amount=10, paid=False, invoice=invoice
        )
        gift_voucher.voucher.purchaser_email = self.student_user.email
        gift_voucher.voucher.save()
        pdt_obj = baker.make(
            PayPalPDT, invoice="foo", custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", mc_gross=10,
            mc_currency="GBP", receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        gift_voucher.refresh_from_db()
        gift_voucher.voucher.refresh_from_db()
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()

        assert gift_voucher.paid is True
        assert gift_voucher.voucher.activated is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

        assert len(mail.outbox) == 3
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject
        assert mail.outbox[2].to == [self.student_user.email]
        assert "Gift Voucher" in mail.outbox[2].subject

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_and_gift_voucher_anon_user(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10,
            business_email="testreceiver@test.com",
            username=""
        )
        gift_voucher = baker.make(
            GiftVoucher, gift_voucher_config__discount_amount=10, paid=False,
            invoice=invoice
        )
        gift_voucher.voucher.purchaser_email = "anon@test.com"
        gift_voucher.voucher.save()
        pdt_obj = baker.make(
            PayPalPDT, invoice="foo", custom=f"{invoice.id}_{invoice.signature()}",
            txn_id="bar", mc_gross=10,
            mc_currency="GBP", receiver_email="testreceiver@test.com",
            payer_email="paypal-buyer@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        gift_voucher.refresh_from_db()
        gift_voucher.voucher.refresh_from_db()
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()

        assert gift_voucher.paid is True
        assert gift_voucher.voucher.activated is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

        # invoice username added from pdt
        assert invoice.username == "paypal-buyer@test.com"
        assert len(mail.outbox) == 3
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        # payment email goes to invoice email
        assert mail.outbox[1].to == ["paypal-buyer@test.com"]
        assert "Your payment has been processed" in mail.outbox[1].subject
        # gift voucher goes to purchaser emailon voucher
        assert mail.outbox[2].to == ["anon@test.com"]
        assert "Gift Voucher" in mail.outbox[2].subject

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_and_merch(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        product_purchase = make_purchase('M', 10, user=self.student_user, invoice=invoice, paid=False)
        pdt_obj = baker.make(
            PayPalPDT, invoice="foo", custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", mc_gross=10,
            mc_currency="GBP", receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        product_purchase.refresh_from_db()
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()

        assert product_purchase.paid is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_block_subscription_gift_voucher_merch(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        block = baker.make_recipe(
            'booking.dropin_block', paid=False, invoice=invoice, user=self.student_user
        )
        subscription = baker.make(Subscription, paid=False, invoice=invoice, user=self.student_user)
        gift_voucher = baker.make(
            GiftVoucher, gift_voucher_config__discount_amount=10, paid=False, invoice=invoice
        )
        gift_voucher.voucher.purchaser_email = self.student_user.email
        gift_voucher.voucher.save()
        product_purchase = make_purchase('M', 10, user=self.student_user, invoice=invoice, paid=False)

        pdt_obj = baker.make(
            PayPalPDT, invoice="foo", custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", mc_gross=10,
            mc_currency="GBP", receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()
        for item in [block, subscription, gift_voucher, product_purchase]:
            item.refresh_from_db()
            assert item.paid is True
        assert gift_voucher.voucher.activated is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

        assert len(mail.outbox) == 3
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject
        assert mail.outbox[2].to == [self.student_user.email]
        assert "Gift Voucher" in mail.outbox[2].subject

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_no_invoice_on_pdt(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        block = baker.make_recipe(
            'booking.dropin_block', paid=False, invoice=invoice, user=self.student_user,
        )
        pdt_obj = baker.make(
            PayPalPDT, invoice="", custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", mc_gross=10, mc_currency="GBP",
            receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        block.refresh_from_db()
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()

        assert block.paid is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_no_invoice_from_pdt_or_custom(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        baker.make_recipe(
            'booking.dropin_block', paid=False, invoice=invoice, user=self.student_user,
        )
        pdt_obj = baker.make(
            PayPalPDT, invoice="foo",
            custom=f"unk_{invoice.signature()}", txn_id="bar", mc_gross=10,
            mc_currency="GBP",
            receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Error Processing Payment" in resp.content.decode("utf-8")

        # No invoice matching PDT value, send failed emails
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == "WARNING: Something went wrong with a payment!"
        assert "No invoice on PDT on return from paypal" in mail.outbox[0].body

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_no_invoice_from_pdt_single_custom(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        baker.make_recipe(
            'booking.dropin_block', paid=False, invoice=invoice, user=self.student_user,
       )
        pdt_obj = baker.make(
            PayPalPDT, invoice="foo",
            custom="unk", txn_id="bar", mc_gross=10,
            mc_currency="GBP",
            receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Error Processing Payment" in resp.content.decode("utf-8")

        # No invoice matching PDT value, send failed emails
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == "WARNING: Something went wrong with a payment!"
        assert "No invoice on PDT on return from paypal" in mail.outbox[0].body

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_multiple_blocks(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.manager_user.username
        )
        block1 = baker.make_recipe(
            'booking.dropin_block', paid=False, invoice=invoice, user=self.manager_user,
        )
        block2 = baker.make_recipe(
            'booking.dropin_block', paid=False, invoice=invoice, user=self.child_user,
        )
        pdt_obj = baker.make(
            PayPalPDT, custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", mc_gross=10, mc_currency="GBP",
            receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        block1.refresh_from_db()
        block2.refresh_from_db()
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()

        assert block1.paid is True
        assert block2.paid is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_invalid_paypal_info(self, process_pdt):
        tests = [
            (
                {"amount": 10, "business_email": "testreceiver@test.com"},
                {"mc_gross": 10, "mc_currency": "GBP", "receiver_email": "testreceiver@test.com"},
                True
            ),
            (
                {"amount": 20, "business_email": "testreceiver@test.com"},
                {"mc_gross": 10, "mc_currency": "GBP", "receiver_email": "testreceiver@test.com"},
                False
            ),
            (
                {"amount": 20, "business_email": "testreceiver@test.com"},
                {"mc_gross": 20, "mc_currency": "USD", "receiver_email": "testreceiver@test.com"},
                False
            ),
            (
                {"amount": 20, "business_email": "testreceiver1@test.com"},
                {"mc_gross": 20, "mc_currency": "GBP", "receiver_email": "testreceiver@test.com"},
                False
            ),

        ]

        for (invoice_values, pdt_values, valid) in tests:
            invoice = baker.make(Invoice, invoice_id="foo", username=self.student_user.username, **invoice_values)
            baker.make_recipe(
                'booking.dropin_block', paid=False, invoice=invoice, user=self.student_user
            )
            pdt_obj = baker.make(PayPalPDT, custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", **pdt_values)
            process_pdt.return_value = (pdt_obj, not valid)

            resp = self.client.get(self.url)
            if valid:
                assert "Payment Processed" in resp.content.decode("utf-8")
            else:
                assert "Error Processing Payment" in resp.content.decode("utf-8")

    @patch("payments.views.process_pdt")
    def test_return_with_invalid_email_signature(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        block = baker.make_recipe(
            'booking.dropin_block', paid=False, invoice=invoice, user=self.student_user
        )
        pdt_obj = baker.make(
            PayPalPDT, custom=f"{invoice.id}_foo", txn_id="bar", mc_gross=10, mc_currency="GBP",
            receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Error Processing Payment" in resp.content.decode("utf-8")
        block.refresh_from_db()
        assert block.paid is False

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_with_matching_invoice_block_already_processed(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username, transaction_id="bar"
        )
        baker.make_recipe(
            'booking.dropin_block', invoice=invoice, user=self.student_user, paid=True
        )
        pdt_obj = baker.make(
            PayPalPDT, custom=f"{invoice.id}_{invoice.signature()}", txn_id="bar", mc_gross=10, mc_currency="GBP",
            receiver_email="testreceiver@test.com"
        )
        process_pdt.return_value = (pdt_obj, False)

        resp = self.client.get(self.url)
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        # already processed, no emails sent
        assert len(mail.outbox) == 0
