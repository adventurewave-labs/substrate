"""Static SQL shape checks.

No local Postgres (rig law: the Mac is a control plane), so DB-path bugs must be
caught without a server. The gate reviewer caught a SELECT referencing an
undeclared alias — a flat alias-declaration check over the module-level SQL
constants pins that regression class. Live round-trips ride the remote plane
(PLAN §7 W2 bootstrap).
"""

import pathlib
import re

from substrate.er.engine import PERSON_LOAD_SQL


def _declared_aliases(sql: str) -> set[str]:
    aliases: set[str] = set()
    for pattern in (
        r"\bFROM\s+([a-z_][a-z0-9_]*)\s+([a-z_][a-z0-9_]*)\b",  # FROM table alias
        r"\bJOIN\s+([a-z_][a-z0-9_]*)\s+([a-z_][a-z0-9_]*)\b",  # JOIN table alias
        r"\bFROM\s+([a-z_][a-z0-9_]*)\b(?!\s+[a-z_])",  # FROM table (no alias)
        r"\bJOIN\s+([a-z_][a-z0-9_]*)\b(?!\s+[a-z_])",  # JOIN table (no alias)
        r"\)\s+(?:AS\s+)?([a-z_][a-z0-9_]*)\s+ON\b",  # ) subquery_alias ON
    ):
        for match in re.findall(pattern, sql, flags=re.IGNORECASE):
            # Single-group patterns return strings, not tuples — guard the unpack.
            groups = match if isinstance(match, tuple) else (match,)
            aliases.update(g for g in groups if g and g.upper() not in {"ON", "TRUE"})
    return aliases


def test_person_load_sql_every_qualified_reference_has_a_declared_alias():
    declared = _declared_aliases(PERSON_LOAD_SQL)
    refs = set(re.findall(r"\b([a-z_][a-z0-9_]*)\s*\.\s*[a-z_][a-z0-9_]*", PERSON_LOAD_SQL))
    # %s placeholders have no dot; function-qualified names don't appear here.
    unqualified = refs - declared
    assert not unqualified, f"aliases used but never declared: {sorted(unqualified)}"


def test_person_load_sql_scopes_bitemporal_axes():
    # Gate finding: filtering only txn_to IS NULL treats a world-ended position as
    # current — the two temporal axes must both be honored.
    assert "pos.txn_to IS NULL" in PERSON_LOAD_SQL
    assert "pos.valid_end IS NULL OR pos.valid_end >= CURRENT_DATE" in PERSON_LOAD_SQL


def test_pair_sql_deterministic_version_ordering():
    # Gate round-11: same-timestamp versions must not reverse — valid_start
    # disambiguates world time within the same transaction-time bucket.
    from substrate.signals.detector import _PAIR_SQL

    assert "ORDER BY p.txn_from, p.valid_start, p.id" in _PAIR_SQL
    expected = (
        "ORDER BY cur.person_id, cur.txn_from, cur.valid_start, cur.id"
    )
    assert expected in _PAIR_SQL


def test_person_load_sql_deterministic_employer_pick():
    # Gate finding: LATERAL ... LIMIT 1 without ORDER BY is nondeterministic.
    assert re.search(r"ORDER BY\s+pos\.txn_from DESC\s+LIMIT 1", PERSON_LOAD_SQL)


def _migration_tables(sql: str) -> dict[str, set[str]]:
    """CREATE TABLE blocks → {table: {column, ...}}."""
    tables: dict[str, set[str]] = {}
    for match in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", sql, flags=re.S):
        name, body = match
        cols: set[str] = set()
        for line in body.splitlines():
            line = line.strip().rstrip(",")
            skips = ("--", "CONSTRAINT", "EXCLUDE", "PRIMARY", "UNIQUE", "CHECK")
            if not line or line.startswith(skips):
                continue
            token = line.split()[0] if line.split() else ""
            if token:
                cols.add(token)
        tables[name] = cols
    return tables


def test_migration_indexes_only_reference_declared_columns():
    # Gate round-1 finding: 004 indexed funding_events.announced_at, a column that
    # does not exist — the whole migration aborted. This checker pins the class.
    from substrate.db import MIGRATIONS_DIR

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text()
        tables = _migration_tables(sql)
        for match in re.findall(r"CREATE INDEX \w+ ON (\w+) \(([^)]+)\)", sql):
            table, col_list = match
            if table not in tables:
                continue  # index on a table defined in an earlier migration
            for column in col_list.split(","):
                column = column.strip().split()[0]
                assert column in tables[table], (
                    f"{path.name}: index column {table}.{column} is not declared"
                )


def test_migrations_ship_inside_the_package():
    # Deploy-drift pin (first Railway deploy): the runner must resolve migrations
    # INSIDE the installed package — repo-relative resolution silently reported
    # "nothing pending" over an empty database in the deployed image.
    import substrate.db as db_module
    from substrate.db import MIGRATIONS_DIR

    package_dir = pathlib.Path(db_module.__file__).resolve().parent
    assert MIGRATIONS_DIR.parent == package_dir  # inside the package, not the repo
    assert (MIGRATIONS_DIR / "001_init.sql").exists()


def test_dockerfile_guards_the_installed_resolution_path():
    dockerfile = pathlib.Path(__file__).resolve().parents[1] / "Dockerfile"
    text = dockerfile.read_text()
    assert "import substrate.db as d" in text  # guard checks the installed path
    assert "COPY db/" not in text  # the stale source-tree copy must not return


def test_seniority_backfill_migration_matches_python_classifier():
    # Gate round-5: migration 005 hand-copies the classifier's keyword table —
    # pin the two against drift. Parses the SQL band regexes and compares the
    # keyword sets (as plain words) against the Python classifier's table.
    from substrate.db import MIGRATIONS_DIR

    migrations_dir = MIGRATIONS_DIR  # substrate package migrations
    migration = next(
        f for f in sorted(migrations_dir.glob("*.sql")) if "backfill_seniority" in f.name
    )
    body = migration.read_text()

    # Python side: band → keyword words (flattened)
    import substrate.seniority as sen

    py_bands = [band for band, _ in sen._SENIORITY_KEYWORDS]

    # SQL side: ordered band lines with their regex alternatives
    sql_lines = [
        line for line in body.splitlines()
        if "THEN '" in line and "\\m" in line
    ]
    sql_bands = []
    for line in sql_lines:
        band = line.split("THEN '")[1].split("'")[0]
        match = re.search(r"\\m\((.*?)\)\\M", line)
        keywords = (
            match.group(1).split("|")
            if match
            else re.search(r"\\m(.*?)\\M", line).group(1).split("|")
        )
        # SQL regexes must escape literal dots: an unescaped "." is a wildcard
        # and matches "srxdirector" (gate review, W7–8 r7).
        for k in keywords:
            assert re.search(r"(?<!\\)\.", k) is None, (
                f"unescaped dot in {band!r} keyword {k!r} (wildcard, not literal)"
            )
        sql_bands.append((band, {k.replace("\\.", ".") for k in keywords}))

    # Bands appear in the same order.
    assert [b for b, _ in sql_bands] == py_bands

    # Each SQL keyword set matches the Python keyword set for that band.
    # Trailing dots normalize away on both sides: "sr." and "sr" match
    # identically under word-boundary regexes (a dot can't end a word).
    def _norm(keywords: set[str]) -> set[str]:
        return {k.rstrip(".") for k in keywords}

    for band, sql_keywords in sql_bands:
        py_keywords = {
            k for b, keywords in sen._SENIORITY_KEYWORDS if b == band for k in keywords
        }
        normalized = _norm({k.replace("\\.", ".") for k in sql_keywords})
        assert normalized == _norm(py_keywords), f"drift in band {band!r}"


def test_migration_006_pins_delivery_attempts():
    # Gate round-11: the bounded-retry column is schema-backed, not just app code.
    from substrate.db import MIGRATIONS_DIR

    migration = next(
        f for f in sorted(MIGRATIONS_DIR.glob("*.sql")) if "delivery_attempts" in f.name
    )
    needle = (
        "ADD COLUMN IF NOT EXISTS delivery_attempts int NOT NULL DEFAULT 0"
    )
    assert needle in migration.read_text()
