from datetime import timedelta
from urllib.parse import urlencode

import pytest

from model_bakery import baker
from unittest.mock import Mock, patch

from django.conf import settings
from django.core import mail
from django.urls import reverse
from django.test import TestCase, override_settings
from django.utils import timezone

from booking.models import Block, Subscription

from paypal.standard.ipn.models import PayPalIPN

from common.test_utils import TestUsersMixin
from ..exceptions import PayPalProcessingError
from ..models import Invoice


# Parameters are all bytestrings, so we can construct a bytestring
# request the same way that Paypal does.
CHARSET = "windows-1252"
TEST_RECEIVER_EMAIL = 'dummy-email@hotmail.com'
IPN_POST_PARAMS = {
    "mc_gross": b"7.00",
    "invoice": b"123",
    "protection_eligibility": b"Ineligible",
    "txn_id": b"51403485VH153354B",
    "last_name": b"User",
    "receiver_email": TEST_RECEIVER_EMAIL.encode("utf-8"),
    "payer_id": b"BN5JZ2V7MLEV4",
    "tax": b"0.00",
    "payment_date": b"23:04:06 Feb 02, 2009 PST",
    "first_name": b"Test",
    "mc_fee": b"0.44",
    "notify_version": b"3.8",
    "custom": b"booking 1",
    "payer_status": b"verified",
    "payment_status": b"Completed",
    "business": TEST_RECEIVER_EMAIL.encode("utf-8"),
    "quantity": b"1",
    "verify_sign": b"An5ns1Kso7MWUdW4ErQKJJJ4qi4-AqdZy6dD.sGO3sDhTf1wAbuO2IZ7",
    "payer_email": b"test_user@gmail.com",
    "payment_type": b"instant",
    "payment_fee": b"",
    "receiver_id": b"258DLEHY2BDK6",
    "txn_type": b"web_accept",
    "item_name": "Pole Level 1 - 24 Nov 2015 20:10",
    "mc_currency": b"GBP",
    "item_number": b"",
    "residence_country": "GB",
    "handling_amount": b"0.00",
    "charset": CHARSET.encode("utf-8"),
    "payment_gross": b"",
    "transaction_subject": b"",
    "ipn_track_id": b"1bd9fe52f058e",
    "shipping": b"0.00",
}


@override_settings(DEFAULT_PAYPAL_EMAIL=TEST_RECEIVER_EMAIL, SEND_ALL_STUDIO_EMAILS=True)
class PaypalSignalsTests(TestUsersMixin, TestCase):

    def setUp(self):
        self.create_users()

    def paypal_post(self, params):
        """
        Does an HTTP POST the way that PayPal does, using the params given.
        Taken from django-paypal
        """
        # We build params into a bytestring ourselves, to avoid some encoding
        # processing that is done by the test client.
        cond_encode = lambda v: v.encode(CHARSET) if isinstance(v, str) else v
        byte_params = {
            cond_encode(k): cond_encode(v) for k, v in params.items()
            }
        post_data = urlencode(byte_params)
        return self.client.post(
            reverse('paypal-ipn'),
            post_data, content_type='application/x-www-form-urlencoded'
        )

    def test_paypal_invalid_ipn(self):
        assert PayPalIPN.objects.exists() is False
        with pytest.raises(PayPalProcessingError):
            self.paypal_post({'charset': CHARSET.encode("utf-8"), 'txn_id': 'test'})
        assert PayPalIPN.objects.count() == 1

        ppipn = PayPalIPN.objects.first()
        assert ppipn.flag is True

        # one error email sent
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [settings.SUPPORT_EMAIL]

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_paypal_notify_url_invalid_ipn(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        assert PayPalIPN.objects.exists() is False
        with pytest.raises(PayPalProcessingError):
            self.paypal_post({'charset': CHARSET.encode("utf-8"), 'txn_id': 'test'})
        assert PayPalIPN.objects.count() == 1

        ppipn = PayPalIPN.objects.first()
        assert ppipn.flag is True

        # one error email sent
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [settings.SUPPORT_EMAIL]

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_valid_ipn_no_matching_invoice(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        assert PayPalIPN.objects.exists() is False
        self.paypal_post(IPN_POST_PARAMS)
        assert PayPalIPN.objects.count() == 1

        # ipn itself is OK
        ppipn = PayPalIPN.objects.first()
        assert ppipn.flag is False

        # one error email sent
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [settings.SUPPORT_EMAIL]
        assert mail.outbox[0].subject == "WARNING: Something went wrong with a payment!"
        assert "could not find invoice" in mail.outbox[0].body

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_valid_ipn_with_matching_invoice_and_block(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email=TEST_RECEIVER_EMAIL,
            username=self.student_user.username
        )
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
        assert PayPalIPN.objects.exists() is False
        self.paypal_post(
            {
                **IPN_POST_PARAMS,
                "invoice": b"foo",
                "custom": f"{invoice.id}_{invoice.signature()}".encode("utf-8"),
                "mc_gross": b"10.00"
            }
        )
        assert PayPalIPN.objects.count() == 1
        block.refresh_from_db()
        assert block.paid is True
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_valid_ipn_with_matching_invoice_subscription_and_block(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email=TEST_RECEIVER_EMAIL,
            username=self.student_user.username
        )
        subscription = baker.make(
            Subscription, paid=False, invoice=invoice, user=self.student_user, purchase_date=timezone.now() - timedelta(3)
        )
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
        assert PayPalIPN.objects.exists() is False
        self.paypal_post(
            {
                **IPN_POST_PARAMS,
                "invoice": b"foo",
                "custom": f"{invoice.id}_{invoice.signature()}".encode("utf-8"),
                "mc_gross": b"10.00"
            }
        )
        assert PayPalIPN.objects.count() == 1
        block.refresh_from_db()
        subscription.refresh_from_db()
        assert block.paid is True
        assert subscription.paid is True
        assert subscription.purchase_date.date() == timezone.now().date()
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.student_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_valid_ipn_no_invoice(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email=TEST_RECEIVER_EMAIL,
            username=self.student_user.username
        )
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
        assert PayPalIPN.objects.exists() is False
        self.paypal_post(
            {
                **IPN_POST_PARAMS,
                "invoice": b"",
                "custom": f"{invoice.id}_{invoice.signature()}".encode("utf-8"),
                "mc_gross": b"10.00"
            }
        )
        assert PayPalIPN.objects.count() == 1
        block.refresh_from_db()
        assert block.paid is True

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_valid_ipn_with_matching_invoice_multiple_blocks(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email=TEST_RECEIVER_EMAIL,
            username=self.manager_user.username
        )
        block1 = baker.make(Block, paid=False, invoice=invoice, user=self.manager_user)
        block2 = baker.make(Block, paid=False, invoice=invoice, user=self.child_user)

        assert PayPalIPN.objects.exists() is False
        self.paypal_post(
            {
                **IPN_POST_PARAMS,
                "invoice": b"foo",
                "custom": f"{invoice.id}_{invoice.signature()}".encode("utf-8"),
                "mc_gross": b"10.00"
            }
        )
        assert PayPalIPN.objects.count() == 1
        block1.refresh_from_db()
        block2.refresh_from_db()
        assert block1.paid is True
        assert block2.paid is True
        assert len(mail.outbox) == 2
        assert mail.outbox[0].to == [settings.DEFAULT_STUDIO_EMAIL]
        assert mail.outbox[1].to == [self.manager_user.email]
        assert "Your payment has been processed" in mail.outbox[1].subject

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_valid_ipn_with_matching_invoice_invalid_paypal_info(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        tests = [
            (   # valid
                {"amount": 10, "business_email": TEST_RECEIVER_EMAIL, "invoice_id": "foo1"},
                {
                    "mc_gross": b"10.00", "mc_currency": b"GBP", "receiver_email": TEST_RECEIVER_EMAIL.encode("utf-8"),
                    "invoice": b"foo1", "txn_id": b"txn1"
                },
                True
            ),
            (   # invalid amount
                {"amount": 20, "business_email": TEST_RECEIVER_EMAIL, "invoice_id": "foo2"},
                {
                    "mc_gross": b"10.00", "mc_currency": b"GBP", "receiver_email": TEST_RECEIVER_EMAIL.encode("utf-8"),
                    "invoice": b"foo2", "txn_id": b"txn2"},
                False
            ),
            (   # invalid currency
                {"amount": 20, "business_email": TEST_RECEIVER_EMAIL, "invoice_id": "foo3"},
                {
                    "mc_gross": b"20.00", "mc_currency": b"USD", "receiver_email": TEST_RECEIVER_EMAIL.encode("utf-8"),
                    "invoice": b"foo3", "txn_id": b"txn3"
                },
                False
            ),
            (   # invalid receiver email
                {"amount": 20, "business_email": TEST_RECEIVER_EMAIL, "invoice_id": "foo4"},
                {
                    "mc_gross": b"20.00", "mc_currency": b"GBP", "receiver_email": b"foo@test.com",
                    "invoice": b"foo4", "txn_id": b"txn4"
                },
                False
            ),

        ]

        for (invoice_values, pdt_values, valid) in tests:
            invoice = baker.make(Invoice, username=self.student_user.username, **invoice_values)
            block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
            self.paypal_post(
                {
                    **IPN_POST_PARAMS,
                    "custom": f"{invoice.id}_{invoice.signature()}".encode("utf-8"),
                    **pdt_values,
                }
            )
            block.refresh_from_db()
            assert block.paid == valid

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_valid_ipn_with_matching_invoice_block_already_processed(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email=TEST_RECEIVER_EMAIL,
            username=self.student_user.username, transaction_id="txn1"
        )
        block = baker.make(Block, paid=True, invoice=invoice, user=self.student_user)
        self.paypal_post(
            {
                **IPN_POST_PARAMS,
                "invoice": b"foo",
                "txn_id": b"txn1",
                "custom": f"{invoice.id}_{invoice.signature()}".encode("utf-8"),
                "mc_gross": b"10.00"
            }
        )
        assert block.paid is True
        # already processed, no emails
        assert len(mail.outbox) == 0

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_refunded_status(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email=TEST_RECEIVER_EMAIL,
            username=self.student_user.username,
        )
        block = baker.make(Block, paid=True, invoice=invoice, user=self.student_user)
        self.paypal_post(
            {
                **IPN_POST_PARAMS,
                "invoice": b"foo",
                "txn_id": b"txn1",
                "custom": f"{invoice.id}_{invoice.signature()}".encode("utf-8"),
                "mc_gross": b"10.00",
                "payment_status": b"Refunded"
            }
        )
        # No change to block status
        assert block.paid is True
        # just sends emails
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == "WARNING: Payment refund processed"

    @patch('paypal.standard.ipn.models.PayPalIPN._postback')
    def test_unexpected_status(self, mock_postback):
        mock_postback.return_value = b"VERIFIED"
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email=TEST_RECEIVER_EMAIL,
            username=self.student_user.username,
        )
        block = baker.make(Block, paid=True, invoice=invoice, user=self.student_user)
        self.paypal_post(
            {
                **IPN_POST_PARAMS,
                "invoice": b"foo",
                "txn_id": b"txn1",
                "custom": f"{invoice.id}_{invoice.signature()}".encode("utf-8"),
                "mc_gross": b"10.00",
                "payment_status": b"Pending"
            }
        )
        # No change to block status
        assert block.paid is True
        # just sends emails
        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject == 'WARNING: Something went wrong with a payment!'
        assert "IPN signal received with unexpecting status" in mail.outbox[0].body
