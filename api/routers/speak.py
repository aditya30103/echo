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

# Keep last N full-round observations in the history; compress older ones.
_KEEP_FULL_ROUNDS = 3


# ── Pydantic models ────────────────────────────────────────────────────────────

class SpeakRequest(BaseModel):
    query: str
    max_rounds: int = 12
    model: str = "auto"
    narrative_blind_rounds: int = 6


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
        return dict(row)
    except Exception:
        return {}


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
        vs. expected. Be specific — not "unusual time" but criteria distinguishing a real
        statistical anomaly from a narrative cliché.
        Return a numbered list only. No preamble.
    """)
    try:
        rubric, _ = llm_chat(
            [{"role": "user", "content": prompt}],
            model=model, max_tokens=400, temperature=0.5,
        )
        return rubric
    except Exception:
        return (
            "1. Quantitatively anomalous relative to the user's own baseline\n"
            "2. Temporally specific — bounded window, not diffuse across all time\n"
            "3. Cross-signal corroborated — appears in multiple data sources\n"
            "4. Contradicts likely self-model (counter-intuitive direction)\n"
            "5. Behaviorally actionable — reveals a habit or pattern, not just a preference"
        )


def _build_system_prompt(stats: dict, rubric: str, narrative_blind_rounds: int) -> str:
    return textwrap.dedent(f"""\
        You are Echo Speaks — an autonomous data analyst working on Aditya Arya's personal behavioral data.
        Explore raw data, form hypotheses, test them, and synthesize surprising findings.

        ## Data in echo.db
        - watches: {stats.get('watch_count','?')} rows ({stats.get('earliest_watch','?')[:10]} – {stats.get('latest_watch','?')[:10]})
          Key columns: video_id, title, channel_name, watched_at, duration_seconds
        - video_metadata: title, channel, duration_seconds, view_count, like_count, tags
        - watch_signals: session_id, session_depth, session_length, is_search_driven,
          was_bookmarked, is_autoplay, is_rewatch, rewatch_count (one row per watch)
        - google_searches: {stats.get('google_search_count','?')} rows — query, timestamp
        - yt_searches: query, timestamp
        - chapters: id, label, start_at, end_at, watch_count
        - chapter_fingerprints: night_ratio, long_form_ratio, shorts_ratio,
          channel_density_score, modal_hour, median_duration_seconds
        - calendar_events: title, start_date (ICS: use substr(start_date,1,4)||'-'||substr(start_date,5,2)||'-'||substr(start_date,7,2))
        - reflections: chapter arc narratives (LLM-generated — [NARRATIVE])

        IST timezone: datetime(watched_at, '+330 minutes') for hour/day analysis.
        Schema inspection: SELECT name, type FROM pragma_table_info('tablename')
        Shorts: duration_seconds < 60.

        ## Epistemic hierarchy — CRITICAL
        - [RAW-SQL]: direct SQLite result — cite freely as evidence
        - [RAW-COMPUTED]: Python/pandas result — cite freely as evidence
        - [SEMANTIC-RAW]: semantic search on raw tables — medium trust
        - [NARRATIVE]: reflections / chapter context — ORIENTATION ONLY.
          Reflections are LLM-generated, may embed user-provided biographical context.
          NEVER cite [NARRATIVE] as primary evidence for a finding.

        ## Surprise rubric
        {rubric}

        ## Phase rules
        Rounds 1–{narrative_blind_rounds}: PHASE 1 — Narrative-blind.
          Available: run_sql, execute_python, vector_search(videos|searches|google_searches)
          BLOCKED: vector_search(reflections), get_chapter_context
          Form ALL hypotheses from raw behavioral data only.

        Rounds {narrative_blind_rounds + 1}+: PHASE 2 — Verification allowed.
          All tools available. [NARRATIVE] only for sanity-checking Phase 1 hypotheses.

        ## Tools
        {{tools}}

        ## Output format — STRICT
        THOUGHT: <your reasoning>
        ACTION: {{"tool": "<name>", "args": {{<json>}}}}

        To finish:
        ACTION: {{"tool": "finish", "args": {{"findings": [{{"claim": "...", "evidence": "...", "source_tag": "RAW-SQL", "confidence": "high"}}], "side_insights": ["..."]}}}}

        Every finding source_tag must be RAW-SQL, RAW-COMPUTED, or SEMANTIC-RAW.
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
    """Truncate old observations so the context window doesn't blow out across 12 rounds.

    Keeps the initial query + last keep_full*2 messages in full.
    Middle observation messages are trimmed to 200 chars.
    """
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
    """Yields event dicts consumed by both the JSON and SSE endpoints."""
    stats = _get_stats(db)

    yield {"type": "rubric_start"}
    rubric = _generate_rubric(stats, req.model)
    yield {"type": "rubric_done", "rubric": rubric}

    system_template = _build_system_prompt(stats, rubric, req.narrative_blind_rounds)
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
                    "get_chapter_context are now available — use them only to verify "
                    "Phase 1 hypotheses. [NARRATIVE] remains inadmissible as primary evidence.]"
                ),
            })

        yield {"type": "round_start", "round": round_n, "phase": phase}

        system_content = system_template.replace("{tools}", tool_descriptions(phase == 1))
        messages = (
            [{"role": "system", "content": system_content}]
            + _trim_history(history, _KEEP_FULL_ROUNDS)
        )

        try:
            raw_response, model_label = llm_chat(
                messages, model=req.model, max_tokens=1200, temperature=0.3,
            )
        except Exception as e:
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
                    "Respond with exactly: THOUGHT: <reasoning>\\nACTION: {\"tool\": \"...\", \"args\": {...}}"
                ),
            })
            continue

        thought, tool, args = parsed

        yield {"type": "thought", "round": round_n, "content": thought}
        yield {"type": "action", "round": round_n, "tool": tool, "args": args}

        if tool == "finish":
            raw_findings  = args.get("findings", [])
            side_insights = [str(s) for s in args.get("side_insights", [])]
            findings      = _validate_findings(raw_findings)
            yield {
                "type": "finish",
                "findings": [f.model_dump() for f in findings],
                "side_insights": side_insights,
                "rounds_used": round_n,
                "model": model_label,
                "hit_round_limit": False,
            }
            return

        observation = dispatch(tool, args, phase)
        tag = _source_tag(observation)

        yield {"type": "observation", "round": round_n, "content": observation, "source_tag": tag}

        history.append({"role": "assistant", "content": raw_response})
        history.append({
            "role": "user",
            "content": f"OBSERVATION (round {round_n}/{req.max_rounds}, phase {phase}):\n{observation}",
        })

    # Hit round limit
    yield {
        "type": "finish",
        "findings": [],
        "side_insights": ["Agent reached the round limit without completing synthesis."],
        "rounds_used": req.max_rounds,
        "model": model_label,
        "hit_round_limit": True,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("", response_model=SpeakResponse)
def speak(req: SpeakRequest, db: sqlite_utils.Database = Depends(get_db)):
    """Non-streaming JSON endpoint (for curl / testing)."""
    trace: list[TraceEntry] = []
    findings: list[Finding] = []
    side_insights: list[str] = []
    model_label = req.model
    hit_limit = False

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
                trace.append(TraceEntry(**pending))
            pending = {}
        elif t == "finish":
            # finish action has no observation event — close the round manually
            if pending.get("tool") == "finish":
                pending["observation"] = "[Agent finished]"
                if pending.get("round"):
                    trace.append(TraceEntry(**pending))
            findings      = [Finding(**f) for f in evt.get("findings", [])]
            side_insights = evt.get("side_insights", [])
            model_label   = evt.get("model", req.model)
            hit_limit     = evt.get("hit_round_limit", False)

    return SpeakResponse(
        query=req.query,
        findings=findings,
        side_insights=side_insights,
        trace=trace,
        rounds_used=len(trace),
        model=model_label,
        hit_round_limit=hit_limit,
    )


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
