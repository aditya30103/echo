<script lang="ts">
	import RoundPillStrip from './RoundPillStrip.svelte';
	import CostFooter from './CostFooter.svelte';

	type Finding = {
		claim: string;
		evidence: string;
		source_tag: string;
		confidence: string;
		narrative_derived: boolean;
		is_side_insight: boolean;
	};

	type Round = {
		round: number;
		phase: number;
		thought: string;
		tool: string;
		args: Record<string, unknown>;
		observation: string;
		source_tag: string;
		done: boolean;      // observation received
		collapsed: boolean;
	};

	const PRESETS = [
		"What are the 3 most important things my data tells me about myself that I don't already know?",
		"What changed most about my content consumption between 2024 and 2025?",
		"Where does my attention actually go — what am I spending the most focus on?",
	];

	const TAG_COLOR: Record<string, string> = {
		'RAW-SQL':      '#22c55e',
		'RAW-COMPUTED': '#3b82f6',
		'SEMANTIC-RAW': '#eab308',
		'NARRATIVE':    '#f97316',
		'EXTERNAL':     '#6b7280',
		'UNKNOWN':      '#6b7280',
	};

	const CONF_COLOR: Record<string, string> = {
		high:   '#22c55e',
		medium: '#eab308',
		low:    '#ef4444',
	};

	type FindingEval = {
		score: number | null;
		correctionOpen: boolean;
		correction: string;
		submitted: boolean;
	};

	let query        = $state('');
	let maxRounds    = $state(20);
	let running      = $state(false);
	let rubricReady  = $state(false);
	let rounds: Round[]      = $state([]);
	let findings: Finding[]  = $state([]);
	let sideInsights: string[] = $state([]);
	let modelLabel   = $state('');
	let hitLimit     = $state(false);
	let done         = $state(false);
	let error        = $state('');
	let traceId      = $state('');
	let scoreGiven          = $state<number | null>(null);
	let totalInputTokens    = $state(0);
	let totalOutputTokens   = $state(0);
	let totalCacheReadTokens = $state(0);
	let expandedFindings    = $state<Set<number>>(new Set());
	let autoScrollPaused    = $state(false);
	let findingScores       = $state<Record<number, FindingEval>>({});

	function reset() {
		rounds = [];
		findings = [];
		sideInsights = [];
		rubricReady = false;
		done = false;
		hitLimit = false;
		modelLabel = '';
		error = '';
		traceId = '';
		scoreGiven = null;
		totalInputTokens = 0;
		totalOutputTokens = 0;
		totalCacheReadTokens = 0;
		expandedFindings = new Set();
		autoScrollPaused = false;
		findingScores = {};
	}

	function currentRound(): Round | undefined {
		return rounds.at(-1);
	}

	function handleEvent(evt: Record<string, unknown>) {
		const type = evt.type as string;

		if (type === 'rubric_start') {
			rubricReady = false;
		} else if (type === 'rubric_done') {
			rubricReady = true;
		} else if (type === 'round_start') {
			// Auto-collapse the previous round when the new one starts
			rounds = rounds.map((r, i) =>
				i < rounds.length - 1 ? { ...r, collapsed: true } : r
			);
			rounds = [...rounds, {
				round:     evt.round as number,
				phase:     evt.phase as number,
				thought:   '',
				tool:      '',
				args:      {},
				observation: '',
				source_tag: '',
				done:      false,
				collapsed: false,
			}];
		} else if (type === 'thought') {
			rounds = rounds.map(r =>
				r.round === evt.round ? { ...r, thought: evt.content as string } : r
			);
		} else if (type === 'action') {
			rounds = rounds.map(r =>
				r.round === evt.round
					? { ...r, tool: evt.tool as string, args: evt.args as Record<string, unknown> }
					: r
			);
		} else if (type === 'observation') {
			rounds = rounds.map(r =>
				r.round === evt.round
					? { ...r, observation: evt.content as string, source_tag: evt.source_tag as string, done: true }
					: r
			);
		} else if (type === 'phase_change') {
			// Visual separator handled via phase field on round_start
		} else if (type === 'format_error') {
			// Model output was not valid THOUGHT/ACTION — mark round done so it doesn't stay "running"
			rounds = rounds.map(r =>
				r.round === (evt.round as number)
					? { ...r, observation: '[FORMAT ERROR] Model output unparseable — agent will retry.', source_tag: 'UNKNOWN', done: true }
					: r
			);
		} else if (type === 'finish') {
			findings             = (evt.findings as Finding[]) ?? [];
			sideInsights         = (evt.side_insights as string[]) ?? [];
			modelLabel           = (evt.model as string) ?? '';
			hitLimit             = (evt.hit_round_limit as boolean) ?? false;
			traceId              = (evt.trace_id as string) ?? '';
			totalInputTokens     = (evt.total_input_tokens as number) ?? 0;
			totalOutputTokens    = (evt.total_output_tokens as number) ?? 0;
			totalCacheReadTokens = (evt.total_cache_read_tokens as number) ?? 0;
			rounds = rounds.map((r, i) => i === rounds.length - 1 ? { ...r, done: true, collapsed: true } : r);
			done = true;
		} else if (type === 'error') {
			error = (evt.message as string) ?? 'Unknown error';
			done = true;
		}
	}

	async function postScore(value: number) {
		if (!traceId || scoreGiven !== null) return;
		scoreGiven = value;
		try {
			await fetch('/api/speak/score', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ trace_id: traceId, value }),
			});
		} catch { /* score is best-effort */ }
	}

	function openCorrection(idx: number, score: number) {
		findingScores[idx] = { score, correctionOpen: true, correction: '', submitted: false };
	}

	async function submitFindingScore(idx: number, score: number | null) {
		if (score === null) return;
		const tid        = traceId; // capture before any await
		const correction = findingScores[idx]?.correction ?? '';
		findingScores[idx] = { score, correctionOpen: false, correction, submitted: true };
		try {
			await fetch('/api/speak/score-finding', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ trace_id: tid, finding_index: idx, value: score, correction }),
			});
		} catch { /* score is best-effort */ }
	}

	async function runSpeak() {
		if (!query.trim() || running) return;
		reset();
		running = true;

		try {
			const res = await fetch('/api/speak/stream', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ query, max_rounds: maxRounds, model: 'auto', narrative_blind_rounds: Math.floor(maxRounds / 2) }),
			});

			if (!res.ok || !res.body) {
				error = `HTTP ${res.status}`;
				return;
			}

			const reader  = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer    = '';

			while (true) {
				const { done: streamDone, value } = await reader.read();
				if (streamDone) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split('\n');
				buffer = lines.pop() ?? '';

				for (const line of lines) {
					if (!line.startsWith('data: ')) continue;
					const raw = line.slice(6).trim();
					if (raw === '[DONE]') break;
					try {
						handleEvent(JSON.parse(raw));
					} catch { /* ignore malformed events */ }
				}
			}
		} catch (e) {
			error = String(e);
		} finally {
			running = false;
			done = true;
		}
	}

	function toggleRound(r: Round) {
		rounds = rounds.map(x => x.round === r.round ? { ...x, collapsed: !x.collapsed } : x);
	}

	function fmtArgs(tool: string, args: Record<string, unknown>): string {
		if (tool === 'run_sql')        return String(args.query ?? '').trim();
		if (tool === 'execute_python') return String(args.code ?? '').trim();
		if (tool === 'vector_search')  return `"${args.query}" → ${args.table}`;
		if (tool === 'web_search')     return `"${args.query}"`;
		if (tool === 'youtube_lookup') return String(args.video_id ?? '');
		return JSON.stringify(args);
	}

	function handlePillSelect(round: number) {
		autoScrollPaused = true;
		const r = rounds.find(x => x.round === round);
		if (!r) return;
		if (r.done) {
			rounds = rounds.map(x => x.round === round ? { ...x, collapsed: false } : x);
		}
		const el = document.getElementById(`round-card-${round}`);
		if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
	}

	function toggleFinding(idx: number) {
		const next = new Set(expandedFindings);
		if (next.has(idx)) next.delete(idx); else next.add(idx);
		expandedFindings = next;
	}
</script>

<div class="speak-wrap">

	<!-- ── Query panel ─────────────────────────────────────────── -->
	<div class="query-panel">
		<textarea
			class="query-input"
			placeholder="Ask Echo to investigate your data…"
			bind:value={query}
			rows={3}
			onkeydown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runSpeak(); } }}
		></textarea>

		<div class="presets">
			{#each PRESETS as p}
				<button class="preset-btn" onclick={() => { query = p; }}>
					{p.slice(0, 55)}…
				</button>
			{/each}
		</div>

		<div class="query-controls">
			<label class="rounds-label">
				Max rounds
				<input type="number" min={4} max={20} bind:value={maxRounds} class="rounds-input" />
			</label>
			<button class="run-btn" onclick={runSpeak} disabled={running || !query.trim()}>
				{running ? 'Investigating…' : 'Investigate'}
			</button>
		</div>
	</div>

	<!-- ── Agent trace ────────────────────────────────────────── -->
	{#if rounds.length > 0 || running}
		{#if rounds.length > 0}
			<RoundPillStrip
				rounds={rounds.map(r => ({ round: r.round, tool: r.tool, done: r.done }))}
				onSelect={handlePillSelect}
			/>
		{/if}
		<div class="trace">

			{#if running && !rubricReady}
				<p class="status-line">Generating rubric…</p>
			{/if}

			{#each rounds as r (r.round)}
				{@const isPhase2Start = r.phase === 2 && (rounds.findIndex(x => x.round === r.round) === 0 || rounds[rounds.findIndex(x => x.round === r.round) - 1]?.phase === 1)}

				{#if isPhase2Start}
					<div class="phase-banner">Phase 2 — all tools unlocked (reflections available for verification only)</div>
				{/if}

				<div class="round-card" class:collapsed={r.collapsed} id="round-card-{r.round}">
					<button class="round-header" onclick={() => toggleRound(r)}>
						<span class="round-num">Round {r.round}</span>
						{#if r.tool}
							<span class="round-tool" style="color:{TAG_COLOR[r.source_tag] ?? '#6b7280'}">{r.tool}</span>
						{/if}
						{#if !r.done}
							<span class="round-status dim">running…</span>
						{/if}
						<span class="round-chevron">{r.collapsed ? '›' : '∨'}</span>
					</button>

					{#if !r.collapsed}
						<div class="round-body">
							{#if r.thought}
								<p class="round-thought">{r.thought}</p>
							{/if}

							{#if r.tool && r.tool !== 'finish'}
								<div class="round-action">
									<span class="action-tag">{r.tool}</span>
									<pre class="action-args">{fmtArgs(r.tool, r.args)}</pre>
								</div>
							{/if}

							{#if r.observation}
								<div class="round-obs">
									<span class="obs-tag" style="color:{TAG_COLOR[r.source_tag] ?? '#6b7280'}">[{r.source_tag}]</span>
									<pre class="obs-text">{r.observation.replace(/^\[[A-Z-]+\]\s*/, '')}</pre>
								</div>
							{:else if !r.done && r.tool}
								<p class="status-line">Waiting for result…</p>
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	<!-- ── Synthesis ─────────────────────────────────────────── -->
	{#if done}
		{#if error}
			<div class="synthesis-error">Error: {error}</div>
		{:else if hitLimit}
			<div class="synthesis-warn">Agent hit the round limit ({maxRounds}) without completing synthesis.</div>
		{/if}

		{#if findings.length > 0}
			{@const primaryFindings  = findings.filter(f => !f.is_side_insight)}
			{@const externalFindings = findings.filter(f => f.is_side_insight)}
			<div class="synthesis">
				<div class="synthesis-header">
					<span>Findings</span>
					{#if modelLabel}<span class="dim" style="font-weight:400;text-transform:none;letter-spacing:0">{modelLabel}</span>{/if}
				</div>
				<ol class="findings-list">
					{#each primaryFindings as f, i}
						<li class="finding-item">
							<div class="finding finding-accordion" onclick={() => toggleFinding(i)}>
								<div class="finding-meta">
									<span class="finding-tag" style="color:{TAG_COLOR[f.source_tag] ?? '#6b7280'}">[{f.source_tag}]</span>
									<span class="finding-conf" style="color:{CONF_COLOR[f.confidence] ?? '#6b7280'}">{f.confidence}</span>
									{#if f.narrative_derived}
										<span class="finding-warn">narrative-derived</span>
									{/if}
									{#if f.evidence}
										<span class="finding-toggle">{expandedFindings.has(i) ? '∨' : '›'}</span>
									{/if}
								</div>
								<p class="finding-claim">{f.claim}</p>
								{#if expandedFindings.has(i) && f.evidence}
									<p class="finding-evidence">{f.evidence}</p>
								{/if}
							</div>
							{#if done && traceId}
								<div class="finding-eval-row">
									{#if findingScores[i]?.submitted}
										<span class="fev-submitted">✓ Submitted</span>
									{:else if findingScores[i]?.correctionOpen}
										<textarea
											class="fev-correction"
											placeholder="What's inaccurate? (optional)"
											aria-label="Correction for this finding"
											bind:value={findingScores[i].correction}
											rows={2}
										></textarea>
										<button
											class="fev-submit-btn"
											aria-label="Submit correction"
											onclick={() => submitFindingScore(i, findingScores[i].score)}
										>Submit correction</button>
									{:else}
										<button class="fev-btn fev-correct" onclick={() => submitFindingScore(i, 1.0)}>✓ Correct</button>
										<button class="fev-btn fev-partial" onclick={() => openCorrection(i, 0.5)}>~ Partial</button>
										<button class="fev-btn fev-wrong"   onclick={() => openCorrection(i, 0.0)}>✗ Wrong</button>
									{/if}
								</div>
							{/if}
						</li>
					{/each}
				</ol>

				{#if externalFindings.length > 0}
					<div class="side-insights">
						<p class="side-label">External context</p>
						<ul>
							{#each externalFindings as f}
								<li class="external-finding">{f.claim}</li>
							{/each}
						</ul>
					</div>
				{/if}

				{#if sideInsights.length > 0}
					<div class="side-insights">
						<p class="side-label">Side insights</p>
						<ul>
							{#each sideInsights as s}
								<li>{s}</li>
							{/each}
						</ul>
					</div>
				{/if}
			</div>
		{/if}

		{#if traceId}
			<div class="score-bar">
				{#if scoreGiven === null}
					<span class="score-label">Was this surprising?</span>
					<button class="score-btn score-yes" onclick={() => postScore(1)}>Yes, surprising</button>
					<button class="score-btn score-no"  onclick={() => postScore(0)}>Expected</button>
				{:else}
					<span class="score-logged">{scoreGiven === 1 ? 'Marked surprising' : 'Marked expected'} — logged to Langfuse</span>
				{/if}
			</div>
		{/if}

		{#if totalInputTokens > 0}
			{@const primaryCount = findings.filter(f => !f.is_side_insight).length}
			<CostFooter
				{totalInputTokens}
				{totalOutputTokens}
				{totalCacheReadTokens}
				model={modelLabel}
				primaryFindingCount={primaryCount}
			/>
		{/if}
	{/if}

</div>

<style>
	.speak-wrap {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	/* ── Query panel ── */
	.query-panel {
		background: #0d1117;
		border: 1px solid #1f2937;
		border-radius: 8px;
		padding: 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.query-input {
		width: 100%;
		background: #111827;
		border: 1px solid #374151;
		border-radius: 6px;
		color: #e5e7eb;
		font-size: 0.9rem;
		line-height: 1.5;
		padding: 0.6rem 0.75rem;
		resize: vertical;
		font-family: inherit;
		box-sizing: border-box;
	}
	.query-input:focus { outline: 1px solid #4b5563; }
	.query-input::placeholder { color: #4b5563; }

	.presets {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.preset-btn {
		background: none;
		border: 1px solid #1f2937;
		border-radius: 4px;
		color: #6b7280;
		font-size: 0.72rem;
		padding: 0.3rem 0.6rem;
		text-align: left;
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
	}
	.preset-btn:hover { color: #9ca3af; border-color: #374151; }

	.query-controls {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.rounds-label {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.72rem;
		color: #6b7280;
	}
	.rounds-input {
		width: 3.5rem;
		background: #111827;
		border: 1px solid #374151;
		border-radius: 4px;
		color: #e5e7eb;
		font-size: 0.8rem;
		padding: 0.2rem 0.4rem;
		text-align: center;
	}

	.run-btn {
		margin-left: auto;
		background: #6366f1;
		border: none;
		border-radius: 6px;
		color: #fff;
		font-size: 0.85rem;
		font-weight: 600;
		padding: 0.45rem 1.1rem;
		cursor: pointer;
		transition: background 0.15s;
	}
	.run-btn:hover:not(:disabled) { background: #4f46e5; }
	.run-btn:disabled { opacity: 0.4; cursor: default; }

	/* ── Trace ── */
	.trace { display: flex; flex-direction: column; gap: 0.4rem; }

	.phase-banner {
		font-size: 0.68rem;
		color: #f97316;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		font-weight: 600;
		padding: 0.3rem 0;
		border-top: 1px solid #1f2937;
		margin-top: 0.25rem;
	}

	.round-card {
		border: 1px solid #1f2937;
		border-radius: 6px;
		overflow: hidden;
	}

	.round-header {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0.75rem;
		background: #0d1117;
		border: none;
		cursor: pointer;
		text-align: left;
	}
	.round-header:hover { background: #111827; }

	.round-num {
		font-size: 0.68rem;
		font-weight: 600;
		color: #4b5563;
		min-width: 4rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
	.round-tool { font-size: 0.78rem; font-weight: 600; }
	.round-status { font-size: 0.68rem; font-style: italic; }
	.round-chevron {
		margin-left: auto;
		font-size: 0.9rem;
		color: #374151;
		line-height: 1;
	}

	.round-body { padding: 0.75rem; display: flex; flex-direction: column; gap: 0.6rem; background: #111827; }

	.round-thought {
		margin: 0;
		font-size: 0.8rem;
		color: #9ca3af;
		line-height: 1.55;
	}

	.round-action { display: flex; flex-direction: column; gap: 0.3rem; }
	.action-tag {
		font-size: 0.65rem;
		font-weight: 700;
		color: #6b7280;
		text-transform: uppercase;
		letter-spacing: 0.07em;
	}
	.action-args {
		margin: 0;
		font-size: 0.75rem;
		color: #d1d5db;
		white-space: pre-wrap;
		word-break: break-all;
		background: #0d1117;
		border: 1px solid #1f2937;
		border-radius: 4px;
		padding: 0.4rem 0.6rem;
		max-height: 8rem;
		overflow-y: auto;
	}

	.round-obs { display: flex; flex-direction: column; gap: 0.3rem; }
	.obs-tag { font-size: 0.65rem; font-weight: 700; }
	.obs-text {
		margin: 0;
		font-size: 0.75rem;
		color: #9ca3af;
		white-space: pre-wrap;
		word-break: break-all;
		max-height: 10rem;
		overflow-y: auto;
		background: #0d1117;
		border: 1px solid #1f2937;
		border-radius: 4px;
		padding: 0.4rem 0.6rem;
	}

	.status-line { margin: 0; font-size: 0.75rem; color: #4b5563; font-style: italic; }

	/* ── Synthesis ── */
	.synthesis {
		border: 1px solid #1f2937;
		border-radius: 8px;
		overflow: hidden;
	}

	.synthesis-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem 1rem;
		background: #0d1117;
		font-size: 0.7rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #6b7280;
		border-bottom: 1px solid #1f2937;
	}

	.findings-list {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.finding {
		padding: 0.9rem 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.finding-accordion {
		cursor: pointer;
		user-select: none;
	}
	.finding-accordion:hover { background: #0d1117; }
	.finding-toggle {
		margin-left: auto;
		font-size: 0.75rem;
		color: #374151;
	}

	.finding-meta {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	.finding-tag { font-size: 0.65rem; font-weight: 700; }
	.finding-conf { font-size: 0.65rem; font-weight: 600; text-transform: capitalize; }
	.finding-warn {
		font-size: 0.65rem;
		color: #f97316;
		font-style: italic;
	}

	.finding-claim {
		margin: 0;
		font-size: 0.88rem;
		color: #f3f4f6;
		line-height: 1.55;
	}

	.finding-evidence {
		margin: 0;
		font-size: 0.72rem;
		color: #6b7280;
		font-family: monospace;
		white-space: pre-wrap;
		word-break: break-all;
	}

	/* ── Per-finding eval row ── */
	.finding-item {
		border-bottom: 1px solid #1f2937;
		display: flex;
		flex-direction: column;
	}
	.finding-item:last-child { border-bottom: none; }

	.finding-eval-row {
		display: flex;
		align-items: flex-start;
		flex-wrap: wrap;
		gap: 0.4rem;
		padding: 0.5rem 1rem;
		border-top: 1px solid #1f2937;
		background: #0a0e14;
	}

	.fev-btn {
		font-size: 0.68rem;
		font-weight: 600;
		padding: 0.25rem 0.65rem;
		border-radius: 4px;
		border: 1px solid;
		cursor: pointer;
		background: none;
		transition: background 0.12s, color 0.12s;
	}
	.fev-correct { border-color: #22c55e; color: #22c55e; }
	.fev-correct:hover { background: #22c55e; color: #0d1117; }
	.fev-partial { border-color: #eab308; color: #eab308; }
	.fev-partial:hover { background: #eab308; color: #0d1117; }
	.fev-wrong   { border-color: #ef4444; color: #ef4444; }
	.fev-wrong:hover   { background: #ef4444; color: #0d1117; }

	.fev-correction {
		width: 100%;
		background: #111827;
		border: 1px solid #374151;
		border-radius: 6px;
		color: #e5e7eb;
		font-size: 0.78rem;
		line-height: 1.5;
		padding: 0.4rem 0.6rem;
		resize: vertical;
		font-family: inherit;
		box-sizing: border-box;
	}
	.fev-correction:focus { outline: 1px solid #4b5563; }
	.fev-correction::placeholder { color: #4b5563; }

	.fev-submit-btn {
		font-size: 0.72rem;
		font-weight: 600;
		padding: 0.3rem 0.8rem;
		border-radius: 4px;
		border: none;
		background: #6366f1;
		color: #fff;
		cursor: pointer;
		transition: background 0.12s;
	}
	.fev-submit-btn:hover { background: #4f46e5; }

	.fev-submitted {
		font-size: 0.68rem;
		color: #4b5563;
		font-style: italic;
	}

	.side-insights {
		padding: 0.75rem 1rem;
		background: #0d1117;
		border-top: 1px solid #1f2937;
	}
	.side-label {
		margin: 0 0 0.4rem;
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: #4b5563;
	}
	.side-insights ul {
		margin: 0;
		padding: 0 0 0 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}
	.side-insights li { font-size: 0.78rem; color: #9ca3af; line-height: 1.5; }
	.external-finding { font-size: 0.78rem; color: #6b7280; line-height: 1.5; }

	.synthesis-error {
		padding: 0.75rem 1rem;
		background: #1a0a0a;
		border: 1px solid #7f1d1d;
		border-radius: 6px;
		color: #fca5a5;
		font-size: 0.8rem;
	}

	.synthesis-warn {
		padding: 0.75rem 1rem;
		background: #1a120a;
		border: 1px solid #78350f;
		border-radius: 6px;
		color: #fbbf24;
		font-size: 0.8rem;
	}

	.dim { color: #6b7280; }

	/* ── Score bar ── */
	.score-bar {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.6rem 1rem;
		border: 1px solid #1f2937;
		border-radius: 6px;
		background: #0d1117;
	}
	.score-label {
		font-size: 0.72rem;
		color: #6b7280;
		margin-right: auto;
	}
	.score-btn {
		font-size: 0.72rem;
		font-weight: 600;
		padding: 0.3rem 0.8rem;
		border-radius: 4px;
		border: 1px solid;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}
	.score-yes {
		background: none;
		border-color: #22c55e;
		color: #22c55e;
	}
	.score-yes:hover { background: #22c55e; color: #0d1117; }
	.score-no {
		background: none;
		border-color: #4b5563;
		color: #6b7280;
	}
	.score-no:hover { background: #1f2937; color: #9ca3af; }
	.score-logged {
		font-size: 0.72rem;
		color: #4b5563;
		font-style: italic;
	}
</style>
