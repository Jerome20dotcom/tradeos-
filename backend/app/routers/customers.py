import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.deps import Ctx, audit, require, workspace_ctx

router = APIRouter(prefix="/v1/w/{workspace_id}", tags=["customers"])


class CustomerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=40)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name cannot be blank")
        return value


@router.get("/customers")
def list_customers(ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "customers:read")
    return ctx.conn.execute(
        "select id, name, email, phone, created_at from customers "
        "where workspace_id = %s order by name limit 500",
        (ctx.workspace_id,),
    ).fetchall()


@router.post("/customers", status_code=201)
def create_customer(body: CustomerIn, ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "customers:write")
    row = ctx.conn.execute(
        "insert into customers (workspace_id, name, email, phone) values (%s, %s, %s, %s) "
        "returning id, name, email, phone, created_at",
        (ctx.workspace_id, body.name.strip(), body.email.strip(), body.phone.strip()),
    ).fetchone()
    audit(ctx, "create", "customer", row["id"], after=body.model_dump())
    ctx.conn.commit()
    return row


@router.put("/customers/{customer_id}")
def update_customer(customer_id: uuid.UUID, body: CustomerIn, ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "customers:write")
    row = ctx.conn.execute(
        "update customers set name = %s, email = %s, phone = %s "
        "where workspace_id = %s and id = %s "
        "returning id, name, email, phone, created_at",
        (body.name.strip(), body.email.strip(), body.phone.strip(), ctx.workspace_id, customer_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    audit(ctx, "update", "customer", customer_id, after=body.model_dump())
    ctx.conn.commit()
    return row


@router.delete("/customers/{customer_id}", status_code=204)
def delete_customer(customer_id: uuid.UUID, ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "customers:write")
    linked_sale = ctx.conn.execute(
        "select 1 from sales where workspace_id = %s and customer_id = %s limit 1",
        (ctx.workspace_id, customer_id),
    ).fetchone()
    if linked_sale is not None:
        raise HTTPException(status_code=409, detail="Customer has sales history and cannot be deleted")
    row = ctx.conn.execute(
        "delete from customers where workspace_id = %s and id = %s returning id, name, email, phone",
        (ctx.workspace_id, customer_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    audit(ctx, "delete", "customer", customer_id, after=row)
    ctx.conn.commit()
