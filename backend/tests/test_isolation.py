"""Tenant isolation. These are the most important tests in the project: one business must never see another's data."""
import uuid

import psycopg
import pytest

from tests.conftest import auth


def names(response):
    return [p["name"] for p in response.json()]


def test_each_business_sees_only_its_own_products(client, world):
    assert names(client.get(f"/v1/w/{world.ws_a}/products", headers=auth(world.user_a))) == ["Alpha product"]
    assert names(client.get(f"/v1/w/{world.ws_b}/products", headers=auth(world.user_b))) == ["Bravo product"]


def test_other_business_workspace_looks_nonexistent(client, world):
    assert client.get(f"/v1/w/{world.ws_a}/products", headers=auth(world.user_b)).status_code == 404
    assert client.get(f"/v1/w/{world.ws_a}/audit-log", headers=auth(world.user_b)).status_code == 404


def test_cannot_write_into_another_business(client, world):
    body = {"name": "Intruder", "price_minor": 1, "cost_minor": 1}
    assert client.post(f"/v1/w/{world.ws_a}/products", json=body, headers=auth(world.user_b)).status_code == 404
    assert names(client.get(f"/v1/w/{world.ws_a}/products", headers=auth(world.user_a))) == ["Alpha product"]


def test_workspace_id_in_body_is_rejected(client, world):
    body = {"name": "Sneaky", "price_minor": 1, "cost_minor": 1, "workspace_id": world.ws_a}
    assert client.post(f"/v1/w/{world.ws_b}/products", json=body, headers=auth(world.user_b)).status_code == 422


def test_my_workspaces_lists_only_mine(client, world):
    ids = [w["id"] for w in client.get("/v1/me/workspaces", headers=auth(world.user_a)).json()]
    assert ids == [world.ws_a]


def test_database_blocks_cross_tenant_reads_even_without_app_filters(world):
    """Simulates a bug where the app forgets its WHERE clause: the database itself still isolates tenants."""
    with psycopg.connect(world.app_dsn) as conn:
        conn.execute("select set_config('app.user_id', %s, true)", (str(world.user_b),))
        conn.execute("select set_config('app.workspace_id', %s, true)", (world.ws_b,))
        rows = conn.execute("select workspace_id::text from products").fetchall()
        assert rows and all(r[0] == world.ws_b for r in rows)


def test_database_blocks_forged_workspace_context(world):
    """User B pretends to be working in business A: the membership check in the policy returns nothing."""
    with psycopg.connect(world.app_dsn) as conn:
        conn.execute("select set_config('app.user_id', %s, true)", (str(world.user_b),))
        conn.execute("select set_config('app.workspace_id', %s, true)", (world.ws_a,))
        assert conn.execute("select count(*) from products").fetchone()[0] == 0
        assert conn.execute("select count(*) from audit_log").fetchone()[0] == 0


def test_database_blocks_cross_tenant_insert(world):
    with psycopg.connect(world.app_dsn) as conn:
        conn.execute("select set_config('app.user_id', %s, true)", (str(world.user_b),))
        conn.execute("select set_config('app.workspace_id', %s, true)", (world.ws_b,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("insert into products (workspace_id, name, price_minor, cost_minor, created_by) "
                         "values (%s, 'x', 1, 1, %s)", (world.ws_a, uuid.uuid4()))


def test_database_blocks_cross_tenant_customer_and_sales_reads(client, world):
    customer = client.post(
        f"/v1/w/{world.ws_a}/customers",
        json={"name": "Private customer"},
        headers=auth(world.user_a),
    ).json()
    with psycopg.connect(world.app_dsn) as conn:
        conn.execute("select set_config('app.user_id', %s, true)", (str(world.user_b),))
        conn.execute("select set_config('app.workspace_id', %s, true)", (world.ws_b,))
        assert conn.execute("select count(*) from customers").fetchone()[0] == 0
        assert conn.execute("select count(*) from sales").fetchone()[0] == 0
        assert conn.execute("select count(*) from sale_items").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "insert into sales (workspace_id, customer_id, sold_by, total_minor) "
                "values (%s, %s, %s, 0)",
                (world.ws_b, customer["id"], world.user_b),
            )


def test_app_role_has_no_special_privileges(world):
    with psycopg.connect(world.app_dsn) as conn:
        row = conn.execute("select rolsuper, rolbypassrls from pg_roles where rolname = current_user").fetchone()
        assert row == (False, False)
