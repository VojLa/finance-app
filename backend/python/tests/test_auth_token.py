import base64
import hashlib
import hmac
import json

import pytest

from app.auth.errors import ExpiredSessionTokenError, InvalidSessionTokenError
from app.auth.token import InternalTokenVerifier

SECRET = "test-secret-that-is-long-enough-for-auth"


def _encode(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(payload: dict[str, object], *, secret: str = SECRET, algorithm: str = "HS256") -> str:
    header = _encode({"alg": algorithm, "typ": "JWT"})
    body = _encode(payload)
    signature = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{body}.{encoded_signature}"


def _signed_segments(header: str, body: str, *, secret: str = SECRET) -> str:
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


@pytest.mark.parametrize("algorithm", ["none", "HS384", "RS256"])
def test_only_hs256_is_accepted(algorithm: str) -> None:
    with pytest.raises(InvalidSessionTokenError):
        _verifier().verify(_token(_claims(), algorithm=algorithm), now=1_100)


@pytest.mark.parametrize(
    "token",
    [
        "header.payload.",
        _signed_segments(_encode({"alg": "HS256"}) + "!", _encode(_claims())),
        _signed_segments(_encode({"alg": "HS256"}), _encode(_claims()) + "!"),
        _signed_segments(_encode(["not", "an", "object"]), _encode(_claims())),
        _signed_segments(_encode({"alg": "HS256"}), _encode(["not", "an", "object"])),
        _signed_segments(
            _encode({"alg": "HS256"}),
            base64.urlsafe_b64encode(b"not-json").rstrip(b"=").decode(),
        ),
    ],
)
def test_malformed_encodings_and_json_are_rejected(token: str) -> None:
    with pytest.raises(InvalidSessionTokenError):
        _verifier().verify(token, now=1_100)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sub": 123},
        {"iat": "1000"},
        {"iat": True},
        {"exp": "1300"},
        {"aud": ["finance-app-python", 123]},
        {"unexpected": "claim"},
    ],
)
def test_unsafe_claim_types_and_unknown_claims_are_rejected(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(InvalidSessionTokenError):
        _verifier().verify(_token(_claims(**overrides)), now=1_100)


@pytest.mark.parametrize(
    "overrides",
    [
        {"iat": 1_101},
        {"sub": ""},
        {"sub": "   "},
    ],
)
def test_future_issued_at_and_empty_subject_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(InvalidSessionTokenError):
        _verifier().verify(_token(_claims(**overrides)), now=1_100)


def test_modified_signature_is_rejected() -> None:
    token = _token(_claims())
    replacement = "A" if token[-1] != "A" else "B"

    with pytest.raises(InvalidSessionTokenError):
        _verifier().verify(token[:-1] + replacement, now=1_100)


def test_modified_payload_is_rejected() -> None:
    header, payload, signature = _token(_claims()).split(".")
    replacement = "A" if payload[-1] != "A" else "B"

    with pytest.raises(InvalidSessionTokenError):
        _verifier().verify(f"{header}.{payload[:-1]}{replacement}.{signature}", now=1_100)
