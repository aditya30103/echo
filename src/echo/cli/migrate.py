"""`echo migrate-data` implementation.

One-time helper that moves (or copies) an existing pre-packaging Echo
install into the new ~/.echo/ data directory. Saves re-running expensive
enrichments (10K YouTube quota) and reflections (~$5 of GPT-4o spend).

What gets migrated (whatever exists at the source):
  - echo.db, echo.db-shm, echo.db-wal     -> <data_dir>/echo.db*
  - lancedb/                              -> <data_dir>/lancedb/
  - private/annotations.yaml              -> <data_dir>/private/annotations.yaml

By default we COPY (safer; the source survives so you can verify before
deleting manually). --move uses os.replace where possible for atomic moves.

Refuses to overwrite existing destinations unless --force is set.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import typer

# Files / dirs to migrate. (relative_source_path, "kind: file|dir", "description")
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("echo.db",                    "file", "main SQLite database"),
    ("echo.db-shm",                "file", "SQLite shared memory (WAL)"),
    ("echo.db-wal",                "file", "SQLite write-ahead log"),
    ("lancedb",                    "dir",  "LanceDB vector index"),
    ("private/annotations.yaml",   "file", "personal life-context annotations"),
)


@dataclass
class MigrationItem:
    src: Path
    dst: Path
    kind: str         # "file" or "dir"
    description: str
    exists: bool      # source exists?
    will_overwrite: bool  # dst exists?


def plan(source_dir: Path, data_dir: Path) -> list[MigrationItem]:
    """Compute what would migrate from source_dir into data_dir.

    Pure function: never touches disk beyond `exists()` checks. Returns the
    full set of items considered (so the caller can show "skipped — missing"
    for sources that aren't present at the source).
    """
    items: list[MigrationItem] = []
    for rel, kind, desc in _MIGRATIONS:
        src = source_dir / rel
        dst = data_dir / rel
        items.append(MigrationItem(
            src=src, dst=dst, kind=kind, description=desc,
            exists=src.exists(),
            will_overwrite=dst.exists(),
        ))
    return items


def execute(
    items: list[MigrationItem],
    *,
    move: bool = False,
    force: bool = False,
) -> tuple[int, int, list[str]]:
    """Apply a migration plan.

    Returns (count_applied, count_skipped, errors). Errors are non-fatal
    per-item messages; the caller decides how to surface them.
    """
    applied = 0
    skipped = 0
    errors: list[str] = []

    for item in items:
        if not item.exists:
            skipped += 1
            continue
        if item.will_overwrite and not force:
            errors.append(
                f"{item.src.name}: destination exists at {item.dst}; "
                f"re-run with --force to overwrite."
            )
            skipped += 1
            continue

        try:
            item.dst.parent.mkdir(parents=True, exist_ok=True)
            if item.will_overwrite and force:
                if item.kind == "file":
                    item.dst.unlink()
                else:
                    shutil.rmtree(item.dst)
            if move:
                shutil.move(str(item.src), str(item.dst))
            else:
                if item.kind == "file":
                    shutil.copy2(item.src, item.dst)
                else:
                    shutil.copytree(item.src, item.dst)
            applied += 1
        except Exception as exc:
            errors.append(f"{item.src.name}: {type(exc).__name__}: {exc}")
            skipped += 1

    return applied, skipped, errors


def render_plan(items: list[MigrationItem], *, move: bool, force: bool) -> str:
    """Format the plan for human review. Used by --dry-run and the confirmation
    prompt before a live migration."""
    verb = "MOVE" if move else "COPY"
    lines: list[str] = []
    for item in items:
        if not item.exists:
            status = "skip (source not found)"
        elif item.will_overwrite and not force:
            status = f"BLOCKED (destination exists - use --force)"
        elif item.will_overwrite and force:
            status = f"{verb} + overwrite"
        else:
            status = verb
        lines.append(f"  [{status}]  {item.src} -> {item.dst}  ({item.description})")
    return "\n".join(lines)


def migrate_data(
    source: Path,
    data_dir: Path,
    *,
    move: bool = False,
    force: bool = False,
    dry_run: bool = False,
    yes: bool = False,
) -> None:
    """Top-level entry called by the `echo migrate-data` CLI subcommand.

    Args:
        source:   Old install root (e.g. D:/Projects/Echo).
        data_dir: New data dir (typically config.data_dir = ~/.echo).
        move:     Use os.move semantics rather than copy.
        force:    Overwrite existing destinations.
        dry_run:  Print what would happen; touch nothing.
        yes:      Skip the confirmation prompt.
    """
    source   = source.expanduser().resolve()
    data_dir = data_dir.expanduser().resolve()

    if source == data_dir:
        typer.echo(f"ERROR: source ({source}) is the same as destination. Nothing to migrate.")
        raise typer.Exit(code=1)
    if not source.exists():
        typer.echo(f"ERROR: source directory does not exist: {source}")
        raise typer.Exit(code=1)

    items = plan(source, data_dir)
    typer.echo(f"Migration plan: {source}  ->  {data_dir}")
    typer.echo(f"Mode: {'MOVE' if move else 'COPY'}{' (overwrite enabled)' if force else ''}")
    typer.echo("")
    typer.echo(render_plan(items, move=move, force=force))
    typer.echo("")

    actionable = sum(1 for i in items if i.exists and not (i.will_overwrite and not force))
    if actionable == 0:
        typer.echo("Nothing to do (no actionable items in the plan).")
        return

    if dry_run:
        typer.echo("[dry-run] no changes made.")
        return

    if not yes and not typer.confirm(f"Proceed with {actionable} migration(s)?", default=False):
        typer.echo("Aborted.")
        raise typer.Exit(code=1)

    data_dir.mkdir(parents=True, exist_ok=True)
    applied, skipped, errors = execute(items, move=move, force=force)

    typer.echo("")
    typer.echo(f"Migration complete: {applied} applied, {skipped} skipped.")
    if errors:
        typer.echo(f"\n{len(errors)} error(s):")
        for err in errors:
            typer.echo(f"  - {err}")
        raise typer.Exit(code=1)
