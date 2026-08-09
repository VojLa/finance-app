from __future__ import annotations

import re

EMAIL_LOCAL_PATTERN = re.compile(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", re.ASCII)
EMAIL_DOMAIN_LABEL_PATTERN = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
    re.ASCII,
)


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    local, separator, domain = normalized.partition("@")
    domain_labels = domain.split(".")
    if (
        not separator
        or len(normalized) > 320
        or len(local) > 64
        or EMAIL_LOCAL_PATTERN.fullmatch(local) is None
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or len(domain) > 253
        or len(domain_labels) < 2
        or any(EMAIL_DOMAIN_LABEL_PATTERN.fullmatch(label) is None for label in domain_labels)
    ):
        raise ValueError("A valid email address is required.")
    return normalized


def validate_password_bytes(value: str) -> str:
    password_bytes = value.encode("utf-8")
    if not value:
        raise ValueError("Password is required.")
    if len(password_bytes) > 72:
        raise ValueError("Password must contain at most 72 UTF-8 bytes.")
    return value


def validate_new_password(value: str) -> str:
    validate_password_bytes(value)
    if len(value) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    return value
