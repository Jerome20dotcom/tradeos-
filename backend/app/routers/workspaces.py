import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.deps import current_user, user_connection

router = APIRouter(prefix="/v1", tags=["workspaces"])


class WorkspaceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    base_currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217 code, for example JMD or USD")


@router.get("/me/workspaces")
def my_workspaces(conn=Depends(user_connection), user_id: uuid.UUID = Depends(current_user)):
    return conn.execute(
        "select w.id, w.name, w.base_currency, m.role from memberships m "
        "join workspaces w on w.id = m.workspace_id where m.user_id = %s order by w.created_at",
        (user_id,)).fetchall()


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, conn=Depends(user_connection)):
    row = conn.execute("select create_workspace(%s, %s) as id", (body.name, body.base_currency)).fetchone()
    conn.commit()
    return {"id": row["id"], "name": body.name, "base_currency": body.base_currency, "role": "owner"}
