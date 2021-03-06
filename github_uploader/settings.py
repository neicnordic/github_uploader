"""
Django settings for github_uploader project.

Generated by 'django-admin startproject' using Django 1.8.4.

For more information on this file, see
https://docs.djangoproject.com/en/1.8/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/1.8/ref/settings/
"""

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# local_settings.py is in a separate dir on the PYTHONPATH, away from prying eyes.
from local_settings import SECRET_KEY
from local_settings import DEBUG
from local_settings import DATABASES
from local_settings import STATIC_ROOT
from local_settings import ALLOWED_HOSTS
from local_settings import GITHUB_UPLOADERS
from local_settings import GITHUB_UPLOADER_CLIENT_ID
from local_settings import GITHUB_UPLOADER_CLIENT_SECRET
from local_settings import EXTRA_TEMPLATE_DIRS
from local_settings import STATICFILES_DIRS
from local_settings import STATIC_URL
from local_settings import MEDIA_ROOT
from local_settings import SESSION_COOKIE_SECURE

# Application definition

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'github_uploader'
)

MIDDLEWARE_CLASSES = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'github_uploader.middleware.ExceptionLogging',
)

AUTHENTICATION_BACKENDS = (
    'github_uploader.auth_backends.GitHubOrgMemberBackend',
)

ROOT_URLCONF = 'github_uploader.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': EXTRA_TEMPLATE_DIRS,
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'github_uploader.wsgi.application'


# Internationalization
# https://docs.djangoproject.com/en/1.8/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'CET'

USE_I18N = True

USE_L10N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/1.8/howto/static-files/

# Session management:
SESSION_COOKIE_AGE = 60 * 60 # Arbitrarily chosen to one hour idle time.

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '%(levelname)s %(asctime)s %(module)s %(message)s'
            },
        'simple': {
            'format': '%(levelname)s %(message)s'
            },
        },
    'handlers': {
        'null': {
            'level': 'DEBUG',
            'class': 'logging.NullHandler',
            },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose'
            },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
        }
    },
    'loggers': {
        'github_uploader': {
            'handlers': ['console', 'mail_admins'],
            'level': 'INFO',
        }
    }
}