from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver

from activitylog.models import ActivityLog
from accounts.models import active_disclaimer_cache_key, managed_users_cache_key, OnlineDisclaimer, \
    ChildUserProfile, UserProfile
from payments.models import Seller


@receiver(post_save, sender=User)
def user_post_save(sender, instance, created, *args, **kwargs):
    # Log when new user created
    if created:
        ActivityLog.objects.create(
            log='New user registered: {} {}, username {}'.format(
                    instance.first_name, instance.last_name, instance.username,
            )
        )


@receiver(post_save, sender=UserProfile)
def userprofile_save(sender, instance, created, **kwargs):
    if created:
        if instance.seller:
            Seller.objects.create(user=instance.user)
    if not created:
        user_id = instance.user.id
        existing_seller = Seller.objects.filter(user=user_id).first()
        if instance.seller and not existing_seller:
            Seller.objects.create(user=instance.user)
        if not instance.seller and existing_seller:
            existing_seller.delete()
    if instance.user.manager_user:
        if created:
            instance.student = True
            instance.save()
        _delete_managed_users_cache(instance.user.manager_user)


@receiver(post_save, sender=ChildUserProfile)
def childuserprofile_save(sender, instance, created, **kwargs):
    if created:
        user_profile, _ = UserProfile.objects.get_or_create(user=instance.user)
        user_profile.student = True
        user_profile.save()


@receiver(post_delete, sender=OnlineDisclaimer)
def update_cache(sender, instance, **kwargs):
    # set cache to False
    cache.set(active_disclaimer_cache_key(instance.user), False, None)


def _delete_managed_users_cache(user):
    cache_key = managed_users_cache_key(user)
    cache.delete(cache_key)


@receiver(post_save, sender=ChildUserProfile)
def update_managed_users_post_child_profile_save(sender, instance, created, *args, **kwargs):
    _delete_managed_users_cache(instance.parent_user_profile.user)


@receiver(post_save, sender=User)
def update_managed_users_cache_post_child_user_save(sender, instance, created, *args, **kwargs):
    if instance.manager_user:
        _delete_managed_users_cache(instance.manager_user)


@receiver(pre_delete, sender=ChildUserProfile)
def delete_managed_users_cache(sender, instance, *args, **kwargs):
    _delete_managed_users_cache(instance.parent_user_profile.user)
