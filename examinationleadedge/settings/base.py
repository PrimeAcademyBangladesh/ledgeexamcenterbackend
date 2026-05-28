from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import timedelta

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ['SECRET_KEY']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # third-party©
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'drf_spectacular',
    # local
    'apps.users',
    'apps.learners',
    'apps.exams',
    'apps.results',
    'apps.retakes',
    'apps.questions',
    'apps.reports',
    'apps.qualifications',
    'apps.invigilators',
    'apps.integrity',
    'apps.adjustments',
    'apps.settings_app',
    'apps.tts',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'examinationleadedge.urls'

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

WSGI_APPLICATION = 'examinationleadedge.wsgi.application'

AUTH_USER_MODEL = 'users.User'


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]




LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Europe/London'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage',
    },
}

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]


MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_RENDERER_CLASSES": (
        "core.renderers.EnvelopeJSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ),
    "EXCEPTION_HANDLER": "core.exceptions.envelope_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "1500/day",
        "user": "20000/day",
        "login": "10/minute",
        "password_reset": "5/hour",
        "resend": "10/hour",
        "registration": "30/day",
        "payment_webhook": "500/hour",
        "payment_verify": "60/minute",
        "cart": "60/minute",
        "search": "120/minute",
        "blog": "500/day",
        "burst": "60/minute",
        "sustained": "5000/day",
        # TTS: learners reading exam questions typically make < 30 calls per exam;
        # 60/hour gives comfortable headroom while blocking automated abuse.
        "tts": "60/hour",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "LeadEdge Examination Backend API",
    "DESCRIPTION": (
        "Official REST API for the exam platform. "
        "Endpoints are grouped by operational domain so frontend teams can "
        "navigate catalogue, question bank, exam delivery, learner, and staff "
        "workflows separately."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": False,
    "SWAGGER_UI_SETTINGS": {
        "defaultModelsExpandDepth": -1,
    },
    "DEFAULT_GENERATOR_CLASS": "drf_spectacular.generators.SchemaGenerator",
    "AUTHENTICATION_WHITELIST": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "SECURITY": [{"bearerAuth": []}],
    "COMPONENTS": {
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            }
        },
    },
    "ENUM_NAME_OVERRIDES": {
        "QuestionType": [
            ("single", "Single answer"),
            ("multiple", "Multiple answer"),
        ],
        "EnrollmentStatus": [
            ("active", "Active"),
            ("withdrawn", "Withdrawn"),
            ("completed", "Completed"),
            ("suspended", "Suspended"),
        ],
        "BankHealthStatus": [
            ("healthy", "healthy"),
            ("warning", "warning"),
            ("critical", "critical"),
        ],
    },
    "TAGS": [
        {
            "name": "Qualification",
            "description": "Qualification catalogue CRUD and admin qualification detail endpoints.",
        },
        {
            "name": "Qualification Sector",
            "description": "Sector lookup and sector administration endpoints used by qualification-related forms.",
        },
        {
            "name": "Qualification Level",
            "description": "Read-only level lookup endpoints used by qualification dropdowns.",
        },
        {
            "name": "Qualification Unit",
            "description": "Qualification unit endpoints used by admin qualification management and question-editor unit pickers.",
        },
        {
            "name": "Qualification Enrollment",
            "description": "Enrollment CRUD and learner enrollment views.",
        },
        {
            "name": "Question",
            "description": "Admin question-bank CRUD, filtering, and bulk import endpoints.",
        },
        {
            "name": "Exam Config",
            "description": "Exam blueprint configuration endpoints used by admin exam setup screens.",
        },
        {
            "name": "Exam Session",
            "description": "Session scheduling and invigilation workflow endpoints.",
        },
        {
            "name": "Exam Runtime",
            "description": "Learner runtime endpoints for mock start, PIN validation, autosave, and submission.",
        },
        {
            "name": "Exam Result",
            "description": "Read-only result endpoints used by admin, invigilator, and learner result views.",
        },
        {
            "name": "Exam Integrity",
            "description": "Exam integrity and incident-reporting endpoints.",
        },
        {
            "name": "Exam Retake",
            "description": "Retake request and resit-session endpoints.",
        },
        {
            "name": "Scenario",
            "description": "Scenario passage management — create, edit, and link scenarios to questions for scenario-based exam sections.",
        },
    ],
}

SIMPLE_JWT = {
    # =====================================================
    # TOKEN LIFETIME
    # =====================================================
    "ACCESS_TOKEN_LIFETIME": timedelta(days=2),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,

    # =====================================================
    # JWT CORE
    # =====================================================
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "TOKEN_OBTAIN_SERIALIZER": "apps.users.serializers.LoginSerializer",
}

# Celery
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'celery.beat.PersistentScheduler'


CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_SSL = True
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@examapi.leadedgeltd.org')

# ── Text-to-Speech (Piper TTS) ─────────────────────────────────────────────
# Install Piper on the server: https://github.com/rhasspy/piper/releases
# Download model files from: https://huggingface.co/rhasspy/piper-voices
#
# Each voice entry maps a safe API name to the on-disk .onnx model and its
# companion .onnx.json config file. Never expose filesystem paths to clients;
# the voice name is validated against this allowlist server-side.

TTS_PIPER_BINARY  = os.environ.get("TTS_PIPER_BINARY",  "/usr/local/bin/piper")
TTS_PIPER_TIMEOUT = int(os.environ.get("TTS_PIPER_TIMEOUT", "30"))  # seconds
TTS_MAX_TEXT_LENGTH = 1500      
TTS_CACHE_TIMEOUT   = 3600  

# Preferred UK female voice. Assumption: en_GB-jenny_dioco-medium is the
# closest freely available Piper voice to a southern English female accent.
# Replace with en_GB-alba-medium (Scottish) or en_GB-aru-medium if preferred.
TTS_DEFAULT_VOICE = os.environ.get("TTS_DEFAULT_VOICE", "southern_english_female")

TTS_VOICES: dict = {
    "southern_english_female": {
        # Jenny DioCo — natural, clear UK female voice; medium quality.
        "model":  os.environ.get(
            "TTS_MODEL_SOUTHERN_ENGLISH_FEMALE",
            "/models/piper/en_GB-jenny_dioco-medium.onnx",
        ),
        "config": os.environ.get(
            "TTS_CONFIG_SOUTHERN_ENGLISH_FEMALE",
            "/models/piper/en_GB-jenny_dioco-medium.onnx.json",
        ),
    },
    "uk_male": {
        # Alan — neutral UK male voice; medium quality.
        "model":  os.environ.get(
            "TTS_MODEL_UK_MALE",
            "/models/piper/en_GB-alan-medium.onnx",
        ),
        "config": os.environ.get(
            "TTS_CONFIG_UK_MALE",
            "/models/piper/en_GB-alan-medium.onnx.json",
        ),
    },
}
