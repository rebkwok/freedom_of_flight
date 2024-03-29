"""
Django settings for freedom_of_flight project.

Generated by 'django-admin startproject' using Django 3.0.7.

For more information on this file, see
https://docs.djangoproject.com/en/3.0/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.0/ref/settings/
"""

import os
import sys

import environ

from django.utils import timezone

root = environ.Path(__file__) - 2  # two folders back (/a/b/ - 3 = /)

# defaults
env = environ.Env(
    DEBUG=(bool, False),
    PAYPAL_TEST=(bool, False),
    SHOW_DEBUG_TOOLBAR=(bool, False),
    SEND_ALL_STUDIO_EMAILS=(bool, False),
    USE_MAILCATCHER=(bool, False),
    CI=(bool, False),
    LOCAL=(bool, False),
    USE_CDN=(bool, False),
    MERCHANDISE_CART_TIMEOUT_MINUTES=(int, 15),
    CART_TIMEOUT_MINUTES=(int, 15),
    TESTING=(bool, False),
)


environ.Env.read_env(root('freedom_of_flight/.env'))  # reading .env file

TESTING = env("TESTING")
if not TESTING:  # pragma: no cover
    TESTING = any([test_str in arg for arg in sys.argv for test_str in ["test", "pytest"]])

BASE_DIR = root()

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')
if SECRET_KEY is None:  # pragma: no cover
    print("No secret key!")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env('DEBUG')
USE_CDN = env('USE_CDN')
# when env variable is changed it will be a string, not bool
if str(DEBUG).lower() in ['true', 'on']:  # pragma: no cover
    DEBUG = True
else:  # pragma: no cover
    DEBUG = False

ALLOWED_HOSTS = [
    'booking.freedomofflightaerial.com',
    'test73623839.freedomofflightaerial.com',
    'test.freedomofflightaerial.rebkwok.co.uk',
    'vagrant.booking.freedomofflightaerial.com',
    'vagrant.test73623839.freedomofflightaerial.com',
    'vagrant.test.freedomofflight.rebkwok.co.uk',
]
if env('LOCAL'):  # pragma: no cover
    ALLOWED_HOSTS = ['*']

# https://docs.djangoproject.com/en/4.0/ref/settings/#std:setting-CSRF_TRUSTED_ORIGINS
CSRF_TRUSTED_ORIGINS = ['https://booking.freedomofflightaerial.com']

CSRF_FAILURE_VIEW = "common.views.csrf_failure"

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    'django.contrib.humanize',
    'cookielaw',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'django_extensions',
    'debug_toolbar',
    'crispy_forms',
    'dynamic_forms',
    'imagekit',
    'accounts',
    'activitylog',
    'booking',
    'merchandise',
    'timetable',
    'studioadmin',
    'ckeditor',
    'paypal.standard.ipn',
    'paypal.standard.pdt',
    'payments',
    'email_obfuscator',
    'notices',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'debug_toolbar.middleware.DebugToolbarMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'common.middleware.TimezoneMiddleware',
]

if TESTING or env('LOCAL'):  # use local cache for tests
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-fof',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'fof',
        }
    }


AUTHENTICATION_BACKENDS = (
    # Needed to login by username in Django admin, regardless of `allauth`
    "django.contrib.auth.backends.ModelBackend",

    # `allauth` specific authentication methods, such as login by e-mail
    "allauth.account.auth_backends.AuthenticationBackend",
)


ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = "optional"
ACCOUNT_EMAIL_SUBJECT_PREFIX = "Freedom of Flight Aerial: "
ACCOUNT_PASSWORD_MIN_LENGTH = 6
ACCOUNT_SIGNUP_FORM_CLASS = 'accounts.forms.SignupForm'
ACCOUNT_LOGIN_ON_PASSWORD_RESET = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = '/accounts/profile/'
ACCOUNT_PRESERVE_USERNAME_CASING=False  # All usernames lowercase
ACCOUNT_SIGNUP_EMAIL_ENTER_TWICE=True

ROOT_URLCONF = 'freedom_of_flight.urls'

ABSOLUTE_URL_OVERRIDES = {
    'auth.user': lambda o: "/users/%s/" % o.username,
}

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [root('templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'booking.context_processors.booking',
                'notices.context_processors.notices',
            ],
        },
    },
]

WSGI_APPLICATION = 'freedom_of_flight.wsgi.application'


# Database
# https://docs.djangoproject.com/en/3.0/ref/settings/#databases

DATABASES = {
    'default': env.db(),
    # Raises ImproperlyConfigured exception if DATABASE_URL not in os.environ
}

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Password validation
# https://docs.djangoproject.com/en/3.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/3.0/topics/i18n/

LANGUAGE_CODE = 'en-gb'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.0/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = (root('static'),)
STATIC_ROOT = root('collected-static')

MEDIA_URL = '/media/'
MEDIA_ROOT = root('media')

if env("LOCAL") or env("CI"):
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_USE_TLS = True
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_HOST_USER = 'freedomofflightbooking@gmail.com'
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', None)
if EMAIL_HOST_PASSWORD is None:  # pragma: no cover
    print("No email host password provided!")
EMAIL_PORT = 587
DEFAULT_FROM_EMAIL = 'freedomofflightbooking@gmail.com'
DEFAULT_STUDIO_EMAIL = 'freedomofflightaerial@gmail.com'
SEND_ALL_STUDIO_EMAILS = env("SEND_ALL_STUDIO_EMAILS")
SUPPORT_EMAIL = 'rebkwok@gmail.com'


# #####LOGGING######
LOG_FOLDER = env('LOG_FOLDER')
# Log to console for CI and Local
if env('CI') or env('LOCAL'):  # pragma: no cover
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                'format': '[%(levelname)s] - %(asctime)s - %(name)s - '
                          '%(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            }
        },
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'verbose'
            },
        },
        'loggers': {
            'django.request': {
                'handlers': ['console'],
                'level': 'INFO',
                'propagate': True,
            },
            'booking': {
                'handlers': ['console'],
                'level': 'INFO',
                'propogate': True,
            },
            'merchandise': {
                'handlers': ['console'],
                'level': 'INFO',
                'propogate': True,
            },
            'payments': {
                'handlers': ['console'],
                'level': 'INFO',
                'propogate': True,
            },
            'studioadmin': {
                'handlers': ['console'],
                'level': 'INFO',
                'propogate': True,
            },
            'timetable': {
                'handlers': ['console'],
                'level': 'INFO',
                'propogate': True,
            },
        },
    }
else:  # pragma: no cover
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                'format': '[%(levelname)s] - %(asctime)s - %(name)s - '
                          '%(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            }
        },
        'handlers': {
            'file_app': {
                'level': 'INFO',
                'class': 'logging.handlers.RotatingFileHandler',
                'filename': os.path.join(LOG_FOLDER, 'freedom_of_flight.log'),
                'maxBytes': 1024*1024*5,  # 5 MB
                'backupCount': 5,
                'formatter': 'verbose'
            },
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'verbose'
            },
            'mail_admins': {
                'level': 'ERROR',
                'class': 'django.utils.log.AdminEmailHandler',
                'include_html': True,
            },
        },
        'loggers': {
            '': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'propagate': True,
            },
            'django.request': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'propagate': True,
            },
            'accounts': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'level': 'INFO',
                'propagate': False,
            },
            'activitylog': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'level': 'INFO',
                'propagate': False,
            },
            'booking': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'level': 'INFO',
                'propagate': False,
            },
            'merchandise': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'level': 'INFO',
                'propagate': False,
            },
            'payments': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'level': 'INFO',
                'propagate': False,
            },
            'studioadmin': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'level': 'INFO',
                'propagate': False,
            },
            'timetable': {
                'handlers': ['console', 'file_app', 'mail_admins'],
                'level': 'INFO',
                'propagate': False,
            },
        },
    }

ADMINS = [("Becky Smith", SUPPORT_EMAIL)]


# Honor the 'X-Forwarded-Proto' header for request.is_secure()
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INTERNAL_IPS = ('127.0.0.1', '10.0.2.2')


# MAILCATCHER
if env('USE_MAILCATCHER'):  # pragma: no cover
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = '127.0.0.1'
    EMAIL_HOST_USER = ''
    EMAIL_HOST_PASSWORD = ''
    EMAIL_PORT = 1025
    EMAIL_USE_TLS = False


# Session cookies
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 604800  # 1 week

if env('LOCAL') or TESTING:
    SESSION_COOKIE_SECURE = False
else:  # pragma: no cover
    SESSION_COOKIE_SECURE = True


def show_toolbar(request):  # pragma: no cover
    return env('SHOW_DEBUG_TOOLBAR')


# With Django 1.11, the TemplatesPanel in the debug toolbar makes everything
# excessively slow
# See https://github.com/jazzband/django-debug-toolbar/issues/910
DEBUG_TOOLBAR_CONFIG = {
    'DISABLE_PANELS': {
        'debug_toolbar.panels.redirects.RedirectsPanel',
        'debug_toolbar.panels.templates.TemplatesPanel'
    },
    "SHOW_TOOLBAR_CALLBACK": show_toolbar,
}


# Increase this to deal with the bulk emails.  Currently just under 2000
# users, posts 2 fields per user
DATA_UPLOAD_MAX_NUMBER_FIELDS = 8000


S3_LOG_BACKUP_PATH = "s3://backups.polefitstarlet.co.uk/freedomofflight_activitylogs"
S3_LOG_BACKUP_ROOT_FILENAME = "freedomofflight_activity_logs_backup"

SITE_ID=1

EXTENSIONS_MAX_UNIQUE_QUERY_ATTEMPTS = 1000

# PAYPAL
PAYPAL_TEST=env("PAYPAL_TEST")
PAYPAL_IDENTITY_TOKEN=env("PAYPAL_IDENTITY_TOKEN")
DEFAULT_PAYPAL_EMAIL=env("DEFAULT_PAYPAL_EMAIL")
INVOICE_KEY=env("INVOICE_KEY")


# for dynamic disclaimer form
CRISPY_TEMPLATE_PACK = 'bootstrap4'
USE_CRISPY = True
DYNAMIC_FORMS_CUSTOM_JS = ""

# CKEDITOR
CKEDITOR_UPLOAD_PATH = "uploads/"
# CKEDITOR_IMAGE_BACKEND = 'pillow'
CKEDITOR_CONFIGS = {
    # 'default': {
    #     'toolbar': [
    #      ['Source', '-', 'Bold', 'Italic', 'Underline',
    #       'TextColor', 'BGColor'],
    #      ['NumberedList', 'BulletedList', '-', 'Outdent', 'Indent', '-',
    #       'JustifyLeft', 'JustifyCenter', 'JustifyRight', '-',
    #       'Table', 'HorizontalRule', 'Smiley', 'SpecialChar'],
    #      ['Format', 'Font', 'FontSize', 'Link']
    #     ],
    #     'width': 350,
    # },
    'default': {
        'toolbar': [
            ['Format', 'Bold', 'Italic', 'Underline', 'FontSize', 'Link', 'BulletedList', 'NumberedList']
        ],
        # 'width': '100%',
    },
}
CKEDITOR_JQUERY_URL = '//code.jquery.com/jquery-3.5.1.min.js'


# STRIPE
CHECKOUT_METHOD = env("CHECKOUT_METHOD")
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY")
STRIPE_CONNECT_CLIENT_ID = env("STRIPE_CONNECT_CLIENT_ID")
STRIPE_ENDPOINT_SECRET = env("STRIPE_ENDPOINT_SECRET")

MERCHANDISE_CART_TIMEOUT_MINUTES = env("MERCHANDISE_CART_TIMEOUT_MINUTES")
CART_TIMEOUT_MINUTES = env("CART_TIMEOUT_MINUTES")
