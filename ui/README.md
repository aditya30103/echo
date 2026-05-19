# Echo UI

SvelteKit frontend for Echo. Surfaces the autonomous agent (Echo Speaks),
Binge Sessions, Agency Map, and Ask Echo (RAG demo) over the FastAPI backend.

## Setup and operation

UI is part of the full Echo stack. See the root
[SETUP.md](../SETUP.md) for end-to-end onboarding (data ingestion, env
configuration, then the UI). The fastest path:

```bash
docker compose up        # from repo root — starts api:8000 + ui:5173
```

For local non-Docker development:

```bash
npm install
npm run dev              # http://localhost:5173, expects api on :8000
npm run build            # production build
```

## Architecture and components

Component map and design rationale live in the root
[ARCHITECTURE.md](../docs/ARCHITECTURE.md).
Key UI entry points:

- `src/routes/+page.svelte` — landing + Echo Speaks
- `src/lib/SpeakView.svelte` — autonomous agent UI (rounds, findings, eval scores, cost footer)
- `src/lib/CostFooter.svelte` — per-run cost breakdown (input / cache write / cache read / output)
- `src/lib/TimelineCard.svelte`, `RoundPillStrip.svelte` — agent execution visualization

## Notes

- Project scaffold originally generated with `npx sv create` (SvelteKit minimal + TypeScript).
- Backend API expected at `http://127.0.0.1:8000` (configurable via env if you fork).
- No telemetry, no analytics — UI never reaches anywhere except the local API.
