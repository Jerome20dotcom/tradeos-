import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.deps import Ctx, audit, require, workspace_ctx

router = APIRouter(prefix="/v1/w/{workspace_id}", tags=["products"])


class ProductIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields (such as a workspace_id) are rejected
    name: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="pcs", min_length=1, max_length=30)
    price_minor: int = Field(ge=0, le=10**12, description="Selling price in minor units (cents)")
    cost_minor: int = Field(ge=0, le=10**12, description="Cost in minor units (cents)")
    stock_quantity: int = Field(default=0, ge=0, le=2_147_483_647)

    @field_validator("name", "unit")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


@router.get("/products")
def list_products(ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "products:read")
    return ctx.conn.execute(
        "select id, name, unit, price_minor, cost_minor, stock_quantity, created_at from products "
        "where workspace_id = %s order by created_at desc limit 200", (ctx.workspace_id,)).fetchall()


@router.post("/products", status_code=201)
def create_product(body: ProductIn, ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "products:write")
    row = ctx.conn.execute(
        "insert into products (workspace_id, name, unit, price_minor, cost_minor, stock_quantity, created_by) "
        "values (%s, %s, %s, %s, %s, %s, %s) "
        "returning id, name, unit, price_minor, cost_minor, stock_quantity, created_at",
        (ctx.workspace_id, body.name, body.unit, body.price_minor, body.cost_minor,
         body.stock_quantity, ctx.user_id)).fetchone()
    audit(ctx, "create", "product", row["id"], after=body.model_dump())
    ctx.conn.commit()
    return row


@router.put("/products/{product_id}")
def update_product(product_id: uuid.UUID, body: ProductIn, ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "products:write")
    row = ctx.conn.execute(
        "update products set name = %s, unit = %s, price_minor = %s, cost_minor = %s, stock_quantity = %s "
        "where workspace_id = %s and id = %s "
        "returning id, name, unit, price_minor, cost_minor, stock_quantity, created_at",
        (body.name, body.unit, body.price_minor, body.cost_minor, body.stock_quantity,
         ctx.workspace_id, product_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    audit(ctx, "update", "product", product_id, after=body.model_dump())
    ctx.conn.commit()
    return row


@router.delete("/products/{product_id}", status_code=204)
def delete_product(product_id: uuid.UUID, ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "products:write")
    row = ctx.conn.execute(
        "delete from products where workspace_id = %s and id = %s "
        "returning id, name, unit, price_minor, cost_minor",
        (ctx.workspace_id, product_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    audit(ctx, "delete", "product", product_id, after=row)
    ctx.conn.commit()
