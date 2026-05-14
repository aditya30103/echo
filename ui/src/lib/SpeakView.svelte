<script lang="ts">
	type Finding = {
		claim: string;
		evidence: string;
		source_tag: string;
		confidence: string;
		narrative_derived: boolean;
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
		'UNKNOWN':      '#6b7280',
	};

	const CONF_COLOR: Record<string, string> = {
		high:   '#22c55e',
		medium: '#eab308',
		low:    '#ef4444',
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

	function reset() {
		rounds = [];
		findings = [];
		sideInsights = [];
		rubricReady = false;
		done = false;
		hitLimit = false;
		modelLabel = '';
		error = '';
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
		} else if (type === 'finish') {
			findings     = (evt.findings as Finding[]) ?? [];
			sideInsights = (evt.side_insights as string[]) ?? [];
			modelLabel   = evt.model as string ?? '';
			hitLimit     = evt.hit_round_limit as boolean ?? false;
			// Mark last round done
			rounds = rounds.map((r, i) => i === rounds.length - 1 ? { ...r, done: true, collapsed: true } : r);
			done = true;
		} else if (type === 'error') {
			error = (evt.message as string) ?? 'Unknown error';
			done = true;
		}
	}

	async function runSpeak() {
		if (!query.trim() || running) return;
		reset();
		running = true;

		try {
			const res = await fetch('/api/speak/stream', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ query, max_rounds: maxRounds, model: 'auto', narrative_blind_rounds: 6 }),
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
		if (tool === 'get_chapter_context') return `Chapter ${args.chapter_id}`;
		return JSON.stringify(args);
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
		<div class="trace">

			{#if running && !rubricReady}
				<p class="status-line">Generating rubric…</p>
			{/if}

			{#each rounds as r (r.round)}
				{@const isPhase2Start = r.phase === 2 && (rounds.findIndex(x => x.round === r.round) === 0 || rounds[rounds.findIndex(x => x.round === r.round) - 1]?.phase === 1)}

				{#if isPhase2Start}
					<div class="phase-banner">Phase 2 — narrative verification unlocked</div>
				{/if}

				<div class="round-card" class:collapsed={r.collapsed}>
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
			<div class="synthesis">
				<div class="synthesis-header">
					<span>Findings</span>
					{#if modelLabel}<span class="dim" style="font-weight:400;text-transform:none;letter-spacing:0">{modelLabel}</span>{/if}
				</div>
				<ol class="findings-list">
					{#each findings as f, i}
						<li class="finding">
							<div class="finding-meta">
								<span class="finding-tag" style="color:{TAG_COLOR[f.source_tag] ?? '#6b7280'}">[{f.source_tag}]</span>
								<span class="finding-conf" style="color:{CONF_COLOR[f.confidence] ?? '#6b7280'}">{f.confidence}</span>
								{#if f.narrative_derived}
									<span class="finding-warn">narrative-derived</span>
								{/if}
							</div>
							<p class="finding-claim">{f.claim}</p>
							{#if f.evidence}
								<p class="finding-evidence">{f.evidence}</p>
							{/if}
						</li>
					{/each}
				</ol>

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
		border-bottom: 1px solid #1f2937;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.finding:last-child { border-bottom: none; }

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
</style>
