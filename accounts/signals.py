from django.contrib.auth.models import User
from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from activitylog.models import ActivityLog
from accounts.models import active_disclaimer_cache_key, OnlineDisclaimer, UserProfile


@receiver(post_save, sender=User)
def user_post_save(sender, instance, created, *args, **kwargs):
    # Log when new user created
    if created:
        ActivityLog.objects.create(
            log='New user registered: {} {}, username {}'.format(
                    instance.first_name, instance.last_name, instance.username,
            )
        )


@receiver(post_delete, sender=OnlineDisclaimer)
def update_cache(sender, instance, **kwargs):
    # set cache to False
    cache.set(active_disclaimer_cache_key(instance.user), False, None)
