import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, '1' if default else '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name: str, default: str = '') -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'dev-secret-key')
DEBUG = env_bool('DJANGO_DEBUG', True)
ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,growlee.fr,www.growlee.fr')
APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:8000' if DEBUG else 'https://growlee.fr').rstrip('/')
CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS', 'https://growlee.fr,https://www.growlee.fr')
for host in ALLOWED_HOSTS:
    if host in {'*', 'localhost', '127.0.0.1'} or host.startswith('.'):
        continue
    origin = f'https://{host}'
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)
if APP_BASE_URL.startswith(('http://', 'https://')) and APP_BASE_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(APP_BASE_URL)
GROWLEE_PAYMENT_LINK_STARTER = os.getenv('GROWLEE_PAYMENT_LINK_STARTER', '').strip()
GROWLEE_PAYMENT_LINK_PRO = os.getenv('GROWLEE_PAYMENT_LINK_PRO', '').strip()
GROWLEE_PAYMENT_LINK_PREMIUM = os.getenv('GROWLEE_PAYMENT_LINK_PREMIUM', '').strip()
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'Growlee <noreply@growlee.local>')
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587') or 587)
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env_bool('EMAIL_USE_TLS', True)
EMAIL_USE_SSL = env_bool('EMAIL_USE_SSL', False)
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
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}
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
SILENCED_SYSTEM_CHECKS = env_list(
    'DJANGO_SILENCED_SYSTEM_CHECKS',
    '' if DEBUG else 'security.W019,security.W021',
)

# Production / reverse proxy HTTPS.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', not DEBUG)
SESSION_COOKIE_SECURE = env_bool('DJANGO_SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = env_bool('DJANGO_CSRF_COOKIE_SECURE', not DEBUG)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
SECURE_HSTS_SECONDS = int(os.getenv('DJANGO_SECURE_HSTS_SECONDS', '31536000' if not DEBUG else '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool('DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS', not DEBUG)
SECURE_HSTS_PRELOAD = env_bool('DJANGO_SECURE_HSTS_PRELOAD', False)
