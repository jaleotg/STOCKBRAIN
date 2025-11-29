from pathlib import Path

# ------------------------------------------
# BASE PATHS
# ------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
# BASE_DIR = ~/STOCKBRAIN/engine

SECRET_KEY = "dev-secret-key-change-in-production"
DEBUG = True

ALLOWED_HOSTS = []


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
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR.parent / "db" / "db.sqlite3",
        # BASE_DIR.parent = ~/STOCKBRAIN
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
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# ------------------------------------------
# STATIC FILES
# ------------------------------------------

STATIC_URL = "static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",     # engine/static/
]


# ------------------------------------------
# DEFAULT PRIMARY KEY
# ------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
