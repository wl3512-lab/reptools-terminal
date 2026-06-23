"""
RepTools Database Module

Uses Postgres (e.g. Neon) when DATABASE_URL is set, otherwise falls back to a
local SQLite file. Going Postgres in production lets Render do zero-downtime
deploys (a persistent disk forces stop-start deploys → the ~20-30s 502 blip).

The rest of the app calls `with get_db() as db: db.execute(sql, params)` in the
sqlite3 style. For Postgres we wrap psycopg2 so that same call style works:
`?` placeholders are translated to `%s` and rows come back dict-accessible.
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_PG = bool(DATABASE_URL)

# Local SQLite fallback path (used only when DATABASE_URL is not set). On Render
# /data is the persistent disk; this is also the source the one-time migration
# reads from when moving onto Postgres.
_data_dir = "/data" if os.path.isdir("/data") else os.path.dirname(__file__)
DB_PATH = os.environ.get("REPTOOLS_DB_PATH", os.path.join(_data_dir, "reptools.db"))

if USE_PG:
    import psycopg2
    import psycopg2.extras


def _q(sql):
    """Translate sqlite-style '?' placeholders to psycopg2 '%s'. Safe in this
    codebase: no SQL string here contains a literal '?' or '%' (LIKE patterns are
    passed as parameters, not embedded)."""
    return sql.replace("?", "%s")


class _PgConn:
    """Adapts a psycopg2 connection to the sqlite3-style `.execute(sql, params)`
    API the rest of the app expects. Each execute returns a RealDict cursor whose
    rows support both `row['col']` and `dict(row)`, matching sqlite3.Row."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_q(sql), params)
        return cur

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


@contextmanager
def get_db():
    """Get a database connection with auto-commit. Postgres if DATABASE_URL is set,
    else local SQLite. Connection-per-call keeps it simple and robust; use Neon's
    POOLED connection string so churn is handled by their pgbouncer."""
    if USE_PG:
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield _PgConn(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


_PG_SCHEMA = """
    CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        price TEXT,
        price_num REAL DEFAULT 0,
        url TEXT,
        image TEXT,
        category TEXT NOT NULL,
        seller TEXT DEFAULT 'Various',
        rating REAL DEFAULT 4.7,
        batch TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS categories (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        icon TEXT DEFAULT '',
        description TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS clicks (
        id SERIAL PRIMARY KEY,
        product_id TEXT,
        product_name TEXT,
        category TEXT,
        agent TEXT DEFAULT 'kakobuy',
        referrer TEXT DEFAULT '',
        user_ip TEXT DEFAULT '',
        user_agent TEXT DEFAULT '',
        country TEXT DEFAULT '',
        clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS daily_stats (
        date TEXT PRIMARY KEY,
        total_clicks INTEGER DEFAULT 0,
        unique_visitors INTEGER DEFAULT 0,
        top_product TEXT DEFAULT '',
        top_category TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tracking_subscriptions (
        id SERIAL PRIMARY KEY,
        tracking_number TEXT NOT NULL,
        courier_code TEXT DEFAULT '',
        email TEXT NOT NULL,
        last_notified_status TEXT DEFAULT '',
        last_notified_at TIMESTAMP,
        unsubscribe_token TEXT,
        active INTEGER DEFAULT 1,
        marketing_consent INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(tracking_number, email)
    );
    CREATE TABLE IF NOT EXISTS email_log (
        id SERIAL PRIMARY KEY,
        email TEXT,
        tracking_number TEXT,
        status_sent TEXT,
        provider_id TEXT DEFAULT '',
        result TEXT DEFAULT '',
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS email_suppression (
        email TEXT PRIMARY KEY,
        reason TEXT DEFAULT '',
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS site_orders (
        id SERIAL PRIMARY KEY,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        data TEXT
    );
    CREATE TABLE IF NOT EXISTS tracking_reports (
        id SERIAL PRIMARY KEY,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        tracking_number TEXT,
        carrier TEXT,
        status TEXT,
        issue_type TEXT,
        description TEXT,
        email TEXT,
        resolved INTEGER DEFAULT 0,
        admin_notes TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS delivery_samples (
        tracking_number TEXT PRIMARY KEY,
        courier_code TEXT,
        origin_country TEXT,
        dest_country TEXT,
        transit_days INTEGER,
        captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_clicks_product ON clicks(product_id);
    CREATE INDEX IF NOT EXISTS idx_clicks_date ON clicks(clicked_at);
    CREATE INDEX IF NOT EXISTS idx_clicks_category ON clicks(category);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
    CREATE INDEX IF NOT EXISTS idx_subs_tracking ON tracking_subscriptions(tracking_number);
    CREATE INDEX IF NOT EXISTS idx_subs_token ON tracking_subscriptions(unsubscribe_token);
"""

_SQLITE_SCHEMA = """
    CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        price TEXT,
        price_num REAL DEFAULT 0,
        url TEXT,
        image TEXT,
        category TEXT NOT NULL,
        seller TEXT DEFAULT 'Various',
        rating REAL DEFAULT 4.7,
        batch TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS categories (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        icon TEXT DEFAULT '',
        description TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS clicks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id TEXT,
        product_name TEXT,
        category TEXT,
        agent TEXT DEFAULT 'kakobuy',
        referrer TEXT DEFAULT '',
        user_ip TEXT DEFAULT '',
        user_agent TEXT DEFAULT '',
        country TEXT DEFAULT '',
        clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS daily_stats (
        date TEXT PRIMARY KEY,
        total_clicks INTEGER DEFAULT 0,
        unique_visitors INTEGER DEFAULT 0,
        top_product TEXT DEFAULT '',
        top_category TEXT DEFAULT '',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS tracking_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_number TEXT NOT NULL,
        courier_code TEXT DEFAULT '',
        email TEXT NOT NULL,
        last_notified_status TEXT DEFAULT '',
        last_notified_at TIMESTAMP,
        unsubscribe_token TEXT,
        active INTEGER DEFAULT 1,
        marketing_consent INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(tracking_number, email)
    );
    CREATE TABLE IF NOT EXISTS email_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT,
        tracking_number TEXT,
        status_sent TEXT,
        provider_id TEXT DEFAULT '',
        result TEXT DEFAULT '',
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS email_suppression (
        email TEXT PRIMARY KEY,
        reason TEXT DEFAULT '',
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS site_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        data TEXT
    );
    CREATE TABLE IF NOT EXISTS tracking_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        tracking_number TEXT,
        carrier TEXT,
        status TEXT,
        issue_type TEXT,
        description TEXT,
        email TEXT,
        resolved INTEGER DEFAULT 0,
        admin_notes TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS delivery_samples (
        tracking_number TEXT PRIMARY KEY,
        courier_code TEXT,
        origin_country TEXT,
        dest_country TEXT,
        transit_days INTEGER,
        captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_clicks_product ON clicks(product_id);
    CREATE INDEX IF NOT EXISTS idx_clicks_date ON clicks(clicked_at);
    CREATE INDEX IF NOT EXISTS idx_clicks_category ON clicks(category);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
    CREATE INDEX IF NOT EXISTS idx_subs_tracking ON tracking_subscriptions(tracking_number);
    CREATE INDEX IF NOT EXISTS idx_subs_token ON tracking_subscriptions(unsubscribe_token);
"""


def init_db():
    """Initialize database tables (Postgres or SQLite)."""
    if USE_PG:
        with get_db() as db:
            db.executescript(_PG_SCHEMA)
        # One-time copy of existing data from the old SQLite disk, if present.
        migrate_sqlite_to_pg()
        migrate_json_stores_to_db()
        print("[DB] Postgres initialized")
        return

    with get_db() as db:
        db.executescript(_SQLITE_SCHEMA)

        # Migration: recreate clicks table without FK if old version exists
        try:
            fk_info = db.execute("PRAGMA foreign_key_list(clicks)").fetchall()
            if fk_info:
                print("[DB] Migrating clicks table (removing FK constraint)...")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS clicks_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_id TEXT, product_name TEXT, category TEXT,
                        agent TEXT DEFAULT 'kakobuy', referrer TEXT DEFAULT '',
                        user_ip TEXT DEFAULT '', user_agent TEXT DEFAULT '',
                        country TEXT DEFAULT '', clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                    INSERT OR IGNORE INTO clicks_new SELECT * FROM clicks;
                    DROP TABLE clicks;
                    ALTER TABLE clicks_new RENAME TO clicks;
                    CREATE TABLE IF NOT EXISTS delivery_samples (
        tracking_number TEXT PRIMARY KEY,
        courier_code TEXT,
        origin_country TEXT,
        dest_country TEXT,
        transit_days INTEGER,
        captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_clicks_product ON clicks(product_id);
                    CREATE INDEX IF NOT EXISTS idx_clicks_date ON clicks(clicked_at);
                    CREATE INDEX IF NOT EXISTS idx_clicks_category ON clicks(category);
                """)
                print("[DB] Clicks table migrated successfully")
        except Exception as e:
            print(f"[DB] Migration check: {e}")

        # Migration: add marketing_consent to tracking_subscriptions if missing
        try:
            cols = [r[1] for r in db.execute("PRAGMA table_info(tracking_subscriptions)").fetchall()]
            if cols and 'marketing_consent' not in cols:
                db.execute("ALTER TABLE tracking_subscriptions ADD COLUMN marketing_consent INTEGER DEFAULT 0")
                print("[DB] Added marketing_consent column to tracking_subscriptions")
        except Exception as e:
            print(f"[DB] marketing_consent migration: {e}")

    print(f"[DB] Database initialized at {DB_PATH}")


def migrate_sqlite_to_pg():
    """One-time copy of live data from the old SQLite disk into Postgres.

    Runs only when DATABASE_URL is set AND the old SQLite file still exists AND
    the destination Postgres table is empty (so it never double-imports). Copies
    the data that must survive — clicks, daily_stats, tracking_subscriptions,
    email_log, email_suppression. products/categories are re-imported from JSON
    by the app on boot, so they're skipped. Integer ids are NOT preserved (none
    are referenced externally); Postgres assigns fresh SERIAL ids."""
    if not USE_PG:
        return
    if not os.path.exists(DB_PATH):
        print("[DB] No old SQLite file to migrate from — fresh Postgres start.")
        return

    # column lists copied verbatim (excluding SERIAL id where present)
    tables = {
        "clicks": ["product_id", "product_name", "category", "agent", "referrer",
                   "user_ip", "user_agent", "country", "clicked_at"],
        "daily_stats": ["date", "total_clicks", "unique_visitors", "top_product",
                        "top_category", "updated_at"],
        "tracking_subscriptions": ["tracking_number", "courier_code", "email",
                                    "last_notified_status", "last_notified_at",
                                    "unsubscribe_token", "active", "marketing_consent",
                                    "created_at"],
        "email_log": ["email", "tracking_number", "status_sent", "provider_id",
                      "result", "sent_at"],
        "email_suppression": ["email", "reason", "added_at"],
    }

    try:
        src = sqlite3.connect(DB_PATH, timeout=10)
        src.row_factory = sqlite3.Row
    except Exception as e:
        print(f"[DB] migrate: could not open old SQLite ({e}) — skipping.")
        return

    total = 0
    try:
        with get_db() as db:
            # Serialize across gunicorn workers: both run init_db() on boot, and
            # clicks/email_log have no unique constraint, so a concurrent migration
            # would double-insert. A transaction-scoped advisory lock (works with
            # Supabase's transaction pooler) makes the loser wait, then it sees the
            # tables already populated and skips. Lock auto-releases on commit.
            db.execute("SELECT pg_advisory_xact_lock(739501)")
            for table, cols in tables.items():
                # skip if PG table already has rows (idempotent / never double-import)
                try:
                    existing = db.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
                except Exception as e:
                    print(f"[DB] migrate: dest {table} check failed ({e}) — skipping table.")
                    continue
                if existing and int(existing) > 0:
                    print(f"[DB] migrate: {table} already has {existing} rows — skip.")
                    continue
                # read source rows (old SQLite may lack a column; guard each)
                try:
                    src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})").fetchall()]
                    use_cols = [c for c in cols if c in src_cols]
                    if not use_cols:
                        continue
                    rows = src.execute(f"SELECT {', '.join(use_cols)} FROM {table}").fetchall()
                except Exception as e:
                    print(f"[DB] migrate: source {table} read failed ({e}) — skipping table.")
                    continue
                placeholders = ", ".join(["?"] * len(use_cols))
                ins = f"INSERT INTO {table} ({', '.join(use_cols)}) VALUES ({placeholders})"
                if table in ("tracking_subscriptions", "email_suppression"):
                    ins += " ON CONFLICT DO NOTHING"  # respect UNIQUE constraints
                n = 0
                for row in rows:
                    try:
                        db.execute(ins, tuple(row[c] for c in use_cols))
                        n += 1
                    except Exception as e:
                        print(f"[DB] migrate: row insert into {table} failed ({e})")
                print(f"[DB] migrate: copied {n} rows into {table}")
                total += n
    finally:
        src.close()
    print(f"[DB] migrate: done — {total} rows copied from SQLite into Postgres.")


def _upsert_product_sql():
    """Dialect-aware upsert for products keyed on id."""
    if USE_PG:
        return ("""
            INSERT INTO products (id, name, price, price_num, url, image, category, seller, rating, batch)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                name=EXCLUDED.name, price=EXCLUDED.price, price_num=EXCLUDED.price_num,
                url=EXCLUDED.url, image=EXCLUDED.image, category=EXCLUDED.category,
                seller=EXCLUDED.seller, rating=EXCLUDED.rating, batch=EXCLUDED.batch,
                updated_at=CURRENT_TIMESTAMP
        """)
    return ("""
        INSERT OR REPLACE INTO products (id, name, price, price_num, url, image, category, seller, rating, batch)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """)


def _upsert_category_sql():
    if USE_PG:
        return ("""
            INSERT INTO categories (slug, name, icon, description)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (slug) DO UPDATE SET
                name=EXCLUDED.name, icon=EXCLUDED.icon, description=EXCLUDED.description
        """)
    return ("""
        INSERT OR REPLACE INTO categories (slug, name, icon, description)
        VALUES (?, ?, ?, ?)
    """)


def import_products_from_json(json_path):
    """Import products from the existing products.json into the database."""
    if not os.path.exists(json_path):
        print(f"[DB] Products file not found: {json_path}")
        return 0

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    count = 0
    cat_sql = _upsert_category_sql()
    prod_sql = _upsert_product_sql()
    with get_db() as db:
        db.execute('DELETE FROM products')
        for cat_slug, cat_data in data.items():
            db.execute(cat_sql, (
                cat_slug,
                cat_data.get("name", cat_slug.title()),
                cat_data.get("icon", ""),
                cat_data.get("description", "")
            ))
            for item in cat_data.get("items", []):
                db.execute(prod_sql, (
                    f"{cat_slug}-{item.get('id', '')}",
                    item.get("name", ""),
                    item.get("price", ""),
                    item.get("priceNum", 0),
                    item.get("url", ""),
                    item.get("image", ""),
                    cat_slug,
                    item.get("seller", "Various"),
                    item.get("rating", 4.7),
                    item.get("batch", "")
                ))
                count += 1

    print(f"[DB] Imported {count} products from JSON")
    return count


def import_hardcoded_products(products_dict):
    """Import products from the hardcoded PRODUCTS dict in app.py."""
    count = 0
    cat_sql = _upsert_category_sql()
    prod_sql = _upsert_product_sql()
    with get_db() as db:
        for cat_slug, cat_data in products_dict.items():
            db.execute(cat_sql, (
                cat_slug,
                cat_data.get("name", cat_slug.title()),
                cat_data.get("icon", ""),
                cat_data.get("description", "")
            ))
            for item in cat_data.get("items", []):
                db.execute(prod_sql, (
                    item.get("id", ""),
                    item.get("name", ""),
                    item.get("price", ""),
                    item.get("priceNum", 0),
                    item.get("url", ""),
                    item.get("image", ""),
                    cat_slug,
                    item.get("seller", "Various"),
                    item.get("rating", 4.7),
                    item.get("batch", "")
                ))
                count += 1

    print(f"[DB] Imported {count} hardcoded products")
    return count


# ============ Product Queries ============

def get_all_products():
    """Get all products organized by category (same format as old JSON)."""
    with get_db() as db:
        categories = db.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()
        result = {}
        for cat in categories:
            items = db.execute(
                "SELECT * FROM products WHERE category = ? ORDER BY name",
                (cat["slug"],)
            ).fetchall()
            result[cat["slug"]] = {
                "name": cat["name"],
                "icon": cat["icon"],
                "description": cat["description"],
                "items": [dict(item) for item in items]
            }
        return result


def get_category_products(category):
    """Get products for a specific category."""
    with get_db() as db:
        cat = db.execute("SELECT * FROM categories WHERE slug = ?", (category,)).fetchone()
        if not cat:
            return None
        items = db.execute(
            "SELECT * FROM products WHERE category = ? ORDER BY name",
            (category,)
        ).fetchall()
        return {
            "name": cat["name"],
            "icon": cat["icon"],
            "description": cat["description"],
            "items": [dict(item) for item in items]
        }


def search_products(query, category=None, limit=20):
    """Search products by name."""
    with get_db() as db:
        if category:
            items = db.execute(
                "SELECT * FROM products WHERE name LIKE ? AND category = ? ORDER BY name LIMIT ?",
                (f"%{query}%", category, limit)
            ).fetchall()
        else:
            items = db.execute(
                "SELECT * FROM products WHERE name LIKE ? ORDER BY name LIMIT ?",
                (f"%{query}%", limit)
            ).fetchall()
        return [dict(item) for item in items]


def add_product(product_data):
    """Add a single product to the database."""
    with get_db() as db:
        db.execute(_upsert_product_sql(), (
            product_data.get("id", ""),
            product_data.get("name", ""),
            product_data.get("price", ""),
            product_data.get("priceNum", product_data.get("price_num", 0)),
            product_data.get("url", ""),
            product_data.get("image", ""),
            product_data.get("category", ""),
            product_data.get("seller", "Various"),
            product_data.get("rating", 4.7),
            product_data.get("batch", "")
        ))
    return True


def delete_product(product_id):
    """Delete a product by ID."""
    with get_db() as db:
        db.execute("DELETE FROM products WHERE id = ?", (product_id,))
    return True


# ============ Click Tracking ============

def track_click(product_id, product_name, category, agent="kakobuy", referrer="", user_ip="", user_agent=""):
    """Record an affiliate link click."""
    with get_db() as db:
        db.execute("""
            INSERT INTO clicks (product_id, product_name, category, agent, referrer, user_ip, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (product_id, product_name, category, agent, referrer, user_ip, user_agent))


def get_click_stats(days=30):
    """Get click statistics for the last N days."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    date_expr = "clicked_at::date" if USE_PG else "DATE(clicked_at)"

    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(*) as count FROM clicks WHERE clicked_at >= ?", (since,)
        ).fetchone()["count"]

        unique = db.execute(
            "SELECT COUNT(DISTINCT user_ip) as count FROM clicks WHERE clicked_at >= ?", (since,)
        ).fetchone()["count"]

        # product_name/category included in GROUP BY for Postgres strictness
        top_products = db.execute("""
            SELECT product_name, category, COUNT(*) as clicks
            FROM clicks WHERE clicked_at >= ?
            GROUP BY product_id, product_name, category ORDER BY clicks DESC LIMIT 10
        """, (since,)).fetchall()

        top_categories = db.execute("""
            SELECT category, COUNT(*) as clicks
            FROM clicks WHERE clicked_at >= ?
            GROUP BY category ORDER BY clicks DESC
        """, (since,)).fetchall()

        daily = db.execute(f"""
            SELECT {date_expr} as date, COUNT(*) as clicks
            FROM clicks WHERE clicked_at >= ?
            GROUP BY {date_expr} ORDER BY date DESC LIMIT 30
        """, (since,)).fetchall()

        top_agents = db.execute("""
            SELECT agent, COUNT(*) as clicks
            FROM clicks WHERE clicked_at >= ?
            GROUP BY agent ORDER BY clicks DESC
        """, (since,)).fetchall()

        return {
            "total_clicks": total,
            "unique_visitors": unique,
            "top_products": [dict(r) for r in top_products],
            "top_categories": [dict(r) for r in top_categories],
            "daily_clicks": [dict(r) for r in daily],
            "top_agents": [dict(r) for r in top_agents],
            "period_days": days
        }


def get_product_clicks(product_id):
    """Get click count for a specific product."""
    with get_db() as db:
        result = db.execute(
            "SELECT COUNT(*) as clicks FROM clicks WHERE product_id = ?",
            (product_id,)
        ).fetchone()
        return result["clicks"]


# ============ Email Notification Subscriptions ============

def add_subscription(tracking_number, email, courier_code="", marketing_consent=0):
    """Upsert a tracking-email subscription. Idempotent on (tracking_number, email).
    The ON CONFLICT ... DO UPDATE syntax below is supported by both Postgres and
    SQLite. Returns the unsubscribe_token."""
    import secrets
    token = secrets.token_urlsafe(18)
    mc = 1 if marketing_consent else 0
    with get_db() as db:
        db.execute("""
            INSERT INTO tracking_subscriptions (tracking_number, courier_code, email, unsubscribe_token, active, marketing_consent)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(tracking_number, email) DO UPDATE SET
                active = 1,
                courier_code = CASE WHEN excluded.courier_code != '' THEN excluded.courier_code ELSE tracking_subscriptions.courier_code END,
                marketing_consent = CASE WHEN excluded.marketing_consent = 1 THEN 1 ELSE tracking_subscriptions.marketing_consent END
        """, (tracking_number.strip().upper(), courier_code, email.strip().lower(), token, mc))
        row = db.execute(
            "SELECT unsubscribe_token FROM tracking_subscriptions WHERE tracking_number = ? AND email = ?",
            (tracking_number.strip().upper(), email.strip().lower())
        ).fetchone()
        return row["unsubscribe_token"] if row else token


def get_active_subscriptions(tracking_number):
    """All active, non-suppressed subscriptions for a tracking number."""
    with get_db() as db:
        rows = db.execute("""
            SELECT s.* FROM tracking_subscriptions s
            WHERE s.tracking_number = ? AND s.active = 1
              AND s.email NOT IN (SELECT email FROM email_suppression)
        """, (tracking_number.strip().upper(),)).fetchall()
        return [dict(r) for r in rows]


def claim_notification(subscription_id, new_status):
    """Atomic send-once guard: only returns True if THIS call transitions the
    subscription into new_status (conditional UPDATE). Safe across workers."""
    with get_db() as db:
        cur = db.execute("""
            UPDATE tracking_subscriptions
            SET last_notified_status = ?, last_notified_at = CURRENT_TIMESTAMP
            WHERE id = ? AND (last_notified_status IS NULL OR last_notified_status != ?)
        """, (new_status, subscription_id, new_status))
        return cur.rowcount > 0


def log_email(email, tracking_number, status_sent, provider_id="", result=""):
    with get_db() as db:
        db.execute("""
            INSERT INTO email_log (email, tracking_number, status_sent, provider_id, result)
            VALUES (?, ?, ?, ?, ?)
        """, (email, tracking_number, status_sent, provider_id, result))


def is_suppressed(email):
    with get_db() as db:
        return db.execute("SELECT 1 FROM email_suppression WHERE email = ?",
                          (email.strip().lower(),)).fetchone() is not None


def add_suppression(email, reason=""):
    if USE_PG:
        sql = ("INSERT INTO email_suppression (email, reason) VALUES (?, ?) "
               "ON CONFLICT (email) DO UPDATE SET reason=EXCLUDED.reason")
    else:
        sql = "INSERT OR REPLACE INTO email_suppression (email, reason) VALUES (?, ?)"
    with get_db() as db:
        db.execute(sql, (email.strip().lower(), reason))


def unsubscribe_by_token(token):
    """Deactivate a subscription via its one-click unsubscribe token. Returns the email or None."""
    with get_db() as db:
        row = db.execute("SELECT email FROM tracking_subscriptions WHERE unsubscribe_token = ?",
                         (token,)).fetchone()
        if not row:
            return None
        db.execute("UPDATE tracking_subscriptions SET active = 0 WHERE unsubscribe_token = ?", (token,))
        return row["email"]


def get_due_recheck_subscriptions(limit=200):
    """Active subscriptions for the periodic backstop re-check (Phase 3)."""
    with get_db() as db:
        rows = db.execute("""
            SELECT DISTINCT tracking_number, courier_code FROM tracking_subscriptions
            WHERE active = 1
              AND (last_notified_status IS NULL OR last_notified_status NOT IN ('delivered'))
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


# ============ Site Orders (was site_orders.json) ============

def add_site_order(order_dict):
    """Store a 'order a site' form submission. The whole dict is kept as JSON text
    so the form's fields can vary without a schema change."""
    with get_db() as db:
        db.execute("INSERT INTO site_orders (data) VALUES (?)", (json.dumps(order_dict),))
    return True


def get_site_orders():
    """All site orders, newest first — list of the original submission dicts (+ id)."""
    with get_db() as db:
        rows = db.execute("SELECT id, submitted_at, data FROM site_orders ORDER BY id DESC").fetchall()
    out = []
    for r in rows:
        try:
            d = json.loads(r["data"]) if r["data"] else {}
        except Exception:
            d = {}
        if not isinstance(d, dict):
            d = {"data": d}
        d.setdefault("id", r["id"])
        out.append(d)
    return out


# ============ Tracking Reports (was tracking_reports.json) ============

def add_tracking_report(report):
    """Store a user-submitted tracking issue report."""
    with get_db() as db:
        db.execute("""
            INSERT INTO tracking_reports
                (tracking_number, carrier, status, issue_type, description, email, resolved, admin_notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (report.get("tracking_number", ""), report.get("carrier", ""), report.get("status", ""),
              report.get("issue_type", "other"), report.get("description", ""), report.get("email", ""),
              1 if report.get("resolved") else 0, report.get("admin_notes", "")))
    return True


def get_tracking_reports():
    """All tracking reports, newest first."""
    with get_db() as db:
        rows = db.execute("""
            SELECT id, submitted_at, tracking_number, carrier, status, issue_type,
                   description, email, resolved, admin_notes
            FROM tracking_reports ORDER BY id DESC
        """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["resolved"] = bool(d.get("resolved"))   # JSON store used a real boolean
        out.append(d)
    return out


def update_tracking_report(report_id, action, notes=""):
    """Admin action on a report: toggle_resolved | update_notes | delete."""
    with get_db() as db:
        if action == "toggle_resolved":
            db.execute("UPDATE tracking_reports SET resolved = CASE WHEN resolved = 1 THEN 0 ELSE 1 END WHERE id = ?", (report_id,))
        elif action == "update_notes":
            db.execute("UPDATE tracking_reports SET admin_notes = ? WHERE id = ?", ((notes or "")[:500], report_id))
        elif action == "delete":
            db.execute("DELETE FROM tracking_reports WHERE id = ?", (report_id,))
    return True


def add_delivery_sample(tracking_number, courier_code, origin_country, dest_country, transit_days):
    """Record a delivered haul's outcome (deduped on tracking_number) so the
    delivery-time model can be rebuilt/sharpened from real outcomes over time."""
    if not tracking_number or transit_days is None:
        return False
    try:
        td = int(transit_days)
    except (TypeError, ValueError):
        return False
    if td <= 0 or td > 200:
        return False
    sql = ("INSERT INTO delivery_samples (tracking_number, courier_code, origin_country, dest_country, transit_days) "
           "VALUES (?, ?, ?, ?, ?) " +
           ("ON CONFLICT (tracking_number) DO NOTHING" if USE_PG else ""))
    if not USE_PG:
        sql = sql.replace("INSERT INTO", "INSERT OR IGNORE INTO")
    try:
        with get_db() as db:
            db.execute(sql, (tracking_number, courier_code or "", origin_country or "", dest_country or "", td))
        return True
    except Exception as e:
        print(f"[DB] add_delivery_sample: {e}")
        return False


def get_delivery_samples():
    """All captured delivery samples (for rebuilding the model)."""
    with get_db() as db:
        rows = db.execute("SELECT courier_code, origin_country, dest_country, transit_days FROM delivery_samples").fetchall()
        return [dict(r) for r in rows]


def migrate_json_stores_to_db():
    """One-time copy of the old disk JSON stores (site_orders.json,
    tracking_reports.json) into the DB. Idempotent: skips a table that already has
    rows. Advisory-locked so concurrent gunicorn workers don't double-import."""
    if not USE_PG:
        return
    _dir = "/data" if os.path.isdir("/data") else os.path.dirname(__file__)
    try:
        with get_db() as db:
            db.execute("SELECT pg_advisory_xact_lock(739502)")

            # site_orders.json
            try:
                if int(db.execute("SELECT COUNT(*) AS c FROM site_orders").fetchone()["c"]) == 0:
                    p = os.path.join(_dir, "site_orders.json")
                    if os.path.exists(p):
                        with open(p, "r", encoding="utf-8") as f:
                            orders = json.load(f) or []
                        for o in orders:
                            db.execute("INSERT INTO site_orders (data) VALUES (?)", (json.dumps(o),))
                        print(f"[DB] migrate: copied {len(orders)} site_orders")
            except Exception as e:
                print(f"[DB] migrate site_orders: {e}")

            # tracking_reports.json
            try:
                if int(db.execute("SELECT COUNT(*) AS c FROM tracking_reports").fetchone()["c"]) == 0:
                    p = os.path.join(_dir, "tracking_reports.json")
                    if os.path.exists(p):
                        with open(p, "r", encoding="utf-8") as f:
                            reps = json.load(f) or []
                        for r in reps:
                            db.execute("""
                                INSERT INTO tracking_reports
                                    (tracking_number, carrier, status, issue_type, description, email, resolved, admin_notes)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (r.get("tracking_number", ""), r.get("carrier", ""), r.get("status", ""),
                                  r.get("issue_type", "other"), r.get("description", ""), r.get("email", ""),
                                  1 if r.get("resolved") else 0, r.get("admin_notes", "")))
                        print(f"[DB] migrate: copied {len(reps)} tracking_reports")
            except Exception as e:
                print(f"[DB] migrate tracking_reports: {e}")
    except Exception as e:
        print(f"[DB] migrate_json_stores_to_db error: {e}")
