"""
Minimal migration runner.

Applies any `migrations/*.sql` file not yet recorded in the `schema_migrations`
table, in filename order (each file's leading numeric prefix is its version).
Deliberately not a heavy framework like Alembic - the schema is small enough
that plain, idempotent SQL files plus a version-tracking table are enough.

Usage:
    uv run python -m scripts.migrate

(Run as a module, not a bare script path, so the project root - and therefore
`utils` - is importable.)
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import List, Set

import asyncpg

from utils.database import DatabaseManager

logger = logging.getLogger(__name__)

MIGRATIONS_DIR: Path = Path(__file__).resolve().parent.parent / "migrations"
_VERSION_PATTERN = re.compile(r"^(\d+)_")


def migration_version(path: Path) -> int:
    """Extract the leading numeric version from a migration filename (e.g. 2 from '0002_lap_aggregates.sql')."""
    match = _VERSION_PATTERN.match(path.name)
    if not match:
        raise ValueError(f"Migration file '{path.name}' must start with a numeric version prefix, e.g. '0001_'.")
    return int(match.group(1))


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> List[Path]:
    """Return all migration files under `migrations_dir`, sorted by their numeric version."""
    return sorted(migrations_dir.glob("*.sql"), key=migration_version)


async def _ensure_migrations_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


async def _already_applied_versions(conn: asyncpg.Connection) -> Set[int]:
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {row["version"] for row in rows}


async def apply_pending_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> List[int]:
    """
    Apply every migration file not yet recorded in schema_migrations, in order.

    Returns the list of versions applied during this run (empty if the
    database was already up to date).
    """
    applied_now: List[int] = []
    async with DatabaseManager.get_connection() as conn:
        await _ensure_migrations_table(conn)
        already_applied = await _already_applied_versions(conn)

        for path in discover_migrations(migrations_dir):
            version = migration_version(path)
            if version in already_applied:
                logger.info("Skipping already-applied migration %s", path.name)
                continue

            logger.info("Applying migration %s", path.name)
            sql = path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1) ON CONFLICT (version) DO NOTHING",
                    version,
                )
            applied_now.append(version)

    return applied_now


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    applied = await apply_pending_migrations()
    if applied:
        logger.info("Applied migrations: %s", applied)
    else:
        logger.info("No pending migrations - database is up to date.")
    await DatabaseManager.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
