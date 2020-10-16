from unittest.mock import patch, Mock
import json

from django.conf import settings
from django.contrib.sites.models import Site
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase, override_settings

import stripe
from model_bakery import baker

from booking.models import Block, Subscription
from common.test_utils import TestUsersMixin
from ..models import Invoice, Seller, StripePaymentIntent


def get_mock_payment_intent(webhook_event_type=None, **params):
    defaults = {
        "id": "mock-intent-id",
        "amount": 1000,
        "description": "",
        "status": "succeeded",
        "metadata": {},
        "currency": "gbp",
        "client_secret": "secret"
    }
    options = {**defaults, **params}
    if webhook_event_type == "payment_intent.payment_failed":
        options["last_payment_error"] = {'error': 'an error'}
    return Mock(**options)


def get_mock_webhook_event(**params):
    webhook_event_type = params.pop("webhook_event_type", "payment_intent.succeeded")
    mock_event = Mock(
        data=Mock(object=get_mock_payment_intent(webhook_event_type, **params)), type=webhook_event_type
    )
    return mock_event


@override_settings(SEND_ALL_STUDIO_EMAILS=True)
class StripePaymentCompleteViewTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        baker.make(Seller, site=Site.objects.get_current())
        self.url = reverse("payments:stripe_payment_complete")

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_no_matching_invoice(self, mock_payment_intent):
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent()
        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})
        assert resp.status_code == 200
        assert "Error Processing Payment" in resp.content.decode("utf-8")

        # No invoice matching PI value, send failed emails
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == "WARNING: Something went wrong with a payment!"
        assert "No invoice could be retrieved from succeeded payment intent mock-intent-id" in mail.outbox[0].body

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_matching_invoice_and_block(self, mock_payment_intent):
        assert StripePaymentIntent.objects.exists() is False
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username, stripe_payment_intent_id="mock-intent-id"
        )
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": invoice.signature(),
            **invoice.items_metadata(),
        }
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent(metadata=metadata)

        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        block.refresh_from_db()
        invoice.refresh_from_db()

        assert block.paid is True
        assert invoice.transaction_id is None
        payment_intent_obj = StripePaymentIntent.objects.latest("id")
        assert payment_intent_obj.invoice == invoice

        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_matching_invoice_and_subscription(self, mock_payment_intent):
        assert StripePaymentIntent.objects.exists() is False
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username, stripe_payment_intent_id="mock-intent-id"
        )
        subscription = baker.make(Subscription, paid=False, invoice=invoice, user=self.student_user)
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": invoice.signature(),
            **invoice.items_metadata(),
        }
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent(metadata=metadata)
        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        subscription.refresh_from_db()
        invoice.refresh_from_db()

        assert subscription.paid is True
        assert invoice.transaction_id is None
        assert invoice.paid is True
        payment_intent_obj = StripePaymentIntent.objects.latest("id")
        assert payment_intent_obj.invoice == invoice

        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_matching_invoice_block_and_subscription(self, mock_payment_intent):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username, stripe_payment_intent_id="mock-intent-id"
        )
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
        subscription = baker.make(Subscription, paid=False, invoice=invoice, user=self.student_user)
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": invoice.signature(),
            **invoice.items_metadata(),
        }
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent(metadata=metadata)
        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})

        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        subscription.refresh_from_db()
        block.refresh_from_db()
        invoice.refresh_from_db()

        assert subscription.paid is True
        assert block.paid is True
        assert invoice.paid is True
        assert invoice.transaction_id is None
        payment_intent_obj = StripePaymentIntent.objects.latest("id")
        assert payment_intent_obj.invoice == invoice
        assert len(mail.outbox) == 2

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_invalid_invoice(self, mock_payment_intent):
        invoice = baker.make(
            Invoice, invoice_id="", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username, stripe_payment_intent_id="mock-intent-id"
        )
        baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
        metadata = {
            "invoice_id": "unk",
            "invoice_signature": invoice.signature(),
            **invoice.items_metadata(),
        }
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent(metadata=metadata)
        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})
        assert "Error Processing Payment" in resp.content.decode("utf-8")
        assert invoice.paid is False
        # send failed emails
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == "WARNING: Something went wrong with a payment!"
        assert "No invoice could be retrieved from succeeded payment intent mock-intent-id" in mail.outbox[0].body

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_valid_pdt_with_matching_invoice_multiple_blocks(self, mock_payment_intent):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.manager_user.username, stripe_payment_intent_id="mock-intent-id"
        )
        block1 = baker.make(Block, paid=False, invoice=invoice, user=self.manager_user)
        block2 = baker.make(Block, paid=False, invoice=invoice, user=self.child_user)

        metadata = {
            "invoice_id": "foo",
            "invoice_signature": invoice.signature(),
            **invoice.items_metadata(),
        }
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent(metadata=metadata)
        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})
        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        block1.refresh_from_db()
        block2.refresh_from_db()
        invoice.refresh_from_db()

        assert block1.paid is True
        assert block2.paid is True
        assert invoice.paid is True
        assert invoice.transaction_id is None

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_matching_invoice_invalid_amount(self, mock_payment_intent):
        invoice = baker.make(
            Invoice, invoice_id="foo", username=self.student_user.username, amount=50,
            stripe_payment_intent_id="mock-intent-id"
        )
        baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": invoice.signature(),
            **invoice.items_metadata(),
        }
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent(metadata=metadata)
        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})
        assert invoice.paid is False
        assert "Error Processing Payment" in resp.content.decode("utf-8")

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_matching_invoice_invalid_signature(self, mock_payment_intent):
        invoice = baker.make(
            Invoice, invoice_id="foo", username=self.student_user.username, amount=50,
            stripe_payment_intent_id="mock-intent-id"
        )
        baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": "foo",
            **invoice.items_metadata(),
        }
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent(metadata=metadata)
        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})
        assert invoice.paid is False
        assert "Error Processing Payment" in resp.content.decode("utf-8")

    @patch("payments.views.stripe.PaymentIntent")
    def test_return_with_matching_invoice_block_already_processed(self, mock_payment_intent):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username, stripe_payment_intent_id="mock-intent-id",
            paid=True
        )
        baker.make(Block, invoice=invoice, user=self.student_user, paid=True)
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": "foo",
            **invoice.items_metadata(),
        }
        mock_payment_intent.retrieve.return_value = get_mock_payment_intent(metadata=metadata)
        resp = self.client.post(self.url, data={"payload": json.dumps({"id": "mock-intent-id"})})

        assert resp.status_code == 200
        assert "Payment Processed" in resp.content.decode("utf-8")
        # already processed, no emails sent
        assert len(mail.outbox) == 0


@override_settings(SEND_ALL_STUDIO_EMAILS=True)
class StripeWebhookTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()
        baker.make(Seller, site=Site.objects.get_current())
        self.url = reverse("payments:stripe_webhook")
        self.invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username, stripe_payment_intent_id="mock-intent-id"
        )
        self.block = baker.make(Block, paid=False, invoice=self.invoice, user=self.student_user)

    @patch("payments.views.stripe.Webhook")
    def test_webhook_with_matching_invoice_and_block(self, mock_webhook):
        assert StripePaymentIntent.objects.exists() is False
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": self.invoice.signature(),
            **self.invoice.items_metadata(),
        }
        mock_webhook.construct_event.return_value = get_mock_webhook_event(metadata=metadata)

        resp = self.client.post(self.url, data={}, HTTP_STRIPE_SIGNATURE="foo")
        assert resp.status_code == 200
        self.block.refresh_from_db()
        self.invoice.refresh_from_db()

        assert self.block.paid is True
        assert self.invoice.paid is True
        assert self.invoice.transaction_id is None
        payment_intent_obj = StripePaymentIntent.objects.latest("id")
        assert payment_intent_obj.invoice == self.invoice

        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch("payments.views.stripe.Webhook")
    def test_webhook_already_processed(self, mock_webhook):
        self.block.paid = True
        self.block.save()
        self.invoice.paid = True
        self.invoice.save()
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": self.invoice.signature(),
            **self.invoice.items_metadata(),
        }
        mock_webhook.construct_event.return_value = get_mock_webhook_event(metadata=metadata)
        resp = self.client.post(self.url, data={}, HTTP_STRIPE_SIGNATURE="foo")

        assert resp.status_code == 200
        # already processed, no emails sent
        assert len(mail.outbox) == 0

    @patch("payments.views.stripe.Webhook")
    def test_webhook_exceptions(self, mock_webhook):
        mock_webhook.construct_event.side_effect = stripe.error.SignatureVerificationError("", "foo")
        resp = self.client.post(self.url, data={}, HTTP_STRIPE_SIGNATURE="foo")
        # stripe verification error returns 400 so stripe will try again
        assert resp.status_code == 400

        mock_webhook.construct_event.side_effect = ValueError
        resp = self.client.post(self.url, data={}, HTTP_STRIPE_SIGNATURE="foo")
        # value error means payload is invalid; returns 400 so stripe will try again
        assert resp.status_code == 400

    @patch("payments.views.stripe.Webhook")
    def test_webhook_exception_retrieving_invoice(self, mock_webhook):
        # invalid invoice signature
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": "foo",
            **self.invoice.items_metadata(),
        }
        mock_webhook.construct_event.return_value = get_mock_webhook_event(metadata=metadata)
        resp = self.client.post(self.url, data={}, HTTP_STRIPE_SIGNATURE="foo")
        assert resp.status_code == 200

        # invoice and block is still unpaid
        assert self.block.paid is False
        assert self.invoice.paid is False

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [settings.SUPPORT_EMAIL]
        assert "WARNING: Something went wrong with a payment!" in mail.outbox[0].subject
        assert "Error: Could not verify invoice signature: payment intent mock-intent-id; invoice id foo" \
               in mail.outbox[0].body

    @patch("payments.views.stripe.Webhook")
    def test_webhook_refunded(self, mock_webhook):
        self.block.paid = True
        self.block.save()
        self.invoice.paid = True
        self.invoice.save()
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": self.invoice.signature(),
            **self.invoice.items_metadata(),
        }
        mock_webhook.construct_event.return_value = get_mock_webhook_event(
            webhook_event_type="payment_intent.refunded", metadata=metadata
        )
        resp = self.client.post(self.url, data={}, HTTP_STRIPE_SIGNATURE="foo")
        assert resp.status_code == 200
        self.block.refresh_from_db()
        self.invoice.refresh_from_db()
        # invoice and block is still paid, we only notify studio by email
        assert self.block.paid is True
        assert self.invoice.paid is True

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [settings.SUPPORT_EMAIL]
        assert "WARNING: Payment refund processed" in mail.outbox[0].subject

    @patch("payments.views.stripe.Webhook")
    def test_webhook_payment_failed(self, mock_webhook):
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": self.invoice.signature(),
            **self.invoice.items_metadata(),
        }
        mock_webhook.construct_event.return_value = get_mock_webhook_event(
            webhook_event_type="payment_intent.payment_failed", metadata=metadata
        )
        resp = self.client.post(self.url, data={}, HTTP_STRIPE_SIGNATURE="foo")
        assert resp.status_code == 200
        self.block.refresh_from_db()
        self.invoice.refresh_from_db()
        # invoice and block is still unpaid
        assert self.block.paid is False
        assert self.invoice.paid is False

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [settings.SUPPORT_EMAIL]
        assert "WARNING: Something went wrong with a payment!" in mail.outbox[0].subject
        assert "Failed payment intent id: mock-intent-id; invoice id foo" in mail.outbox[0].body

    @patch("payments.views.stripe.Webhook")
    def test_webhook_payment_requires_action(self, mock_webhook):
        metadata = {
            "invoice_id": "foo",
            "invoice_signature": self.invoice.signature(),
            **self.invoice.items_metadata(),
        }
        mock_webhook.construct_event.return_value = get_mock_webhook_event(
            webhook_event_type="payment_intent.requires_action", metadata=metadata
        )
        resp = self.client.post(self.url, data={}, HTTP_STRIPE_SIGNATURE="foo")
        assert resp.status_code == 200
        self.block.refresh_from_db()
        self.invoice.refresh_from_db()
        # invoice and block is still unpaid
        assert self.block.paid is False
        assert self.invoice.paid is False

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [settings.SUPPORT_EMAIL]
        assert "WARNING: Something went wrong with a payment!" in mail.outbox[0].subject
        assert "Payment intent requires action: id mock-intent-id; invoice id foo" in mail.outbox[0].body
