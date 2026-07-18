from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from typing import Any

from pydantic import ValidationError

from app.auth.errors import ExpiredSessionTokenError, InvalidSessionTokenError
from app.auth.models import InternalTokenClaims


class InternalTokenVerifier:
    """Verify short-lived HS256 tokens issued by the trusted Next.js adapter."""

    def __init__(
        self,
        *,
        secret: str,
        issuer: str,
        audience: str,
        clock_skew_seconds: int = 30,
    ) -> None:
        self._secret = secret.encode("utf-8")
        self._issuer = issuer
        self._audience = audience
        self._clock_skew_seconds = clock_skew_seconds

    def verify(self, token: str, *, now: int | None = None) -> InternalTokenClaims:
        current_time = int(time.time()) if now is None else now
        header_segment, payload_segment, signature_segment = self._split_token(token)
        header = self._decode_json(header_segment)
        payload = self._decode_json(payload_segment)

        if header.get("alg") != "HS256":
            raise InvalidSessionTokenError("The session token uses an unsupported algorithm.")

        signed_value = f"{header_segment}.{payload_segment}".encode()
        expected_signature = hmac.new(self._secret, signed_value, hashlib.sha256).digest()
        supplied_signature = self._decode_segment(signature_segment)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise InvalidSessionTokenError()

        try:
            claims = InternalTokenClaims.model_validate(payload)
        except ValidationError as exc:
            raise InvalidSessionTokenError("The session token claims are invalid.") from exc

        if claims.iss != self._issuer:
            raise InvalidSessionTokenError("The session token issuer is invalid.")
        audiences = [claims.aud] if isinstance(claims.aud, str) else claims.aud
        if self._audience not in audiences:
            raise InvalidSessionTokenError("The session token audience is invalid.")
        if claims.iat > current_time + self._clock_skew_seconds:
            raise InvalidSessionTokenError("The session token was issued in the future.")
        if claims.exp <= current_time - self._clock_skew_seconds:
            raise ExpiredSessionTokenError()
        if not claims.sub.strip():
            raise InvalidSessionTokenError("The session token subject is invalid.")

        return claims

    @staticmethod
    def _split_token(token: str) -> tuple[str, str, str]:
        parts = token.split(".")
        if len(parts) != 3 or any(not part for part in parts):
            raise InvalidSessionTokenError("The session token format is invalid.")
        return parts[0], parts[1], parts[2]

    @staticmethod
    def _decode_segment(segment: str) -> bytes:
        padding = "=" * (-len(segment) % 4)
        try:
            return base64.urlsafe_b64decode(segment + padding)
        except (ValueError, binascii.Error) as exc:
            raise InvalidSessionTokenError("The session token encoding is invalid.") from exc

    @classmethod
    def _decode_json(cls, segment: str) -> dict[str, Any]:
        try:
            value = json.loads(cls._decode_segment(segment))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidSessionTokenError("The session token payload is invalid.") from exc
        if not isinstance(value, dict):
            raise InvalidSessionTokenError("The session token payload is invalid.")
        return value
