from django.contrib import admin

from .models import ProductCategory, ProductPurchase, ProductStock, Product, ProductVariant


class ProductInline(admin.TabularInline):
    model = Product


class ProductStockInline(admin.TabularInline):
    model = ProductStock


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = (ProductVariantInline,)


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    inlines = (ProductInline,)


@admin.register(ProductVariant)
class ProductAdmin(admin.ModelAdmin):
    inlines = (ProductStockInline,)


@admin.register(ProductPurchase)
class ProductPurchaseAdmin(admin.ModelAdmin):
    ...