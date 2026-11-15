"""Print a development login token so you can try the API at http://127.0.0.1:8000/docs.

Usage:  python scripts/dev_token.py            (new random user)
        python scripts/dev_token.py <user-uuid> (same user again)
Only works when ENVIRONMENT=development. Real sign-in replaces this later.
"""
import pathlib
import sys
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import jwt  # noqa: E402

from app.config import get_settings  # noqa: E402

s = get_settings()
if s.environment != "development":
    sys.exit("dev tokens are only available when ENVIRONMENT=development")
user = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
token = jwt.encode({"sub": user, "aud": s.jwt_audience, "exp": int(time.time()) + 8 * 3600}, s.jwt_secret, "HS256")
print("user id:", user)
print("token:  ", token)
