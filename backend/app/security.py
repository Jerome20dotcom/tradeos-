import uuid

import jwt

from app.config import get_settings


class InvalidToken(Exception):
    pass


def decode_token(token: str) -> uuid.UUID:
    """Verify signature, expiry and audience. Returns the user id.

    Phase 1 uses a shared secret (HS256). When a hosted identity provider is added,
    only this function changes (verify against the provider's public keys instead).
    """
    s = get_settings()
    try:
        claims = jwt.decode(token, s.jwt_secret, algorithms=["HS256"], audience=s.jwt_audience,
                            options={"require": ["exp", "sub", "aud"]})
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidToken from exc
