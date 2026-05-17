"""Echo CLI entry point.

Skeleton wired in Step P2.2. Subcommands stub-only here; real implementations
land across Steps P2.5+.

After `pip install -e .` this is reachable as:

    $ echo --help
    $ echo --version
"""

import typer

from echo import __version__

app = typer.Typer(
    name="echo",
    help="Personal data archaeology - analyze your own YouTube + Spotify + Calendar history.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"echo {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Echo CLI root callback. Adds --version, otherwise hands off to subcommands."""
    pass


@app.command()
def init() -> None:
    """First-run setup wizard. (Implementation lands in Step P2.5.)"""
    typer.echo("[stub] echo init - wizard implementation pending (Step P2.5).")


@app.command()
def doctor() -> None:
    """Sanity-check the install: paths, deps, API keys, schema. (Step P2.5.)"""
    typer.echo("[stub] echo doctor - implementation pending (Step P2.5).")


@app.command()
def run() -> None:
    """Run the full pipeline: ingest -> enrich -> detect -> signals -> reflect -> embed. (Step P2.5.)"""
    typer.echo("[stub] echo run - implementation pending (Step P2.5).")


if __name__ == "__main__":
    app()
