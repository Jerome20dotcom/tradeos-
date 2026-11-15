import json
import time

import jwt
import pytest
import psycopg

from app.config import get_settings
from tests.conftest import auth


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_requires_sign_in(client):
    assert client.get("/v1/me/workspaces").status_code == 401


def test_rejects_token_signed_with_wrong_secret(client, world):
    bad = jwt.encode({"sub": str(world.user_a), "aud": "tradeos", "exp": int(time.time()) + 600},
                     "x" * 40, "HS256")
    assert client.get("/v1/me/workspaces", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_rejects_expired_token(client, world):
    s = get_settings()
    old = jwt.encode({"sub": str(world.user_a), "aud": s.jwt_audience, "exp": int(time.time()) - 10},
                     s.jwt_secret, "HS256")
    assert client.get("/v1/me/workspaces", headers={"Authorization": f"Bearer {old}"}).status_code == 401


@pytest.mark.parametrize("bad", [
    {"name": "", "price_minor": 1, "cost_minor": 1},
    {"name": "  ", "price_minor": 1, "cost_minor": 1},
    {"name": "x", "price_minor": -5, "cost_minor": 1},
    {"name": "x", "price_minor": 1.5, "cost_minor": 1},
    {"name": "x", "price_minor": 1},
])
def test_invalid_product_input_is_rejected(client, world, bad):
    assert client.post(f"/v1/w/{world.ws_a}/products", json=bad, headers=auth(world.user_a)).status_code == 422


def test_invalid_currency_is_rejected(client):
    r = client.post("/v1/workspaces", json={"name": "X", "base_currency": "jmd"}, headers=auth(__import__("uuid").uuid4()))
    assert r.status_code == 422


def test_blank_customer_name_is_rejected(client, world):
    response = client.post(
        f"/v1/w/{world.ws_a}/customers",
        json={"name": "   "},
        headers=auth(world.user_a),
    )
    assert response.status_code == 422


def test_roles_are_enforced(client, world):
    new = {"name": "Thing", "price_minor": 5, "cost_minor": 2}
    assert client.get(f"/v1/w/{world.ws_a}/products", headers=auth(world.accountant)).status_code == 200
    assert client.post(f"/v1/w/{world.ws_a}/products", json=new, headers=auth(world.accountant)).status_code == 403
    assert client.post(f"/v1/w/{world.ws_a}/products", json=new, headers=auth(world.staff)).status_code == 201
    assert client.get(f"/v1/w/{world.ws_a}/audit-log", headers=auth(world.staff)).status_code == 403
    assert client.get(f"/v1/w/{world.ws_a}/audit-log", headers=auth(world.user_a)).status_code == 200


def test_product_can_be_updated_and_deleted(client, world):
    headers = auth(world.user_a)
    product = client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]
    changed = {"name": "Updated Alpha", "unit": "box", "price_minor": 1250, "cost_minor": 700}

    updated = client.put(
        f"/v1/w/{world.ws_a}/products/{product['id']}", json=changed, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated Alpha"

    deleted = client.delete(f"/v1/w/{world.ws_a}/products/{product['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json() == []


def test_product_mutations_are_audited(client, world):
    headers = auth(world.user_a)
    product = client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]
    product_id = product["id"]
    body = {"name": "Changed", "unit": "pcs", "price_minor": 1000, "cost_minor": 600}
    assert client.put(f"/v1/w/{world.ws_a}/products/{product_id}", json=body, headers=headers).status_code == 200
    assert client.delete(f"/v1/w/{world.ws_a}/products/{product_id}", headers=headers).status_code == 204
    actions = client.get(f"/v1/w/{world.ws_a}/audit-log", headers=headers).json()
    assert {item["action"] for item in actions if item["entity"] == "product"} == {
        "create", "update", "delete"
    }


def test_product_cannot_be_changed_by_read_only_member(client, world):
    product = client.get(
        f"/v1/w/{world.ws_a}/products", headers=auth(world.accountant)
    ).json()[0]
    body = {"name": "Changed", "unit": "pcs", "price_minor": 1000, "cost_minor": 600}
    response = client.put(
        f"/v1/w/{world.ws_a}/products/{product['id']}",
        json=body,
        headers=auth(world.accountant),
    )
    assert response.status_code == 403


def test_customers_can_be_created_updated_and_deleted(client, world):
    headers = auth(world.user_a)
    created = client.post(
        f"/v1/w/{world.ws_a}/customers",
        json={"name": "  Ada Customer  ", "email": "ada@example.com", "phone": "555-0100"},
        headers=headers,
    )
    assert created.status_code == 201
    customer = created.json()
    assert customer["name"] == "Ada Customer"
    assert len(client.get(f"/v1/w/{world.ws_a}/customers", headers=headers).json()) == 1

    updated = client.put(
        f"/v1/w/{world.ws_a}/customers/{customer['id']}",
        json={"name": "Ada Lovelace", "email": "", "phone": "555-0101"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Ada Lovelace"
    assert client.delete(
        f"/v1/w/{world.ws_a}/customers/{customer['id']}", headers=headers
    ).status_code == 204


def test_sale_deducts_stock_and_preserves_price_snapshot(client, world):
    headers = auth(world.user_a)
    product = client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]
    product_body = {
        "name": product["name"],
        "unit": product["unit"],
        "price_minor": product["price_minor"],
        "cost_minor": product["cost_minor"],
        "stock_quantity": 5,
    }
    assert client.put(
        f"/v1/w/{world.ws_a}/products/{product['id']}", json=product_body, headers=headers
    ).status_code == 200
    customer = client.post(
        f"/v1/w/{world.ws_a}/customers",
        json={"name": "Sale Customer"},
        headers=headers,
    ).json()

    response = client.post(
        f"/v1/w/{world.ws_a}/sales",
        json={"customer_id": customer["id"], "items": [{"product_id": product["id"], "quantity": 2}]},
        headers=headers,
    )
    assert response.status_code == 201
    sale = response.json()
    assert sale["total_minor"] == 2000
    assert sale["items"][0]["product_name"] == "Alpha product"
    assert sale["items"][0]["quantity"] == 2
    assert client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]["stock_quantity"] == 3
    assert client.get(f"/v1/w/{world.ws_a}/sales", headers=headers).json()[0]["id"] == sale["id"]


def test_sale_with_insufficient_stock_changes_nothing(client, world):
    headers = auth(world.user_a)
    product = client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]
    response = client.post(
        f"/v1/w/{world.ws_a}/sales",
        json={"items": [{"product_id": product["id"], "quantity": 1}]},
        headers=headers,
    )
    assert response.status_code == 409
    assert client.get(f"/v1/w/{world.ws_a}/sales", headers=headers).json() == []
    assert client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]["stock_quantity"] == 0


def test_customer_and_sale_routes_preserve_tenant_isolation(client, world):
    assert client.get(f"/v1/w/{world.ws_a}/customers", headers=auth(world.user_b)).status_code == 404
    assert client.get(f"/v1/w/{world.ws_a}/sales", headers=auth(world.user_b)).status_code == 404


def test_read_only_member_cannot_create_customer_or_sale(client, world):
    headers = auth(world.accountant)
    customer = client.post(
        f"/v1/w/{world.ws_a}/customers",
        json={"name": "No write"},
        headers=headers,
    )
    assert customer.status_code == 403
    assert client.post(
        f"/v1/w/{world.ws_a}/sales",
        json={"items": [{"product_id": str(__import__("uuid").uuid4()), "quantity": 1}]},
        headers=headers,
    ).status_code == 403


def test_customer_with_sales_history_cannot_be_deleted(client, world):
    headers = auth(world.user_a)
    product = client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]
    product_body = {
        "name": product["name"],
        "unit": product["unit"],
        "price_minor": product["price_minor"],
        "cost_minor": product["cost_minor"],
        "stock_quantity": 1,
    }
    client.put(
        f"/v1/w/{world.ws_a}/products/{product['id']}", json=product_body, headers=headers
    )
    customer = client.post(
        f"/v1/w/{world.ws_a}/customers",
        json={"name": "History Customer"},
        headers=headers,
    ).json()
    client.post(
        f"/v1/w/{world.ws_a}/sales",
        json={"customer_id": customer["id"], "items": [{"product_id": product["id"], "quantity": 1}]},
        headers=headers,
    )
    assert client.delete(
        f"/v1/w/{world.ws_a}/customers/{customer['id']}", headers=headers
    ).status_code == 409


def test_dev_session_is_disabled_outside_development(client):
    assert client.post("/v1/dev/session").status_code == 404


def test_email_registration_and_login(client, monkeypatch):
    sent = configure_email_for_test(monkeypatch)
    registration = client.post(
        "/v1/auth/register",
        json={"email": "Ada@example.com", "password": "a-very-long-test-password"},
    )
    assert registration.status_code == 201
    assert registration.json()["message"] == "Check your email to verify your account"
    assert sent[0][0:2] == ("ada@example.com", "verify_email")
    verified = client.post("/v1/auth/verify-email", json={"token": sent[0][2]})
    assert verified.status_code == 200
    created = verified.json()
    assert created["email"] == "ada@example.com"
    assert created["expires_in"] == 30 * 60
    assert client.get(
        "/v1/me/workspaces",
        headers={"Authorization": f"Bearer {created['access_token']}"},
    ).json() == []

    login = client.post(
        "/v1/auth/login",
        json={"email": "ADA@example.com", "password": "a-very-long-test-password"},
    )
    assert login.status_code == 200
    assert login.json()["user_id"] == created["user_id"]


def test_password_is_hashed_and_wrong_login_is_generic(client, admin, monkeypatch):
    sent = configure_email_for_test(monkeypatch)
    client.post(
        "/v1/auth/register",
        json={"email": "password@example.com", "password": "another-long-password"},
    )
    stored = admin.execute(
        "select password_hash from auth_users where email = 'password@example.com'"
    ).fetchone()[0]
    assert stored != "another-long-password"
    assert stored.startswith("$argon2")
    client.post("/v1/auth/verify-email", json={"token": sent[0][2]})

    wrong_password = client.post(
        "/v1/auth/login",
        json={"email": "password@example.com", "password": "incorrect-long-password"},
    )
    unknown_email = client.post(
        "/v1/auth/login",
        json={"email": "missing@example.com", "password": "incorrect-long-password"},
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_email_auth_rejects_short_password_and_duplicate_email(client, monkeypatch):
    configure_email_for_test(monkeypatch)
    short = client.post(
        "/v1/auth/register",
        json={"email": "short@example.com", "password": "too-short"},
    )
    assert short.status_code == 422
    credentials = {"email": "same@example.com", "password": "a-valid-long-password"}
    assert client.post("/v1/auth/register", json=credentials).status_code == 201
    duplicate = client.post("/v1/auth/register", json=credentials)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Unable to register with this email address"


def test_auth_config_hides_development_login_outside_development(client):
    assert client.get("/v1/auth/config").json() == {
        "development_login_available": False,
        "email_password_available": False,
    }


def test_email_registration_and_password_reset_require_mail_configuration(client):
    registration = client.post(
        "/v1/auth/register",
        json={"email": "no-mail@example.com", "password": "a-valid-long-password"},
    )
    reset = client.post(
        "/v1/auth/password-reset/request",
        json={"email": "no-mail@example.com"},
    )
    assert registration.status_code == reset.status_code == 503


def test_app_pages_send_security_headers(client):
    response = client.get("/")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_copilot_requires_authentication(client):
    assert client.get("/v1/w/00000000-0000-0000-0000-000000000001/copilot/config").status_code == 401


def test_copilot_is_hidden_until_provider_key_is_configured(client, world):
    assert client.get(
        f"/v1/w/{world.ws_a}/copilot/config",
        headers=auth(world.user_a),
    ).json()["available"] is False
    response = client.post(
        f"/v1/w/{world.ws_a}/copilot/chat",
        json={"message": "How much stock do I have?"},
        headers=auth(world.user_a),
    )
    assert response.status_code == 503


def test_copilot_action_requires_confirmation_and_cannot_be_replayed(client, world, monkeypatch):
    from app.routers import copilot

    settings = get_settings()
    monkeypatch.setattr(settings, "copilot_api_key", "test-key")
    tool_call = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "function": {
                        "name": "add_product",
                        "arguments": (
                            '{"name":"Coffee","unit":"bag","price_minor":850,'
                            '"cost_minor":400,"stock_quantity":12}'
                        ),
                    },
                }],
            },
        }],
    }

    async def fake_completion(messages):
        assert "Coffee" not in messages[0]["content"]
        return tool_call

    monkeypatch.setattr(copilot, "_request_completion", fake_completion)
    headers = auth(world.user_a)
    root = f"/v1/w/{world.ws_a}/copilot"
    response = client.post(f"{root}/chat", json={"message": "Add 12 bags of coffee"}, headers=headers)
    assert response.status_code == 200
    result = response.json()
    assert "Nothing has been changed" in result["reply"]
    assert result["proposal"]["title"] == "Add product"
    assert len(client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()) == 1

    confirmed = client.post(f"{root}/proposals/{result['proposal']['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200
    products = client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()
    assert any(product["name"] == "Coffee" and product["stock_quantity"] == 12 for product in products)
    replay = client.post(f"{root}/proposals/{result['proposal']['id']}/confirm", headers=headers)
    assert replay.status_code == 409


def test_copilot_can_cancel_proposal_without_writing(client, world, monkeypatch):
    from app.routers import copilot

    monkeypatch.setattr(get_settings(), "copilot_api_key", "test-key")

    async def fake_completion(messages):
        return {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "create_customer",
                            "arguments": '{"name":"Taylor","email":"","phone":""}',
                        },
                    }],
                },
            }],
        }

    monkeypatch.setattr(copilot, "_request_completion", fake_completion)
    headers = auth(world.user_a)
    root = f"/v1/w/{world.ws_a}/copilot"
    proposal = client.post(
        f"{root}/chat", json={"message": "Add Taylor as a customer"}, headers=headers
    ).json()["proposal"]
    cancelled = client.post(f"{root}/proposals/{proposal['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert client.get(f"/v1/w/{world.ws_a}/customers", headers=headers).json() == []
    assert client.post(f"{root}/proposals/{proposal['id']}/confirm", headers=headers).status_code == 409


def test_copilot_sale_preview_deducts_stock_only_after_confirmation(client, world, monkeypatch):
    from app.routers import copilot

    monkeypatch.setattr(get_settings(), "copilot_api_key", "test-key")
    headers = auth(world.user_a)
    products = client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()
    product = products[0]
    product_body = {
        "name": product["name"],
        "unit": product["unit"],
        "price_minor": product["price_minor"],
        "cost_minor": product["cost_minor"],
        "stock_quantity": 3,
    }
    assert client.put(
        f"/v1/w/{world.ws_a}/products/{product['id']}", json=product_body, headers=headers
    ).status_code == 200

    async def fake_completion(messages):
        return {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "record_sale",
                            "arguments": json.dumps({
                                "customer_id": None,
                                "items": [{"product_id": product["id"], "quantity": 2}],
                            }),
                        },
                    }],
                },
            }],
        }

    monkeypatch.setattr(copilot, "_request_completion", fake_completion)
    root = f"/v1/w/{world.ws_a}/copilot"
    proposal = client.post(
        f"{root}/chat",
        json={"message": "Sell two Alpha products"},
        headers=headers,
    ).json()["proposal"]
    assert "2 × Alpha product" in proposal["description"]
    assert client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]["stock_quantity"] == 3
    confirmed = client.post(f"{root}/proposals/{proposal['id']}/confirm", headers=headers)
    assert confirmed.status_code == 200
    assert client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]["stock_quantity"] == 1
    assert len(client.get(f"/v1/w/{world.ws_a}/sales", headers=headers).json()) == 1


def test_copilot_cannot_prepare_writes_for_read_only_members(client, world, monkeypatch):
    from app.routers import copilot

    monkeypatch.setattr(get_settings(), "copilot_api_key", "test-key")

    async def fake_completion(messages):
        return {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "create_customer",
                            "arguments": '{"name":"Not allowed","email":"","phone":""}',
                        },
                    }],
                },
            }],
        }

    monkeypatch.setattr(copilot, "_request_completion", fake_completion)
    response = client.post(
        f"/v1/w/{world.ws_a}/copilot/chat",
        json={"message": "Add a customer named Not allowed"},
        headers=auth(world.accountant),
    )
    assert response.status_code == 403
    assert client.get(
        f"/v1/w/{world.ws_a}/customers", headers=auth(world.user_a)
    ).json() == []


def test_copilot_report_is_read_only_and_returns_assistant_text(client, world, monkeypatch):
    from app.routers import copilot

    monkeypatch.setattr(get_settings(), "copilot_api_key", "test-key")
    observed_messages = []

    async def fake_completion(messages):
        observed_messages.extend(messages)
        return {"choices": [{"message": {"content": "There is one product in this workspace."}}]}

    monkeypatch.setattr(copilot, "_request_completion", fake_completion)
    headers = auth(world.user_a)
    response = client.post(
        f"/v1/w/{world.ws_a}/copilot/chat",
        json={"message": "How many products are in my workspace?"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == {
        "reply": "There is one product in this workspace.",
        "proposal": None,
    }
    assert "Alpha product" in observed_messages[0]["content"]
    assert client.get(f"/v1/w/{world.ws_a}/products", headers=headers).json()[0]["name"] == "Alpha product"


def test_copilot_proposal_is_workspace_scoped(client, world, monkeypatch):
    from app.routers import copilot

    monkeypatch.setattr(get_settings(), "copilot_api_key", "test-key")

    async def fake_completion(messages):
        return {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "function": {
                            "name": "create_customer",
                            "arguments": '{"name":"Private","email":"","phone":""}',
                        },
                    }],
                },
            }],
        }

    monkeypatch.setattr(copilot, "_request_completion", fake_completion)
    proposal = client.post(
        f"/v1/w/{world.ws_a}/copilot/chat",
        json={"message": "Add a customer named Private"},
        headers=auth(world.user_a),
    ).json()["proposal"]
    assert client.post(
        f"/v1/w/{world.ws_a}/copilot/proposals/{proposal['id']}/confirm",
        headers=auth(world.user_b),
    ).status_code == 404


def test_unverified_account_cannot_log_in_and_verification_is_one_time(client, monkeypatch):
    sent = configure_email_for_test(monkeypatch)
    credentials = {"email": "verify@example.com", "password": "valid-long-password"}
    assert client.post("/v1/auth/register", json=credentials).status_code == 201
    login = client.post("/v1/auth/login", json=credentials)
    assert login.status_code == 403
    verified = client.post("/v1/auth/verify-email", json={"token": sent[0][2]})
    assert verified.status_code == 200
    assert client.post("/v1/auth/verify-email", json={"token": sent[0][2]}).status_code == 400


def test_password_reset_is_generic_one_time_and_changes_password(client, monkeypatch):
    sent = configure_email_for_test(monkeypatch)
    old_credentials = {"email": "reset@example.com", "password": "old-valid-password"}
    client.post("/v1/auth/register", json=old_credentials)
    client.post("/v1/auth/verify-email", json={"token": sent[0][2]})
    reset_request = client.post(
        "/v1/auth/password-reset/request",
        json={"email": "reset@example.com"},
    )
    unknown_request = client.post(
        "/v1/auth/password-reset/request",
        json={"email": "nobody@example.com"},
    )
    assert reset_request.json() == unknown_request.json()
    reset_token = sent[-1][2]
    new_password = "new-password-is-long-enough"
    reset = client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": reset_token, "password": new_password},
    )
    assert reset.status_code == 200
    assert client.post(
        "/v1/auth/password-reset/confirm",
        json={"token": reset_token, "password": new_password},
    ).status_code == 400
    assert client.post("/v1/auth/login", json=old_credentials).status_code == 401
    assert client.post(
        "/v1/auth/login",
        json={"email": old_credentials["email"], "password": new_password},
    ).status_code == 200


def test_dev_session_issues_a_temporary_token_in_development(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "development")
    response = client.post("/v1/dev/session")
    assert response.status_code == 200
    session = response.json()
    claims = jwt.decode(
        session["access_token"],
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=settings.jwt_audience,
    )
    assert claims["sub"] == session["user_id"]
    assert session["expires_in"] == 8 * 60 * 60


def configure_email_for_test(monkeypatch):
    from app import routers

    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(settings, "smtp_sender", "TradeOS <no-reply@example.test>")
    monkeypatch.setattr(settings, "public_base_url", "http://127.0.0.1:8000")
    sent = []
    monkeypatch.setattr(
        routers.auth, "_email_security_link",
        lambda email, purpose, token: sent.append((email, purpose, token)),
    )
    return sent


def test_changes_are_audited(client, world):
    log = client.get(f"/v1/w/{world.ws_a}/audit-log", headers=auth(world.user_a)).json()
    assert {(e["action"], e["entity"]) for e in log} == {("create", "workspace"), ("create", "product")}
    assert all(e["actor_id"] == str(world.user_a) for e in log)


def test_audit_log_is_append_only_for_the_app_role(world):
    with psycopg.connect(world.app_dsn) as conn:
        conn.execute("select set_config('app.user_id', %s, true)", (str(world.user_a),))
        conn.execute("select set_config('app.workspace_id', %s, true)", (world.ws_a,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("update audit_log set action = 'tampered'")


def test_audit_log_is_append_only_even_for_the_owner(admin, world):
    with pytest.raises(psycopg.errors.RaiseException):
        admin.execute("delete from audit_log")
