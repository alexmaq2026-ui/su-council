"""
Django Settings - University Council Management System
"""
import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

if os.path.exists(BASE_DIR / '.env'):
    load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-fallback-key-change-this')
DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*').split(',')
if '*' in ALLOWED_HOSTS or not os.getenv('ALLOWED_HOSTS'):
    ALLOWED_HOSTS = ['*']

CSRF_TRUSTED_ORIGINS = [
    'https://*.onrender.com',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

# ── Applications ──────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'crispy_forms',
    'crispy_bootstrap5',
    # Local apps
    'accounts',
    'council',
    'search_engine',
    'ai_assistant',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'council.middleware.SessionLifecycleGuardMiddleware',
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
                'council.context_processors.live_session_context',
                'council.context_processors.isolation_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ── Isolation Mode & Dynamic Air-Gap Controller ───────────────────────────────
from config.isolation import is_isolated, get_isolation_status

# ── Database ──────────────────────────────────────────────────────────────────
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES['cloud'] = dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    DATABASES['cloud']['DISABLE_SERVER_SIDE_CURSORS'] = True
    DATABASES['cloud']['CONN_HEALTH_CHECKS'] = False

    # Strict Isolation Logic:
    # When ISOLATED (default), 'default' database is ALWAYS local SQLite.
    # Only if isolation is explicitly switched to CONNECTED by Super Admin will 'default' use the cloud database.
    if not is_isolated():
        DATABASES['default'] = DATABASES['cloud']


# ── In-Memory Caching (Optimizes repetitive live session polling & queries) ───
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'council-locmem-cache',
    }
}

# ── Auth ──────────────────────────────────────────────────────────────────────
AUTH_USER_MODEL = 'accounts.User'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ── Internationalization ──────────────────────────────────────────────────────
LANGUAGE_CODE = 'ar'
TIME_ZONE = 'Asia/Riyadh'
USE_I18N = True
USE_TZ = True

# ── Static & Media ────────────────────────────────────────────────────────────
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
    WHITENOISE_MANIFEST_STRICT = False
    WHITENOISE_USE_FINDERS = True

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── Cloud Storage (Supabase Media Storage) ──────────────────────────────────
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://hhqrohrclfekmjqhlaet.supabase.co').rstrip('/')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', 'sb_publishable_4cBv9I9tNFWSaTYbLxs3fA_bGBHifXz')
SUPABASE_STORAGE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'council-media')

# If in isolated mode, FORCE local FileSystemStorage; only use Supabase if connected
if not is_isolated() and SUPABASE_URL and SUPABASE_KEY:
    DEFAULT_STORAGE_BACKEND = 'config.storage.SupabaseMediaStorage'
else:
    DEFAULT_STORAGE_BACKEND = 'django.core.files.storage.FileSystemStorage'


STORAGES = {
    'default': {
        'BACKEND': DEFAULT_STORAGE_BACKEND,
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage' if not DEBUG else 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}

# ── Crispy Forms ──────────────────────────────────────────────────────────────
CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

# ── AI Settings (Phase 3) ─────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── File Upload Limits ────────────────────────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800   # 50 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800   # 50 MB

# ── Session ───────────────────────────────────────────────────────────────────
SESSION_COOKIE_AGE = 86400 * 7  # 7 days
SESSION_SAVE_EVERY_REQUEST = False
