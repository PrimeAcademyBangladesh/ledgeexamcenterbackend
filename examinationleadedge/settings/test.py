from .dev import *  # noqa: F401, F403

# Disable throttling so freeze_time doesn't conflict with DRF's timer().
# Views that set their own throttle_classes/throttle_scope (LoginView,
# ForgotPasswordView) bypass DEFAULT_THROTTLE_CLASSES, so ScopedRateThrottle
# still looks up DEFAULT_THROTTLE_RATES[scope] — a `None` rate tells it to
# never throttle, keeping those views exercised in tests without conflicting
# with freeze_time.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {
        "login": None,
        "password_reset": None,
    },
}

# Django test client uses http://testserver — disable HTTPS-only enforcement
# so requests reach views instead of being 301-redirected to HTTPS.
SECURE_SSL_REDIRECT = False
SECURE_PROXY_SSL_HEADER = None
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
