# -*- coding: utf-8 -*-
import pytz

from model_bakery import baker

from django.test import TestCase

from booking.models import Block, BlockConfig, BlockVoucher, TotalVoucher
from studioadmin.views.vouchers import BlockVoucherStudioadminForm


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

        block_type = baker.make(BlockConfig, active=True)
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