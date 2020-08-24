import os
from unittest.mock import patch
from hashlib import sha512

import pytest
from django.conf import settings
from django.core import mail
from django.shortcuts import reverse
from django.test import TestCase, override_settings

from model_bakery import baker

from paypal.standard.pdt.models import PayPalPDT

from booking.models import Block, Subscription
from common.test_utils import TestUsersMixin
from ..models import Invoice


class PaypalCancelReturnViewTests(TestCase):

    def test_get(self):
        resp = self.client.get(reverse("payments:paypal_cancel"))
        assert resp.status_code == 200


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
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
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
    def test_return_with_valid_pdt_with_matching_invoice_block_and_subscription(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
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
        block.refresh_from_db()
        invoice.refresh_from_db()
        pdt_obj.refresh_from_db()

        assert subscription.paid is True
        assert block.paid is True
        assert invoice.transaction_id == "bar"
        assert pdt_obj.invoice == "foo"

        assert len(mail.outbox) == 2

    @patch("payments.views.process_pdt")
    def test_return_with_valid_pdt_no_invoice_on_pdt(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.student_user.username
        )
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
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
        baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
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
    def test_return_with_valid_pdt_with_matching_invoice_multiple_blocks(self, process_pdt):
        invoice = baker.make(
            Invoice, invoice_id="foo", amount=10, business_email="testreceiver@test.com",
            username=self.manager_user.username
        )
        block1 = baker.make(Block, paid=False, invoice=invoice, user=self.manager_user)
        block2 = baker.make(Block, paid=False, invoice=invoice, user=self.child_user)
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
            baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
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
        block = baker.make(Block, paid=False, invoice=invoice, user=self.student_user)
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
        baker.make(Block, invoice=invoice, user=self.student_user, paid=True)
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
