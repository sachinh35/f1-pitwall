"""Unit tests for scripts/migrate.py's pure file-discovery/version-parsing logic."""
from pathlib import Path

import pytest

from scripts.migrate import discover_migrations, migration_version


def test_migration_version_parses_leading_number() -> None:
    assert migration_version(Path("0001_baseline.sql")) == 1
    assert migration_version(Path("0042_something_else.sql")) == 42


def test_migration_version_rejects_files_without_numeric_prefix() -> None:
    with pytest.raises(ValueError):
        migration_version(Path("baseline.sql"))


def test_discover_migrations_sorted_by_version_not_filename(tmp_path: Path) -> None:
    # Deliberately create out of order, and with a version that would sort
    # wrong lexicographically if treated as a string (0010 vs 0002).
    (tmp_path / "0010_later.sql").write_text("-- later")
    (tmp_path / "0002_earlier.sql").write_text("-- earlier")
    (tmp_path / "0001_first.sql").write_text("-- first")

    result = discover_migrations(tmp_path)

    assert [p.name for p in result] == ["0001_first.sql", "0002_earlier.sql", "0010_later.sql"]


def test_real_migrations_directory_is_discoverable_and_ordered() -> None:
    """Sanity check against the actual migrations/ directory shipped with the project."""
    result = discover_migrations()
    versions = [migration_version(p) for p in result]
    assert versions == sorted(versions)
    assert 1 in versions  # 0001_baseline.sql must exist
