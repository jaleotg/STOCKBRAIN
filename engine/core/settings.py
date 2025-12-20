from pathlib import Path

# ------------------------------------------
# BASE PATHS
# ------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
# BASE_DIR = ~/STOCKBRAIN/engine

SECRET_KEY = "dev-secret-key-change-in-production"
DEBUG = True

ALLOWED_HOSTS = [
    "192.168.0.200", #lokal Hydrotec LAN
    "localhost",
    "127.0.0.1",
    "100.120.14.89", #tailscale kmoid
    "100.120.120.120", #tailscale raspberry
    "192.168.0.134", #lokal LAN Raspberry
]

# ------------------------------------------
# CSRF
# ------------------------------------------
# Trust the same hosts for CSRF (esp. for admin POST logout)
CSRF_TRUSTED_ORIGINS = [
    "http://192.168.0.200",
    "http://192.168.0.200:8000",
    "http://localhost",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:8000",
    "http://100.120.14.89",
    "http://100.120.14.89:8000",
    "https://100.120.14.89",
]

# ------------------------------------------
# INSTALLED APPS
# ------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "inventory",
    "worklog",
    "datatools",
    "config",
    "lifemotivation",
]


# ------------------------------------------
# MIDDLEWARE
# ------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ------------------------------------------
# URL CONFIG
# ------------------------------------------

ROOT_URLCONF = "core.urls"


# ------------------------------------------
# TEMPLATES
# ------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            BASE_DIR / "templates"   # <- /home/leo/STOCKBRAIN/engine/templates
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "inventory.context_processors.user_flags",
            ],
        },
    },
]


# ------------------------------------------
# WSGI
# ------------------------------------------

WSGI_APPLICATION = "core.wsgi.application"


# ------------------------------------------
# DATABASE 
# ------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'stockbrain_db',
        'USER': 'leo_admin',
        'PASSWORD': 'Hydrotek,./',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}



# ------------------------------------------
# AUTH & PASSWORDS
# ------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# ------------------------------------------
# LANGUAGE & TIMEZONE
# ------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kuwait"
USE_I18N = True
USE_TZ = True

# ------------------------------------------
# Authentication redirects
# ------------------------------------------

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
# Admin logout (Django admin) powinien wracać na stronę logowania admina.
LOGOUT_REDIRECT_URL = "/admin/login/"

# ------------------------------------------
# STATIC FILES
# ------------------------------------------

STATIC_URL = "static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",     # engine/static/
]

# Root-level assets like favicons and manifest.
PUBLIC_ROOT = BASE_DIR / "public"

# Media uploads (docx exports, etc.)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ------------------------------------------
# DEFAULT PRIMARY KEY
# ------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
