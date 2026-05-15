# Echo Speaks — Context Management Analysis

Dataset: 10 Langfuse traces, 502 observations, 265 rounds, $6.53 total observed cost.
Date: 2026-05-15.

## TL;DR

Five claims, ranked by evidence strength.

1. **The current `_trim_history` doesn't fail through repetition or loops.** I initially thought the 50-round failure was the agent stuck in a loop. It wasn't — that "failure" was an Anthropic API timeout at R46, plus the agent never calling `finish` even after declaring "I have all the evidence I need" at R45.

2. **The trim DOES degrade information quality.** Old observations are reduced to their first 200 chars + `[... trimmed]`. For a typical SQL result that's the column header + 3-4 rows of a 200-row dataset. Late-round synthesis effectively works on the last 4 rounds + breadcrumbs.

3. **Per-round input tokens oscillate 4K–15K, not monotonically growing.** The trim caps history but creates a sawtooth pattern depending on what's in the last 4 rounds. The 48-round successful run averaged ~6.6K input tokens per round.

4. **Cost is approximately linear in rounds:** $0.025/round average. 50-round runs cost ~$1.30. Cost per finding rises sharply after round 25 (best efficiency: 36-round 10-finding run at $0.10/finding; worst: 48-round 7-finding at $0.19/finding).

5. **Langfuse cost numbers are upper bounds.** `observability.py` only emits `input_tokens` (the uncached portion) and never `cache_read` or `cache_creation`. Real costs are lower than reported. This is also a monitoring bug — we can't see cache hit rate from the dashboard.

## The data

### Per-trace summary (sorted by rounds_used)

| idx | rounds | findings | hit_limit | latency | in_tok | out_tok | cost (Langfuse, no-cache) |
|-----|--------|----------|-----------|---------|--------|---------|----|
| 0   | 3      | 2        | False     | 0s      | 0      | 10      | $0.000 (test) |
| 1   | 7      | 3        | False     | 35s     | 55,260 | 1,168   | $0.150 |
| 2   | 19     | 7        | False     | 269s    | 129,033| 13,714  | $0.593 |
| 3   | 19     | 5        | False     | 190s    | 0*     | 2,390   | $0.036 |
| 4   | 19     | 6        | False     | 197s    | 0*     | 2,373   | $0.036 |
| 5   | 25     | 7        | False     | 418s    | 240,438| 21,270  | $1.040 |
| 6   | 36     | 10       | False     | 599s    | 184,073| 31,734  | $1.028 |
| 7   | 39     | 8        | False     | 470s    | 222,099| 22,375  | $1.002 |
| 8   | 48     | 7        | False     | 561s    | 293,619| 29,129  | $1.318 |
| 9   | 50     | 0        | True**    | 714s    | 325,333| 23,141  | $1.323 |

*Traces 3,4 have null input_tokens because they used the OpenRouter or OpenAI path; cache token reporting differs and the Anthropic-style fields aren't populated.
**Trace 9 "hit_limit" is misleading — actual cause was an Anthropic API timeout at R46, then the loop's exception handler `break` falls through to the hit-limit branch in speak.py:673 which reports rounds_used=max_rounds.

### Per-round input token growth (the cost-per-round curve)

```
idx rounds R 1   R 5    R 10   R 15   R 20   R 25   R 30   R 35   R 40   R 45   R 48
  5     25  22   3,363  8,586  14,726 15,736 8,214
  6     36  66   2,788  5,932  3,211  4,977  6,050  6,600  9,815
  7     39  1260 3,655  6,951  5,844  6,669  5,902  5,420  7,173
  8     48  95   6,880  13,679 7,214  3,315  6,080  5,533  7,148  4,273  2,865  7,209
  9     50  66   5,065  13,148 6,425  6,721  7,711  4,984  8,061  10,332 6,738
```

Pattern: input tokens RAMP UP through rounds 5-15 as full observations accumulate in
the keep-full window, then OSCILLATE 4K-15K depending on which big observations
are in the last 4 rounds at any moment.

### What the agent actually does in long runs

48-round successful trace (Spotify+YouTube alignment): 33 unique tool+arg signatures,
9 repeated signatures (12 actual repeat calls, 27%). Re-checking the "repeats":
they're mostly progressive refinements — `SELECT strftime('%Y-%m'...)` queries with
different filters/joins/columns. Shared prefix tricked my counter into flagging
healthy iteration as redundant.

True duplicate: only ~2-3 calls per long run are byte-for-byte the same.
Adjusted estimate: real wasted-on-repetition rate is ~5-10%, not 27%.

### What 200-char observation trim actually looks like

Sample old SQL observation after trim:
```
[RAW-SQL]
{'month': '2016-12', 'n': 2}
{'month': '2020-05', 'n': 3}
{'month': '2020-06', 'n': 3}
{'month': '2020-07', 'n': 4}
{'month': '2020-08', 'n': 5}
{'month': '2020-09', 'n' [... trimmed]
```
First 5 rows of 60-row monthly result. Trend, recent months, totals — all gone.

Sample old execute_python observation after trim:
```
[RAW-COMPUTED]
=== TOPIC FIRST APPEARANCE vs SEARCH PRECURSOR ===

AI/Tech: 262 watches, first=2024-11-20
  Search-driven: 24 (9%), Autoplay: 11 [... trimmed]
```
First topic only. Rest of the analysis lost.

Sample old assistant message after trim (120 chars):
```
THOUGHT: This is very revealing! Session depth measures how far into a session th [... trimmed]
```
The reasoning is decapitated mid-sentence.

### Tool observation size ceilings (live, not Langfuse-truncated)

| tool | max chars | typical chars | typical tokens |
|------|-----------|---------------|----------------|
| run_sql | 6,000 (200 rows) | 1,500-4,000 | 400-1,000 |
| execute_python | 10,000 (stdout) + 3,000 (stderr) | 500-3,000 | 125-750 |
| vector_search | ~3,000 (5 results × 200 chars + header) | 1,500-2,500 | 400-625 |
| run_pelt / run_clustering | ~1,500 | 800-1,500 | 200-375 |
| youtube_lookup / web_search | ~2,000 | 800-1,500 | 200-400 |

Trim from full → 200 chars saves ~300-900 tokens per old observation per LLM call.
At 50 rounds × 46 trimmed observations × ~500 tokens saved = ~23,000 tokens saved
per round, ~1,150,000 token-equivalents saved across the run. Without trim, a
50-round run would cost ~$5-8 instead of ~$1.30.

**Conclusion: trim is necessary for cost. The question is HOW to trim, not WHETHER.**

## Failure modes observed

| Failure | Frequency | Real cause | Context-mgmt fix? |
|---------|-----------|-----------|---|
| API timeout mid-run | 1 / 10 traces (R46 of trace 9) | Anthropic API hiccup | No — needs retry logic in speak.py |
| Agent doesn't call finish when it should | 1 / 10 (trace 9 R45) | Agent behavior, not context | Maybe — clearer "rounds remaining" signal helps |
| Wasted exploration / mild repetition | ~5-10% of calls in long runs | Lossy 200-char trim | YES — better trim helps |
| Late synthesis missing early findings | Hard to measure; hypothesized | Lossy trim hides early discoveries | YES — better trim or scratchpad |
| Output token cap (max_tokens=4096) hit | 0 / 10 traces flagged | n/a | n/a |

Context management isn't the dominant failure mode. But it's the dominant
silent quality degradation — long runs synthesize from a 4-round window with
breadcrumbs of everything earlier.

## Cost surface (corrected for cache)

Per round on the Anthropic native path with current caching:
- Block 1 (preamble: ~5K tokens): cached after R1 → cache_read at $0.30/M = ~$0.0015
- Block 2 (instructions: ~1.5K tokens): cached within phase → cache_read = ~$0.0005
- Phase 1→2 boundary: 1× Block 2 cache_creation at $3.75/M = ~$0.006 once
- Trimmed history (variable, 4K-15K tokens fresh each round): full input rate $3/M = $0.012-0.045
- Output (~150-1000 tokens): $15/M = $0.002-0.015

Real per-round cost: roughly $0.015-0.060 (Langfuse over-reports by ~2-3× because
it doesn't see cache reads).

Real 50-round run cost: probably ~$1.00 (not $1.30 reported).

## Architecture options for context management

Five candidates. Stack-rankable by complexity and value.

### Option A: Status quo — string trim
- Cost: baseline. ~$0.025/round Langfuse, ~$0.018/round real.
- Quality: degraded synthesis, occasional confused refinement.
- Effort: zero.

### Option B: Tool-aware structured compression
Replace 200-char string trim with per-tool semantic compression:
- `run_sql` old → `[RAW-SQL] N rows, columns: c1,c2,...; first row: {...}; last row: {...}; key aggregates if numeric column present`
- `execute_python` old → first non-empty stdout line + last 200 chars
- `vector_search` old → just IDs/spans of top-3 results
- `run_pelt`, `run_clustering`, `youtube_lookup`, `web_search` → existing summary heuristic

Per-old-observation: ~400-600 chars instead of 200 chars. ~150 tokens vs 50 tokens.
Net: +100 tokens per trimmed obs, ~+5K tokens per LLM call at round 50.
Cost: +$0.015 per long run. Quality: dramatically better — agent sees STRUCTURE.

- Cost: tiny increase (~+$0.015/run for 50-round runs).
- Quality: agent retains row counts, columns, and key aggregates instead of arbitrary first chars.
- Effort: ~1 day per tool to write good summarizers + tests. ~4 days total.
- Latency: zero added (deterministic).

### Option C: AI summarization (Haiku 4.5)
When an observation ages out of `_KEEP_FULL_ROUNDS`, summarize it once via Haiku
with a fixed prompt: "Summarize this tool result in ≤2 sentences. Preserve all
key numbers, table names, column names. Drop raw data rows."

Cache summaries by round number — each observation is summarized exactly once.

- Per summary: ~2K input + 100 output @ Haiku ($1/M in, $5/M out) = ~$0.0025
- 50-round run: 46 summaries × $0.0025 = $0.115 added per run (+8% on a $1.30 run)
- Latency: ~0.5s per summary, can be parallelized in background between rounds
- Quality: very high — preserves the SEMANTIC content of old observations
- Effort: ~3 days (summarizer function, cache, integration with `_trim_history`, tests)

### Option D: Persistent scratchpad
Add a `note` tool the agent can call at any point to write a persistent fact.
Notes never get trimmed; they appear at the top of every system message under
"Findings recorded so far".

OR: heuristically extract a "key fact" line from each THOUGHT and append to a
running scratchpad — no agent action required.

- Cost: ~free (heuristic) or ~+1 round per note (agent-driven)
- Quality: depends entirely on agent discipline / heuristic quality
- Effort: ~2 days
- Risk: agent may not use it; heuristic extraction may grab noise

### Option E: Retrieval-augmented context
Store full observations server-side (already happens — `history` is monotonic).
Each round, embed current thought, retrieve top-K most relevant past observations,
inject them in addition to the trim window.

- Per round: 1 embedding ($0.00001) + retrieval (~50ms)
- Quality: targeted recall — agent gets exactly what it needs
- Effort: ~5 days (embedder, vector store, retrieval logic, prompt integration)
- Risk: retrieval can pull irrelevant context; needs threshold tuning

## Recommended architecture (first principles)

The right design is layered, not single-shot:

1. **Ground floor: Tool-aware structured compression (Option B).** Free win.
   Always-on. Replaces the dumb 200-char trim with smart per-tool summaries.
   Captures 80% of the value at 0% added cost or latency.

2. **Mid layer: Persistent micro-scratchpad (Option D, heuristic variant).**
   Each round, after the agent's THOUGHT lands, regex-extract sentences that
   match `\d+%|\d+ (rows|watches|plays)|peak|spike|cluster|chapter \d+` and
   append the top match to a never-trimmed scratchpad section in the system
   message. ~Free, ~10 lines of code.

3. **Top layer: AI summarization for runs >25 rounds (Option C).**
   Below 25 rounds, structured compression alone is enough.
   Above 25, when the trim window holds 21+ trimmed observations,
   spend the +8% to upgrade those summaries via Haiku.

4. **Skip retrieval for now (Option E).** Over-engineered. The scratchpad +
   AI summarization solve the "long-run synthesis is shallow" problem more
   directly with less complexity.

5. **Bonus fix: emit cache tokens to Langfuse (observability.py).** Five lines.
   Unblocks accurate cost monitoring. Should ship regardless.

## Open questions to validate before building

1. Is the agent ACTUALLY losing findings due to trim, or does it just synthesize
   from the last 4 rounds and that's fine? Need: instrument a 30-round run with
   structured compression, compare findings to a control run with current trim.

2. What % of trimmed observations are referenced again later? If <5%, the trim
   is barely costing anything in quality. If >20%, it's a real problem.

3. Should trim depth (`_KEEP_FULL_ROUNDS`) scale with round count? At 50 rounds
   keeping the last 4 full is much harsher than at 20 rounds keeping the last 4.
   Maybe `keep_full = max(4, max_rounds // 8)`?

4. Is the network timeout in trace 9 a recurring issue? Need: retry logic on
   API failures, with exponential backoff, before declaring failure.
