"""Tests for the dual-dialect database module (running on the SQLite fallback)."""
import database

database.init_db()


def test_subscription_lifecycle():
    tok = database.add_subscription("LXTEST0001CN", "sub1@x.com", courier_code="takesend", marketing_consent=1)
    assert tok
    subs = database.get_active_subscriptions("lxtest0001cn")  # case-insensitive
    assert len(subs) == 1
    assert subs[0]["email"] == "sub1@x.com"
    assert subs[0]["courier_code"] == "takesend"
    sid = subs[0]["id"]
    # atomic send-once guard
    assert database.claim_notification(sid, "in_transit") is True
    assert database.claim_notification(sid, "in_transit") is False
    # idempotent upsert — re-subscribing doesn't duplicate
    database.add_subscription("LXTEST0001CN", "sub1@x.com")
    assert len(database.get_active_subscriptions("LXTEST0001CN")) == 1
    # unsubscribe
    assert database.unsubscribe_by_token(tok) == "sub1@x.com"
    assert database.get_active_subscriptions("LXTEST0001CN") == []


def test_click_stats():
    database.track_click("cat-x", "Prod", "shoes", agent="kakobuy", user_ip="1.1.1.1")
    database.track_click("cat-x", "Prod", "shoes", agent="cnfans", user_ip="1.1.1.2")
    s = database.get_click_stats(30)
    assert s["total_clicks"] >= 2
    assert s["unique_visitors"] >= 2
    assert isinstance(s["daily_clicks"], list)
    assert isinstance(s["top_products"], list)


def test_suppression():
    database.add_suppression("Bounce@X.com", "bounce")
    assert database.is_suppressed("bounce@x.com") is True
    assert database.is_suppressed("nobody@x.com") is False


def test_suppressed_email_excluded_from_active():
    database.add_subscription("LXTEST0002CN", "supp@x.com")
    assert len(database.get_active_subscriptions("LXTEST0002CN")) == 1
    database.add_suppression("supp@x.com", "complaint")
    assert database.get_active_subscriptions("LXTEST0002CN") == []


def test_site_orders():
    database.add_site_order({"submitted_at": "2026-01-01", "brand_name": "Acme", "email": "o@x.com"})
    orders = database.get_site_orders()
    assert len(orders) >= 1
    assert orders[0].get("brand_name") == "Acme"
    assert "id" in orders[0]


def test_tracking_reports():
    database.add_tracking_report({"tracking_number": "RPT0001CN", "description": "stuck", "email": "r@x.com"})
    reps = database.get_tracking_reports()
    assert len(reps) >= 1
    rid = reps[0]["id"]
    assert reps[0]["resolved"] is False
    database.update_tracking_report(rid, "toggle_resolved")
    updated = [r for r in database.get_tracking_reports() if r["id"] == rid][0]
    assert updated["resolved"] is True
    database.update_tracking_report(rid, "update_notes", "looked into it")
    updated = [r for r in database.get_tracking_reports() if r["id"] == rid][0]
    assert updated["admin_notes"] == "looked into it"
    database.update_tracking_report(rid, "delete")
    assert not any(r["id"] == rid for r in database.get_tracking_reports())
