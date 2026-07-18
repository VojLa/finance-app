import base64
import hashlib
import hmac
import json

import pytest

from app.auth.errors import ExpiredSessionTokenError, InvalidSessionTokenError
from app.auth.token import InternalTokenVerifier

SECRET = "test-secret-that-is-long-enough-for-auth"


def _encode(value: dict[str, object]) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(payload: dict[str, object], *, secret: str = SECRET, algorithm: str = "HS256") -> str:
    header = _encode({"alg": algorithm, "typ": "JWT"})
    body = _encode(payload)
    signature = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{body}.{encoded_signature}"


def _claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "sub": "user-1",
        "email": "user@example.com",
        "iss": "finance-app-next",
        "aud": "finance-app-python",
        "iat": 1_000,
        "exp": 1_300,
        "jti": "session-1",
    }
    claims.update(overrides)
    return claims


def _verifier() -> InternalTokenVerifier:
    return InternalTokenVerifier(
        secret=SECRET,
        issuer="finance-app-next",
        audience="finance-app-python",
        clock_skew_seconds=0,
    )


def test_valid_token_returns_claims() -> None:
    claims = _verifier().verify(_token(_claims()), now=1_100)

    assert claims.sub == "user-1"
    assert claims.jti == "session-1"


@pytest.mark.parametrize(
    ("token", "expected_error"),
    [
        ("invalid", InvalidSessionTokenError),
        (_token(_claims(), secret="wrong-secret"), InvalidSessionTokenError),
        (_token(_claims(iss="wrong")), InvalidSessionTokenError),
        (_token(_claims(aud="wrong")), InvalidSessionTokenError),
        (_token(_claims(), algorithm="none"), InvalidSessionTokenError),
        (_token(_claims(exp=1_000)), ExpiredSessionTokenError),
    ],
)
def test_invalid_tokens_are_rejected(token: str, expected_error: type[Exception]) -> None:
    with pytest.raises(expected_error):
        _verifier().verify(token, now=1_100)
