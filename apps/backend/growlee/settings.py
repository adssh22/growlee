import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-secret-key')
DEBUG = os.getenv('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = ['*']
APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://192.168.1.27:8000').rstrip('/')
GROWLEE_PAYMENT_LINK_STARTER = os.getenv('GROWLEE_PAYMENT_LINK_STARTER', '').strip()
GROWLEE_PAYMENT_LINK_PRO = os.getenv('GROWLEE_PAYMENT_LINK_PRO', '').strip()
GROWLEE_PAYMENT_LINK_PREMIUM = os.getenv('GROWLEE_PAYMENT_LINK_PREMIUM', '').strip()
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Growlee <noreply@growlee.local>')
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
SMS_BACKEND = os.getenv('SMS_BACKEND', 'console')
SMS_FROM = os.getenv('SMS_FROM', 'Growlee')
SMS_PROVIDER = os.getenv('SMS_PROVIDER', SMS_BACKEND).strip().lower()
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '').strip()
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '').strip()
TWILIO_FROM_NUMBER = os.getenv('TWILIO_FROM_NUMBER', SMS_FROM).strip()
BREVO_API_KEY = os.getenv('BREVO_API_KEY', '').strip()
BREVO_SMS_SENDER = os.getenv('BREVO_SMS_SENDER', SMS_FROM).strip()[:11]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.core',
    'apps.accounts',
    'apps.merchants',
    'apps.campaigns',
    'apps.rewards',
    'apps.customers',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'growlee.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'growlee.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB', 'growlee'),
        'USER': os.getenv('POSTGRES_USER', 'growlee'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'growlee'),
        'HOST': os.getenv('POSTGRES_HOST', 'db'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = 'fr-fr'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/admin/'
LOGOUT_REDIRECT_URL = '/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Wallet providers — remplis quand les comptes/certificats seront prêts.
APPLE_WALLET_PASS_TYPE_ID = os.getenv('APPLE_WALLET_PASS_TYPE_ID', '')
APPLE_WALLET_TEAM_ID = os.getenv('APPLE_WALLET_TEAM_ID', '')
APPLE_WALLET_CERT_PATH = os.getenv('APPLE_WALLET_CERT_PATH', '')
APPLE_WALLET_KEY_PATH = os.getenv('APPLE_WALLET_KEY_PATH', '')
APPLE_WALLET_WWDR_CERT_PATH = os.getenv('APPLE_WALLET_WWDR_CERT_PATH', '')
GOOGLE_WALLET_ISSUER_ID = os.getenv('GOOGLE_WALLET_ISSUER_ID', '')
GOOGLE_WALLET_SERVICE_ACCOUNT_PATH = os.getenv('GOOGLE_WALLET_SERVICE_ACCOUNT_PATH', '')

# Autorise les previews intégrées dans l'admin Growlee (même origine uniquement).
X_FRAME_OPTIONS = 'SAMEORIGIN'
