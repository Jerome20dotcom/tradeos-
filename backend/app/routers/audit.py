from fastapi import APIRouter, Depends

from app.deps import Ctx, require, workspace_ctx

router = APIRouter(prefix="/v1/w/{workspace_id}", tags=["audit"])


@router.get("/audit-log")
def audit_log(ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "audit:read")
    return ctx.conn.execute(
        "select id, actor_id, action, entity, entity_id, at from audit_log "
        "where workspace_id = %s order by id desc limit 100", (ctx.workspace_id,)).fetchall()
