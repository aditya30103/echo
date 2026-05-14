"""Echo Speaks — ReAct agentic analysis endpoint."""

import json
import re
import textwrap

from fastapi import APIRouter, Depends
from pydantic import BaseModel
import sqlite_utils

from api.db import get_db
from api.llm import chat as llm_chat
from api.tools import dispatch, tool_descriptions

router = APIRouter(prefix="/api/speak", tags=["speak"])

_STATS_SQL = """
SELECT
    (SELECT COUNT(*)           FROM watches)                                AS watch_count,
    (SELECT MIN(watched_at)    FROM watches)                                AS earliest_watch,
    (SELECT MAX(watched_at)    FROM watches)                                AS latest_watch,
    (SELECT COUNT(*)           FROM google_searches)                        AS google_search_count,
    (SELECT COUNT(DISTINCT query) FROM yt_searches)                         AS yt_search_count,
    (SELECT COUNT(*)           FROM chapters)                               AS chapter_count,
    (SELECT COUNT(*)           FROM calendar_events)                        AS calendar_count
"""

# Regex to extract ACTION JSON from model output.
_ACTION_RE = re.compile(r'ACTION:\s*(\{.*\})', re.DOTALL)
_THOUGHT_RE = re.compile(r'THOUGHT:\s*(.*?)(?=ACTION:|$)', re.DOTALL)


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
    """One-shot call to produce surprise criteria. Data-profile only — no narratives."""
    prompt = textwrap.dedent(f"""\
        A personal behavioral dataset has these characteristics:
        - YouTube watch history: {stats.get('watch_count', '?')} videos over {stats.get('earliest_watch','')[:10]} to {stats.get('latest_watch','')[:10]}
        - Google searches: {stats.get('google_search_count','?')} entries
        - YouTube searches: {stats.get('yt_search_count','?')} unique queries
        - {stats.get('chapter_count','?')} behavioral chapters (changepoint-detected)
        - {stats.get('calendar_count','?')} calendar events
        - Owner: 23-year-old, IST timezone, dense data 2024–2026, sparse 2020–2023

        Generate exactly 5 rubric criteria for what would make a discovered pattern GENUINELY SURPRISING
        vs. expected for someone with this data profile. Be specific — not "unusual viewing time"
        but criteria that would distinguish a real statistical anomaly from a narrative cliché.
        Return as a numbered list, one criterion per line. No preamble.
    """)
    try:
        rubric, _ = llm_chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=400,
            temperature=0.5,
        )
        return rubric
    except Exception:
        return (
            "1. Quantitatively anomalous relative to the user's own baseline (not just 'high')\n"
            "2. Temporally specific — happened in a bounded window, not diffusely across all time\n"
            "3. Cross-signal corroborated — appears in watch data AND search data or calendar data\n"
            "4. Contradicts the user's likely self-model (counter-intuitive direction)\n"
            "5. Behaviorally actionable — reveals a habit or pattern, not just a preference"
        )


def _build_system_prompt(stats: dict, rubric: str, narrative_blind_rounds: int) -> str:
    return textwrap.dedent(f"""\
        You are Echo Speaks — an autonomous data analyst working on Aditya Arya's personal behavioral data.
        Your goal: answer the user's query by exploring raw data, forming hypotheses, testing them, and synthesizing findings.

        ## Data available in echo.db
        - watches: {stats.get('watch_count','?')} rows ({stats.get('earliest_watch','?')[:10]} – {stats.get('latest_watch','?')[:10]})
          Columns: video_id, title, channel, watched_at, duration_seconds
        - video_metadata: title, channel, duration_seconds, view_count, like_count, tags
        - watch_signals: session_id, session_depth, session_length, is_search_driven,
          was_bookmarked, is_autoplay, is_rewatch, rewatch_count (per watch row)
        - google_searches: {stats.get('google_search_count','?')} rows — query, timestamp
        - yt_searches: {stats.get('yt_search_count','?')} unique queries — query, timestamp
        - chapters: {stats.get('chapter_count','?')} rows — id, label, start_at, end_at, watch_count
        - chapter_fingerprints: per-chapter night_ratio, long_form_ratio, shorts_ratio,
          channel_density_score, modal_hour, median_duration_seconds
        - calendar_events: {stats.get('calendar_count','?')} rows — title, start_date (ICS format), end_date
          ICS date normalization: substr(start_date,1,4)||'-'||substr(start_date,5,2)||'-'||substr(start_date,7,2)
        - reflections: chapter arc narratives (LLM-generated)

        IST timezone: all hour/day queries use datetime(watched_at, '+330 minutes').
        Shorts: duration_seconds < 60.

        ## Epistemic hierarchy — CRITICAL
        Observations are tagged by source. Honor these tiers:
        - [RAW-SQL]: direct SQLite result — cite freely as evidence
        - [RAW-COMPUTED]: Python/pandas computation — cite freely as evidence
        - [SEMANTIC-RAW]: semantic search on videos/searches — medium trust
        - [NARRATIVE]: chapter reflections or chapter context — ORIENTATION ONLY.
          Reflections are LLM-generated and may embed user-provided biographical context,
          not purely discovered patterns. NEVER use [NARRATIVE] as primary evidence.

        ## Surprise rubric — rank findings by these criteria
        {rubric}

        ## Phase rules
        Rounds 1–{narrative_blind_rounds}: PHASE 1 — Narrative-blind.
          Available: run_sql, execute_python, vector_search(videos|searches|google_searches)
          BLOCKED: vector_search(reflections), get_chapter_context
          Form ALL hypotheses from raw data only.

        Rounds {narrative_blind_rounds + 1}+: PHASE 2 — Verification allowed.
          All tools available. Use [NARRATIVE] only to sanity-check Phase 1 hypotheses.
          [NARRATIVE] may NOT be cited as primary evidence for any finding.

        ## Tools
        {{tools}}

        ## Output format — STRICT, no deviation
        Every response must be exactly:

        THOUGHT: <your reasoning about what to discover or verify next>
        ACTION: {{"tool": "<name>", "args": {{<json>}}}}

        To finish, call:
        ACTION: {{"tool": "finish", "args": {{"findings": [{{"claim": "...", "evidence": "...", "source_tag": "RAW-SQL", "confidence": "high"}}], "side_insights": ["..."]}}}}

        Every finding MUST have source_tag = "RAW-SQL", "RAW-COMPUTED", or "SEMANTIC-RAW".
        If a finding can only be supported by [NARRATIVE] evidence, do NOT include it in findings — put it in side_insights with a note.
        Produce ONLY the THOUGHT/ACTION block. No prose, headers, or explanation outside it.
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


def _validate_findings(raw: list) -> list[Finding]:
    """Downgrade any finding that slipped through with NARRATIVE as its only source."""
    out = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        tag = str(f.get("source_tag", "")).upper()
        narrative_only = tag == "NARRATIVE" or tag not in ("RAW-SQL", "RAW-COMPUTED", "SEMANTIC-RAW")
        out.append(Finding(
            claim=str(f.get("claim", "")),
            evidence=str(f.get("evidence", "")),
            source_tag=f.get("source_tag", "UNKNOWN"),
            confidence="low" if narrative_only else str(f.get("confidence", "medium")),
            narrative_derived=narrative_only,
        ))
    return out


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("", response_model=SpeakResponse)
def speak(req: SpeakRequest, db: sqlite_utils.Database = Depends(get_db)):
    stats  = _get_stats(db)
    rubric = _generate_rubric(stats, req.model)

    system_prompt_template = _build_system_prompt(stats, rubric, req.narrative_blind_rounds)
    trace: list[TraceEntry] = []

    # Conversation history (excludes system — injected fresh each call)
    history: list[dict] = [
        {"role": "user", "content": req.query}
    ]

    findings: list[Finding] = []
    side_insights: list[str] = []
    model_label = req.model
    hit_limit = False

    for round_n in range(1, req.max_rounds + 1):
        phase = 1 if round_n <= req.narrative_blind_rounds else 2
        narrative_blind = (phase == 1)

        # Inject current tools into system prompt based on phase
        system_content = system_prompt_template.replace(
            "{tools}", tool_descriptions(narrative_blind)
        )

        messages = [{"role": "system", "content": system_content}] + history

        # Add a round-awareness note as the last user message when phase changes
        if round_n == req.narrative_blind_rounds + 1:
            # Phase transition: update the last observation message or append
            history.append({
                "role": "user",
                "content": (
                    f"[System: Phase 2 begins. Narrative tools (vector_search on reflections, "
                    f"get_chapter_context) are now available — use them only to verify hypotheses "
                    f"formed from raw data. [NARRATIVE] remains inadmissible as primary evidence.]"
                )
            })
            messages = [{"role": "system", "content": system_content}] + history

        raw_response, model_label = llm_chat(
            messages,
            model=req.model,
            max_tokens=1200,
            temperature=0.3,
        )

        parsed = _parse_response(raw_response)
        if parsed is None:
            # Unparseable — give the model a correction nudge and continue
            history.append({"role": "assistant", "content": raw_response})
            history.append({
                "role": "user",
                "content": (
                    f"OBSERVATION (round {round_n}/{req.max_rounds}): "
                    "[FORMAT ERROR] Your response did not follow the required format. "
                    "Respond with exactly: THOUGHT: <reasoning>\\nACTION: {\"tool\": \"...\", \"args\": {...}}"
                )
            })
            continue

        thought, tool, args = parsed

        if tool == "finish":
            raw_findings    = args.get("findings", [])
            side_insights   = [str(s) for s in args.get("side_insights", [])]
            findings        = _validate_findings(raw_findings)
            trace.append(TraceEntry(
                round=round_n, thought=thought, tool="finish", args={},
                observation="[Agent finished]"
            ))
            break

        observation = dispatch(tool, args, phase)

        trace.append(TraceEntry(
            round=round_n, thought=thought, tool=tool, args=args, observation=observation
        ))

        history.append({"role": "assistant", "content": raw_response})
        history.append({
            "role": "user",
            "content": f"OBSERVATION (round {round_n}/{req.max_rounds}, phase {phase}):\n{observation}"
        })
    else:
        hit_limit = True

    return SpeakResponse(
        query=req.query,
        findings=findings,
        side_insights=side_insights,
        trace=trace,
        rounds_used=len(trace),
        model=model_label,
        hit_round_limit=hit_limit,
    )
