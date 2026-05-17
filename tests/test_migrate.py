"""Tests for `echo migrate-data` — specifically the 0-byte placeholder handling.

Friends hit this when they run any pipeline step (or even `echo doctor` in
some paths) against a fresh ~/.echo/ before doing migrate-data: sqlite_utils
opens the connection eagerly and leaves a 0-byte echo.db sitting there. Without
the placeholder check, migrate-data refuses to copy the real db without --force.
"""

from pathlib import Path

from echo.cli.migrate import plan, execute, _is_placeholder


def _seed_source(source: Path) -> None:
    """Build a minimal source dir mimicking a legacy pre-packaging install."""
    (source / "echo.db").write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    (source / "lancedb").mkdir()
    (source / "lancedb" / "table.lance").write_bytes(b"fake-lance-data")
    (source / "private").mkdir()
    (source / "private" / "annotations.yaml").write_text("life:\n  - event\n")


# ── _is_placeholder ────────────────────────────────────────────────────────────

def test_placeholder_zero_byte_file(tmp_path):
    f = tmp_path / "echo.db"
    f.write_bytes(b"")
    assert _is_placeholder(f, "file") is True


def test_placeholder_non_empty_file(tmp_path):
    f = tmp_path / "echo.db"
    f.write_bytes(b"real data here")
    assert _is_placeholder(f, "file") is False


def test_placeholder_empty_directory(tmp_path):
    d = tmp_path / "lancedb"
    d.mkdir()
    assert _is_placeholder(d, "dir") is True


def test_placeholder_non_empty_directory(tmp_path):
    d = tmp_path / "lancedb"
    d.mkdir()
    (d / "table.lance").write_text("x")
    assert _is_placeholder(d, "dir") is False


# ── plan() integration ─────────────────────────────────────────────────────────

def test_plan_ignores_zero_byte_placeholder(tmp_path):
    """A 0-byte echo.db at the destination should NOT be marked will_overwrite.

    This is the real-world regression that surfaced during the Echo packaging
    rollout: a prior pipeline call had eagerly opened sqlite_utils.Database,
    leaving a 0-byte file that then blocked migrate-data.
    """
    source = tmp_path / "src"
    dest   = tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _seed_source(source)

    # Simulate the placeholder leftover
    (dest / "echo.db").write_bytes(b"")

    items = plan(source, dest)
    db_item = next(i for i in items if i.src.name == "echo.db")

    assert db_item.exists is True
    assert db_item.will_overwrite is False, "0-byte placeholder must not block migration"


def test_plan_blocks_on_real_destination(tmp_path):
    """A non-empty destination should still set will_overwrite=True."""
    source = tmp_path / "src"
    dest   = tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _seed_source(source)

    (dest / "echo.db").write_bytes(b"real legacy data, do not clobber")

    items = plan(source, dest)
    db_item = next(i for i in items if i.src.name == "echo.db")

    assert db_item.will_overwrite is True


# ── execute() integration ──────────────────────────────────────────────────────

def test_execute_silently_clears_placeholder(tmp_path):
    """Without --force, a 0-byte placeholder is cleared and the real file copied."""
    source = tmp_path / "src"
    dest   = tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _seed_source(source)
    (dest / "echo.db").write_bytes(b"")  # the placeholder

    items = plan(source, dest)
    applied, _, errors = execute(items, move=False, force=False)

    assert errors == []
    assert applied >= 1
    copied = (dest / "echo.db").read_bytes()
    assert copied.startswith(b"SQLite format 3"), "real db should have replaced the placeholder"


def test_execute_clears_empty_placeholder_directory(tmp_path):
    """An empty lancedb/ at the destination should also be silently cleared."""
    source = tmp_path / "src"
    dest   = tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _seed_source(source)
    (dest / "lancedb").mkdir()  # empty placeholder dir

    items = plan(source, dest)
    applied, _, errors = execute(items, move=False, force=False)

    assert errors == []
    assert (dest / "lancedb" / "table.lance").exists()


def test_execute_refuses_real_destination_without_force(tmp_path):
    """A non-empty destination still blocks without --force (no regression)."""
    source = tmp_path / "src"
    dest   = tmp_path / "dst"
    source.mkdir()
    dest.mkdir()
    _seed_source(source)
    (dest / "echo.db").write_bytes(b"real legacy data")

    items = plan(source, dest)
    _, _, errors = execute(items, move=False, force=False)

    assert any("echo.db" in e and "force" in e for e in errors)
    # And the real file is untouched:
    assert (dest / "echo.db").read_bytes() == b"real legacy data"
