import os
from pathlib import Path
from urllib.parse import quote

from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parents[2]


def _secret(name: str, default: str = "") -> str:
    file_name = os.environ.get(f"{name}_FILE", "")
    if file_name:
        return Path(file_name).read_text(encoding="utf-8").strip()
    return os.environ.get(name, default)


SECRET_KEY = _secret("DJANGO_SECRET_KEY", "unsafe-development-only-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [host for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if host]
CSRF_TRUSTED_ORIGINS = [url for url in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if url]
TIME_ZONE = "Asia/Shanghai"
USE_TZ = True
LANGUAGE_CODE = "zh-hans"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "axes",
    "apps.accounts",
    "apps.sources",
    "apps.articles",
    "apps.platforms",
    "apps.audit",
    "apps.monitoring",
    "apps.reposts",
    "apps.reports",
    "apps.operations",
    "apps.core",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "repost_monitor"),
        "USER": os.environ.get("DB_USER", "repost_monitor"),
        "PASSWORD": _secret("DB_PASSWORD"),
        "HOST": os.environ.get("DB_HOST", "mysql"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }
}
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "文章转载监测系统 API",
    "VERSION": "1.0.0",
    "ENUM_NAME_OVERRIDES": {
        "ArticleStatusEnum": "apps.articles.models.ArticleStatus",
        "ImportStatusEnum": "apps.articles.models.ImportStatus",
        "PlatformStatusEnum": "apps.platforms.models.PlatformStatus",
        "BatchStatusEnum": "apps.monitoring.models.BatchStatus",
        "DetectionStatusEnum": "apps.monitoring.models.PlatformDetectionStatus",
        "DeliveryStatusEnum": "apps.reports.models.DeliveryStatus",
        "MaintenanceStatusEnum": "apps.operations.models.MaintenanceStatus",
    },
}
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
PRIVATE_UPLOAD_ROOT = Path(os.environ.get("PRIVATE_UPLOAD_ROOT", BASE_DIR / "private_uploads"))
MEDIA_ROOT = PRIVATE_UPLOAD_ROOT
FIELD_ENCRYPTION_KEY = _secret("FIELD_ENCRYPTION_KEY")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 28800
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 0.25
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
_redis_password = _secret("REDIS_PASSWORD")
_redis_auth = f":{quote(_redis_password, safe='')}@" if _redis_password else ""
REDIS_URL = os.environ.get("REDIS_URL", f"redis://{_redis_auth}redis:6379/0")
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", f"redis://{_redis_auth}redis:6379/1")
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = False
SEARCH_PROVIDER = os.environ.get("SEARCH_PROVIDER", "")
BRAVE_SEARCH_API_KEY = _secret("BRAVE_SEARCH_API_KEY")
TENCENTCLOUD_WSA_APIKEY = _secret("TENCENTCLOUD_WSA_APIKEY")
SEARCH_SIMILARITY_THRESHOLD = float(os.environ.get("SEARCH_SIMILARITY_THRESHOLD", "90"))
SEARCH_SHORT_TITLE_LENGTH = int(os.environ.get("SEARCH_SHORT_TITLE_LENGTH", "8"))
SEARCH_RESULT_LIMIT = int(os.environ.get("SEARCH_RESULT_LIMIT", "20"))
SEARCH_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("SEARCH_REQUEST_TIMEOUT_SECONDS", "15"))
SEARCH_MAX_RESPONSE_BYTES = int(os.environ.get("SEARCH_MAX_RESPONSE_BYTES", str(2 * 1024 * 1024)))
SEARCH_PUBLISHED_TIME_TOLERANCE_HOURS = int(os.environ.get("SEARCH_PUBLISHED_TIME_TOLERANCE_HOURS", "24"))
SEARCH_ERROR_BACKOFF_MINUTES = int(os.environ.get("SEARCH_ERROR_BACKOFF_MINUTES", "30"))
SEARCH_LOCK_TIMEOUT_SECONDS = int(os.environ.get("SEARCH_LOCK_TIMEOUT_SECONDS", "300"))
SEARCH_SCHEDULER_BATCH_SIZE = int(os.environ.get("SEARCH_SCHEDULER_BATCH_SIZE", "100"))
ARTICLE_MONITOR_DAYS = int(os.environ.get("ARTICLE_MONITOR_DAYS", "7"))
ARTICLE_RETENTION_DAYS = int(os.environ.get("ARTICLE_RETENTION_DAYS", "365"))
ARTICLE_SEARCH_SCHEDULE_MINUTES = tuple(
    int(value)
    for value in os.environ.get("ARTICLE_SEARCH_SCHEDULE_MINUTES", "0,15,30,60,120,240,480").split(",")
    if value.strip()
)
ARTICLE_SEARCH_REPEAT_MINUTES = int(os.environ.get("ARTICLE_SEARCH_REPEAT_MINUTES", "720"))
CELERY_TASK_DEFAULT_QUEUE = "http"
CELERY_TASK_ROUTES = {
    "apps.sources.tasks.search_article_reposts": {"queue": "search"},
    "apps.sources.tasks.schedule_due_article_searches": {"queue": "search"},
    "apps.sources.tasks.complete_expired_article_monitoring": {"queue": "search"},
    "apps.sources.tasks.purge_expired_monitoring_data": {"queue": "report"},
    "apps.monitoring.tasks.*": {"queue": "http"},
    "apps.reports.tasks.*": {"queue": "report"},
    "apps.operations.tasks.*": {"queue": "report"},
}
CELERY_BEAT_SCHEDULE = {
    "schedule-due-global-repost-searches": {
        "task": "apps.sources.tasks.schedule_due_article_searches",
        "schedule": crontab(minute="*/5"),
    },
    "complete-expired-global-monitoring": {
        "task": "apps.sources.tasks.complete_expired_article_monitoring",
        "schedule": crontab(minute="*/10"),
    },
    "purge-expired-global-monitoring": {
        "task": "apps.sources.tasks.purge_expired_monitoring_data",
        "schedule": crontab(minute=15, hour=2),
    },
    "schedule-automatic-detection-hourly": {
        "task": "apps.monitoring.tasks.schedule_automatic_batches",
        "schedule": crontab(minute=0),
    },
    "schedule-weekly-final-detection": {
        "task": "apps.monitoring.tasks.schedule_weekly_final_batch",
        "schedule": crontab(minute=0, hour=7, day_of_week="mon"),
    },
    "snapshot-daily-status": {
        "task": "apps.monitoring.tasks.create_daily_status_snapshot",
        "schedule": crontab(minute=0, hour=0),
    },
    "snapshot-weekly-status": {
        "task": "apps.monitoring.tasks.create_weekly_status_snapshot",
        "schedule": crontab(minute=30, hour=7, day_of_week="mon"),
    },
    "cleanup-expired-data": {
        "task": "apps.operations.tasks.cleanup_expired_data_task",
        "schedule": crontab(minute=0, hour=2),
    },
    "database-backup-daily": {
        "task": "apps.operations.tasks.create_database_backup_task",
        "schedule": crontab(minute=30, hour=1),
    },
}
