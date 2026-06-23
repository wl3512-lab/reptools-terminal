"""Smoke tests for the Flask app: key routes load, and the input-validation
bug fixes hold (these are exactly the regressions worth catching pre-deploy)."""
import pytest

import app as appmod


@pytest.fixture(scope="module")
def client():
    appmod.app.config["TESTING"] = True
    return appmod.app.test_client()


def test_home_ok(client):
    assert client.get("/").status_code == 200


def test_tools_ok(client):
    assert client.get("/tools").status_code == 200


def test_products_ok(client):
    assert client.get("/products").status_code == 200


def test_subscribe_rejects_undefined(client):
    # the literal "undefined" the frontend sends when the field is empty
    r = client.post("/api/subscribe-tracking",
                    json={"tracking_number": "undefined", "email": "a@b.com"})
    assert r.status_code == 400


def test_subscribe_rejects_no_digit(client):
    # real tracking numbers always have a digit
    r = client.post("/api/subscribe-tracking",
                    json={"tracking_number": "ABCDEFGH", "email": "a@b.com"})
    assert r.status_code == 400


def test_subscribe_rejects_bad_email(client):
    r = client.post("/api/subscribe-tracking",
                    json={"tracking_number": "EB1234567CN", "email": "not-an-email"})
    assert r.status_code == 400


def test_safe_int_helper():
    assert appmod._safe_int("abc", 30) == 30
    assert appmod._safe_int("5", 30) == 5
    assert appmod._safe_int(None, 7) == 7
    assert appmod._safe_int("12", 0) == 12


def test_malformed_json_no_500(client):
    # request.json -> get_json(silent=True) guard: must not 500
    r = client.post("/api/identify-product", data="not json",
                    content_type="application/json")
    assert r.status_code != 500
