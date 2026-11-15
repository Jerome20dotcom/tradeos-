import json
import uuid
from dataclasses import dataclass

import psycopg
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg.types.json import Jsonb

from app.db import connect
from app.security import InvalidToken, decode_token

bearer = HTTPBearer(auto_error=False)

# One central place that decides who may do what. Add actions here as modules are built.
PERMISSIONS: dict[str, set[str]] = {
    "products:read": {"owner", "admin", "staff", "accountant"},
    "products:write": {"owner", "admin", "staff"},
    "customers:read": {"owner", "admin", "staff", "accountant"},
    "customers:write": {"owner", "admin", "staff"},
    "sales:read": {"owner", "admin", "staff", "accountant"},
    "sales:write": {"owner", "admin", "staff"},
    "copilot:read": {"owner", "admin", "staff", "accountant"},
    "copilot:write": {"owner", "admin", "staff"},
    "audit:read": {"owner", "admin"},
}


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> uuid.UUID:
    if creds is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    try:
        return decode_token(creds.credentials)
    except InvalidToken:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def user_connection(user_id: uuid.UUID = Depends(current_user)):
    """One database transaction per request, with the user id set for row-level security."""
    conn = connect()
    try:
        conn.execute("select set_config('app.user_id', %s, true)", (str(user_id),))
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass
class Ctx:
    conn: psycopg.Connection
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    role: str


def workspace_ctx(workspace_id: uuid.UUID,
                  conn: psycopg.Connection = Depends(user_connection),
                  user_id: uuid.UUID = Depends(current_user)) -> Ctx:
    """Resolve the workspace in the URL. Not a member means 404, so other businesses look non-existent."""
    row = conn.execute("select role from memberships where workspace_id = %s and user_id = %s",
                       (workspace_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    conn.execute("select set_config('app.workspace_id', %s, true)", (str(workspace_id),))
    return Ctx(conn=conn, user_id=user_id, workspace_id=workspace_id, role=row["role"])


def require(ctx: Ctx, permission: str) -> None:
    if ctx.role not in PERMISSIONS[permission]:
        raise HTTPException(status_code=403, detail="You do not have permission to do this")


def audit(ctx: Ctx, action: str, entity: str, entity_id: uuid.UUID, after: dict | None = None) -> None:
    """Write an audit record in the same transaction as the change it describes."""
    payload = Jsonb(json.loads(json.dumps(after, default=str))) if after is not None else None
    ctx.conn.execute(
        "insert into audit_log (workspace_id, actor_id, action, entity, entity_id, after) "
        "values (%s, %s, %s, %s, %s, %s)",
        (ctx.workspace_id, ctx.user_id, action, entity, entity_id, payload))
