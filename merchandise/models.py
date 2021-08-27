# -*- coding: utf-8 -*-
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from imagekit.models import ImageSpecField, ProcessedImageField
from imagekit.processors import ResizeToFill

from activitylog.models import ActivityLog


class ProductCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)

    class Meta:
        verbose_name_plural = "product categories"
        ordering = ("name",)

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=255)
    category = models.ForeignKey(ProductCategory, on_delete=models.CASCADE, related_name="products")
    active = models.BooleanField(default=True, help_text="Visible on site and available to purchase")

    image = ProcessedImageField(
        upload_to='merchandise',
        format='JPEG',
        options={'quality': 70},
        null=True, blank=True,
    )

    thumbnail = ImageSpecField(source='image',
                               processors=[ResizeToFill(150, 150)],
                               format='JPEG',
                               options={'quality': 100})

    class Meta:
        ordering = ("-active", "category", "name")
        unique_together = ("category", "name")

    def __str__(self):
        return f"{self.category} - {self.name}"


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    size = models.CharField(max_length=50, null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        unique_together = ("product", "size")

    def __str__(self):
        return f"{self.product} - size {self.size}"

    def update_stock(self, quantity):
        stock, _ = ProductStock.objects.get_or_create(
            product_variant=self, defaults={"quantity": quantity}
        )
        stock.quantity = quantity
        stock.save()

    @property
    def current_stock(self):
        stock, _ = ProductStock.objects.get_or_create(product_variant=self, defaults={"quantity": 0})
        return stock.quantity


class ProductStock(models.Model):
    product_variant = models.OneToOneField(
        ProductVariant, on_delete=models.CASCADE, related_name="stock"
    )
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "product stock"

    def __str__(self):
        return f"{self.product_variant} - in stock {self.quantity}"


class ProductPurchase(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="purchases")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchases")
    cost = models.DecimalField(max_digits=10, decimal_places=2)
    size = models.CharField(max_length=50)
    created_at = models.DateTimeField(default=timezone.now)
    paid = models.BooleanField(default=False)
    date_paid = models.DateTimeField(null=True, blank=True, help_text="Leave blank for today")
    received = models.BooleanField(default=False)
    date_received = models.DateTimeField(null=True, blank=True, help_text="Leave blank for today")

    def __str__(self):
        paid_status = "paid" if self.paid else "not paid"
        return f"{self.product} - {self.user} - {paid_status}"

    def get_stock(self, obj):
        try:
            variant = ProductVariant.objects.get(product=obj.product, size=obj.size)
        except ProductVariant.DoesNotExist as e:
            if self.id:
                stock = None
            else:
                raise e
        else:
            stock = ProductStock.objects.get(product_variant=variant)
        return stock

    def _pre_save_purchase(self):
        return ProductPurchase.objects.get(pk=self.pk)

    def check_stock(self):
        # Run this in the views before saving, NOT in clean method when size/cost
        # have not been assigned yet
        stock = self.get_stock(self)
        if stock is not None and stock.quantity <= 0:
            if not self.id or (self.id and (self._pre_save_purchase().size != self.size)):
                raise ValidationError("Out of stock")

    def reduce_stock(self, obj):
        stock = self.get_stock(obj)
        if stock is not None:
            # can't reduce stock below 0
            if stock.quantity > 1:
                stock.quantity -= 1
            stock.save()

    def save(self, *args, **kwargs):
        if self.product and self.cost and self.size:
            # only check the stock if we have the required fields already; views that do a
            # form.save(commit=False) before assigning these fields need to call check_stock
            # explicitly
            self.check_stock()

        if not self.id:
            # new purchase, reduce stock quantity
            self.reduce_stock(self)
        else:
            presave = self._pre_save_purchase()
            if presave.size != self.size:
                # size has changed, update stock for old and new variant
                presave_stock = self.get_stock(presave)
                if presave_stock is not None:
                    # old variant removed, no stock to update
                    presave_stock.quantity += 1
                    presave_stock.save()
                self.reduce_stock(self)

        if self.paid:
            if not self.date_paid:
                self.date_paid = timezone.now()
        else:
            self.date_paid = None

        if self.received:
            if not self.date_received:
                self.date_received = timezone.now()
        else:
            self.date_received = None

        return super().save(*args, **kwargs)

    def delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)
        stock = self.get_stock(self)
        stock.quantity += 1
        stock.save()
