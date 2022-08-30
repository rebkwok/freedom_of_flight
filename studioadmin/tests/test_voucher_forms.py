# -*- coding: utf-8 -*-
from model_bakery import baker

from django.test import TestCase

from booking.models import BaseVoucher, Block, BlockConfig, BlockVoucher, TotalVoucher, GiftVoucher, GiftVoucherConfig
from payments.models import Invoice
from studioadmin.forms.voucher_forms import BlockVoucherStudioadminForm, GiftVoucherConfigForm


class BlockVoucherStudioadminFormTests(TestCase):

    def test_only_active_and_non_free_blocktypes_in_choices(self):
        # inactive_block
        baker.make(BlockConfig, active=False)
        active_blocktypes = baker.make(BlockConfig, active=True, _quantity=2)

        form = BlockVoucherStudioadminForm()
        block_types = form.fields['block_configs']
        self.assertEqual(
            sorted(list([bt.id for bt in block_types.queryset])),
            sorted([bt.id for bt in active_blocktypes])
        )

    def test_validate_code(self):
        data = {
            'code': 'test code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(data=data)
        assert form.is_valid() is False
        assert form.errors == {"code": ["Code must not contain spaces"]}

    def test_validate_discount(self):
        data = {
            'code': 'test_code',
            'discount': 110,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(data=data)
        assert form.is_valid() is False
        assert "Discount must be between 1% and 100%" in form.errors["discount"]

    def test_validate_discount_or_amount(self):
        data = {
            'code': 'test_code',
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(data=data)
        assert form.is_valid() is False
        assert "One of discount % or discount amount is required" in form.errors["discount"]
        assert "One of discount % or discount amount is required" in form.errors["discount_amount"]

        data = {
            'code': 'test_code',
            'discount': 10,
            'discount_amount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(data=data)
        assert form.is_valid() is False
        assert form.non_field_errors() == ["Enter either a discount % or discount amount (not both)"]

    def test_validate_max_vouchers(self):
        data = {
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 0,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(data=data)
        assert form.is_valid() is False
        assert form.errors == {"max_vouchers": ["Must be greater than 0 (leave blank if no maximum)"]}

    def test_validate_max_vouchers_for_used_voucher(self):
        voucher = baker.make(TotalVoucher, discount=10)
        # voucher has been used twice
        baker.make(Invoice, total_voucher_code=voucher.code, paid=True, _quantity=2)
        base_voucher = BaseVoucher.objects.get(id=voucher.id)
        # try to change max vouchers to < 2
        data = {
            "id": base_voucher.id,
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 1,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(instance=base_voucher, data=data)
        assert form.is_valid() is False
        assert form.errors == {"max_vouchers": ["Voucher code has already been used 2 times in total; set max uses to 2 or greater"]}

    def test_validate_expiry_date(self):
        data = {
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Feb-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 1,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(data=data)
        assert form.is_valid() is False
        assert form.errors == {"expiry_date": ["Expiry date must be after start date"]}

    def test_cannot_make_max_vouchers_greater_than_number_already_used(self):
        block_type = baker.make(BlockConfig, active=True)
        voucher = baker.make(BlockVoucher, max_vouchers=3, discount=10)
        voucher.block_configs.add(block_type)
        baker.make(Block, voucher=voucher, paid=True, _quantity=3)
        data = {
            'id': voucher.id,
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'block_configs': [block_type.id]
        }

        form = BlockVoucherStudioadminForm(data=data, instance=voucher)
        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors,
            {'max_vouchers': [
                'Voucher code has already been used 3 times in total; '
                'set max uses to 3 or greater'
            ]}
        )

        data.update({'max_vouchers': 3})
        form = BlockVoucherStudioadminForm(data=data, instance=voucher)
        self.assertTrue(form.is_valid())

    def test_block_type_or_total_required(self):
        block_type = baker.make(BlockConfig, active=True)
        data = {
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
        }
        form = BlockVoucherStudioadminForm(data=data)
        self.assertFalse(form.is_valid())

        data = {
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'block_configs': [block_type.id]
        }
        form = BlockVoucherStudioadminForm(data=data)
        self.assertTrue(form.is_valid())

        data = {
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(data=data)
        self.assertTrue(form.is_valid())

        data = {
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True,
            'block_configs': [block_type.id]
        }
        form = BlockVoucherStudioadminForm(data=data)
        self.assertFalse(form.is_valid())

    def test_form_save_block_voucher(self):
        assert BlockVoucher.objects.exists() is False
        assert TotalVoucher.objects.exists() is False

        block_type = baker.make(BlockConfig, active=True)
        data = {
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'block_configs': [block_type.id]
        }
        form = BlockVoucherStudioadminForm(data=data)
        self.assertTrue(form.is_valid())
        form.save()
        assert BlockVoucher.objects.exists() is True
        assert TotalVoucher.objects.exists() is False

    def test_form_save_total_voucher(self):
        assert BlockVoucher.objects.exists() is False
        assert TotalVoucher.objects.exists() is False
        data = {
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(data=data)
        self.assertTrue(form.is_valid())
        form.save()
        assert BlockVoucher.objects.exists() is False
        assert TotalVoucher.objects.exists() is True

    def test_form_save_change_voucher_type(self):
        assert TotalVoucher.objects.exists() is False

        block_type = baker.make(BlockConfig, active=True)
        block_voucher = baker.make(BlockVoucher, discount=10)
        block_voucher.block_configs.add(block_type)
        assert BlockVoucher.objects.count() == 1
        base_voucher = BaseVoucher.objects.get(id=block_voucher.id)
        data = {
            'id': block_voucher.id,
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(instance=base_voucher, data=data)
        self.assertTrue(form.is_valid())
        form.save()
        assert BlockVoucher.objects.exists() is False
        assert TotalVoucher.objects.exists() is True
        assert TotalVoucher.objects.first().code == "test_code"

    def test_form_already_used_block_voucher(self):
        block_type = baker.make(BlockConfig, active=True)
        block_voucher = baker.make(BlockVoucher, discount=10)
        block_voucher.block_configs.add(block_type)

        #used voucher
        baker.make(Block, voucher=block_voucher, paid=True)

        base_voucher = BaseVoucher.objects.get(id=block_voucher.id)
        form = BlockVoucherStudioadminForm(instance=base_voucher)
        for field in ["item_count", "discount", "discount_amount", "total_voucher"]:
            assert form.fields[field].disabled is True
        assert form.fields["block_configs"].disabled is False

    def test_form_already_used_total_voucher(self):
        total_voucher = baker.make(TotalVoucher, discount=10)

        #used voucher
        baker.make(Invoice, total_voucher_code=total_voucher.code, paid=True)
        base_voucher = BaseVoucher.objects.get(id=total_voucher.id)

        form = BlockVoucherStudioadminForm(instance=base_voucher)
        for field in ["item_count", "discount", "discount_amount", "total_voucher", "block_configs"]:
            assert form.fields[field].disabled is True

    def test_update_gift_voucher(self):
        gift_voucher = baker.make(GiftVoucher, gift_voucher_config__discount_amount=10)
        base_voucher = BaseVoucher.objects.get(id=gift_voucher.voucher.id)
        data = {
            'id': base_voucher.id,
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(instance=base_voucher, data=data)
        assert form.is_valid() is True

        layout_field_names = [field_name[1] for field_name in form.helper.layout.get_field_names()]
        gift_voucher_fields = ["message", "name", "purchaser_email"]
        for gift_voucher_field in gift_voucher_fields:
            assert gift_voucher_field in layout_field_names

        voucher = baker.make(TotalVoucher, discount_amount=10)
        base_total_voucher = BaseVoucher.objects.get(id=voucher.id)
        data = {
            'id': base_total_voucher.id,
            'code': 'test_code',
            'discount': 10,
            'start_date': '01-Jan-2016',
            'expiry_date': '31-Jan-2016',
            'max_vouchers': 2,
            'total_voucher': True
        }
        form = BlockVoucherStudioadminForm(instance=base_total_voucher, data=data)
        assert form.is_valid() is True
        layout_field_names = [field_name[1] for field_name in form.helper.layout.get_field_names()]
        gift_voucher_fields = ["message", "name", "purchaser_email"]
        for gift_voucher_field in gift_voucher_fields:
            assert gift_voucher_field not in layout_field_names


class GiftVoucherConfigFormTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.other_block_config = baker.make(BlockConfig, active=False)
        cls.active_block_config = baker.make(BlockConfig, active=True)

    def test_block_config_options(self):
        # active block configs first
        form = GiftVoucherConfigForm()
        assert [
            block_config.id for block_config in form.fields["block_config"].queryset
        ] == [self.active_block_config.id, self.other_block_config.id]

    def test_block_config_or_discount_amount_required(self):
        form = GiftVoucherConfigForm(data={})
        assert form.is_valid() is False
        assert form.errors == {
            "__all__": ['One of credit block or a fixed voucher value is required'],
        }
        assert form.non_field_errors() == ['One of credit block or a fixed voucher value is required']

        form = GiftVoucherConfigForm(data={"block_config": self.active_block_config.id, "discount_amount": 10})
        assert form.is_valid() is False
        assert form.errors == {
            "__all__": ["Select either a credit block or a fixed voucher value (not both)"]
        }
        assert form.non_field_errors() == ["Select either a credit block or a fixed voucher value (not both)"]

        form = GiftVoucherConfigForm(data={"discount_amount": 10})
        assert form.is_valid() is True

        form = GiftVoucherConfigForm(data={"block_config": self.active_block_config.id})
        assert form.is_valid() is True
