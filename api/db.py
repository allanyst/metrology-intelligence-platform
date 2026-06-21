"""Thin PostgreSQL connection helper — no ORM, just psycopg2."""
import os
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DB_URL", "postgresql://mip:mip_pass@localhost:5436/mip_db")


def get_conn():
    return psycopg2.connect(DB_URL)


def query(sql: str, params=None) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
