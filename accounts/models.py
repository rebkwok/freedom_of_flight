# -*- coding: utf-8 -*-
import logging
import pytz
import uuid

from datetime import timedelta

from math import floor

from dateutil.relativedelta import relativedelta

from django.db import models
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.contrib.auth.models import User
from django.utils import timezone

from dynamic_forms.models import FormField, ResponseField

from activitylog.models import ActivityLog


logger = logging.getLogger(__name__)


# Decorator for django models that contain readonly fields.
def has_readonly_fields(original_class):
    def store_read_only_fields(sender, instance, **kwargs):
        if not instance.id:
            return
        for field_name in sender.read_only_fields:
            val = getattr(instance, field_name)
            setattr(instance, field_name + "_oldval", val)

    def check_read_only_fields(sender, instance, **kwargs):
        if not instance.id:
            return
        elif instance.id and hasattr(instance, "is_draft") and instance.is_draft:
            return
        for field_name in sender.read_only_fields:
            old_value = getattr(instance, field_name + "_oldval")
            new_value = getattr(instance, field_name)
            if old_value != new_value:
                raise ValueError("Field %s is read only." % field_name)

    models.signals.post_init.connect(
        store_read_only_fields, original_class, weak=False) # for load
    models.signals.post_save.connect(
        store_read_only_fields, original_class, weak=False) # for save
    models.signals.pre_save.connect(
        check_read_only_fields, original_class, weak=False)
    return original_class


BOOL_CHOICES = ((True, 'Yes'), (False, 'No'))


class BaseUserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    date_of_birth = models.DateField(verbose_name='date of birth', null=True, blank=True)
    address = models.CharField(max_length=512, null=True, blank=True)
    postcode = models.CharField(max_length=10, null=True, blank=True)
    phone = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        abstract = True


class UserProfile(BaseUserProfile):
    student = models.BooleanField(default=True)
    manager = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username


class ChildUserProfile(BaseUserProfile):
    parent_user_profile = models.ForeignKey(
        UserProfile, null=True, blank=True, on_delete=models.CASCADE, related_name="managed_profiles"
    )



@has_readonly_fields
class CookiePolicy(models.Model):
    read_only_fields = ('content', 'version', 'issue_date')

    content = models.TextField()
    version = models.DecimalField(unique=True, decimal_places=1, max_digits=100)
    issue_date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-version",)
        verbose_name_plural = "Cookie Policies"

    @classmethod
    def current_version(cls):
        current_policy = CookiePolicy.current()
        if current_policy is None:
            return 0
        return current_policy.version

    @classmethod
    def current(cls):
        return CookiePolicy.objects.order_by('version').last()

    def __str__(self):
        return 'Cookie Policy - Version {}'.format(self.version)

    def save(self, **kwargs):
        if not self.id:
            current = CookiePolicy.current()
            if current and current.content == self.content:
                raise ValidationError('No changes made to content; not saved')

        if not self.id and not self.version:
            # if no version specified, go to next major version
            self.version = floor((CookiePolicy.current_version() + 1))
        super(CookiePolicy, self).save(**kwargs)
        ActivityLog.objects.create(
            log='Cookie Policy version {} created'.format(self.version)
        )


@has_readonly_fields
class DataPrivacyPolicy(models.Model):
    read_only_fields = ('content', 'version', 'issue_date')

    content = models.TextField()
    version = models.DecimalField(unique=True, decimal_places=1, max_digits=100)
    issue_date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("-version",)
        verbose_name_plural = "Data Privacy Policies"

    @classmethod
    def current_version(cls):
        current_policy = DataPrivacyPolicy.current()
        if current_policy is None:
            return 0
        return current_policy.version

    @classmethod
    def current(cls):
        return DataPrivacyPolicy.objects.order_by('version').last()

    def __str__(self):
        return 'Data Privacy Policy - Version {}'.format(self.version)

    def save(self, **kwargs):

        if not self.id:
            current = DataPrivacyPolicy.current()
            if current and current.content == self.content:
                raise ValidationError('No changes made to content; not saved')

        if not self.id and not self.version:
            # if no version specified, go to next major version
            self.version = floor((DataPrivacyPolicy.current_version() + 1))
        super().save(**kwargs)
        ActivityLog.objects.create(
            log='Data Privacy Policy version {} created'.format(self.version)
        )


class SignedDataPrivacy(models.Model):
    read_only_fields = ('date_signed', 'version')

    user = models.ForeignKey(
        User, related_name='data_privacy_agreement', on_delete=models.CASCADE
    )
    date_signed = models.DateTimeField(default=timezone.now)
    version = models.DecimalField(decimal_places=1, max_digits=100)

    class Meta:
        unique_together = ('user', 'version')
        verbose_name = "Signed Data Privacy Agreement"

    def __str__(self):
        return '{} - V{}'.format(self.user.username, self.version)

    @property
    def is_active(self):
        return self.version == DataPrivacyPolicy.current_version()

    def save(self, **kwargs):
        if not self.id:
            ActivityLog.objects.create(
                log="Signed data privacy policy agreement created: {}".format(self.__str__())
            )
        super().save()
        # cache agreement
        if self.is_active:
            cache.set(
                active_data_privacy_cache_key(self.user), True, timeout=600
            )

    def delete(self, using=None, keep_parents=False):
        # clear cache if this is the active signed agreement
        if self.is_active:
            cache.delete(active_data_privacy_cache_key(self.user))
        super().delete(using, keep_parents)


@has_readonly_fields
class DisclaimerContent(models.Model):
    read_only_fields = ('disclaimer_terms', 'version', 'issue_date', 'form')
    disclaimer_terms = models.TextField()
    version = models.DecimalField(unique=True, decimal_places=1, max_digits=100)
    issue_date = models.DateTimeField(default=timezone.now)

    form = FormField(verbose_name="health questionnaire", null=True, blank=True)
    is_draft = models.BooleanField(default=False)

    class Meta:
        ordering = ("-version",)

    @classmethod
    def current_version(cls):
        current_content = DisclaimerContent.current()
        if current_content is None:
            return 0
        return current_content.version

    @classmethod
    def current(cls):
        return DisclaimerContent.objects.filter(is_draft=False).order_by('version').last()

    @property
    def status(self):
        return "draft" if self.is_draft else "published"

    def __str__(self):
        return f'Disclaimer Content - Version {self.version} ({self.status})'

    def save(self, **kwargs):
        if not self.id:
            current = DisclaimerContent.current()
            if current and current.disclaimer_terms == self.disclaimer_terms and current.form == self.form:
                raise ValidationError('No changes made to content; not saved')

        if not self.id and not self.version:
            # if no version specified, go to next major version
            self.version = float(floor((DisclaimerContent.current_version() + 1)))

        # Always update issue date on saving drafts
        if self.is_draft:
            self.issue_date = timezone.now()
        super().save(**kwargs)
        ActivityLog.objects.create(
            log='Disclaimer Content version {} created'.format(self.version)
        )

@has_readonly_fields
class BaseOnlineDisclaimer(models.Model):
    read_only_fields = ('date', 'version')
    date = models.DateTimeField(default=timezone.now)
    version = models.DecimalField(decimal_places=1, max_digits=100)

    emergency_contact_name = models.CharField(max_length=255)
    emergency_contact_relationship = models.CharField(max_length=255)
    emergency_contact_phone = models.CharField(max_length=255)

    health_questionnaire_responses = ResponseField()

    terms_accepted = models.BooleanField()

    class Meta:
        abstract = True


@has_readonly_fields
class OnlineDisclaimer(BaseOnlineDisclaimer):

    user = models.ForeignKey(
        User, related_name='online_disclaimer', on_delete=models.CASCADE
    )

    date_updated = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return '{} - V{} - {}'.format(
            self.user.username,
            self.version,
            self.date.astimezone(pytz.timezone('Europe/London')).strftime('%d %b %Y, %H:%M'))

    @property
    def is_active(self):
        # Disclaimer is active if it was signed <1 yr ago AND it is the current version
        date_signed = self.date_updated if self.date_updated else self.date
        return self.version == DisclaimerContent.current_version() and (date_signed + timedelta(days=365)) > timezone.now()

    def save(self, **kwargs):
        if not self.id:
            existing_disclaimers = OnlineDisclaimer.objects.filter(
                user=self.user
            )
            if existing_disclaimers and [
                True for disc in existing_disclaimers if disc.is_active
            ]:
                raise ValidationError('Active disclaimer already exists')

            ActivityLog.objects.create(
                log="Online disclaimer created: {}".format(self.__str__())
            )
        super().save()
        # cache disclaimer
        if self.is_active:
            cache.set(
                active_disclaimer_cache_key(self.user), True, timeout=600
            )
        else:
            cache.set(
                expired_disclaimer_cache_key(self.user), True, timeout=600
            )

    def delete(self, using=None, keep_parents=False):
        # clear active cache if there is any
        cache.delete(active_disclaimer_cache_key(self.user))
        expiry = timezone.now() - relativedelta(years=6)
        if self.date > expiry or (self.date_updated and self.date_updated > expiry):
            ignore_fields = ['id', 'user_id', '_state']
            fields = {key: value for key, value in self.__dict__.items() if key not in ignore_fields and not key.endswith('_oldval')}
            fields["name"] = f"{self.user.first_name} {self.user.last_name}"
            ArchivedDisclaimer.objects.create(
                date_of_birth=self.user.userprofile.date_of_birth,
                phone=self.user.userprofile.phone,
                address=self.user.userprofile.address,
                postcode=self.user.userprofile.postcode,
                **fields)
            ActivityLog.objects.create(
                log="Online disclaimer deleted; archive created for user {} {}".format(
                    self.user.first_name, self.user.last_name
                )
            )
        super().delete(using, keep_parents)


@has_readonly_fields
class NonRegisteredDisclaimer(BaseOnlineDisclaimer):
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255)
    # These fields are on the user profile for registered users
    email = models.EmailField()
    date_of_birth = models.DateField(verbose_name='date of birth')
    address = models.CharField(max_length=512, null=True, blank=True)
    postcode = models.CharField(max_length=10, null=True, blank=True)
    phone = models.CharField(max_length=255, null=True, blank=True)

    event_date = models.DateField()
    user_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        verbose_name = 'Event disclaimer'

    @property
    def is_active(self):
        # Disclaimer is active if it was created <1 yr ago AND it is the current version
        return self.version == DisclaimerContent.current_version() and (self.date + timedelta(days=365)) > timezone.now()

    def __str__(self):
        return '{} {} - V{} - {}'.format(
            self.first_name,
            self.last_name,
            self.version,
            self.date.astimezone(pytz.timezone('Europe/London')).strftime('%d %b %Y, %H:%M'))

    def delete(self, using=None, keep_parents=False):
        expiry = timezone.now() - relativedelta(years=6)
        if self.date > expiry:
            ignore_fields = [
                'id', '_state', 'first_name', 'last_name', 'email', 'user_uuid',
            ]
            fields = {key: value for key, value in self.__dict__.items() if key not in ignore_fields and not key.endswith('_oldval')}

            ArchivedDisclaimer.objects.create(name='{} {}'.format(self.first_name, self.last_name), **fields)
            ActivityLog.objects.create(
                log="Event disclaimer < 6years old deleted; archive created for user {} {}".format(
                    self.first_name, self.last_name
                )
            )
        super().delete(using=using, keep_parents=keep_parents)


class ArchivedDisclaimer(BaseOnlineDisclaimer):

    name = models.CharField(max_length=255)
    date_updated = models.DateTimeField(null=True, blank=True)
    date_archived = models.DateTimeField(default=timezone.now)
    date_of_birth = models.DateField(verbose_name='date of birth')
    address = models.CharField(max_length=512, null=True, blank=True)
    postcode = models.CharField(max_length=10, null=True, blank=True)
    phone = models.CharField(max_length=255, null=True, blank=True)
    event_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return '{} - V{} - {} (archived {})'.format(
            self.name,
            self.version,
            self.date.astimezone(pytz.timezone('Europe/London')).strftime('%d %b %Y, %H:%M'),
            self.date_archived.astimezone(pytz.timezone('Europe/London')).strftime('%d %b %Y, %H:%M')
        )


# CACHING

def active_disclaimer_cache_key(user):
    return f'user_{user.id}_active_disclaimer_v{DisclaimerContent.current_version()}'


def expired_disclaimer_cache_key(user):
    return 'user_{}_expired_disclaimer'.format(user.id)


def has_active_disclaimer(user):
    key = active_disclaimer_cache_key(user)
    has_disclaimer = cache.get(key)
    if has_disclaimer is None:
        has_disclaimer = has_active_online_disclaimer(user)
        cache.set(key, has_disclaimer, timeout=600)
    else:
        has_disclaimer = bool(cache.get(key))
    return has_disclaimer


def has_active_online_disclaimer(user):
    has_disclaimer = any(
        True for od in user.online_disclaimer.all() if od.is_active
    )
    return has_disclaimer


def has_expired_disclaimer(user):
    key = expired_disclaimer_cache_key(user)
    has_expired_disclaimer = cache.get(key)
    if has_expired_disclaimer is None:
        has_expired_disclaimer = bool(
                [
                    True for od in user.online_disclaimer.all()
                    if not od.is_active
                ]
            )
        if has_expired_disclaimer:
            # Only set cache if we know the disclaimer has expired
            cache.set(key, has_expired_disclaimer, timeout=600)
    else:
        has_expired_disclaimer = bool(cache.get(key))
    return has_expired_disclaimer


def active_data_privacy_cache_key(user):
    current_version = DataPrivacyPolicy.current_version()
    return 'user_{}_active_data_privacy_agreement_version_{}'.format(
        user.id, current_version
    )


def has_active_data_privacy_agreement(user):
    key = active_data_privacy_cache_key(user)
    if cache.get(key) is None:
        has_active_agreement = bool(
            [
                True for dp in user.data_privacy_agreement.all()
                if dp.is_active
            ]
        )
        cache.set(key, has_active_agreement, timeout=600)
    else:
        has_active_agreement = bool(cache.get(key))
    return has_active_agreement


@property
def managed_users(self):
    if self.userprofile:
        child_users = [childprofile.user for childprofile in self.userprofile.managed_profiles.all()]
        return [self, *child_users] if self.is_student else [*child_users, self]
    return [self]


@property
def is_student(self):
    if hasattr(self, "userprofile"):
        return self.userprofile.student
    return False


@property
def is_manager(self):
    if hasattr(self, "userprofile"):
        return self.userprofile.manager
    return False


User.add_to_class("managed_users", managed_users)
User.add_to_class("is_student", is_student)
User.add_to_class("is_manager", is_manager)
