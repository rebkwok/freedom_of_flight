from datetime import datetime, timezone
import os
from unittest.mock import patch
from hashlib import sha512

import pytest
from django.test import TestCase

from model_bakery import baker

from booking.models import Block, Booking, EventType, Subscription, GiftVoucher
from merchandise.tests.utils import make_purchase
from ..models import Invoice, Seller


@pytest.fixture
def invoice_keyenv():
    old = os.environ.get("INVOICE_KEY")
    os.environ["INVOICE_KEY"] = "test"
    yield os.environ["INVOICE_KEY"]
    if old is None:  # pragma: no cover
        del os.environ["INVOICE_KEY"]
    else:  # pragma: no cover
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
            subscriptions=baker.make(Subscription, _quantity=1),
            gift_vouchers=baker.make(GiftVoucher, gift_voucher_config__discount_amount=10, _quantity=1),
            product_purchases=make_purchase(quantity=2)
        )
        assert invoice.item_count() == 6

    @pytest.mark.usefixtures("invoice_keyenv")
    def test_invoice_items_metadata(self):
        invoice = baker.make(Invoice, invoice_id="foo123")
        block = baker.make(Block, block_config__cost=10, block_config__name="test block", invoice=invoice)
        booking_block = baker.make(
            Block, block_config__cost=8, block_config__name="dropin block", block_config__size=1, invoice=invoice)
        baker.make(
            Booking, event__name="test class", 
            event__start=datetime(2022, 11, 1, 10, 0, tzinfo=timezone.utc), 
            block=booking_block
        )
        event_type = baker.make(EventType)
        course_booking_block = baker.make(
            Block, 
            block_config__course=True, 
            block_config__cost=50, 
            block_config__name="course block", 
            block_config__size=12, 
            block_config__event_type=event_type,
            invoice=invoice
        )
        baker.make(
            Booking, 
            block=course_booking_block, 
            event__course__event_type=event_type,
            event__event_type=event_type,
            event__course__name="test course", 
            _quantity=2
        )
        
        subscription = baker.make(Subscription, config__name="test subscription", config__cost=50, invoice=invoice)
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config__discount_amount=10, invoice=invoice)
        product_purchase = make_purchase(invoice=invoice)
        product_purchase_no_size = make_purchase(size=None, product_name="Onesie", invoice=invoice)
        assert invoice.items_metadata() == {
            f"#{course_booking_block.id} test course": f"£50.00 (block-{course_booking_block.id})",
            f"#{booking_block.id} test class - 01 Nov 2022, 10:00": f"£8.00 (block-{booking_block.id})",
            f"#{block.id} Credit block: test block": f"£10.00 (block-{block.id})",
            f"#{subscription.id} Sub: test subscription": f"£50.00 (subscription-{subscription.id})",
            f"#{gift_voucher.id} Gift Voucher: £10.00": f"£10.00 (gift_voucher-{gift_voucher.id})",
            f"#{product_purchase.id} Clothing - Hoodie - S": f"£5.00 (product_purchase-{product_purchase.id})",
            f"#{product_purchase_no_size.id} Clothing - Onesie": f"£5.00 (product_purchase-{product_purchase_no_size.id})",
        }
        assert not invoice.final_metadata
        invoice.paid = True
        invoice.save()
        assert invoice.final_metadata == {
            f"block-{course_booking_block.id}": {"name": f"test course", "cost": "£50.00"},
            f"block-{booking_block.id}": {"name": "test class - 01 Nov 2022, 10:00", "cost": "£8.00"},
            f"block-{block.id}": {"name": "Credit block: test block", "cost": "£10.00"},
            f"subscription-{subscription.id}": {"name": "Sub: test subscription", "cost": "£50.00"},
            f"gift_voucher-{gift_voucher.id}": {"name": "Gift Voucher: £10.00", "cost": "£10.00"},
            f"product_purchase-{product_purchase.id}": {"name": "Clothing - Hoodie - S", "cost": "£5.00"},
            f"product_purchase-{product_purchase_no_size.id}": {"name": "Clothing - Onesie", "cost": "£5.00"},
        }

    def test_seller_str(self):
        seller = baker.make(Seller, user__email="testuser@test.com")
        assert str(seller) == "testuser@test.com"
