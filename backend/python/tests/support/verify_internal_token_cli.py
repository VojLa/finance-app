"""Safe stdin-only bridge for cross-runtime internal-token compatibility tests."""

from __future__ import annotations

import json
import sys
from typing import Any

from app.auth.errors import ExpiredSessionTokenError, InvalidSessionTokenError
from app.auth.token import InternalTokenVerifier


def _safe_failure() -> dict[str, object]:
    return {"ok": False, "error": "invalid_token"}


def _request() -> dict[str, Any]:
    if len(sys.argv) != 1:
        raise ValueError("Arguments are not accepted.")
    value = json.loads(sys.stdin.read())
    if not isinstance(value, dict):
        raise ValueError("The request must be an object.")
    return value


def main() -> int:
    try:
        request = _request()
        token = request["token"]
        secret = request["secret"]
        issuer = request["issuer"]
        audience = request["audience"]
        now = request["now"]
        if not all(isinstance(value, str) for value in (token, secret, issuer, audience)):
            raise ValueError("String configuration is required.")
        if not isinstance(now, int) or isinstance(now, bool):
            raise ValueError("Integer time is required.")

        claims = InternalTokenVerifier(
            secret=secret,
            issuer=issuer,
            audience=audience,
            clock_skew_seconds=0,
        ).verify(token, now=now)
    except (
        ExpiredSessionTokenError,
        InvalidSessionTokenError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        print(json.dumps(_safe_failure(), separators=(",", ":")))
        return 0

    result = {
        "ok": True,
        "algorithm": "HS256",
        "claims": {
            "sub": claims.sub,
            "email": claims.email,
            "iss": claims.iss,
            "aud": claims.aud,
            "iat": claims.iat,
            "exp": claims.exp,
            "jti": claims.jti,
        },
    }
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
