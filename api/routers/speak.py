"""Echo Speaks — ReAct agentic analysis endpoint."""

import json
import re
import textwrap
from typing import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import sqlite_utils

from api.db import get_db
from api.llm import chat as llm_chat
from api.observability import get_langfuse
from api.tools import dispatch, tool_descriptions

router = APIRouter(prefix="/api/speak", tags=["speak"])

_STATS_SQL = """
SELECT
    (SELECT COUNT(*)              FROM watches)              AS watch_count,
    (SELECT MIN(watched_at)       FROM watches)              AS earliest_watch,
    (SELECT MAX(watched_at)       FROM watches)              AS latest_watch,
    (SELECT COUNT(*)              FROM google_searches)      AS google_search_count,
    (SELECT COUNT(DISTINCT query) FROM yt_searches)          AS yt_search_count,
    (SELECT COUNT(*)              FROM chapters)             AS chapter_count,
    (SELECT COUNT(*)              FROM calendar_events)      AS calendar_count
"""

_ACTION_RE = re.compile(r'ACTION:\s*(\{.*\})', re.DOTALL)
_THOUGHT_RE = re.compile(r'THOUGHT:\s*(.*?)(?=ACTION:|$)', re.DOTALL)

_KEEP_FULL_ROUNDS = 4   # compress observations older than this many rounds

# Tables to include in the pre-built schema dictionary.
_SCHEMA_TABLES = [
    "watches", "video_metadata", "watch_signals",
    "google_searches", "yt_searches",
    "chapters", "chapter_fingerprints", "reflections",
    "calendar_events", "transactions",
]

# Hand-written notes that supplement the schema — things pragma_table_info can't express.
_SCHEMA_NOTES = """\

## Key relationships (exact column names — verified against live schema)
- watches ↔ watch_signals: JOIN ON watch_signals.watch_id = watches.id
  (one watch_signals row per watch row; same 6,280 count)
- watches ↔ video_metadata: JOIN ON video_metadata.video_id = watches.video_id
- watch ↔ chapter (by date): watches.watched_at BETWEEN chapters.start_at AND chapters.end_at
- chapter_fingerprints.chapter_id = chapters.id
- reflections.chapter_id = chapters.id  (column name: 'reflection', not 'text')

## Column name clarifications (common mistakes to avoid)
- watches: channel_name (NOT channel), watched_at (NOT timestamp)
- video_metadata: channel_title (NOT channel), duration_seconds
- watch_signals: watch_id (joins to watches.id), session_depth, session_length
- google_searches: searched_at (NOT timestamp)
- yt_searches: searched_at (NOT timestamp)
- reflections: reflection (the text column, NOT 'text')

## Critical patterns — tested and correct

IST hour of watch:
  CAST(strftime('%H', datetime(watched_at, '+330 minutes')) AS INTEGER)

Night watch (22:00–04:00 IST):
  CAST(strftime('%H', datetime(watched_at, '+330 minutes')) AS INTEGER) >= 22
  OR CAST(strftime('%H', datetime(watched_at, '+330 minutes')) AS INTEGER) < 4

Shorts (< 60 s):
  watches.duration_seconds < 60

ICS calendar date → ISO:
  substr(start_date,1,4)||'-'||substr(start_date,5,2)||'-'||substr(start_date,7,2)

## Proven starter queries (copy-paste ready)

-- Top channels by watch count
SELECT channel_name, COUNT(*) n FROM watches
GROUP BY channel_name ORDER BY n DESC LIMIT 15

-- Agency breakdown (searched vs autoplay vs bookmarked vs rewatch)
SELECT SUM(is_search_driven) searched, SUM(is_autoplay) autoplay,
       SUM(was_bookmarked) bookmarked, SUM(is_rewatch) rewatch
FROM watch_signals

-- Watches per chapter with fingerprint stats
SELECT c.id, c.label, c.watch_count,
       cf.night_ratio, cf.shorts_ratio, cf.long_form_ratio, cf.modal_hour
FROM chapters c JOIN chapter_fingerprints cf ON cf.chapter_id = c.id
ORDER BY c.id

-- Watch density by month (IST)
SELECT strftime('%Y-%m', datetime(watched_at, '+330 minutes')) month,
       COUNT(*) n FROM watches GROUP BY month ORDER BY month

-- Binge sessions (≥5 videos)
SELECT ws.session_id, MAX(ws.session_length) depth,
       MIN(w.watched_at) started
FROM watch_signals ws
JOIN watches w ON ws.watch_id = w.id
WHERE ws.session_length >= 5
GROUP BY ws.session_id ORDER BY depth DESC LIMIT 20

-- Google search volume by month
SELECT strftime('%Y-%m', searched_at) month, COUNT(*) n
FROM google_searches GROUP BY month ORDER BY month
"""


# ── Pydantic models ────────────────────────────────────────────────────────────

class SpeakRequest(BaseModel):
    query: str
    max_rounds: int = 20
    model: str = "auto"
    narrative_blind_rounds: int = 10   # half of default max_rounds


class TraceEntry(BaseModel):
    round: int
    thought: str
    tool: str
    args: dict
    observation: str


class Finding(BaseModel):
    claim: str
    evidence: str
    source_tag: str
    confidence: str
    narrative_derived: bool = False


class SpeakResponse(BaseModel):
    query: str
    findings: list[Finding]
    side_insights: list[str]
    trace: list[TraceEntry]
    rounds_used: int
    model: str
    hit_round_limit: bool


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_stats(db: sqlite_utils.Database) -> dict:
    try:
        row = list(db.execute(_STATS_SQL))[0]
        # db.execute returns plain tuples — use positional indexing
        return {
            "watch_count":         row[0],
            "earliest_watch":      row[1] or "",
            "latest_watch":        row[2] or "",
            "google_search_count": row[3],
            "yt_search_count":     row[4],
            "chapter_count":       row[5],
            "calendar_count":      row[6],
        }
    except Exception:
        return {}


def _fetch_schema_context(db: sqlite_utils.Database) -> str:
    """Build a full schema dictionary from pragma_table_info + row counts.

    This is injected into the system prompt so the agent never needs to waste
    rounds on schema exploration.
    """
    lines = ["## Complete table schemas — do NOT use pragma_table_info, schema is here\n"]
    for table in _SCHEMA_TABLES:
        try:
            count = list(db.execute(f"SELECT COUNT(*) FROM [{table}]"))[0][0]
            # pragma_table_info columns: cid(0), name(1), type(2), notnull(3), dflt_value(4), pk(5)
            cols  = list(db.execute(f"SELECT name, type FROM pragma_table_info('{table}')"))
            col_str = ", ".join(
                f"{c[0]} {c[1]}" if c[1] else c[0]
                for c in cols
            )
            lines.append(f"{table} ({count:,} rows): {col_str}")
        except Exception as e:
            lines.append(f"{table}: unavailable ({e})")
    lines.append(_SCHEMA_NOTES)
    return "\n".join(lines)


def _generate_rubric(stats: dict, model: str) -> str:
    prompt = textwrap.dedent(f"""\
        A personal behavioral dataset has these characteristics:
        - YouTube watch history: {stats.get('watch_count','?')} videos, {stats.get('earliest_watch','')[:10]} to {stats.get('latest_watch','')[:10]}
        - Google searches: {stats.get('google_search_count','?')} entries
        - YouTube searches: {stats.get('yt_search_count','?')} unique queries
        - {stats.get('chapter_count','?')} behavioral chapters (changepoint-detected)
        - {stats.get('calendar_count','?')} calendar events
        - Owner: 23-year-old, IST timezone, data dense 2024–2026, sparse 2020–2023

        Generate exactly 5 rubric criteria for what makes a pattern GENUINELY SURPRISING
        vs. expected for this person. Be specific — not "unusual time" but criteria that
        distinguish a real statistical anomaly from a narrative cliché.
        Return a numbered list only. No preamble.
    """)
    try:
        rubric, *_ = llm_chat(
            [{"role": "user", "content": prompt}],
            model=model, max_tokens=400, temperature=0.5,
        )
        return rubric
    except Exception:
        return (
            "1. Quantitatively anomalous relative to the user's own baseline (not just 'high')\n"
            "2. Temporally specific — bounded window, not diffuse across all time\n"
            "3. Cross-signal corroborated — appears in multiple data sources\n"
            "4. Contradicts likely self-model (counter-intuitive direction)\n"
            "5. Behaviorally actionable — reveals a habit or pattern, not just a preference"
        )


def _build_system_prompt(
    stats: dict,
    rubric: str,
    schema_context: str,
    narrative_blind_rounds: int,
    max_rounds: int,
) -> str:
    return textwrap.dedent(f"""\
        You are Echo Speaks — an autonomous data analyst working on Aditya Arya's personal behavioral data.
        Explore raw data, form hypotheses, test them, synthesize surprising findings.
        You have {max_rounds} rounds total. Use them wisely: start broad, go deep on promising signals.

        {schema_context}

        ## Epistemic hierarchy — CRITICAL
        Observations are tagged by source. Honor these tiers strictly:
        - [RAW-SQL]: direct SQLite result — primary evidence, cite freely
        - [RAW-COMPUTED]: Python/pandas/numpy result — primary evidence, cite freely
        - [SEMANTIC-RAW]: semantic search on raw tables — medium trust
        - [NARRATIVE]: chapter reflections or chapter context — ORIENTATION ONLY.
          Reflections are LLM-generated, may embed user-provided biographical context.
          NEVER use [NARRATIVE] as primary evidence for a finding.

        ## Surprise rubric — rank findings by these criteria
        {rubric}

        ## Phase rules
        Rounds 1–{narrative_blind_rounds}: PHASE 1 — Narrative-blind.
          Available: run_sql, execute_python, vector_search(videos|searches|google_searches)
          BLOCKED: vector_search(reflections), get_chapter_context
          Form ALL hypotheses from raw behavioral data only.

        Rounds {narrative_blind_rounds + 1}+: PHASE 2 — Verification allowed.
          All tools available. [NARRATIVE] only to sanity-check Phase 1 hypotheses.

        ## Tools
        {{tools}}

        ## Output format — STRICT, no deviation
        THOUGHT: <your reasoning>
        ACTION: {{"tool": "<name>", "args": {{<json>}}}}

        To finish:
        ACTION: {{"tool": "finish", "args": {{"findings": [{{"claim": "...", "evidence": "...", "source_tag": "RAW-SQL", "confidence": "high"}}], "side_insights": ["..."]}}}}

        findings.source_tag must be RAW-SQL, RAW-COMPUTED, or SEMANTIC-RAW.
        [NARRATIVE]-only findings go in side_insights with a note.
        No prose outside the THOUGHT/ACTION block.
    """)


def _parse_response(text: str) -> tuple[str, str, dict] | None:
    thought_m = _THOUGHT_RE.search(text)
    action_m  = _ACTION_RE.search(text)
    if not action_m:
        return None
    thought = thought_m.group(1).strip() if thought_m else ""
    try:
        action = json.loads(action_m.group(1))
        return thought, str(action.get("tool", "")), dict(action.get("args", {}))
    except json.JSONDecodeError:
        return None


def _source_tag(observation: str) -> str:
    for tag in ("RAW-SQL", "RAW-COMPUTED", "SEMANTIC-RAW", "NARRATIVE"):
        if observation.startswith(f"[{tag}]"):
            return tag
    return "UNKNOWN"


def _trim_history(history: list[dict], keep_full: int = _KEEP_FULL_ROUNDS) -> list[dict]:
    """Compress old observations so context window stays manageable over 20 rounds."""
    if len(history) <= keep_full * 2 + 1:
        return history
    cutoff = max(1, len(history) - keep_full * 2)
    result = []
    for i, msg in enumerate(history):
        if i == 0 or i >= cutoff:
            result.append(msg)
        elif msg["role"] == "user" and "OBSERVATION" in msg["content"]:
            short = msg["content"][:200] + " [... trimmed]"
            result.append({"role": "user", "content": short})
        else:
            result.append(msg)
    return result


def _validate_findings(raw: list) -> list[Finding]:
    out = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        tag = str(f.get("source_tag", "")).upper().replace("[", "").replace("]", "")
        narrative_only = tag not in ("RAW-SQL", "RAW-COMPUTED", "SEMANTIC-RAW")
        out.append(Finding(
            claim=str(f.get("claim", "")),
            evidence=str(f.get("evidence", "")),
            source_tag=tag or "UNKNOWN",
            confidence="low" if narrative_only else str(f.get("confidence", "medium")),
            narrative_derived=narrative_only,
        ))
    return out


# ── Core generator ─────────────────────────────────────────────────────────────

def _react_loop(req: SpeakRequest, db: sqlite_utils.Database) -> Iterator[dict]:
    """Yields event dicts. Both the JSON and SSE endpoints consume this."""
    lf    = get_langfuse()
    trace = lf.trace(query=req.query, max_rounds=req.max_rounds, model=req.model)

    try:
        stats          = _get_stats(db)
        schema_context = _fetch_schema_context(db)

        yield {"type": "rubric_start"}
        rubric = _generate_rubric(stats, req.model)
        yield {"type": "rubric_done", "rubric": rubric}

        system_template = _build_system_prompt(
            stats, rubric, schema_context, req.narrative_blind_rounds, req.max_rounds
        )
        history: list[dict] = [{"role": "user", "content": req.query}]
        model_label = req.model

        for round_n in range(1, req.max_rounds + 1):
            phase = 1 if round_n <= req.narrative_blind_rounds else 2

            if round_n == req.narrative_blind_rounds + 1:
                yield {"type": "phase_change", "phase": 2}
                history.append({
                    "role": "user",
                    "content": (
                        "[System: Phase 2 begins. vector_search(reflections) and "
                        "get_chapter_context are now available — use only to verify "
                        "Phase 1 hypotheses. [NARRATIVE] remains inadmissible as primary evidence.]"
                    ),
                })

            # Inject "time remaining" urgency when 3 rounds remain
            rounds_left = req.max_rounds - round_n
            if rounds_left == 3:
                history.append({
                    "role": "user",
                    "content": (
                        f"[System: {rounds_left} rounds remaining. "
                        "Stop exploring — call finish with your best findings from what you have so far.]"
                    ),
                })

            yield {"type": "round_start", "round": round_n, "phase": phase}

            system_content = system_template.replace("{tools}", tool_descriptions(phase == 1))
            messages = (
                [{"role": "system", "content": system_content}]
                + _trim_history(history, _KEEP_FULL_ROUNDS)
            )

            llm_gen = trace.generation(round_n, model_label, len(history))

            try:
                raw_response, model_label, usage = llm_chat(
                    messages, model=req.model, max_tokens=1200, temperature=0.3,
                )
                llm_gen.done(raw_response[:500], usage=usage)
            except Exception as e:
                llm_gen.done(str(e))
                yield {"type": "error", "round": round_n, "message": str(e)}
                break

            parsed = _parse_response(raw_response)
            if parsed is None:
                yield {"type": "format_error", "round": round_n, "raw": raw_response[:300]}
                history.append({"role": "assistant", "content": raw_response})
                history.append({
                    "role": "user",
                    "content": (
                        f"OBSERVATION (round {round_n}): [FORMAT ERROR] "
                        "Respond with exactly: THOUGHT: <reasoning>\\n"
                        "ACTION: {\"tool\": \"...\", \"args\": {...}}"
                    ),
                })
                continue

            thought, tool, args = parsed

            yield {"type": "thought", "round": round_n, "content": thought}
            yield {"type": "action",  "round": round_n, "tool": tool, "args": args}

            if tool == "finish":
                raw_findings  = args.get("findings", [])
                side_insights = [str(s) for s in args.get("side_insights", [])]
                findings      = _validate_findings(raw_findings)
                trace.finish(len(findings), round_n, hit_limit=False)
                finish_evt = {
                    "type": "finish",
                    "findings": [f.model_dump() for f in findings],
                    "side_insights": side_insights,
                    "rounds_used": round_n,
                    "model": model_label,
                    "hit_round_limit": False,
                    "trace_id": trace.trace_id,
                }
                yield finish_evt
                return

            tool_span   = trace.tool(tool, args, round_n)
            observation = dispatch(tool, args, phase)
            tag         = _source_tag(observation)
            tool_span.done(observation[:400], source_tag=tag)

            yield {"type": "observation", "round": round_n, "content": observation, "source_tag": tag}

            history.append({"role": "assistant", "content": raw_response})
            history.append({
                "role": "user",
                "content": f"OBSERVATION (round {round_n}/{req.max_rounds}, phase {phase}):\n{observation}",
            })

        # Hit round limit
        trace.finish(0, req.max_rounds, hit_limit=True)
        limit_evt = {
            "type": "finish",
            "findings": [],
            "side_insights": [f"Agent reached the {req.max_rounds}-round limit without completing synthesis."],
            "rounds_used": req.max_rounds,
            "model": model_label,
            "hit_round_limit": True,
            "trace_id": trace.trace_id,
        }
        yield limit_evt

    finally:
        lf.flush()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("", response_model=SpeakResponse)
def speak(req: SpeakRequest, db: sqlite_utils.Database = Depends(get_db)):
    """Non-streaming JSON endpoint (curl / testing)."""
    trace_entries: list[TraceEntry] = []
    findings:      list[Finding]    = []
    side_insights: list[str]        = []
    model_label = req.model
    hit_limit   = False
    pending: dict = {}

    for evt in _react_loop(req, db):
        t = evt["type"]
        if t == "thought":
            pending = {"round": evt["round"], "thought": evt["content"], "tool": "", "args": {}, "observation": ""}
        elif t == "action":
            pending["tool"] = evt["tool"]
            pending["args"] = evt["args"]
        elif t == "observation":
            pending["observation"] = evt["content"]
            if pending.get("round"):
                trace_entries.append(TraceEntry(**pending))
            pending = {}
        elif t == "finish":
            if pending.get("tool") == "finish":
                pending["observation"] = "[Agent finished]"
                if pending.get("round"):
                    trace_entries.append(TraceEntry(**pending))
            findings      = [Finding(**f) for f in evt.get("findings", [])]
            side_insights = evt.get("side_insights", [])
            model_label   = evt.get("model", req.model)
            hit_limit     = evt.get("hit_round_limit", False)

    return SpeakResponse(
        query=req.query,
        findings=findings,
        side_insights=side_insights,
        trace=trace_entries,
        rounds_used=len(trace_entries),
        model=model_label,
        hit_round_limit=hit_limit,
    )


class ScoreRequest(BaseModel):
    trace_id: str
    value: float  # 1.0 = surprising / useful, 0.0 = expected / not useful


@router.post("/score")
def score_run(req: ScoreRequest):
    """Post a 'surprising' score to the Langfuse trace for a completed run."""
    lf = get_langfuse()
    lf.score(req.trace_id, "surprising", req.value)
    lf.flush()
    return {"ok": True}


@router.post("/stream")
def speak_stream(req: SpeakRequest, db: sqlite_utils.Database = Depends(get_db)):
    """SSE streaming endpoint — yields events as they happen."""
    def _generate():
        for evt in _react_loop(req, db):
            yield f"data: {json.dumps(evt)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
