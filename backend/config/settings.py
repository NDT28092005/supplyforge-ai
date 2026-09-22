import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR.parent / '.env')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-supplyforge-ai-mvp-secret-key-change-me')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['*']

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'supplyforge',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'supplyforge.middleware.TenantIsolationMiddleware',
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
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'change-me')
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
    }
}

if 'test' in os.sys.argv or os.getenv('USE_SQLITE') == '1':
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }

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
CORS_ALLOW_ALL_ORIGINS = True  # For MVP simplified connection
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in os.getenv('CORS_ALLOWED_ORIGINS', 'http://localhost:3000').split(',') if origin.strip()
]

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
        'api_key': os.getenv('GEMINI_API_KEY', ''),
        'model': os.getenv('GEMINI_MODEL', 'gemini-1.5-flash'),
        'base_url': os.getenv('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com'),
    },
    'google_oauth': {
        'client_id': os.getenv('GOOGLE_CLIENT_ID', '7581962747-uj20trqmtba57s3psahigngcopku3ub3.apps.googleusercontent.com'),
        'client_secret': os.getenv('GOOGLE_CLIENT_SECRET', ''),
    },
    'odoo': {
        'url': os.getenv('ODOO_URL', 'http://34.130.191.122/odoo'),
        'db': os.getenv('ODOO_DB', 'odoo'),
        'username': os.getenv('ODOO_USERNAME', 'admin'),
        'password': os.getenv('ODOO_PASSWORD', 'admin'),
    },
    'shopee': {
        'partner_id': os.getenv('SHOPEE_PARTNER_ID', '0'),
        'partner_key': os.getenv('SHOPEE_PARTNER_KEY', ''),
        'api_host': os.getenv('SHOPEE_API_HOST', 'https://partner.shopeemobile.com'),
        'redirect_url': os.getenv('SHOPEE_REDIRECT_URL', 'http://localhost:8080/api/v1/shopee/oauth/callback'),
    },
}

# Celery Configuration
REDIS_HOST = os.getenv('REDIS_HOST', '127.0.0.1')
REDIS_PORT = os.getenv('REDIS_PORT', '6379')
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE

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
INGESTION_MAX_FILE_SIZE_MB = 500

# Increase Django's default data upload limit for large CSVs (500 MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = INGESTION_MAX_FILE_SIZE_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024  # 10 MB — above this, Django uses temp file on disk
