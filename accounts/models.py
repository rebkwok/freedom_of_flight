# -*- coding: utf-8 -*-
import logging
import pytz
import uuid

from datetime import timedelta, datetime, time
from datetime import timezone as dt_timezone

from math import floor

from dateutil.relativedelta import relativedelta

from django.db import models
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.contrib.auth.models import User, Group
from django.utils import timezone

from dynamic_forms.models import FormField, ResponseField

from activitylog.models import ActivityLog


logger = logging.getLogger(__name__)


# Decorator for django models that contain readonly fields.
def has_readonly_fields(original_class):
    def store_read_only_fields(sender, instance, **kwargs):
        if not instance.id:
            return
        fields_to_store = list(sender.read_only_fields)
        if hasattr(instance, "is_draft"):
            fields_to_store.append("is_draft")
        for field_name in fields_to_store:
            val = getattr(instance, field_name)
            setattr(instance, field_name + "_oldval", val)

    def check_read_only_fields(sender, instance, **kwargs):
        if not instance.id:
            return
        elif instance.id and hasattr(instance, "is_draft"):
            if instance.is_draft:
                # we can edit if we're changing a draft
                return
            if instance.is_draft_oldval and not instance.is_draft:
                # we can edit if we're changing a draft to published
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
    pronouns = models.CharField(max_length=50, null=True, blank=True)
    class Meta:
        abstract = True


class UserProfile(BaseUserProfile):
    student = models.BooleanField(default=False)
    manager = models.BooleanField(default=False)
    seller = models.BooleanField(default=False)

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
        super().save(**kwargs)
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
        # delete the cache entry if it exists, so we re-cache if necessary
        cache.delete(active_data_privacy_cache_key(self.user))
        if not self.id:
            ActivityLog.objects.create(
                log="Signed data privacy policy agreement created: {}".format(self.__str__())
            )
        super().save(**kwargs)

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

    form = FormField(verbose_name="Questionnaire questions", null=True, blank=True)
    form_title = models.CharField(max_length=255, default="Health Questionnaire")
    form_info = models.TextField(null=True, blank=True, verbose_name="Additional questionnaire info", help_text="Optional text to display after the questionnaire questions")
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
            if current and current.disclaimer_terms == self.disclaimer_terms \
                    and current.form == self.form and current.form_title == self.form_title \
                    and current.form_info == self.form_info:
                raise ValidationError('No changes made to content; not saved')

        if not self.id and not self.version:
            # if no version specified, go to next major version
            self.version = float(floor((DisclaimerContent.current_version() + 1)))

        # Always update issue date on saving drafts or on first publish
        if self.is_draft or getattr(self, "is_draft_oldval", False):
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
        # delete the cache keys to force re-cache
        cache.delete(active_disclaimer_cache_key(self.user))
        cache.delete(expired_disclaimer_cache_key(self.user))
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
        super().save(**kwargs)

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


def managed_users_cache_key(user):
    return f"managed_users_{user.id}"


def _get_managed_users(user):
    cache_key = managed_users_cache_key(user)
    managed_users = cache.get(cache_key)
    if not managed_users:
        if hasattr(user, "userprofile"):
            child_users = [childprofile.user for childprofile in user.userprofile.managed_profiles.all() if
                           childprofile.user.is_active]
            managed_users = [user, *child_users] if user.is_student else child_users
            if child_users and not user.is_manager:
                user.userprofile.manager = True
                user.userprofile.save()
        else:
            UserProfile.objects.create(user=user, student=True)
            managed_users = [user]
        cache.set(cache_key, managed_users, timeout=60 * 60)
    return managed_users


def _get_managed_users_excluding_self(user):
    managed_users = _get_managed_users(user)
    return [managed_user for managed_user in managed_users if managed_user != user]

@property
def user_age(self):
    if self.manager_user:
        date_of_birth = self.childuserprofile.date_of_birth
    else:
        date_of_birth = self.userprofile.date_of_birth
    if date_of_birth:
        date_of_birth_datetime = datetime.combine(date_of_birth, time(0, 0), tzinfo=dt_timezone.utc)
        return relativedelta(timezone.now(), date_of_birth_datetime).years


@property
def managed_users(self):
    return _get_managed_users(self)


@property
def managed_users_excluding_self(self):
    return _get_managed_users_excluding_self(self)


@property
def managed_users_including_self(self):
    return [self, *_get_managed_users(self)]


@property
def managed_student_users(self):
    if self.userprofile.student:
        return _get_managed_users(self)
    return _get_managed_users_excluding_self(self)


@property
def is_instructor(self):
    cache_key = f"user_{self.id}_is_instructor"
    user_is_instructor = cache.get(cache_key)
    if user_is_instructor is not None:
        user_is_instructor = bool(user_is_instructor)
    else:
        group, _ = Group.objects.get_or_create(name='instructors')
        user_is_instructor = group in self.groups.all()
        cache.set(cache_key, user_is_instructor, 1800)
    return user_is_instructor


@property
def is_student(self):
    if hasattr(self, "userprofile"):
        return self.userprofile.student
    else:
        UserProfile.objects.create(user=self)
    return False


@property
def is_manager(self):
    if hasattr(self, "userprofile"):
        return self.userprofile.manager
    else:
        UserProfile.objects.create(user=self)
    return False


@property
def is_seller(self):
    if hasattr(self, "userprofile"):
        return self.userprofile.seller
    else:
        UserProfile.objects.create(user=self)
    return False


@property
def manager_user(self):
    if hasattr(self, "childuserprofile"):
        return self.childuserprofile.parent_user_profile.user
    return None


@property
def contact_email(self):
    if hasattr(self, "childuserprofile"):
        return self.childuserprofile.parent_user_profile.user.email
    return self.email


@property
def pronouns(self):
    if hasattr(self, "childuserprofile"):
        return self.childuserprofile.pronouns
    return self.userprofile.pronouns


User.add_to_class("managed_users", managed_users)
User.add_to_class("managed_users_excluding_self", managed_users_excluding_self)
User.add_to_class("managed_users_including_self", managed_users_including_self)
User.add_to_class("managed_student_users", managed_student_users)
User.add_to_class("is_student", is_student)
User.add_to_class("is_manager", is_manager)
User.add_to_class("is_seller", is_seller)
User.add_to_class("is_instructor", is_instructor)
User.add_to_class("manager_user", manager_user)
User.add_to_class("age", user_age)
User.add_to_class("contact_email", contact_email)
User.add_to_class("pronouns", pronouns)
