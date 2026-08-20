from __future__ import annotations

import json
import sqlite3
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
"""


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
            return [dict(row) for row in conn.execute(
                """SELECT p.id,p.source,p.source_id,p.title,p.updated_at,
                m.destination_id AS shopify_id FROM products p LEFT JOIN mappings m
                ON m.source=p.source AND m.source_id=p.source_id AND m.destination='shopify'
                ORDER BY p.updated_at DESC"""
            )]

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
