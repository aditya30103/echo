<script lang="ts">
	import TimelineCard from '$lib/TimelineCard.svelte';
	import SpeakView from '$lib/SpeakView.svelte';

	type WatchItem = {
		watch_id: number;
		video_id: string;
		watched_at_ist: string;
		title: string | null;
		channel: string | null;
		is_rewatch: number | null;
		session_depth: number | null;
		is_search_driven: number | null;
		thumbnail_url: string;
		chapter_id: number | null;
		chapter_label: string | null;
	};

	// ── view state ───────────────────────────────────────────────────────────────
	type View = 'sessions' | 'agency' | 'chat' | 'speak';
	let selectedView: View = $state('speak');

	// ── binge sessions view ───────────────────────────────────────────────────────
	type Session = {
		session_id: number;
		depth: number;
		depth_pct: number;
		session_start: string;
		session_end: string;
		duration_min: number;
		watch_count: number;
		top_channel: string;
		searched_count: number;
		autoplay_count: number;
		rewatch_count: number;
		shorts_pct: number;
		start_hour: number;
		is_night: boolean;
		sample_titles: string[];
	};
	let sessions: Session[] = $state([]);
	let sessionsLoading: boolean = $state(false);
	let sessionsError: string = $state('');
	let sessionsLoaded: boolean = $state(false);

	async function loadSessions() {
		if (sessionsLoaded) return;
		sessionsLoading = true;
		sessionsError = '';
		try {
			const res = await fetch('/api/insights/sessions?limit=50&min_depth=5');
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = await res.json();
			sessions = data.sessions;
			sessionsLoaded = true;
		} catch (e) {
			sessionsError = String(e);
		} finally {
			sessionsLoading = false;
		}
	}

	// ── agency map view ────────────────────────────────────────────────────────────
	type AgencyChapter = {
		chapter_id: number;
		label: string;
		start_at: string;
		end_at: string;
		total: number;
		searched: number;
		bookmarked: number;
		autoplay: number;
		rewatch: number;
		searched_pct: number;
		bookmarked_pct: number;
		autoplay_pct: number;
		rewatch_pct: number;
	};
	let agencyData: AgencyChapter[] = $state([]);
	let agencyLoading: boolean = $state(false);
	let agencyError: string = $state('');
	let agencyLoaded: boolean = $state(false);

	async function loadAgency() {
		if (agencyLoaded) return;
		agencyLoading = true;
		agencyError = '';
		try {
			const res = await fetch('/api/insights/agency');
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = await res.json();
			agencyData = data.chapters;
			agencyLoaded = true;
		} catch (e) {
			agencyError = String(e);
		} finally {
			agencyLoading = false;
		}
	}

	// ── chat view ─────────────────────────────────────────────────────────────────
	type Source = { kind: string; label: string; similarity: number | null; };
	type ChatMessage = {
		role: 'user' | 'assistant';
		content: string;
		model?: string;
		sources?: Source[];
		error?: boolean;
	};

	let chatHistory: ChatMessage[] = $state([]);
	let chatInput: string = $state('');
	let chatModel: string = $state('auto');
	let chatStart: string = $state('');
	let chatEnd: string = $state('');
	let chatIncludeReflections: boolean = $state(false);
	let chatLoading: boolean = $state(false);
	let availableModels: string[] = $state([]);
	let chatModelsLoaded: boolean = $state(false);

	async function loadChatModels() {
		if (chatModelsLoaded) return;
		try {
			const res = await fetch('/api/chat/models');
			if (res.ok) { const d = await res.json(); availableModels = d.models; }
		} catch { /* ignore */ }
		chatModelsLoaded = true;
	}

	async function sendChat() {
		const q = chatInput.trim();
		if (!q || chatLoading) return;
		chatInput = '';
		chatHistory = [...chatHistory, { role: 'user', content: q }];
		chatLoading = true;
		try {
			const body: Record<string, unknown> = { question: q, model: chatModel, include_reflections: chatIncludeReflections };
			if (chatStart && chatEnd) body.time_range = { start: chatStart, end: chatEnd };
			const res = await fetch('/api/chat', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			});
			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail ?? `${res.status}`);
			}
			const d = await res.json();
			chatHistory = [...chatHistory, {
				role: 'assistant',
				content: d.answer,
				model: d.model,
				sources: d.sources,
			}];
		} catch (e) {
			chatHistory = [...chatHistory, { role: 'assistant', content: String(e), error: true }];
		} finally {
			chatLoading = false;
		}
	}

	function onChatKey(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
	}

	function simColor(s: number | null) {
		if (s == null) return '#6b5a45';
		if (s >= 0.40) return '#4a7c59';
		if (s >= 0.25) return '#b07820';
		return '#6b5a45';
	}

	// ── lifecycle ─────────────────────────────────────────────────────────────────
	function switchView(v: View) {
		selectedView = v;
		if (v === 'sessions' && !sessionsLoaded) loadSessions();
		if (v === 'agency'   && !agencyLoaded)   loadAgency();
		if (v === 'chat') loadChatModels();
	}


	import { fmtDate } from '$lib/fmt';
</script>

<svelte:head><title>Echo</title></svelte:head>

<div class="shell">
	<header>
		<h1>Echo</h1>
		<p class="subtitle">Six years of watching. Who were you?</p>
		<nav>
			<button class:active={selectedView === 'speak'} onclick={() => switchView('speak')}>
				Echo Speaks
			</button>
			<button class:active={selectedView === 'sessions'} onclick={() => switchView('sessions')}>
				Binge Sessions
			</button>
			<button class:active={selectedView === 'agency'} onclick={() => switchView('agency')}>
				Agency Map
			</button>
			<button class:active={selectedView === 'chat'} onclick={() => switchView('chat')}>
				Ask Echo
			</button>
		</nav>
	</header>

	<!-- ── Binge Sessions view ────────────────────────────────────────── -->
	{#if selectedView === 'sessions'}
		<section>
			<div class="view-header">
				<h2>Binge Sessions</h2>
				<span class="view-descriptor">Sessions of 5+ consecutive videos (≤30 min gap)</span>
			</div>
			{#if sessionsLoading}
				<p class="status">Loading…</p>
			{:else if sessionsError}
				<p class="error">{sessionsError}</p>
			{:else}
				<div class="sessions-list">
					{#each sessions as s (s.session_id)}
						<div class="session-card">
							<div class="session-left">
								<div class="session-depth">{s.depth}<span class="session-depth-label">videos</span></div>
								<div class="session-depth-bar-track">
									<div class="session-depth-bar" style="height:{s.depth_pct}%"></div>
								</div>
							</div>
							<div class="session-body">
								<div class="session-meta">
									<span class="session-date">{fmtDate(s.session_start)}</span>
									<span class="session-time dim">{s.session_start.slice(11, 16)} – {s.session_end.slice(11, 16)}</span>
									{#if s.duration_min > 0}
										<span class="dim">· {s.duration_min} min</span>
									{/if}
									{#if s.is_night}
										<span class="badge badge-night">night</span>
									{/if}
								</div>
								{#if s.top_channel}
									<p class="session-channel"><span class="dim" style="font-size:0.68rem">top channel · </span>{s.top_channel}</p>
								{/if}
								{#if s.sample_titles.length > 0}
									<ul class="session-titles">
										{#each s.sample_titles as title}
											<li>{title}</li>
										{/each}
									</ul>
								{/if}
								<div class="session-signals">
									{#if s.shorts_pct >= 50}
										<span class="badge badge-shorts">{s.shorts_pct}% shorts</span>
									{/if}
									{#if s.searched_count > 0}
										<span class="badge badge-searched">{s.searched_count} searched</span>
									{/if}
									{#if s.autoplay_count > 0}
										<span class="badge badge-autoplay">{s.autoplay_count} autoplay</span>
									{/if}
									{#if s.rewatch_count > 0}
										<span class="badge badge-rewatch">{s.rewatch_count} rewatch</span>
									{/if}
								</div>
							</div>
						</div>
					{/each}
				</div>
				</div>
			{/if}
		</section>
	{/if}

	<!-- ── Agency Map view ────────────────────────────────────────────── -->
	{#if selectedView === 'agency'}
		<section>
			<div class="view-header">
				<h2>Agency Map</h2>
				<span class="view-descriptor">How you found content — searched vs passive — by chapter</span>
			</div>
			{#if agencyLoading}
				<p class="status">Loading…</p>
			{:else if agencyError}
				<p class="error">{agencyError}</p>
			{:else}
				<div class="agency-table-scroll">
				<div class="agency-table">
					<div class="agency-header">
						<span>Chapter</span>
						<span>Watches</span>
						<span title="Actively searched for">Searched</span>
						<span title="Saved to Watch Later">Bookmarked</span>
						<span title="Same-channel autoplay">Autoplay</span>
						<span title="Watched before">Rewatch</span>
					</div>
					{#each agencyData as ch (ch.chapter_id)}
						<div class="agency-row">
							<div class="agency-chapter">
								<span class="agency-ch-num">Ch {ch.chapter_id}</span>
								<span class="agency-ch-label dim">{ch.label}</span>
								<span class="agency-ch-date dim">{fmtDate(ch.start_at)}</span>
							</div>
							<span class="agency-total">{ch.total.toLocaleString()}</span>
							<div class="agency-bar-cell">
								<div class="agency-bar" style="width:{Math.min(ch.searched_pct, 100)}%; background:var(--signal-cold)"></div>
								<span class="agency-pct">{ch.searched_pct}%</span>
							</div>
							<div class="agency-bar-cell">
								<div class="agency-bar" style="width:{Math.min(ch.bookmarked_pct, 100)}%; background:var(--accent)"></div>
								<span class="agency-pct">{ch.bookmarked_pct}%</span>
							</div>
							<div class="agency-bar-cell">
								<div class="agency-bar" style="width:{Math.min(ch.autoplay_pct, 100)}%; background:var(--text-muted)"></div>
								<span class="agency-pct">{ch.autoplay_pct}%</span>
							</div>
							<div class="agency-bar-cell">
								<div class="agency-bar" style="width:{Math.min(ch.rewatch_pct, 100)}%; background:var(--data-amber)"></div>
								<span class="agency-pct">{ch.rewatch_pct}%</span>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</section>
	{/if}

	<!-- ── Chat view ─────────────────────────────────────────────────── -->
	{#if selectedView === 'chat'}
		<section class="chat-section">
			<div class="view-header">
				<h2>Ask Echo</h2>
				<span class="view-descriptor">RAG across your watch history, arcs, and search queries</span>
			</div>

			<!-- Controls row -->
			<div class="chat-controls">
				<select class="search-select" bind:value={chatModel}>
					<option value="auto">Auto (Claude preferred)</option>
					{#if availableModels.includes('claude')}
						<option value="claude">Claude Sonnet 4.6</option>
					{/if}
					{#if availableModels.includes('gpt4o')}
						<option value="gpt4o">GPT-4o</option>
					{/if}
				</select>
				<span class="dim" style="font-size:0.72rem;padding:0 0.25rem">Time filter (optional):</span>
				<input type="date" class="date-input" bind:value={chatStart} min="2019-12-01" max="2026-05-31" />
				<span class="dim" style="font-size:0.72rem">→</span>
				<input type="date" class="date-input" bind:value={chatEnd}   min="2019-12-01" max="2026-05-31" />
				{#if chatStart || chatEnd}
					<button class="diff-btn-ghost" onclick={() => { chatStart = ''; chatEnd = ''; }}>Clear</button>
				{/if}
				<label class="chat-toggle" title="Uncheck to skip chapter arc summaries and answer from raw data only">
					<input type="checkbox" bind:checked={chatIncludeReflections} />
					<span class="dim" style="font-size:0.72rem">Chapter context</span>
				</label>
			</div>

			<!-- Message thread -->
			<div class="chat-thread">
				{#if chatHistory.length === 0}
					<div class="chat-empty">
						<p>Ask anything about your six years of watching.</p>
						<div class="chat-suggestions">
							{#each [
								'What was I watching the week before JEE Advanced?',
								'When did I start watching philosophy content?',
								'What do my late-night watches say about my state of mind?',
								'What chapters had the most concentrated viewing habits?',
							] as suggestion}
								<button class="suggestion" onclick={() => { chatInput = suggestion; }}>
									{suggestion}
								</button>
							{/each}
						</div>
					</div>
				{/if}

				{#each chatHistory as msg}
					<div class="msg msg-{msg.role}" class:error={msg.error}>
						<div class="msg-bubble">
							<p class="msg-text">{msg.content}</p>
						</div>
						{#if msg.role === 'assistant' && !msg.error}
							<div class="msg-meta">
								{#if msg.model}<span class="msg-model">{msg.model}</span>{/if}
								{#if msg.sources && msg.sources.length > 0}
									<span class="msg-sources">
										{#each msg.sources.slice(0, 6) as src}
											<span class="src-chip" style="border-color:{simColor(src.similarity)}">
												{src.label.length > 40 ? src.label.slice(0, 40) + '…' : src.label}
												{#if src.similarity != null}
													<span style="color:{simColor(src.similarity)}">{(src.similarity * 100).toFixed(0)}%</span>
												{/if}
											</span>
										{/each}
									</span>
								{/if}
							</div>
						{/if}
					</div>
				{/each}

				{#if chatLoading}
					<div class="msg msg-assistant">
						<div class="msg-bubble loading">
							<span class="dot"></span><span class="dot"></span><span class="dot"></span>
						</div>
					</div>
				{/if}
			</div>

			<!-- Input -->
			<div class="chat-input-row">
				<textarea
					class="chat-textarea"
					bind:value={chatInput}
					onkeydown={onChatKey}
					placeholder="Ask about your history… (Enter to send, Shift+Enter for newline)"
					rows="2"
					disabled={chatLoading}
				></textarea>
				<button class="diff-btn" onclick={sendChat} disabled={chatLoading || !chatInput.trim()}>
					Send
				</button>
			</div>
		</section>
	{/if}

	<!-- ── Echo Speaks view ─────────────────────────────────────────── -->
	{#if selectedView === 'speak'}
		<section>
			<div class="view-header">
				<h2>Echo Speaks</h2>
				<span class="view-descriptor">Autonomous agentic analysis</span>
			</div>
			<SpeakView />
		</section>
	{/if}

</div>

<style>
	.shell { max-width: 860px; margin: 0 auto; padding: 1.5rem 1rem; }

	header { margin-bottom: 1.5rem; }
	h1 {
		margin: 0;
		font-size: 2.4rem;
		letter-spacing: -0.02em;
		font-family: 'Lora', serif;
		font-weight: 700;
		background: linear-gradient(135deg, var(--accent), var(--accent-glow));
		-webkit-background-clip: text;
		-webkit-text-fill-color: transparent;
		background-clip: text;
	}
	.subtitle {
		margin: 0.25rem 0 1rem;
		color: var(--text-secondary);
		font-size: 1rem;
		font-family: 'Lora', serif;
		font-style: italic;
	}

	nav { display: flex; gap: 0.5rem; flex-wrap: wrap; }
	nav button {
		background: var(--surface-0);
		border: 1px solid var(--border);
		color: var(--text-secondary);
		padding: 0 1rem;
		min-height: 44px;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.8rem;
		font-family: 'Geist Mono', monospace;
		transition: border-color 0.15s, color 0.15s;
	}
	nav button:hover { border-color: var(--accent-dim); color: var(--text-primary); }
	nav button.active { background: var(--surface-1); border-color: var(--accent); color: var(--accent); }

	.view-header {
		display: flex;
		align-items: baseline;
		gap: 1rem;
		margin-bottom: 1rem;
		flex-wrap: wrap;
	}
	h2 { margin: 0; font-size: 1.3rem; color: var(--text-bright); font-family: 'Geist Mono', monospace; word-spacing: -0.05em; }
	.view-descriptor {
		font-size: 0.65rem;
		font-weight: 600;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}
	.dim { color: var(--text-muted); font-weight: 400; }
	.count { font-size: 0.75rem; color: var(--text-muted); }

	.card-list { border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }

	.status { color: var(--text-muted); padding: 2rem; text-align: center; }
	.error  { color: var(--data-red); padding: 1rem; }

	/* ── binge sessions ──────────────────────────────────────────────── */
	.sessions-list { display: flex; flex-direction: column; gap: 0.5rem; }

	.session-card {
		display: flex;
		gap: 1rem;
		align-items: flex-start;
		padding: 0.75rem 1rem;
		background: var(--surface-0);
		border: 1px solid var(--border);
		border-radius: 8px;
	}

	.session-left {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.35rem;
		flex-shrink: 0;
		width: 3rem;
	}

	.session-depth {
		font-size: 1.4rem;
		font-weight: 700;
		font-family: 'Lora', serif;
		color: var(--text-bright);
		line-height: 1;
		text-align: center;
	}

	.session-depth-label {
		display: block;
		font-size: 0.6rem;
		font-weight: 400;
		color: var(--text-muted);
		letter-spacing: 0.03em;
	}

	.session-depth-bar-track {
		width: 4px;
		height: 56px;
		background: var(--border);
		border-radius: 2px;
		display: flex;
		align-items: flex-end;
		overflow: hidden;
	}

	.session-depth-bar {
		width: 100%;
		background: var(--accent);
		border-radius: 2px;
		min-height: 2px;
		transition: height 0.3s ease;
	}

	.session-body { flex: 1; min-width: 0; }

	.session-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		align-items: center;
		margin-bottom: 0.25rem;
		font-size: 0.78rem;
	}

	.session-date { color: var(--text-primary); font-weight: 600; }
	.session-time { font-size: 0.72rem; }

	.session-channel {
		margin: 0 0 0.3rem;
		font-size: 0.82rem;
		color: var(--text-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.session-signals { display: flex; gap: 0.3rem; flex-wrap: wrap; }

	.badge {
		display: inline-block;
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
		font-size: 0.68rem;
		font-weight: 600;
	}
	.badge-night    { background: var(--signal-cold-dim); color: var(--signal-cold); }
	.badge-searched { background: var(--signal-cold-dim); color: var(--signal-cold); }
	.badge-autoplay { background: var(--surface-1); color: var(--text-muted); }
	.badge-rewatch  { background: var(--surface-0); color: var(--data-amber); }
	.badge-shorts   { background: var(--surface-1); color: var(--text-secondary); }

	.session-titles {
		margin: 0.25rem 0 0.35rem;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.session-titles li {
		font-size: 0.76rem;
		color: var(--text-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.session-titles li::before {
		content: '· ';
		color: var(--border);
	}

	/* ── agency map ──────────────────────────────────────────────────── */
	.agency-table-scroll {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
		border: 1px solid var(--border);
		border-radius: 8px;
	}
	.agency-table {
		min-width: 600px;
		font-size: 0.8rem;
	}

	.agency-header, .agency-row {
		display: grid;
		grid-template-columns: 2fr 80px repeat(4, 1fr);
		align-items: center;
		gap: 0.5rem;
		padding: 0.6rem 1rem;
		border-bottom: 1px solid var(--border);
	}

	.agency-header {
		background: var(--surface-0);
		color: var(--text-muted);
		font-size: 0.72rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.agency-row:last-child { border-bottom: none; }
	.agency-row:hover { background: var(--surface-0); }

	.agency-chapter {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.agency-ch-num   { font-weight: 700; color: var(--text-bright); }
	.agency-ch-label { font-size: 0.72rem; }
	.agency-ch-date  { font-size: 0.68rem; }

	.agency-total { color: var(--text-secondary); text-align: right; }

	.agency-bar-cell {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}

	.agency-bar {
		height: 6px;
		border-radius: 3px;
		min-width: 2px;
		flex-shrink: 0;
	}

	.agency-pct {
		color: var(--text-primary);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.load-more {
		display: block;
		width: 100%;
		margin-top: 0.75rem;
		padding: 0.6rem;
		background: var(--surface-0);
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text-secondary);
		cursor: pointer;
		font-size: 0.8rem;
	}
	.load-more:hover:not(:disabled) { border-color: var(--accent-dim); color: var(--text-primary); }
	.load-more:disabled { opacity: 0.5; cursor: default; }

	.search-select {
		background: var(--surface-0);
		border: 1px solid var(--border);
		color: var(--text-secondary);
		padding: 0.5rem 0.5rem;
		border-radius: 6px;
		font-size: 0.8rem;
		cursor: pointer;
	}

	.diff-btn {
		background: var(--accent);
		border: none;
		color: var(--bg);
		padding: 0.45rem 1rem;
		min-height: 44px;
		border-radius: 6px;
		font-size: 0.85rem;
		cursor: pointer;
		font-weight: 600;
		white-space: nowrap;
		transition: background 0.15s;
	}
	.diff-btn:hover:not(:disabled) { background: var(--accent-glow); }
	.diff-btn:disabled { opacity: 0.5; cursor: default; }

	.diff-btn-ghost {
		background: transparent;
		border: 1px solid var(--border);
		color: var(--text-muted);
		padding: 0.45rem 0.75rem;
		border-radius: 6px;
		font-size: 0.8rem;
		cursor: pointer;
		white-space: nowrap;
	}
	.diff-btn-ghost:hover:not(:disabled) { border-color: var(--accent-dim); color: var(--text-secondary); }
	.diff-btn-ghost:disabled { opacity: 0.4; cursor: default; }

	/* ── chat ────────────────────────────────────────────────────────── */
	.chat-section { display: flex; flex-direction: column; }

	.chat-controls {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		margin-bottom: 1rem;
		flex-wrap: wrap;
	}

	.chat-toggle {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		cursor: pointer;
		margin-left: 0.25rem;
	}

	.date-input {
		background: var(--surface-0);
		border: 1px solid var(--border);
		color: var(--text-primary);
		padding: 0.3rem 0.5rem;
		border-radius: 5px;
		font-size: 0.8rem;
	}

	.chat-thread {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		margin-bottom: 1rem;
		min-height: 120px;
	}

	.chat-empty {
		padding: 1.5rem;
		text-align: center;
		color: var(--text-muted);
		border: 1px dashed var(--border);
		border-radius: 8px;
	}
	.chat-empty p { margin: 0 0 1rem; font-size: 0.85rem; }

	.chat-suggestions {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		align-items: stretch;
		max-width: 500px;
		margin: 0 auto;
	}

	.suggestion {
		background: var(--surface-0);
		border: 1px solid var(--border);
		color: var(--text-muted);
		padding: 0.4rem 0.75rem;
		border-radius: 6px;
		font-size: 0.78rem;
		cursor: pointer;
		text-align: left;
		transition: border-color 0.15s, color 0.15s;
	}
	.suggestion:hover { border-color: var(--accent-dim); color: var(--text-secondary); }

	.msg { display: flex; flex-direction: column; }
	.msg-user { align-items: flex-end; }
	.msg-assistant { align-items: flex-start; }

	.msg-bubble {
		max-width: 85%;
		padding: 0.65rem 0.9rem;
		border-radius: 8px;
		font-size: 0.85rem;
		line-height: 1.6;
	}
	.msg-user .msg-bubble {
		background: var(--surface-1);
		border: 1px solid var(--accent-dim);
		color: var(--text-primary);
	}
	.msg-assistant .msg-bubble {
		background: var(--surface-0);
		border: 1px solid var(--border);
		color: var(--text-primary);
	}
	.msg.error .msg-bubble { border-color: var(--data-red); color: var(--data-red); }

	.msg-text { margin: 0; white-space: pre-wrap; }

	.msg-meta {
		margin-top: 0.35rem;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		max-width: 85%;
	}

	.msg-model { font-size: 0.65rem; color: var(--text-muted); }

	.msg-sources { display: flex; flex-wrap: wrap; gap: 0.3rem; }

	.src-chip {
		font-size: 0.62rem;
		padding: 2px 6px;
		border-radius: 3px;
		background: var(--surface-0);
		border: 1px solid var(--signal-cold-dim);
		color: var(--text-secondary);
		display: flex;
		gap: 0.3rem;
		align-items: center;
	}

	/* loading dots */
	.loading {
		display: flex;
		gap: 4px;
		align-items: center;
		padding: 0.75rem 1rem;
	}
	.dot {
		width: 6px; height: 6px;
		background: var(--text-muted);
		border-radius: 50%;
		animation: blink 1.2s infinite;
	}
	.dot:nth-child(2) { animation-delay: 0.2s; }
	.dot:nth-child(3) { animation-delay: 0.4s; }
	@keyframes blink {
		0%, 80%, 100% { opacity: 0.2; }
		40% { opacity: 1; }
	}

	.chat-input-row {
		display: flex;
		gap: 0.5rem;
		align-items: flex-end;
	}

	.chat-textarea {
		flex: 1;
		background: var(--surface-0);
		border: 1px solid var(--border);
		color: var(--text-primary);
		padding: 0.6rem 0.75rem;
		border-radius: 6px;
		font-size: 0.85rem;
		font-family: inherit;
		resize: none;
		line-height: 1.5;
	}
	.chat-textarea:focus { outline: none; border-color: var(--accent-dim); }
	.chat-textarea:disabled { opacity: 0.5; }
	.chat-textarea::placeholder { color: var(--text-muted); }

</style>
