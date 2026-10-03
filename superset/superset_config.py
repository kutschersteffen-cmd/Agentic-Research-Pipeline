"""Superset settings for ARP, mounted at /app/pythonpath/ (see
docker-compose.yml). Secrets come from backend/.env; there are no
defaults, so a missing one stops the container instead of running with a
guessable key."""

import os


# The .env.example placeholder and Superset's own shipped defaults.
PLACEHOLDERS = {"change-me-dev-only", "CHANGE_ME_SECRET_KEY", "test-guest-secret-change-me"}


def required(name: str, min_length: int = 0) -> str:
    """The env var's value; raises if it is unset, a known placeholder or
    shorter than `min_length`. Also called by entrypoint.sh."""
    value = os.environ.get(name, "")
    if not value or value in PLACEHOLDERS or len(value) < min_length:
        too_short = f" or shorter than {min_length} characters" if min_length else ""
        raise RuntimeError(
            f"{name} is unset, a placeholder{too_short} -- set it in backend/.env, e.g. to the output of `openssl rand -base64 42`"
        )
    return value


SECRET_KEY = required("SUPERSET_SECRET_KEY", 32)
SQLALCHEMY_DATABASE_URI = required("SUPERSET_DATABASE_URI")

# Embedded dashboards in the ARP UI, authorised by short-lived guest tokens
# that the ARP backend requests as arp_designer.
FEATURE_FLAGS = {"EMBEDDED_SUPERSET": True}
GUEST_TOKEN_JWT_SECRET = required("SUPERSET_GUEST_TOKEN_JWT_SECRET", 32)
# Guest access to the dashboard's own datasets comes from the token itself;
# the role only adds the base read permissions the embedded app needs.
GUEST_ROLE_NAME = "Gamma"

# Only the ARP UI may frame Superset. Same CSP as Superset's default plus
# frame-ancestors.
TALISMAN_ENABLED = True
TALISMAN_CONFIG = {
    "content_security_policy": {
        "base-uri": ["'self'"],
        "default-src": ["'self'"],
        "img-src": ["'self'", "blob:", "data:"],
        "worker-src": ["'self'", "blob:"],
        "connect-src": ["'self'"],
        "object-src": "'none'",
        "style-src": ["'self'", "'unsafe-inline'"],
        "script-src": ["'self'", "'strict-dynamic'"],
        "frame-ancestors": ["'self'", "http://localhost:5173"],
    },
    "content_security_policy_nonce_in": ["script-src"],
    "force_https": False,
    "session_cookie_secure": False,
}

# No cache backend in v1: Superset's default CACHE_CONFIG/DATA_CACHE_CONFIG
# are NullCache, which is what we want.
