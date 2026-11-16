"""Database access: connections and the SQL migration runner.

Migration contract: numbered ``*.sql`` files shipped INSIDE the package
(``substrate/migrations``), applied in lexical order, each in its own transaction,
recorded in ``schema_migrations``. SQL files must not carry their own BEGIN/COMMIT.

Package-relative resolution is deliberate: it is identical from a repo checkout and
from an installed image — a deploy can never silently resolve a different (or
missing) migrations directory than the one the code shipped with.
"""

from __future__ import annotations

from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url)


def applied_versions(conn: psycopg.Connection) -> set[str]:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    text PRIMARY KEY,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def run_migrations(
    conn: psycopg.Connection, migrations_dir: Path | None = None
) -> list[str]:
    """Apply pending migrations in lexical order; returns the versions applied now."""
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    done = applied_versions(conn)
    conn.commit()

    applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.name
        if version in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
            )
        applied.append(version)
    conn.commit()
    return applied
