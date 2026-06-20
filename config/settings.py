"""
Django settings for Roma ERP.

This file supports BOTH local development (SQLite, DEBUG=True) AND production
(PostgreSQL, DEBUG=False, HTTPS) via environment variables.  See `.env.example`
in the project root for the full list of supported env vars.

Defaults are dev-friendly so `python manage.py runserver` still works as before.
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_bool(key, default=False):
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(key, default=()):
    val = os.environ.get(key)
    if not val:
        return list(default)
    return [item.strip() for item in val.split(',') if item.strip()]


# ---------------- Core security settings ----------------

SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-cto2#q^h7$rhj31(x$#mj2ps$_=zo*3=td9*nv3u)co1)#=7%x',
)

DEBUG = _env_bool('DJANGO_DEBUG', default=True)

ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS', default=['*'])

CSRF_TRUSTED_ORIGINS = _env_list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[])

# في الإنتاج (DEBUG=False) لازم المفتاح السري والمضيفين يكونوا متظبطين صح —
# نفشل بصوت عالي بدل ما نشتغل بقيمة افتراضية معروفة/غير آمنة.
if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured
    if SECRET_KEY.startswith('django-insecure-'):
        raise ImproperlyConfigured(
            'لازم تحدّد DJANGO_SECRET_KEY في الإنتاج (المفتاح الافتراضي غير آمن).')
    if not ALLOWED_HOSTS or ALLOWED_HOSTS == ['*']:
        raise ImproperlyConfigured(
            'لازم تحدّد DJANGO_ALLOWED_HOSTS صراحةً في الإنتاج (مش «*»).')


# ---------------- Apps + middleware ----------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'inventory',
    'sales',
    'manufacturing',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # WhiteNoise serves static files in production without a separate server.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
            # Auto-load `money` filter in every template (no need for {% load %})
            'builtins': ['core.templatetags.money_filters'],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# ---------------- Database ----------------
# DATABASE_URL takes precedence (e.g. postgres://user:pass@host:5432/db).
# Falls back to SQLite for local dev.

DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR / "db.sqlite3"}',
        conn_max_age=600,
        conn_health_checks=True,
    ),
}


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------------- i18n + l10n ----------------

LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Africa/Cairo'
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ('ar', 'العربية'),
    ('en', 'English'),
]

# Number formatting — Western digits, comma thousands + dot decimal (e.g. 5,500.00).
# The settings below are overridden by the bundled 'ar' locale, so we also ship a
# custom format module (config/formats/ar/) and point FORMAT_MODULE_PATH at it.
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = ','
NUMBER_GROUPING = 3
DECIMAL_SEPARATOR = '.'
FORMAT_MODULE_PATH = ['config.formats']


# ---------------- Static + media ----------------

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

# Compressed + cached static files in production via WhiteNoise.
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {
        'BACKEND': (
            'whitenoise.storage.CompressedManifestStaticFilesStorage'
            if not DEBUG
            else 'django.contrib.staticfiles.storage.StaticFilesStorage'
        )
    },
}

MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_REDIRECT_URL = '/admin/'
LOGIN_URL = '/admin/login/'


# ---------------- Production security toggles ----------------
# Applied automatically when DEBUG=False (i.e. on the server).

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = _env_bool('DJANGO_SECURE_SSL_REDIRECT', default=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_SECURE_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    X_FRAME_OPTIONS = 'DENY'
