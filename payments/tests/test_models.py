import os
from unittest.mock import patch
from hashlib import sha512

import pytest
from django.test import TestCase

from model_bakery import baker

from booking.models import Block, Subscription
from ..models import Invoice, Seller


@pytest.fixture
def invoice_keyenv():
    old = os.environ.get("INVOICE_KEY")
    os.environ["INVOICE_KEY"] = "test"
    yield os.environ["INVOICE_KEY"]
    if old is None:
        del os.environ["INVOICE_KEY"]
    else:
        os.environ["INVOICE_KEY"] = old


class TestModels(TestCase):

    def test_invoice_str(self):
        invoice = baker.make(Invoice, username="test@test.com", invoice_id="foo123", amount="10", transaction_id=None)
        assert str(invoice) == "foo123 - test@test.com - £10"

        invoice.transaction_id = "txn1"
        invoice.save()
        assert str(invoice) == "foo123 - test@test.com - £10 (paid)"

    @patch("payments.models.ShortUUID.random")
    def test_generate_invoice_id(self, short_uuid_random):
        short_uuid_random.side_effect = ["foo123", "foo234", "foo567"]
        # inv id generated from random shortuuid
        assert Invoice.generate_invoice_id() == "foo123"

        # if an invoice already exists with that id, try again until we get a unique one
        baker.make(Invoice, invoice_id="foo234")
        assert Invoice.generate_invoice_id() == "foo567"

    @pytest.mark.usefixtures("invoice_keyenv")
    def test_signature(self):
        invoice = baker.make(Invoice, invoice_id="foo123")
        assert invoice.signature() == sha512("foo123test".encode("utf-8")).hexdigest()

    @pytest.mark.usefixtures("invoice_keyenv")
    def test_invoice_item_count(self):
        invoice = baker.make(
            Invoice, invoice_id="foo123",
            blocks=baker.make(Block, _quantity=2),
            subscriptions=baker.make(Subscription, _quantity=1)
        )
        assert invoice.item_count() == 3

    @pytest.mark.usefixtures("invoice_keyenv")
    def test_invoice_items_metadata(self):
        invoice = baker.make(Invoice, invoice_id="foo123")
        block = baker.make(Block, block_config__cost=10, block_config__name="test block", invoice=invoice)
        subscription = baker.make(Subscription, config__name="test subscription", config__cost=50, invoice=invoice)

        assert invoice.items_metadata() == {
            "test block": f"£10.00 (block-{block.id})",
            "test subscription": f"£50.00 (subscription-{subscription.id})",
        }

    def seller_str(self):
        seller = baker.make(Seller, user__email="testuser@test.com")
        assert str(seller) == "testuser@test.com"
