<script lang="ts">
	import { onMount } from 'svelte';
	import TimelineCard from '$lib/TimelineCard.svelte';
	import SearchResult from '$lib/SearchResult.svelte';
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
	type View = 'sessions' | 'agency' | 'search' | 'chat' | 'speak';
	let selectedView: View = $state('sessions');

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

	// ── search view ──────────────────────────────────────────────────────────────
	type SearchRow = Record<string, unknown> & { similarity: number };
	type SearchResults = Record<string, SearchRow[]>;

	let searchQuery: string = $state('');
	let searchTable: string = $state('all');
	let searchTop: number = $state(10);
	let searchResults: SearchResults = $state({});
	let searchLoading: boolean = $state(false);
	let searchError: string = $state('');
	let searchDone: boolean = $state(false);

	async function runSearch() {
		if (!searchQuery.trim()) return;
		searchLoading = true;
		searchError = '';
		searchDone = false;
		searchResults = {};
		try {
			const tableParam = searchTable === 'all' ? '' : `&table=${searchTable}`;
			const url = `/api/search?q=${encodeURIComponent(searchQuery)}&top=${searchTop}${tableParam}`;
			const res = await fetch(url);
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = await res.json();
			searchResults = data.results;
			searchDone = true;
		} catch (e) {
			searchError = String(e);
		} finally {
			searchLoading = false;
		}
	}

	function onSearchKey(e: KeyboardEvent) {
		if (e.key === 'Enter') runSearch();
	}

	const TABLE_LABELS: Record<string, string> = {
		reflections: 'Chapter arcs',
		videos: 'Videos',
		searches: 'YouTube searches',
		google_searches: 'Google searches',
	};

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
		if (s == null) return '#6b7280';
		if (s >= 0.40) return '#22c55e';
		if (s >= 0.25) return '#eab308';
		return '#6b7280';
	}

	// ── lifecycle ─────────────────────────────────────────────────────────────────
	onMount(() => loadSessions());

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
			<button class:active={selectedView === 'sessions'} onclick={() => switchView('sessions')}>
				Binge Sessions
			</button>
			<button class:active={selectedView === 'agency'} onclick={() => switchView('agency')}>
				Agency Map
			</button>
			<button class:active={selectedView === 'search'} onclick={() => switchView('search')}>
				Search
			</button>
			<button class:active={selectedView === 'chat'} onclick={() => switchView('chat')}>
				Ask Echo
			</button>
			<button class:active={selectedView === 'speak'} onclick={() => switchView('speak')}>
				Echo Speaks
			</button>
		</nav>
	</header>

	<!-- ── Binge Sessions view ────────────────────────────────────────── -->
	{#if selectedView === 'sessions'}
		<section>
			<div class="view-header">
				<h2>Binge Sessions</h2>
				<span class="dim" style="font-size:0.75rem">Sessions of 5+ consecutive videos (≤30 min gap)</span>
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
			{/if}
		</section>
	{/if}

	<!-- ── Agency Map view ────────────────────────────────────────────── -->
	{#if selectedView === 'agency'}
		<section>
			<div class="view-header">
				<h2>Agency Map</h2>
				<span class="dim" style="font-size:0.75rem">How you found content — searched vs passive — by chapter</span>
			</div>
			{#if agencyLoading}
				<p class="status">Loading…</p>
			{:else if agencyError}
				<p class="error">{agencyError}</p>
			{:else}
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
								<div class="agency-bar" style="width:{Math.min(ch.searched_pct, 100)}%; background:#3b82f6"></div>
								<span class="agency-pct">{ch.searched_pct}%</span>
							</div>
							<div class="agency-bar-cell">
								<div class="agency-bar" style="width:{Math.min(ch.bookmarked_pct, 100)}%; background:#8b5cf6"></div>
								<span class="agency-pct">{ch.bookmarked_pct}%</span>
							</div>
							<div class="agency-bar-cell">
								<div class="agency-bar" style="width:{Math.min(ch.autoplay_pct, 100)}%; background:#6b7280"></div>
								<span class="agency-pct">{ch.autoplay_pct}%</span>
							</div>
							<div class="agency-bar-cell">
								<div class="agency-bar" style="width:{Math.min(ch.rewatch_pct, 100)}%; background:#f59e0b"></div>
								<span class="agency-pct">{ch.rewatch_pct}%</span>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</section>
	{/if}

	<!-- ── Search view ───────────────────────────────────────────────── -->
	{#if selectedView === 'search'}
		<section>
			<div class="view-header">
				<h2>Semantic Search</h2>
				<span class="dim" style="font-size:0.75rem">across chapter arcs, videos, and YouTube searches</span>
			</div>

			<div class="search-bar">
				<input
					class="search-input"
					type="text"
					placeholder='e.g. "stoicism late at night" or "week before JEE Advanced"'
					bind:value={searchQuery}
					onkeydown={onSearchKey}
				/>
				<select class="search-select" bind:value={searchTable}>
					<option value="all">All tables</option>
					<option value="reflections">Chapter arcs</option>
					<option value="videos">Videos</option>
					<option value="searches">Searches</option>
				</select>
				<select class="search-select" bind:value={searchTop}>
					<option value={5}>Top 5</option>
					<option value={10}>Top 10</option>
					<option value={20}>Top 20</option>
				</select>
				<button class="search-btn" onclick={runSearch} disabled={searchLoading || !searchQuery.trim()}>
					{searchLoading ? '…' : 'Search'}
				</button>
			</div>

			{#if searchLoading}
				<p class="status">Embedding query and searching…</p>
			{:else if searchError}
				<p class="error">{searchError}</p>
			{:else if searchDone}
				{#each Object.entries(searchResults) as [tbl, rows]}
					{#if rows.length > 0}
						<div class="result-section">
							<p class="result-label">{TABLE_LABELS[tbl] ?? tbl}</p>
							<div class="card-list">
								{#each rows as row}
									<SearchResult result={row as any} table={tbl as any} />
								{/each}
							</div>
						</div>
					{/if}
				{/each}
			{/if}
		</section>
	{/if}

	<!-- ── Chat view ─────────────────────────────────────────────────── -->
	{#if selectedView === 'chat'}
		<section class="chat-section">
			<div class="view-header">
				<h2>Ask Echo</h2>
				<span class="dim" style="font-size:0.75rem">RAG across your watch history, arcs, and search queries</span>
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
				<span class="dim" style="font-size:0.75rem">Autonomous agentic analysis</span>
			</div>
			<SpeakView />
		</section>
	{/if}

</div>

<style>
	:global(*, *::before, *::after) { box-sizing: border-box; }
	:global(body) {
		margin: 0;
		background: #030712;
		color: #f3f4f6;
		font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
		font-size: 14px;
	}

	.shell { max-width: 860px; margin: 0 auto; padding: 1.5rem 1rem; }

	header { margin-bottom: 1.5rem; }
	h1 { margin: 0; font-size: 1.8rem; letter-spacing: -0.03em; color: #a78bfa; }
	.subtitle { margin: 0.25rem 0 1rem; color: #6b7280; font-size: 0.85rem; }

	nav { display: flex; gap: 0.5rem; }
	nav button {
		background: #111827;
		border: 1px solid #1f2937;
		color: #9ca3af;
		padding: 0.4rem 0.9rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: 0.8rem;
		transition: all 0.15s;
	}
	nav button:hover { border-color: #374151; color: #d1d5db; }
	nav button.active { background: #1e1b4b; border-color: #4f46e5; color: #a78bfa; }

	.view-header {
		display: flex;
		align-items: baseline;
		gap: 1rem;
		margin-bottom: 1rem;
		flex-wrap: wrap;
	}
	h2 { margin: 0; font-size: 1rem; color: #e5e7eb; }
	.dim { color: #6b7280; font-weight: 400; }
	.count { font-size: 0.75rem; color: #6b7280; }

	.card-list { border: 1px solid #1f2937; border-radius: 8px; overflow: hidden; }

	.status { color: #6b7280; padding: 2rem; text-align: center; }
	.error  { color: #f87171; padding: 1rem; }

	/* ── binge sessions ──────────────────────────────────────────────── */
	.sessions-list { display: flex; flex-direction: column; gap: 0.5rem; }

	.session-card {
		display: flex;
		gap: 1rem;
		align-items: flex-start;
		padding: 0.75rem 1rem;
		background: #111827;
		border: 1px solid #1f2937;
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
		color: #6366f1;
		line-height: 1;
		text-align: center;
	}

	.session-depth-label {
		display: block;
		font-size: 0.6rem;
		font-weight: 400;
		color: #6b7280;
		letter-spacing: 0.03em;
	}

	.session-depth-bar-track {
		width: 4px;
		height: 56px;
		background: #1f2937;
		border-radius: 2px;
		display: flex;
		align-items: flex-end;
		overflow: hidden;
	}

	.session-depth-bar {
		width: 100%;
		background: #4f46e5;
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

	.session-date { color: #d1d5db; font-weight: 600; }
	.session-time { font-size: 0.72rem; }

	.session-channel {
		margin: 0 0 0.3rem;
		font-size: 0.82rem;
		color: #9ca3af;
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
	.badge-night    { background: #1e1b4b; color: #a5b4fc; }
	.badge-searched { background: #1e3a5f; color: #93c5fd; }
	.badge-autoplay { background: #1f2937; color: #9ca3af; }
	.badge-rewatch  { background: #2d1b0e; color: #f59e0b; }
	.badge-shorts   { background: #1a1a2e; color: #c084fc; }

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
		color: #9ca3af;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.session-titles li::before {
		content: '· ';
		color: #374151;
	}

	/* ── agency map ──────────────────────────────────────────────────── */
	.agency-table {
		border: 1px solid #1f2937;
		border-radius: 8px;
		overflow: hidden;
		font-size: 0.8rem;
	}

	.agency-header, .agency-row {
		display: grid;
		grid-template-columns: 2fr 80px repeat(4, 1fr);
		align-items: center;
		gap: 0.5rem;
		padding: 0.6rem 1rem;
		border-bottom: 1px solid #1f2937;
	}

	.agency-header {
		background: #0d1117;
		color: #6b7280;
		font-size: 0.72rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.agency-row:last-child { border-bottom: none; }
	.agency-row:hover { background: #0d1117; }

	.agency-chapter {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}
	.agency-ch-num   { font-weight: 700; color: #e5e7eb; }
	.agency-ch-label { font-size: 0.72rem; }
	.agency-ch-date  { font-size: 0.68rem; }

	.agency-total { color: #9ca3af; text-align: right; }

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
		color: #d1d5db;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.load-more {
		display: block;
		width: 100%;
		margin-top: 0.75rem;
		padding: 0.6rem;
		background: #111827;
		border: 1px solid #1f2937;
		border-radius: 6px;
		color: #9ca3af;
		cursor: pointer;
		font-size: 0.8rem;
	}
	.load-more:hover:not(:disabled) { border-color: #374151; color: #d1d5db; }
	.load-more:disabled { opacity: 0.5; cursor: default; }

	.search-bar {
		display: flex;
		gap: 0.5rem;
		margin-bottom: 1.25rem;
		flex-wrap: wrap;
	}

	.search-input {
		flex: 1;
		min-width: 200px;
		background: #111827;
		border: 1px solid #374151;
		color: #f3f4f6;
		padding: 0.5rem 0.75rem;
		border-radius: 6px;
		font-size: 0.85rem;
	}
	.search-input:focus {
		outline: none;
		border-color: #4f46e5;
	}
	.search-input::placeholder { color: #4b5563; }

	.search-select {
		background: #111827;
		border: 1px solid #1f2937;
		color: #9ca3af;
		padding: 0.5rem 0.5rem;
		border-radius: 6px;
		font-size: 0.8rem;
		cursor: pointer;
	}

	.search-btn {
		background: #4f46e5;
		border: none;
		color: #fff;
		padding: 0.5rem 1rem;
		border-radius: 6px;
		font-size: 0.85rem;
		cursor: pointer;
		font-weight: 600;
		transition: background 0.15s;
	}
	.search-btn:hover:not(:disabled) { background: #4338ca; }
	.search-btn:disabled { opacity: 0.5; cursor: default; }

	.diff-btn {
		background: #4f46e5;
		border: none;
		color: #fff;
		padding: 0.45rem 1rem;
		border-radius: 6px;
		font-size: 0.85rem;
		cursor: pointer;
		font-weight: 600;
		white-space: nowrap;
		transition: background 0.15s;
	}
	.diff-btn:hover:not(:disabled) { background: #4338ca; }
	.diff-btn:disabled { opacity: 0.5; cursor: default; }

	.diff-btn-ghost {
		background: transparent;
		border: 1px solid #374151;
		color: #6b7280;
		padding: 0.45rem 0.75rem;
		border-radius: 6px;
		font-size: 0.8rem;
		cursor: pointer;
		white-space: nowrap;
	}
	.diff-btn-ghost:hover:not(:disabled) { border-color: #4b5563; color: #9ca3af; }
	.diff-btn-ghost:disabled { opacity: 0.4; cursor: default; }

	.result-section { margin-bottom: 1.5rem; }

	.result-label {
		margin: 0 0 0.4rem;
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #6b7280;
	}

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
		background: #111827;
		border: 1px solid #1f2937;
		color: #d1d5db;
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
		color: #4b5563;
		border: 1px dashed #1f2937;
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
		background: #0d1117;
		border: 1px solid #1f2937;
		color: #6b7280;
		padding: 0.4rem 0.75rem;
		border-radius: 6px;
		font-size: 0.78rem;
		cursor: pointer;
		text-align: left;
		transition: all 0.15s;
	}
	.suggestion:hover { border-color: #374151; color: #9ca3af; }

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
		background: #1e1b4b;
		border: 1px solid #312e81;
		color: #e0e7ff;
	}
	.msg-assistant .msg-bubble {
		background: #0d1117;
		border: 1px solid #1f2937;
		color: #d1d5db;
	}
	.msg.error .msg-bubble { border-color: #7f1d1d; color: #fca5a5; }

	.msg-text { margin: 0; white-space: pre-wrap; }

	.msg-meta {
		margin-top: 0.35rem;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		max-width: 85%;
	}

	.msg-model { font-size: 0.65rem; color: #374151; }

	.msg-sources { display: flex; flex-wrap: wrap; gap: 0.3rem; }

	.src-chip {
		font-size: 0.62rem;
		padding: 2px 6px;
		border-radius: 3px;
		background: #0d1117;
		border: 1px solid #1f2937;
		color: #6b7280;
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
		background: #4b5563;
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
		background: #111827;
		border: 1px solid #374151;
		color: #f3f4f6;
		padding: 0.6rem 0.75rem;
		border-radius: 6px;
		font-size: 0.85rem;
		font-family: inherit;
		resize: none;
		line-height: 1.5;
	}
	.chat-textarea:focus { outline: none; border-color: #4f46e5; }
	.chat-textarea:disabled { opacity: 0.5; }
	.chat-textarea::placeholder { color: #374151; }

</style>
