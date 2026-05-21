from .dev import *  # noqa: F401, F403

# Disable throttling so freeze_time doesn't conflict with DRF's timer()
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {},
}
