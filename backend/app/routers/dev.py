import time
import uuid

import jwt
from fastapi import APIRouter, HTTPException

from app.config import get_settings

router = APIRouter(prefix="/v1/dev", tags=["development"])


@router.post("/session", include_in_schema=False)
def create_dev_session():
    """Issue a temporary local identity for the development UI; never enabled outside development."""
    settings = get_settings()
    if settings.environment != "development":
        raise HTTPException(status_code=404, detail="Not found")

    user_id = uuid.uuid4()
    expires_in = 8 * 60 * 60
    token = jwt.encode(
        {"sub": str(user_id), "aud": settings.jwt_audience, "exp": int(time.time()) + expires_in},
        settings.jwt_secret,
        "HS256",
    )
    return {"user_id": str(user_id), "access_token": token, "expires_in": expires_in}
