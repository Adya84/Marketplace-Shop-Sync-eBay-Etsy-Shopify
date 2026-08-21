from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone

from .models import Product


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS credentials (
  provider TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  payload TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source, source_id)
);
CREATE TABLE IF NOT EXISTS mappings (
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  destination TEXT NOT NULL,
  destination_id TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  PRIMARY KEY(source, source_id, destination)
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  message TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS duplicate_approvals (
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  destination TEXT NOT NULL,
  approved_at TEXT NOT NULL,
  PRIMARY KEY(source, source_id, destination)
);
CREATE TABLE IF NOT EXISTS completed_dismissals (
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  destination TEXT NOT NULL,
  dismissed_at TEXT NOT NULL,
  PRIMARY KEY(source, source_id, destination)
);
"""


def normalized_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path):
        self.path = path
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def put_credential(self, provider: str, encrypted_payload: str):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO credentials VALUES (?, ?, ?) ON CONFLICT(provider) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (provider, encrypted_payload, now()),
            )

    def get_credential(self, provider: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM credentials WHERE provider=?", (provider,)).fetchone()
            return row[0] if row else None

    def delete_credential(self, provider: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM credentials WHERE provider=?", (provider,))

    def save_product(self, product: Product):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO products(source, source_id, title, payload, updated_at) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source, source_id) DO UPDATE SET title=excluded.title, payload=excluded.payload, updated_at=excluded.updated_at""",
                (product.source, product.source_id, product.title, json.dumps(product.to_dict()), now()),
            )

    def list_products(self):
        with self.connect() as conn:
            products = [dict(row) for row in conn.execute(
                """SELECT p.id,p.source,p.source_id,p.title,p.payload,p.updated_at,
                m.destination_id AS shopify_id,
                CASE WHEN d.source IS NULL THEN 0 ELSE 1 END AS completed_hidden
                FROM products p LEFT JOIN mappings m
                ON m.source=p.source AND m.source_id=p.source_id AND m.destination='shopify'
                LEFT JOIN completed_dismissals d
                ON d.source=p.source AND d.source_id=p.source_id AND d.destination='shopify'
                ORDER BY p.updated_at DESC"""
            )]
            approvals = {
                (row["source"], row["source_id"], row["destination"])
                for row in conn.execute("SELECT source,source_id,destination FROM duplicate_approvals")
            }
        counts = {}
        for product in products:
            key = normalized_title(product["title"])
            counts[key] = counts.get(key, 0) + 1
        for product in products:
            product["normalized_title"] = normalized_title(product["title"])
            product["is_duplicate"] = counts[product["normalized_title"]] > 1
            product["duplicate_approved_shopify"] = (product["source"], product["source_id"], "shopify") in approvals
            product["duplicate_approved_etsy"] = (product["source"], product["source_id"], "etsy") in approvals
            product["duplicate_approved_ebay"] = (product["source"], product["source_id"], "ebay") in approvals
            try:
                payload = json.loads(product.pop("payload") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = {}
            variants = payload.get("variants") or []
            quantities = []
            skus = []
            for variant in variants:
                try:
                    quantities.append(max(0, int(variant.get("quantity") or 0)))
                except (TypeError, ValueError):
                    quantities.append(0)
                sku = str(variant.get("sku") or "").strip()
                if sku:
                    skus.append(sku)
            product["stock_total"] = sum(quantities)
            product["variant_count"] = len(variants)
            product["skus"] = list(dict.fromkeys(skus))
            product["sku_summary"] = ", ".join(product["skus"][:3])
            if len(product["skus"]) > 3:
                product["sku_summary"] += f" +{len(product['skus']) - 3} more"
        return products

    def duplicate_is_blocked(self, source: str, source_id: str, destination: str) -> bool:
        products = self.list_products()
        product = next((p for p in products if p["source"] == source and p["source_id"] == source_id), None)
        return bool(product and product["is_duplicate"] and not product.get(f"duplicate_approved_{destination}"))

    def approve_duplicate(self, source: str, source_id: str, destination: str):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO duplicate_approvals VALUES (?, ?, ?, ?)",
                (source, source_id, destination, now()),
            )

    def get_product(self, source: str, source_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM products WHERE source=? AND source_id=?", (source, source_id)).fetchone()
            return json.loads(row[0]) if row else None

    def save_mapping(self, source: str, source_id: str, destination: str, destination_id: str, payload: dict):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO mappings VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(source,source_id,destination)
                DO UPDATE SET destination_id=excluded.destination_id,payload=excluded.payload,updated_at=excluded.updated_at""",
                (source, source_id, destination, destination_id, json.dumps(payload), now()),
            )
            conn.execute(
                "DELETE FROM completed_dismissals WHERE source=? AND source_id=? AND destination=?",
                (source, source_id, destination),
            )

    def clear_completed(self, destination: str = "shopify"):
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO completed_dismissals(source,source_id,destination,dismissed_at)
                SELECT source,source_id,destination,? FROM mappings WHERE destination=?""",
                (now(), destination),
            )

    def create_job(self, kind: str) -> int:
        stamp = now()
        with self.connect() as conn:
            cur = conn.execute("INSERT INTO jobs(kind,status,created_at,updated_at) VALUES (?, 'queued', ?, ?)", (kind, stamp, stamp))
            return cur.lastrowid

    def update_job(self, job_id: int, **values):
        allowed = {"status", "progress", "total", "message"}
        values = {k: v for k, v in values.items() if k in allowed}
        values["updated_at"] = now()
        sql = ",".join(f"{k}=?" for k in values)
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {sql} WHERE id=?", (*values.values(), job_id))

    def list_jobs(self, limit=20):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))]

    def clear_finished_jobs(self):
        with self.connect() as conn:
            conn.execute("DELETE FROM jobs WHERE status IN ('complete', 'failed')")
