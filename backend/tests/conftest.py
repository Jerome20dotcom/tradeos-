import os
import time
import uuid

os.environ["ENVIRONMENT"] = "test"  # must be set before the app reads its settings

import jwt  # noqa: E402
import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import admin_dsn, app_dsn, get_settings  # noqa: E402
from app.main import app  # noqa: E402

S = get_settings()
assert S.active_db == S.test_db_name, "Tests must only ever run against the test database"


def token_for(user_id) -> str:
    return jwt.encode({"sub": str(user_id), "aud": S.jwt_audience, "exp": int(time.time()) + 600},
                      S.jwt_secret, "HS256")


def auth(user_id) -> dict:
    return {"Authorization": f"Bearer {token_for(user_id)}"}


@pytest.fixture
def admin():
    with psycopg.connect(admin_dsn(S.test_db_name), autocommit=True) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_database(admin):
    admin.execute("truncate audit_log, copilot_proposals, sale_items, sales, customers, products, memberships, "
                  "workspaces, auth_tokens, auth_users "
                  "restart identity cascade")


@pytest.fixture
def client():
    return TestClient(app)


class World:
    """Two separate businesses, each with an owner and one product."""


@pytest.fixture
def world(client, admin):
    w = World()
    w.user_a, w.user_b = uuid.uuid4(), uuid.uuid4()
    w.ws_a = client.post("/v1/workspaces", json={"name": "Alpha Traders", "base_currency": "JMD"},
                         headers=auth(w.user_a)).json()["id"]
    w.ws_b = client.post("/v1/workspaces", json={"name": "Bravo Supplies", "base_currency": "USD"},
                         headers=auth(w.user_b)).json()["id"]
    for ws, user, name in ((w.ws_a, w.user_a, "Alpha product"), (w.ws_b, w.user_b, "Bravo product")):
        r = client.post(f"/v1/w/{ws}/products", json={"name": name, "price_minor": 1000, "cost_minor": 600},
                        headers=auth(user))
        assert r.status_code == 201, r.text
    # extra members in business A with other roles
    w.staff, w.accountant = uuid.uuid4(), uuid.uuid4()
    admin.execute("insert into memberships (workspace_id, user_id, role) values (%s, %s, 'staff'), (%s, %s, 'accountant')",
                  (w.ws_a, w.staff, w.ws_a, w.accountant))
    w.app_dsn = app_dsn()
    return w
