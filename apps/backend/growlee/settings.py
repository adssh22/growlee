import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, '1' if default else '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(name: str, default: str = '') -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


DEBUG = env_bool('DJANGO_DEBUG', True)
_SECRET_KEY_ENV = os.getenv('DJANGO_SECRET_KEY', '').strip()
if not DEBUG and (not _SECRET_KEY_ENV or _SECRET_KEY_ENV == 'dev-secret-key'):
    raise RuntimeError('DJANGO_SECRET_KEY must be set to a strong non-default value when DJANGO_DEBUG=0.')
SECRET_KEY = _SECRET_KEY_ENV or 'dev-secret-key'
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

def postgres_config_from_env(prefix: str = 'POSTGRES', url_env: str = 'DATABASE_URL') -> dict:
    """Build a cloud-friendly PostgreSQL DATABASES entry.

    Priority:
    1. DATABASE_URL / READ_REPLICA_DATABASE_URL style value for managed cloud DBs.
    2. POSTGRES_* variables for local Docker / VPS deployments.

    Supported URL example:
    postgresql://user:password@host:5432/dbname?sslmode=require
    """
    database_url = os.getenv(url_env, '').strip()
    conn_max_age = int(os.getenv(f'{prefix}_CONN_MAX_AGE', os.getenv('DB_CONN_MAX_AGE', '60')) or 60)
    conn_health_checks = env_bool(f'{prefix}_CONN_HEALTH_CHECKS', env_bool('DB_CONN_HEALTH_CHECKS', True))

    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme not in {'postgres', 'postgresql'}:
            raise RuntimeError(f'{url_env} must use postgres:// or postgresql://')
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        options = {}
        sslmode = query.pop('sslmode', os.getenv(f'{prefix}_SSLMODE', os.getenv('POSTGRES_SSLMODE', '')).strip())
        if sslmode:
            options['sslmode'] = sslmode
        config = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': unquote((parsed.path or '/').lstrip('/')),
            'USER': unquote(parsed.username or ''),
            'PASSWORD': unquote(parsed.password or ''),
            'HOST': parsed.hostname or '',
            'PORT': str(parsed.port or query.pop('port', '5432')),
            'CONN_MAX_AGE': conn_max_age,
            'CONN_HEALTH_CHECKS': conn_health_checks,
        }
        if options:
            config['OPTIONS'] = options
        return config

    options = {}
    sslmode = os.getenv(f'{prefix}_SSLMODE', os.getenv('POSTGRES_SSLMODE', '')).strip()
    if sslmode:
        options['sslmode'] = sslmode
    config = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv(f'{prefix}_DB', os.getenv('POSTGRES_DB', 'growlee')),
        'USER': os.getenv(f'{prefix}_USER', os.getenv('POSTGRES_USER', 'growlee')),
        'PASSWORD': os.getenv(f'{prefix}_PASSWORD', os.getenv('POSTGRES_PASSWORD', 'growlee')),
        'HOST': os.getenv(f'{prefix}_HOST', os.getenv('POSTGRES_HOST', 'db')),
        'PORT': os.getenv(f'{prefix}_PORT', os.getenv('POSTGRES_PORT', '5432')),
        'CONN_MAX_AGE': conn_max_age,
        'CONN_HEALTH_CHECKS': conn_health_checks,
    }
    if options:
        config['OPTIONS'] = options
    return config


DATABASES = {'default': postgres_config_from_env()}
READ_REPLICA_DATABASE_URL = os.getenv('READ_REPLICA_DATABASE_URL', '').strip()
if READ_REPLICA_DATABASE_URL:
    DATABASES['replica'] = postgres_config_from_env('READ_REPLICA_POSTGRES', 'READ_REPLICA_DATABASE_URL')


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
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
