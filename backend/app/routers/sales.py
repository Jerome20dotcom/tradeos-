import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.deps import Ctx, audit, require, workspace_ctx

router = APIRouter(prefix="/v1/w/{workspace_id}", tags=["sales"])


class SaleLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=2_147_483_647)


class SaleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: uuid.UUID | None = None
    items: list[SaleLineIn] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def product_ids_are_unique(self):
        ids = [item.product_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("Each product can only appear once in a sale")
        return self


@router.get("/sales")
def list_sales(ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "sales:read")
    sales = ctx.conn.execute(
        "select s.id, s.customer_id, c.name as customer_name, s.total_minor, s.created_at "
        "from sales s left join customers c on c.id = s.customer_id "
        "where s.workspace_id = %s order by s.created_at desc limit 200",
        (ctx.workspace_id,),
    ).fetchall()
    if not sales:
        return []
    sale_ids = [sale["id"] for sale in sales]
    items = ctx.conn.execute(
        "select sale_id, product_name, unit, quantity, unit_price_minor, unit_cost_minor, line_total_minor "
        "from sale_items where workspace_id = %s and sale_id = any(%s) order by product_name",
        (ctx.workspace_id, sale_ids),
    ).fetchall()
    items_by_sale: dict[uuid.UUID, list[dict]] = {sale_id: [] for sale_id in sale_ids}
    for item in items:
        items_by_sale[item["sale_id"]].append(item)
    return [{**sale, "items": items_by_sale[sale["id"]]} for sale in sales]


@router.post("/sales", status_code=201)
def create_sale(body: SaleIn, ctx: Ctx = Depends(workspace_ctx)):
    require(ctx, "sales:write")
    sale = record_sale(ctx, body)
    ctx.conn.commit()
    return sale


def record_sale(ctx: Ctx, body: SaleIn) -> dict:
    if body.customer_id is not None:
        customer = ctx.conn.execute(
            "select id from customers where workspace_id = %s and id = %s",
            (ctx.workspace_id, body.customer_id),
        ).fetchone()
        if customer is None:
            raise HTTPException(status_code=404, detail="Customer not found")

    product_ids = [line.product_id for line in body.items]
    products = ctx.conn.execute(
        "select id, name, unit, price_minor, cost_minor, stock_quantity from products "
        "where workspace_id = %s and id = any(%s) order by id for update",
        (ctx.workspace_id, product_ids),
    ).fetchall()
    product_by_id = {product["id"]: product for product in products}
    if len(product_by_id) != len(body.items):
        raise HTTPException(status_code=404, detail="One or more products were not found")

    sale_lines = []
    total_minor = 0
    for line in body.items:
        product = product_by_id[line.product_id]
        if product["stock_quantity"] < line.quantity:
            raise HTTPException(
                status_code=409,
                detail=f"Not enough stock for {product['name']} (available: {product['stock_quantity']})",
            )
        line_total = product["price_minor"] * line.quantity
        total_minor += line_total
        sale_lines.append((line, product, line_total))
    if total_minor > 9_223_372_036_854_775_807:
        raise HTTPException(status_code=422, detail="Sale total exceeds the supported range")

    sale = ctx.conn.execute(
        "insert into sales (workspace_id, customer_id, sold_by, total_minor) "
        "values (%s, %s, %s, %s) returning id, customer_id, total_minor, created_at",
        (ctx.workspace_id, body.customer_id, ctx.user_id, total_minor),
    ).fetchone()
    for line, product, line_total in sale_lines:
        ctx.conn.execute(
            "update products set stock_quantity = stock_quantity - %s "
            "where workspace_id = %s and id = %s",
            (line.quantity, ctx.workspace_id, line.product_id),
        )
        ctx.conn.execute(
            "insert into sale_items (workspace_id, sale_id, product_name, unit, quantity, "
            "unit_price_minor, unit_cost_minor, line_total_minor) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s)",
            (ctx.workspace_id, sale["id"], product["name"], product["unit"], line.quantity,
             product["price_minor"], product["cost_minor"], line_total),
        )
    audit(ctx, "create", "sale", sale["id"], after={
        "customer_id": body.customer_id,
        "total_minor": total_minor,
        "items": [
            {"product_id": line.product_id, "quantity": line.quantity, "line_total_minor": line_total}
            for line, _, line_total in sale_lines
        ],
    })
    return {
        **sale,
        "items": [
            {
                "product_name": product["name"],
                "unit": product["unit"],
                "quantity": line.quantity,
                "unit_price_minor": product["price_minor"],
                "unit_cost_minor": product["cost_minor"],
                "line_total_minor": line_total,
            }
            for line, product, line_total in sale_lines
        ],
    }
