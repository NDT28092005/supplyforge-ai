import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured
from config.logging_config import build_logging_config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Determine environment (development | staging | production)
APP_ENV = os.getenv('APP_ENV', os.getenv('ENVIRONMENT', 'development')).lower()
IS_DEPLOYED = APP_ENV in {'staging', 'production'}
IS_TEST_RUN = 'test' in sys.argv

# Load environment variables (.env.<APP_ENV>, .env, root .env)
env_file_specific = BASE_DIR / f'.env.{APP_ENV}'
if env_file_specific.exists():
    load_dotenv(env_file_specific)
elif (BASE_DIR.parent / f'.env.{APP_ENV}').exists():
    load_dotenv(BASE_DIR.parent / f'.env.{APP_ENV}')

load_dotenv(BASE_DIR / '.env')
load_dotenv(BASE_DIR.parent / '.env')

# App Versioning
VERSION_FILE = BASE_DIR.parent / 'VERSION'
if VERSION_FILE.exists():
    APP_VERSION = VERSION_FILE.read_text().strip()
else:
    APP_VERSION = '1.0.0'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', '').strip()
if IS_DEPLOYED:
    if not SECRET_KEY:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY is required for staging/production.')
    if len(SECRET_KEY) < 50:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must contain at least 50 characters.')
else:
    SECRET_KEY = SECRET_KEY or 'django-insecure-dev-only-key-not-for-production'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DJANGO_DEBUG', 'True' if APP_ENV == 'development' else 'False').lower() in {
    '1', 'true', 'yes'
}
if IS_DEPLOYED and DEBUG:
    raise ImproperlyConfigured('DJANGO_DEBUG must be false for staging/production.')

_configured_hosts = [
    host.strip() for host in os.getenv('ALLOWED_HOSTS', '').split(',') if host.strip()
]
if IS_DEPLOYED:
    if not _configured_hosts or '*' in _configured_hosts:
        raise ImproperlyConfigured('ALLOWED_HOSTS must be an explicit allowlist.')
    ALLOWED_HOSTS = _configured_hosts
else:
    ALLOWED_HOSTS = _configured_hosts or [
        'localhost',
        '127.0.0.1',
        '0.0.0.0',
        'host.docker.internal',
    ]

# Application definition
INSTALLED_APPS = [
    'django_prometheus',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'supplyforge.apps.SupplyforgeConfig',
]

MIDDLEWARE = [
    'django_prometheus.middleware.PrometheusBeforeMiddleware',
    'supplyforge.middleware.RequestObservabilityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.gzip.GZipMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'supplyforge.middleware.SecurityHeadersMiddleware',
    # Rate-limit before JWT parsing so malformed/invalid bearer floods are
    # throttled even when tenant authentication rejects the request.
    'supplyforge.middleware.APIRateLimiterMiddleware',
    'supplyforge.middleware.TenantIsolationMiddleware',
    'django_prometheus.middleware.PrometheusAfterMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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

WSGI_APPLICATION = 'config.wsgi.application'

# Database
# Using PyMySQL as driver (installed in backend/supplyforge_ai/__init__.py)
MYSQL_DB = os.getenv('MYSQL_DATABASE', 'supplyforge')
MYSQL_USER = os.getenv('MYSQL_USER', 'supplyforge')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '').strip()
if IS_DEPLOYED:
    if not MYSQL_PASSWORD:
        raise ImproperlyConfigured('MYSQL_PASSWORD is required for staging/production.')
    if MYSQL_PASSWORD.lower() in {'change-me', 'rootpassword', 'admin', 'supplyforge'}:
        raise ImproperlyConfigured('MYSQL_PASSWORD must not use a development default.')
else:
    MYSQL_PASSWORD = MYSQL_PASSWORD or 'change-me'
MYSQL_HOST = os.getenv('MYSQL_HOST', '127.0.0.1')
if MYSQL_HOST == 'localhost':
    MYSQL_HOST = '127.0.0.1'
MYSQL_PORT = os.getenv('MYSQL_PORT', '3306')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': MYSQL_DB,
        'USER': MYSQL_USER,
        'PASSWORD': MYSQL_PASSWORD,
        'HOST': MYSQL_HOST,
        'PORT': MYSQL_PORT,
        # Django's persistent connections are the application-side pool. A
        # real proxy (for example ProxySQL) can be put in front for larger
        # deployments without changing application code.
        'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '600' if IS_DEPLOYED else '0')),
        'CONN_HEALTH_CHECKS': True,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'connect_timeout': 10,
            'read_timeout': 30,
            'write_timeout': 30,
        },
    }
}

if IS_TEST_RUN or os.getenv('USE_SQLITE') == '1':
    if IS_DEPLOYED:
        raise ImproperlyConfigured('SQLite is not allowed in staging/production.')
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        # Keep test data in memory. Local development may opt into a
        # persistent SQLite path explicitly with SQLITE_PATH.
        'NAME': ':memory:' if IS_TEST_RUN else os.getenv(
            'SQLITE_PATH',
            str(BASE_DIR / 'db.sqlite3'),
        ),
        'CONN_MAX_AGE': 0,
    }

DB_REPLICA_ENABLED = os.getenv('DB_REPLICA_ENABLED', 'false').lower() in {
    '1', 'true', 'yes'
}
if DB_REPLICA_ENABLED:
    DB_REPLICA_HOST = os.getenv('DB_REPLICA_HOST', '').strip()
    if IS_DEPLOYED and not DB_REPLICA_HOST:
        raise ImproperlyConfigured(
            'DB_REPLICA_HOST is required when DB_REPLICA_ENABLED is true.'
        )
    if DB_REPLICA_HOST and not IS_TEST_RUN:
        DATABASES['replica'] = {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': os.getenv('DB_REPLICA_DATABASE', MYSQL_DB),
            'USER': os.getenv('DB_REPLICA_USER', MYSQL_USER),
            'PASSWORD': os.getenv('DB_REPLICA_PASSWORD', MYSQL_PASSWORD),
            'HOST': DB_REPLICA_HOST,
            'PORT': os.getenv('DB_REPLICA_PORT', MYSQL_PORT),
            'CONN_MAX_AGE': int(os.getenv('DB_REPLICA_CONN_MAX_AGE', '600')),
            'CONN_HEALTH_CHECKS': True,
            'OPTIONS': {
                'charset': 'utf8mb4',
                'connect_timeout': 10,
                'read_timeout': 30,
                'write_timeout': 30,
            },
        }

DATABASE_ROUTERS = ['supplyforge.db_router.ReadReplicaRouter']

# Password validation
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
LANGUAGE_CODE = 'vi'
TIME_ZONE = 'Asia/Ho_Chi_Minh'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS Config
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        'CORS_ALLOWED_ORIGINS',
        '' if IS_DEPLOYED else 'http://localhost:3000',
    ).split(',')
    if origin.strip()
]
if IS_DEPLOYED and not CORS_ALLOWED_ORIGINS:
    raise ImproperlyConfigured(
        'CORS_ALLOWED_ORIGINS is required for staging/production.'
    )
CORS_ALLOW_CREDENTIALS = False

# Custom SupplyForge settings (mapped from application.yml)
SUPPLYFORGE = {
    'finance': {
        'storage_cost_yearly_rate': 0.25,
        'depreciation_cost_yearly_rate': 0.10,
        'tax_rate': 0.20,
        'marketing_cost_rate': 0.08,
        'high_value_threshold': 10000000.0,
        'mid_value_threshold': 1000000.0,
    },
    'aging': {
        'healthy_max_days': 30,
        'watchlist_max_days': 60,
        'slow_moving_max_days': 90,
    },
    'gemini': {
        'enabled': os.getenv('GEMINI_ENABLED', 'false').lower() in {'1', 'true', 'yes'},
        'api_key': os.getenv('GEMINI_API_KEY', ''),
        'model': os.getenv('GEMINI_MODEL', 'gemini-1.5-flash'),
        'base_url': os.getenv('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com'),
    },
    'google_oauth': {
        'enabled': os.getenv('GOOGLE_OAUTH_ENABLED', 'false').lower() in {'1', 'true', 'yes'},
        'client_id': os.getenv('GOOGLE_CLIENT_ID', '').strip(),
        'client_secret': os.getenv('GOOGLE_CLIENT_SECRET', ''),
    },
    'odoo': {
        'enabled': os.getenv('ODOO_ENABLED', 'false').lower() in {'1', 'true', 'yes'},
        'url': os.getenv(
            'ODOO_URL',
            'http://localhost:8069' if not IS_DEPLOYED else '',
        ),
        'db': os.getenv('ODOO_DB', ''),
        'username': os.getenv('ODOO_USERNAME', ''),
        'password': os.getenv('ODOO_PASSWORD', ''),
    },
    'shopee': {
        'partner_id': os.getenv('SHOPEE_PARTNER_ID', '0'),
        'partner_key': os.getenv('SHOPEE_PARTNER_KEY', ''),
        'api_host': os.getenv('SHOPEE_API_HOST', 'https://partner.shopeemobile.com'),
        'redirect_url': os.getenv('SHOPEE_REDIRECT_URL', 'http://localhost:8080/api/v1/shopee/oauth/callback'),
    },
}

if IS_DEPLOYED and SUPPLYFORGE['odoo']['enabled']:
    for _name in ('ODOO_URL', 'ODOO_DB', 'ODOO_USERNAME', 'ODOO_PASSWORD'):
        if not os.getenv(_name, '').strip():
            raise ImproperlyConfigured(
                f'{_name} is required when ODOO_ENABLED is true.'
            )

if IS_DEPLOYED and SUPPLYFORGE['gemini']['enabled'] and not SUPPLYFORGE['gemini']['api_key'].strip():
    raise ImproperlyConfigured(
        'GEMINI_API_KEY is required when GEMINI_ENABLED is true.'
    )

if IS_DEPLOYED and SUPPLYFORGE['google_oauth']['enabled']:
    for _name in ('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'):
        if not os.getenv(_name, '').strip():
            raise ImproperlyConfigured(
                f'{_name} is required when GOOGLE_OAUTH_ENABLED is true.'
            )

# Security headers. HTTPS redirect is safe only when the trusted proxy forwards
# X-Forwarded-Proto correctly.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
TRUSTED_PROXY_IPS = tuple(
    value.strip()
    for value in os.getenv('TRUSTED_PROXY_IPS', '').split(',')
    if value.strip()
)
CONTENT_SECURITY_POLICY = os.getenv(
    'CONTENT_SECURITY_POLICY',
    "default-src 'self'; base-uri 'self'; object-src 'none'; "
    "frame-ancestors 'none'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "font-src 'self' data:; connect-src 'self' https: wss:; "
    "form-action 'self'",
)
if APP_ENV == 'production':
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# Celery & Redis Configuration
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = os.getenv('REDIS_PORT', '6379')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

REDIS_CACHE_URL = os.getenv('REDIS_CACHE_URL', f'redis://{REDIS_HOST}:{REDIS_PORT}/1')
# A local UI should remain usable without separately starting Redis. Production
# retains Redis unless it is explicitly configured otherwise.
USE_LOCMEM_CACHE = os.getenv(
    'USE_LOCMEM_CACHE',
    '1' if not IS_DEPLOYED else '0',
).lower() in {'1', 'true', 'yes'}

if 'test' in os.sys.argv or USE_LOCMEM_CACHE:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test-cache',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_CACHE_URL,
            'TIMEOUT': 86400,  # 24 hours default TTL
        }
    }

LOCAL_SQLITE_DEVELOPMENT = APP_ENV == 'development' and os.getenv('USE_SQLITE') == '1'
CELERY_EAGER_REQUESTED = os.getenv('CELERY_TASK_ALWAYS_EAGER', '').lower() in {
    '1', 'true', 'yes',
}

# SQLite is the supported single-process development setup. Execute background
# tasks eagerly there so imports can materialize their dashboard read models
# without a separately managed Redis/Celery stack. Deployed environments keep
# the broker-backed worker path.
if IS_TEST_RUN or LOCAL_SQLITE_DEVELOPMENT or CELERY_EAGER_REQUESTED:
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
    CELERY_RESULT_BACKEND = 'cache+memory://'
    import logging
    logging.getLogger('django.request').setLevel(logging.CRITICAL)

# Python 3.14 + Django 5 test runner template context copy compatibility fix
try:
    from django.template.context import Context
    def _fixed_context_copy(self):
        dup = Context()
        dup.dicts = [d.copy() if hasattr(d, 'copy') else d for d in self.dicts]
        return dup
    Context.__copy__ = _fixed_context_copy
except Exception:
    pass


# Sentry Configuration (Feedback Sensors)
SENTRY_DSN = os.getenv('SENTRY_DSN', '')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=1.0,
        send_default_pii=True
    )

# ── Ingestion File Storage (Module 01) ─────────────────────────────
INGESTION_UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads', 'ingestion')
INGESTION_MAX_FILE_SIZE_MB = int(os.getenv('INGESTION_MAX_FILE_SIZE_MB', '500'))
INGESTION_CHUNK_ROW_SIZE = int(os.getenv('INGESTION_CHUNK_ROW_SIZE', '20000'))
INGESTION_MAX_REPORTED_ERRORS = int(os.getenv('INGESTION_MAX_REPORTED_ERRORS', '1000'))
INGESTION_ARCHIVE_SNAPSHOT_ROW_LIMIT = int(os.getenv('INGESTION_ARCHIVE_SNAPSHOT_ROW_LIMIT', '1000'))
INGESTION_MAX_ROWS = int(os.getenv('INGESTION_MAX_ROWS', '10000000'))
MLOPS_FEATURE_SNAPSHOT_BATCH_SIZE = int(
    os.getenv('MLOPS_FEATURE_SNAPSHOT_BATCH_SIZE', '1000')
)
MLOPS_LABEL_OBSERVATION_DAYS = int(os.getenv('MLOPS_LABEL_OBSERVATION_DAYS', '90'))
MLOPS_MIN_HIGH_RISK_RECALL = float(os.getenv('MLOPS_MIN_HIGH_RISK_RECALL', '0.80'))
MLOPS_MIN_MACRO_F1 = float(os.getenv('MLOPS_MIN_MACRO_F1', '0.60'))
MLOPS_MAX_ECE = float(os.getenv('MLOPS_MAX_ECE', '0.12'))
MLOPS_MAX_MISSING_RATE = float(os.getenv('MLOPS_MAX_MISSING_RATE', '0.05'))
MLOPS_MAX_METRIC_REGRESSION = float(os.getenv('MLOPS_MAX_METRIC_REGRESSION', '0.03'))
if INGESTION_CHUNK_ROW_SIZE < 100:
    raise ImproperlyConfigured('INGESTION_CHUNK_ROW_SIZE must be at least 100.')
if INGESTION_MAX_REPORTED_ERRORS < 1:
    raise ImproperlyConfigured('INGESTION_MAX_REPORTED_ERRORS must be positive.')
if INGESTION_ARCHIVE_SNAPSHOT_ROW_LIMIT < 1:
    raise ImproperlyConfigured('INGESTION_ARCHIVE_SNAPSHOT_ROW_LIMIT must be positive.')
if INGESTION_MAX_ROWS < 1:
    raise ImproperlyConfigured('INGESTION_MAX_ROWS must be positive.')
if MLOPS_FEATURE_SNAPSHOT_BATCH_SIZE < 1:
    raise ImproperlyConfigured('MLOPS_FEATURE_SNAPSHOT_BATCH_SIZE must be positive.')
if MLOPS_LABEL_OBSERVATION_DAYS < 0:
    raise ImproperlyConfigured('MLOPS_LABEL_OBSERVATION_DAYS cannot be negative.')
if not all(0 <= value <= 1 for value in (
    MLOPS_MIN_HIGH_RISK_RECALL,
    MLOPS_MIN_MACRO_F1,
    MLOPS_MAX_ECE,
    MLOPS_MAX_MISSING_RATE,
    MLOPS_MAX_METRIC_REGRESSION,
)):
    raise ImproperlyConfigured('MLOps quality-gate thresholds must be between 0 and 1.')
STORAGE_BACKEND = os.getenv(
    'STORAGE_BACKEND',
    's3' if IS_DEPLOYED else 'local',
).lower()
if STORAGE_BACKEND not in {'local', 's3'}:
    raise ImproperlyConfigured('STORAGE_BACKEND must be either local or s3.')
if IS_DEPLOYED and STORAGE_BACKEND != 's3':
    raise ImproperlyConfigured(
        'STORAGE_BACKEND=s3 is required in staging/production.'
    )

S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL', '').strip()
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', '').strip()
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY', '').strip()
S3_BUCKET = os.getenv('S3_BUCKET', '').strip()
S3_LAKE_BUCKET = os.getenv('S3_LAKE_BUCKET', '').strip()
S3_REGION = os.getenv('S3_REGION', '').strip()
S3_AUTH_MODE = os.getenv('S3_AUTH_MODE', 'auto').strip().lower()
S3_MULTIPART_PART_SIZE_BYTES = int(
    os.getenv('S3_MULTIPART_PART_SIZE_BYTES', str(8 * 1024 * 1024))
)
S3_PRESIGNED_UPLOAD_TTL_SECONDS = int(
    os.getenv('S3_PRESIGNED_UPLOAD_TTL_SECONDS', '900')
)
SQS_INGESTION_QUEUE_URL = os.getenv('SQS_INGESTION_QUEUE_URL', '').strip()
if S3_AUTH_MODE not in {'auto', 'static'}:
    raise ImproperlyConfigured('S3_AUTH_MODE must be either auto or static.')
if S3_MULTIPART_PART_SIZE_BYTES < 5 * 1024 * 1024:
    raise ImproperlyConfigured(
        'S3_MULTIPART_PART_SIZE_BYTES must be at least 5 MiB.'
    )
if S3_MULTIPART_PART_SIZE_BYTES > 5 * 1024 * 1024 * 1024:
    raise ImproperlyConfigured(
        'S3_MULTIPART_PART_SIZE_BYTES must not exceed 5 GiB.'
    )
if not 60 <= S3_PRESIGNED_UPLOAD_TTL_SECONDS <= 3600:
    raise ImproperlyConfigured(
        'S3_PRESIGNED_UPLOAD_TTL_SECONDS must be between 60 and 3600.'
    )

if STORAGE_BACKEND == 's3':
    if bool(S3_ACCESS_KEY) != bool(S3_SECRET_KEY):
        raise ImproperlyConfigured(
            'S3_ACCESS_KEY and S3_SECRET_KEY must be configured together.'
        )
    if S3_AUTH_MODE == 'static' and not S3_ACCESS_KEY:
        raise ImproperlyConfigured(
            'S3_ACCESS_KEY and S3_SECRET_KEY are required when S3_AUTH_MODE=static.'
        )

if STORAGE_BACKEND == 's3' and IS_DEPLOYED:
    for _name, _value in (
        ('S3_BUCKET', S3_BUCKET),
        ('S3_LAKE_BUCKET', S3_LAKE_BUCKET),
        ('S3_REGION', S3_REGION),
    ):
        if not _value:
            raise ImproperlyConfigured(
                f'{_name} is required when STORAGE_BACKEND=s3.'
            )

# Increase Django's default data upload limit for large CSVs (500 MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = INGESTION_MAX_FILE_SIZE_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB — above this, Django uses temp file on disk

# Application rate limiting is enabled by default in deployed environments.
RATE_LIMIT_ENABLED = os.getenv(
    'RATE_LIMIT_ENABLED',
    'true' if IS_DEPLOYED else 'false',
).lower() in {'1', 'true', 'yes'}
RATE_LIMIT_FAIL_CLOSED = os.getenv(
    'RATE_LIMIT_FAIL_CLOSED',
    'true' if IS_DEPLOYED else 'false',
).lower() in {'1', 'true', 'yes'}
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv('RATE_LIMIT_WINDOW_SECONDS', '60'))
RATE_LIMIT_API_REQUESTS = int(os.getenv('RATE_LIMIT_API_REQUESTS', '120'))
RATE_LIMIT_AUTH_REQUESTS = int(os.getenv('RATE_LIMIT_AUTH_REQUESTS', '20'))
RATE_LIMIT_UPLOAD_REQUESTS = int(os.getenv('RATE_LIMIT_UPLOAD_REQUESTS', '10'))

# Logs are machine-readable in deployed environments so API traces can be
# correlated by X-Request-ID without recording request payloads or PII.
LOG_FORMAT = os.getenv('LOG_FORMAT', 'json').lower()
if LOG_FORMAT not in {'json', 'text'}:
    raise ImproperlyConfigured('LOG_FORMAT must be either json or text.')
LOGGING = build_logging_config(json_format=LOG_FORMAT == 'json')

# ── Email Delivery Configuration (SMTP & SaaS Mail Provider) ─────────
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '').strip()
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '').replace(' ', '').strip()
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'SupplyForge AI <ndaitung28092005@gmail.com>')
