"""Echo Speaks — ReAct agentic analysis endpoint."""

import json
import re
import textwrap
from typing import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
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
    "spotify_plays", "spotify_signals",
]

# ── Langfuse-managed instruction template ─────────────────────────────────────
# This string is seeded to Langfuse Prompt Management on first startup under the
# name "echo-speaks-instructions" with the "production" label.  Edit it from the
# Langfuse dashboard to iterate prompt behaviour without touching code.
# Variables: {{narrative_blind_rounds}}, {{phase_2_start}}, {{tools}}

_INSTRUCTION_TEMPLATE = """\
## Epistemic hierarchy — CRITICAL
Observations are tagged by source. Honor these tiers strictly:
- [RAW-SQL]: direct SQLite result — primary evidence, cite freely
- [RAW-COMPUTED]: Python/pandas/numpy/scipy/sklearn result — primary evidence, cite freely
- [SEMANTIC-RAW]: semantic search on raw tables — medium trust
- [EXTERNAL]: YouTube Data API or web search — supplementary context, medium confidence
- [NARRATIVE]: chapter reflections — ORIENTATION ONLY.
  Reflections are LLM-generated, may embed user-provided biographical context.
  NEVER use [NARRATIVE] as primary evidence for a finding.

## Phase rules
Rounds 1-{{narrative_blind_rounds}}: PHASE 1 - Narrative-blind.
  Available: run_sql, execute_python, vector_search(videos|searches|google_searches),
             run_pelt, run_clustering, youtube_lookup, web_search
  BLOCKED: vector_search(reflections), run_sql on reflections table
  Form ALL hypotheses from raw behavioral data only.

Rounds {{phase_2_start}}+: PHASE 2 - Verification allowed.
  All tools available. [NARRATIVE] only to sanity-check Phase 1 hypotheses.

## Tools
{{tools}}

## Output format - STRICT, no deviation
THOUGHT: <your reasoning>
ACTION: {"tool": "<name>", "args": {<json>}}

To finish:
ACTION: {"tool": "finish", "args": {"findings": [{"claim": "...", "evidence": "...", "source_tag": "RAW-SQL", "confidence": "high"}], "side_insights": ["..."]}}

findings.source_tag must be RAW-SQL, RAW-COMPUTED, SEMANTIC-RAW, or EXTERNAL.
EXTERNAL findings: set confidence="medium" — they appear as supplementary in the response.
[NARRATIVE]-only findings go in side_insights as strings.
No prose outside the THOUGHT/ACTION block.

## finish call rules — READ CAREFULLY
claim: ≤25 words, plain sentence.
evidence: ≤30 words — cite round numbers and key numbers only (e.g. "rounds 3,7: 68% of watches were autoplay in Ch16"). NEVER paste raw SQL output or multi-line tables into evidence.
side_insights: plain strings, ≤20 words each.
Violating these length limits causes JSON parse failures and burns rounds.
"""

_prompt_client       = None   # cached Langfuse TextPromptClient (or _NoopPrompt)
_prompt_seeded       = False  # only seed once per server process

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

## Spotify data (spotify_plays table)
Timestamps: ts column is UTC ISO-8601 with +00:00 suffix — same as watches.watched_at.
IST hour of play:
  CAST(strftime('%H', datetime(ts, '+330 minutes')) AS INTEGER)

reason_start semantics:
  'trackdone'           = natural album/playlist flow (algorithm-driven)
  'clickrow' / 'playbtn' = user explicitly chose this track (intentional)
  'fwdbtn'              = user skipped forward (not interested in previous)
  'backbtn'             = user went back (replaying)
  'appload' / 'remote'  = app resumed or remote control

Key behavioral flags:
  skipped = 1           = user skipped before track ended
  shuffle = 1           = shuffle mode was active
  prior plays of a track = use COUNT(*) WHERE spotify_track_uri = X AND ts < current_ts

Cross-modal join (Spotify + YouTube same week):
  SELECT strftime('%Y-%W', datetime(sp.ts, '+330 minutes')) AS week,
         COUNT(DISTINCT sp.id) AS spotify_plays,
         COUNT(DISTINCT w.id) AS yt_watches
  FROM spotify_plays sp
  LEFT JOIN watches w
    ON strftime('%Y-%W', datetime(sp.ts, '+330 minutes'))
     = strftime('%Y-%W', datetime(w.watched_at, '+330 minutes'))
  GROUP BY week ORDER BY week

-- Top artists by play count
SELECT artist_name, COUNT(*) n, SUM(ms_played)/3600000.0 hrs
FROM spotify_plays WHERE content_type='track'
GROUP BY artist_name ORDER BY n DESC LIMIT 20

-- Listening volume by year (IST)
SELECT strftime('%Y', datetime(ts, '+330 minutes')) yr,
       COUNT(*) plays, ROUND(SUM(ms_played)/3600000.0,1) hours
FROM spotify_plays GROUP BY yr ORDER BY yr

-- Skip rate by artist
SELECT artist_name, COUNT(*) plays, ROUND(100.0*SUM(skipped)/COUNT(*),1) skip_pct
FROM spotify_plays WHERE content_type='track'
GROUP BY artist_name HAVING COUNT(*) >= 10
ORDER BY skip_pct DESC LIMIT 20

## Spotify behavioral signals (spotify_signals table)
JOIN: spotify_signals.play_id = spotify_plays.id  (one row per play, same 16,678 count)

Key columns:
  session_id        = Spotify session (30-min gap between plays = new session; 2,165 total)
  session_depth     = position within session (1 = first play)
  session_length    = total plays in that session
  is_repeat         = 1 if this URI was played before in history (73% of plays)
  prior_play_count  = how many times this URI was played before this instance
  fully_played      = 1 if reason_end = 'trackdone' (track finished naturally; ~55% of plays)
  user_skipped      = 1 if reason_end = 'fwdbtn' OR skipped = 1 (user cut it short; ~32%)
  intent_class      = derived from reason_start:
                        'intentional'   = clickrow / playbtn (user chose this track)
                        'passive'       = trackdone (previous track ended, algorithm continued)
                        'seek'          = fwdbtn / backbtn (user navigated)
                        'session_start' = appload / remote / trackerror
                        'unknown'       = reason_start not in known values

Completion signal: fully_played is authoritative — prefer it over computing ms_played / duration_ms.
Skip signal: user_skipped = 1 means the user actively rejected the track.

Cross-modal session comparison (Spotify vs YouTube):
  Both use 30-min gap session definition → session_length distributions are directly comparable.

-- Fully played vs skipped by intent class
SELECT intent_class,
       COUNT(*) plays,
       ROUND(100.0*SUM(fully_played)/COUNT(*),1) pct_completed,
       ROUND(100.0*SUM(user_skipped)/COUNT(*),1) pct_skipped
FROM spotify_signals
GROUP BY intent_class ORDER BY plays DESC

-- Most repeated tracks (high prior_play_count)
SELECT sp.track_name, sp.artist_name,
       MAX(ss.prior_play_count)+1 AS total_plays
FROM spotify_signals ss
JOIN spotify_plays sp ON ss.play_id = sp.id
WHERE sp.content_type = 'track'
GROUP BY sp.spotify_track_uri
ORDER BY total_plays DESC LIMIT 20

-- Binge listening sessions (≥10 plays)
SELECT ss.session_id, MAX(ss.session_length) depth,
       MIN(sp.ts) started_at,
       ROUND(100.0*SUM(ss.fully_played)/COUNT(*),1) completion_pct
FROM spotify_signals ss
JOIN spotify_plays sp ON ss.play_id = sp.id
WHERE ss.session_length >= 10
GROUP BY ss.session_id ORDER BY depth DESC LIMIT 20

-- Intent class distribution
SELECT intent_class, COUNT(*) n, ROUND(100.0*COUNT(*)/16678.0,1) pct
FROM spotify_signals GROUP BY intent_class ORDER BY n DESC
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
    is_side_insight: bool = False


class SpeakResponse(BaseModel):
    query: str
    findings: list[Finding]
    side_insights: list[str]
    trace: list[TraceEntry]
    rounds_used: int
    model: str
    hit_round_limit: bool
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_creation_tokens: int = 0


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
        return rubric  # _* discards model_label, usage, stop_reason
    except Exception:
        return (
            "1. Quantitatively anomalous relative to the user's own baseline (not just 'high')\n"
            "2. Temporally specific — bounded window, not diffuse across all time\n"
            "3. Cross-signal corroborated — appears in multiple data sources\n"
            "4. Contradicts likely self-model (counter-intuitive direction)\n"
            "5. Behaviorally actionable — reveals a habit or pattern, not just a preference"
        )


def _build_preamble(stats: dict, rubric: str, schema_context: str, max_rounds: int) -> str:
    """Data-specific context injected before the Langfuse-managed instructions."""
    return textwrap.dedent(f"""\
        You are Echo Speaks — an autonomous data analyst working on Aditya Arya's personal behavioral data.
        Explore raw data, form hypotheses, test them, synthesize surprising findings.
        You have {max_rounds} rounds total. Use them wisely: start broad, go deep on promising signals.

        {schema_context}

        ## Surprise rubric — rank findings by these criteria
        {rubric}
    """)


def _get_instruction_prompt():
    """Return a compiled-prompt client for the Langfuse-managed instruction block.

    Seeds the prompt to Langfuse on first call if it doesn't exist.
    Falls back to _NoopPrompt (local template) when Langfuse is unavailable.
    Cached for the lifetime of the server process.
    """
    global _prompt_client, _prompt_seeded
    if _prompt_client is not None:
        return _prompt_client
    lf = get_langfuse()
    if not _prompt_seeded:
        lf.seed_prompt("echo-speaks-instructions", _INSTRUCTION_TEMPLATE)
        _prompt_seeded = True
    _prompt_client = lf.get_prompt("echo-speaks-instructions", fallback=_INSTRUCTION_TEMPLATE)
    return _prompt_client


def _repair_json_strings(s: str) -> str:
    """Escape unescaped control characters inside JSON string values.

    The finish tool embeds evidence text that often contains literal newlines
    from SQL result tables. json.loads rejects those — this repairs them without
    touching structural whitespace between keys/values.
    """
    result = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            result.append(ch)
            escape_next = False
        elif ch == '\\' and in_string:
            result.append(ch)
            escape_next = True
        elif ch == '"':
            result.append(ch)
            in_string = not in_string
        elif in_string and ch == '\n':
            result.append('\\n')
        elif in_string and ch == '\r':
            result.append('\\r')
        elif in_string and ch == '\t':
            result.append('\\t')
        else:
            result.append(ch)
    return ''.join(result)


def _parse_response(text: str) -> tuple[str, str, dict] | None:
    thought_m = _THOUGHT_RE.search(text)
    action_m  = _ACTION_RE.search(text)
    if not action_m:
        return None
    thought  = thought_m.group(1).strip() if thought_m else ""
    raw_json = action_m.group(1)
    try:
        action = json.loads(raw_json)
    except json.JSONDecodeError:
        try:
            action = json.loads(_repair_json_strings(raw_json))
        except json.JSONDecodeError:
            return None
    return thought, str(action.get("tool", "")), dict(action.get("args", {}))


def _source_tag(observation: str) -> str:
    for tag in ("RAW-SQL", "RAW-COMPUTED", "SEMANTIC-RAW", "NARRATIVE"):
        if observation.startswith(f"[{tag}]"):
            return tag
    return "UNKNOWN"


def _trim_history(history: list[dict], keep_full: int = _KEEP_FULL_ROUNDS) -> list[dict]:
    """Compress old rounds so context window stays manageable over long sessions.

    For the _KEEP_FULL_ROUNDS most recent rounds: kept verbatim.
    For older rounds:
    - user OBSERVATION messages: first 200 chars + "[... trimmed]"
    - assistant THOUGHT+ACTION messages: first 120 chars + "[... trimmed]"
      (old reasoning is noise after 50 rounds; the agent only needs the gist)
    """
    if len(history) <= keep_full * 2 + 1:
        return history
    cutoff = max(1, len(history) - keep_full * 2)
    result = []
    for i, msg in enumerate(history):
        if i == 0 or i >= cutoff:
            result.append(msg)
        elif msg["role"] == "user" and "OBSERVATION" in msg["content"]:
            result.append({"role": "user", "content": msg["content"][:200] + " [... trimmed]"})
        elif msg["role"] == "assistant":
            result.append({"role": "assistant", "content": msg["content"][:120] + " [... trimmed]"})
        else:
            result.append(msg)
    return result


def _validate_findings(raw: list) -> list[Finding]:
    out = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        tag = str(f.get("source_tag", "")).upper().replace("[", "").replace("]", "")

        claim    = str(f.get("claim",    ""))[:500]   # hard cap: prevents finish JSON overflow
        evidence = str(f.get("evidence", ""))[:800]

        if tag == "EXTERNAL":
            out.append(Finding(
                claim=claim, evidence=evidence, source_tag=tag,
                confidence="medium", narrative_derived=False, is_side_insight=True,
            ))
        elif tag in ("RAW-SQL", "RAW-COMPUTED", "SEMANTIC-RAW"):
            out.append(Finding(
                claim=claim, evidence=evidence, source_tag=tag,
                confidence=str(f.get("confidence", "medium")),
                narrative_derived=False, is_side_insight=False,
            ))
        else:
            out.append(Finding(
                claim=claim, evidence=evidence, source_tag=tag or "UNKNOWN",
                confidence="low", narrative_derived=True, is_side_insight=False,
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

        preamble      = _build_preamble(stats, rubric, schema_context, req.max_rounds)
        prompt_client = _get_instruction_prompt()
        history: list[dict] = [{"role": "user", "content": req.query}]
        model_label = req.model

        session_state: dict = {}
        _tool_calls: list[str] = []
        _total_input_tokens          = 0
        _total_output_tokens         = 0
        _total_cache_read_tokens     = 0
        _total_cache_creation_tokens = 0

        # round_n is bound by the loop, but we read it after the loop to report
        # the actual last round reached (vs req.max_rounds). Initialise here so
        # the post-loop branch is safe even if max_rounds=0 or the loop breaks
        # before round 1.
        round_n = 0
        error_msg: str | None = None

        for round_n in range(1, req.max_rounds + 1):
            phase = 1 if round_n <= req.narrative_blind_rounds else 2

            if round_n == req.narrative_blind_rounds + 1:
                yield {"type": "phase_change", "phase": 2}
                history.append({
                    "role": "user",
                    "content": (
                        "[System: Phase 2 begins. vector_search(reflections) is now available "
                        "— use only to verify Phase 1 hypotheses. "
                        "[NARRATIVE] remains inadmissible as primary evidence.]"
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

            instructions = prompt_client.compile(
                narrative_blind_rounds=str(req.narrative_blind_rounds),
                phase_2_start=str(req.narrative_blind_rounds + 1),
                tools=tool_descriptions(phase == 1),
            )
            # preamble is passed as cached_prefix — stable across rounds on Anthropic path.
            # instructions change at Phase 2 (tool list differs) so they stay uncached.
            messages = (
                [{"role": "system", "content": instructions}]
                + _trim_history(history, _KEEP_FULL_ROUNDS)
            )

            llm_gen = trace.generation(round_n, model_label, len(history))

            try:
                raw_response, model_label, usage, stop_reason = llm_chat(
                    messages, model=req.model, max_tokens=4096, temperature=0.3,
                    cached_prefix=preamble,
                )
                _total_input_tokens          += usage.get("input_tokens", 0)
                _total_output_tokens         += usage.get("output_tokens", 0)
                _total_cache_read_tokens     += usage.get("cache_read_input_tokens", 0)
                _total_cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
                llm_gen.done(raw_response[:500], usage=usage, model=model_label)
                # Langfuse: flag truncated rounds immediately.
                if stop_reason in ("max_tokens", "length"):
                    lf.score(trace.trace_id, "quality.truncated", 1.0)
            except Exception as e:
                llm_gen.done(str(e))
                error_msg = str(e)
                yield {"type": "error", "round": round_n, "message": error_msg}
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

                # Langfuse quality metrics at finish.
                if _tool_calls:
                    unique_combos  = len(set(_tool_calls))
                    efficiency     = unique_combos / len(_tool_calls)
                    lf.score(trace.trace_id, "quality.efficiency", round(efficiency, 3))
                primary_count = sum(1 for f in findings if not f.is_side_insight)
                if primary_count > 0 and _total_input_tokens > 0:
                    cost_per_finding = _total_input_tokens / primary_count
                    lf.score(trace.trace_id, "quality.cost_per_finding", round(cost_per_finding, 0))

                trace.finish(len(findings), round_n, hit_limit=False)
                finish_evt = {
                    "type": "finish",
                    "findings": [f.model_dump() for f in findings],
                    "side_insights": side_insights,
                    "rounds_used": round_n,
                    "model": model_label,
                    "hit_round_limit": False,
                    "trace_id": trace.trace_id,
                    "total_input_tokens": _total_input_tokens,
                    "total_output_tokens": _total_output_tokens,
                    "total_cache_read_tokens": _total_cache_read_tokens,
                    "total_cache_creation_tokens": _total_cache_creation_tokens,
                }
                yield finish_evt
                return

            tool_span   = trace.tool(tool, args, round_n)
            observation = dispatch(tool, args, phase, session_state)
            tag         = _source_tag(observation)
            tool_span.done(observation[:400], source_tag=tag)

            # Track this call for efficiency metric (tool + serialised args).
            try:
                _tool_calls.append(f"{tool}:{json.dumps(args, sort_keys=True, default=str)}")
            except Exception:
                _tool_calls.append(tool)

            yield {"type": "observation", "round": round_n, "content": observation, "source_tag": tag}

            history.append({"role": "assistant", "content": raw_response})
            history.append({
                "role": "user",
                "content": f"OBSERVATION (round {round_n}/{req.max_rounds}, phase {phase}):\n{observation}",
            })

        # Loop exited without finish. Two distinct cases:
        # (a) error_msg set → exception broke the loop early. rounds_used = actual
        #     round reached, hit_round_limit = False (we crashed, didn't run out).
        # (b) loop completed naturally → rounds_used = max_rounds, hit_limit = True.
        if error_msg:
            rounds_used   = round_n
            hit_limit     = False
            side_insights = [
                f"Run aborted at round {round_n}/{req.max_rounds} due to error: {error_msg[:200]}"
            ]
        else:
            rounds_used   = req.max_rounds
            hit_limit     = True
            side_insights = [
                f"Agent reached the {req.max_rounds}-round limit without completing synthesis."
            ]

        trace.finish(0, rounds_used, hit_limit=hit_limit)
        limit_evt = {
            "type": "finish",
            "findings": [],
            "side_insights": side_insights,
            "rounds_used": rounds_used,
            "model": model_label,
            "hit_round_limit": hit_limit,
            "trace_id": trace.trace_id,
            "total_input_tokens": _total_input_tokens,
            "total_output_tokens": _total_output_tokens,
            "total_cache_read_tokens": _total_cache_read_tokens,
            "total_cache_creation_tokens": _total_cache_creation_tokens,
        }
        yield limit_evt

    finally:
        lf.flush()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("", response_model=SpeakResponse)
def speak(req: SpeakRequest, db: sqlite_utils.Database = Depends(get_db)):
    """Non-streaming JSON endpoint (curl / testing)."""
    trace_entries:          list[TraceEntry] = []
    findings:               list[Finding]    = []
    side_insights:          list[str]        = []
    model_label                  = req.model
    hit_limit                    = False
    total_input_tokens           = 0
    total_output_tokens          = 0
    total_cache_read_tokens      = 0
    total_cache_creation_tokens  = 0
    pending: dict                = {}

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
            findings                = [Finding(**f) for f in evt.get("findings", [])]
            side_insights           = evt.get("side_insights", [])
            model_label             = evt.get("model", req.model)
            hit_limit               = evt.get("hit_round_limit", False)
            total_input_tokens          = evt.get("total_input_tokens", 0)
            total_output_tokens         = evt.get("total_output_tokens", 0)
            total_cache_read_tokens     = evt.get("total_cache_read_tokens", 0)
            total_cache_creation_tokens = evt.get("total_cache_creation_tokens", 0)

    return SpeakResponse(
        query=req.query,
        findings=findings,
        side_insights=side_insights,
        trace=trace_entries,
        rounds_used=len(trace_entries),
        model=model_label,
        hit_round_limit=hit_limit,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_cache_read_tokens=total_cache_read_tokens,
        total_cache_creation_tokens=total_cache_creation_tokens,
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


class FindingScoreRequest(BaseModel):
    trace_id: str
    finding_index: int
    # finding_index: 0-based position among primary (non-side-insight) findings only.
    # Langfuse score key: finding_0, finding_1, … — no gaps, side insights excluded.
    value: float = Field(ge=0.0, le=1.0)  # 1.0=Correct, 0.5=Partial, 0.0=Wrong
    correction: str = ""


@router.post("/score-finding")
def score_finding(req: FindingScoreRequest):
    """Post a per-finding accuracy score to the Langfuse trace."""
    lf = get_langfuse()
    lf.score(
        req.trace_id,
        f"finding_{req.finding_index}",
        req.value,
        comment=req.correction or None,
    )
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
