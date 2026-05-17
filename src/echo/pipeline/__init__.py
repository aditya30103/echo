"""Echo data pipeline modules.

Each submodule wraps one step of the pipeline (ingest, enrich, detect, signals,
reflect, embed) as a `run(config: EchoConfig) -> None` function. The CLI
(`echo.cli.run_cmd`) invokes them in order; each is also exposed as its own
subcommand for partial reruns.

Populated in Step P2.3 of the packaging session. Until then, the old root
scripts (`ingest.py`, `enrich.py`, etc.) remain the active pipeline.
"""
