# Echo TODOS

Deferred work captured during engineering reviews. Each item includes enough context to
pick up without re-reading the session that produced it.

---

## TODO: Validate finding_index in /api/speak/score-finding

**What:** Check that `finding_index` is in range `[0, len(findings) - 1]` for the given trace.

**Why:** `score_finding` currently posts any `finding_index` to Langfuse without bounds
checking. An out-of-bounds index (e.g., `finding_999` on a 3-finding trace) creates a
spurious Langfuse score with no error to the caller.

**Pros:** Prevents silent data corruption in the Langfuse eval dashboard. Becomes important
if any external caller or script sends requests.

**Cons:** Requires server-side state: storing finding count per `trace_id`. Adds complexity.

**Context:** Currently single caller (frontend), which generates the index directly from the
findings array — will never be out-of-bounds in practice. Low priority until external callers
exist or spurious scores appear in the Langfuse dashboard.

**Approach:** Store `{trace_id: finding_count}` in a module-level dict in `speak.py` (populated
at `trace.finish()` time). Or add `GET /api/speak/trace/{trace_id}/findings` for server-side
count lookup.

**Blocked by:** Not pressing. Revisit after open-source release if external callers emerge.

---

## TODO: Handle score-finding network errors in SpeakView.svelte

**What:** When `POST /api/speak/score-finding` returns non-200, show a brief inline error
next to the score button instead of the optimistic "submitted" state.

**Why:** The button currently shows "submitted" regardless of response status. If Langfuse is
down, the eval score is silently lost — defeating the eval collection purpose.

**Pros:** Makes failures visible. Allows user to retry.

**Cons:** Minor UI complexity (new 'error' state in `findingScores`).

**Context:** Only matters when Langfuse is configured as a remote instance and experiences
downtime. Local noop Langfuse (no key configured) silently drops scores by design — this
is expected behavior, not an error.

**Approach:** Check `response.ok` after fetch. Add `'error'` state alongside `'idle'` and
`'submitted'` in the `findingScores` record. Show a red `!` icon with tooltip "Score failed
— try again."

**Blocked by:** Low priority while Langfuse is noop or always-available.

---

## TODO: LLM-as-judge eval batch after 20+ annotated traces

**What:** After 20+ human-annotated findings exist in Langfuse, run a batch LLM-as-judge pass.
For each finding, submit `(claim + evidence + source_tag)` to GPT-4o and ask: "Is this claim
well-supported by the evidence? Score 0–1 with justification." Compare to human score.

**Why:** Per-finding human evals (via the Sprint 5 score buttons) build the ground truth dataset.
LLM-as-judge can then scale to all new sessions automatically, surfacing systematic gaps (e.g.,
SEMANTIC-RAW findings always overconfident).

**Pros:** Scales eval coverage beyond what manual annotation can sustain.

**Cons:** Requires OpenAI API credits. Outputs are probabilistic — treat as signal, not ground truth.

**Context:** Sprint 5 builds the human eval collection mechanism. This TODO activates once the
dataset exists. Design doc (Task 7) already anticipated this.

**Approach:** New script `eval_findings.py`. Fetches Langfuse traces where `finding_N` scores
exist, runs GPT-4o judge prompt per finding, logs human/LLM score correlation, flags systematic
biases by `source_tag`.

**Blocked by:** Needs 20+ human-annotated sessions. Estimate: 3–4 hrs once dataset exists.
