<script lang="ts">
	import { onMount } from 'svelte';
	import TimelineCard from '$lib/TimelineCard.svelte';
	import SearchResult from '$lib/SearchResult.svelte';
	import DiffView from '$lib/DiffView.svelte';

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

	type Chapter = {
		id: number;
		start_at: string;
		end_at: string;
		label: string;
		reflection: string | null;
		night_ratio: number | null;
		modal_hour: number | null;
		long_form_ratio: number | null;
		top_categories: Record<string, number>;
	};

	// ── view state ───────────────────────────────────────────────────────────────
	type View = 'night' | 'month' | 'chapters' | 'search' | 'diff' | 'chat';
	let selectedView: View = $state('night');

	// ── night view ───────────────────────────────────────────────────────────────
	let nightItems: WatchItem[] = $state([]);
	let nightLoading: boolean = $state(false);
	let nightError: string = $state('');
	let nightLoaded: boolean = $state(false);

	async function loadNight() {
		if (nightLoaded) return;
		nightLoading = true;
		nightError = '';
		try {
			const res = await fetch('/api/timeline/night');
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = await res.json();
			nightItems = data.items;
			nightLoaded = true;
		} catch (e) {
			nightError = String(e);
		} finally {
			nightLoading = false;
		}
	}

	// ── month view ───────────────────────────────────────────────────────────────
	let monthItems: WatchItem[] = $state([]);
	let monthLoading: boolean = $state(false);
	let monthError: string = $state('');
	let selectedMonth: string = $state(new Date().toISOString().slice(0, 7));
	let monthTotal: number = $state(0);
	let monthOffset: number = $state(0);
	const MONTH_LIMIT = 200;

	async function loadMonth(reset = false) {
		if (reset) { monthOffset = 0; monthItems = []; }
		monthLoading = true;
		monthError = '';
		try {
			const url = `/api/timeline?month=${selectedMonth}&limit=${MONTH_LIMIT}&offset=${monthOffset}`;
			const res = await fetch(url);
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = await res.json();
			monthItems = reset ? data.items : [...monthItems, ...data.items];
			monthTotal = data.total;
			monthOffset += data.items.length;
		} catch (e) {
			monthError = String(e);
		} finally {
			monthLoading = false;
		}
	}

	// ── chapters view ─────────────────────────────────────────────────────────────
	let chapters: Chapter[] = $state([]);
	let chaptersLoading: boolean = $state(false);
	let chaptersError: string = $state('');
	let chaptersLoaded: boolean = $state(false);
	let expandedChapter: number | null = $state(null);

	async function loadChapters() {
		if (chaptersLoaded) return;
		chaptersLoading = true;
		chaptersError = '';
		try {
			const res = await fetch('/api/chapters');
			if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
			const data = await res.json();
			chapters = data.chapters;
			chaptersLoaded = true;
		} catch (e) {
			chaptersError = String(e);
		} finally {
			chaptersLoading = false;
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
	};

	// ── diff view ─────────────────────────────────────────────────────────────────
	type ChapterSummary = {
		id: number; label: string; start_at: string; end_at: string;
		night_ratio: number | null; modal_hour: number | null;
		long_form_ratio: number | null; shorts_ratio: number | null;
		channel_density_score: number | null; median_duration_seconds: number | null;
		top_categories: Record<string, number>;
	};
	type DiffResult = {
		chapter_a: number; chapter_b: number;
		chapter_a_data: ChapterSummary & { reflection?: string | null };
		chapter_b_data: ChapterSummary & { reflection?: string | null };
		narrative: string; model: string; cached: boolean; created_at: string;
	};

	let diffChapters: ChapterSummary[] = $state([]);
	let diffChaptersLoaded: boolean = $state(false);
	let diffSelA: number = $state(2);
	let diffSelB: number = $state(5);
	let diffLoading: boolean = $state(false);
	let diffError: string = $state('');
	let diffResult: DiffResult | null = $state(null);

	async function loadDiffChapters() {
		if (diffChaptersLoaded) return;
		const res = await fetch('/api/diff/chapters');
		if (res.ok) {
			const d = await res.json();
			diffChapters = d.chapters;
			diffChaptersLoaded = true;
		}
	}

	async function runDiff(force = false) {
		if (diffSelA === diffSelB) return;
		diffLoading = true;
		diffError = '';
		diffResult = null;
		try {
			const res = await fetch('/api/diff', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ chapter_a: diffSelA, chapter_b: diffSelB, force }),
			});
			if (!res.ok) {
				const err = await res.json();
				throw new Error(err.detail ?? `${res.status}`);
			}
			diffResult = await res.json();
		} catch (e) {
			diffError = String(e);
		} finally {
			diffLoading = false;
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
			const body: Record<string, unknown> = { question: q, model: chatModel };
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
	onMount(() => loadNight());

	function switchView(v: View) {
		selectedView = v;
		if (v === 'night' && !nightLoaded) loadNight();
		if (v === 'month') loadMonth(true);
		if (v === 'chapters' && !chaptersLoaded) loadChapters();
		if (v === 'diff') loadDiffChapters();
		if (v === 'chat') loadChatModels();
	}

	function fmtDate(d: string) { return d.slice(0, 10); }
	function pct(n: number | null) { return n != null ? `${(n * 100).toFixed(0)}%` : '—'; }
</script>

<svelte:head><title>Echo</title></svelte:head>

<div class="shell">
	<header>
		<h1>Echo</h1>
		<p class="subtitle">Six years of watching. Who were you?</p>
		<nav>
			<button class:active={selectedView === 'night'} onclick={() => switchView('night')}>
				Night Archaeology
			</button>
			<button class:active={selectedView === 'month'} onclick={() => switchView('month')}>
				By Month
			</button>
			<button class:active={selectedView === 'chapters'} onclick={() => switchView('chapters')}>
				Chapters
			</button>
			<button class:active={selectedView === 'search'} onclick={() => switchView('search')}>
				Search
			</button>
			<button class:active={selectedView === 'diff'} onclick={() => switchView('diff')}>
				Psyche Diff
			</button>
			<button class:active={selectedView === 'chat'} onclick={() => switchView('chat')}>
				Ask Echo
			</button>
		</nav>
	</header>

	<!-- ── Night view ─────────────────────────────────────────────────── -->
	{#if selectedView === 'night'}
		<section>
			<div class="view-header">
				<h2>Night Archaeology <span class="dim">11 PM – 4 AM IST</span></h2>
				{#if nightLoaded}
					<span class="count">{nightItems.length} watches across 6 years</span>
				{/if}
			</div>

			{#if nightLoading}
				<p class="status">Loading…</p>
			{:else if nightError}
				<p class="error">{nightError}</p>
			{:else}
				<div class="card-list">
					{#each nightItems as item (item.watch_id)}
						<TimelineCard {item} />
					{/each}
				</div>
			{/if}
		</section>
	{/if}

	<!-- ── Month view ─────────────────────────────────────────────────── -->
	{#if selectedView === 'month'}
		<section>
			<div class="view-header">
				<h2>Month View</h2>
				<div class="month-controls">
					<input
						type="month"
						bind:value={selectedMonth}
						min="2019-12"
						max="2026-05"
						onchange={() => loadMonth(true)}
					/>
					{#if monthTotal > 0}
						<span class="count">{monthTotal} watches</span>
					{/if}
				</div>
			</div>

			{#if monthLoading && monthItems.length === 0}
				<p class="status">Loading…</p>
			{:else if monthError}
				<p class="error">{monthError}</p>
			{:else}
				<div class="card-list">
					{#each monthItems as item (item.watch_id)}
						<TimelineCard {item} />
					{/each}
				</div>
				{#if monthItems.length < monthTotal}
					<button class="load-more" onclick={() => loadMonth()} disabled={monthLoading}>
						{monthLoading ? 'Loading…' : `Load more (${monthTotal - monthItems.length} remaining)`}
					</button>
				{/if}
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

	<!-- ── Diff view ─────────────────────────────────────────────────── -->
	{#if selectedView === 'diff'}
		<section>
			<div class="view-header">
				<h2>Psyche Diff</h2>
				<span class="dim" style="font-size:0.75rem">Who were you then vs who were you later?</span>
			</div>

			<div class="diff-controls">
				<select class="diff-select" bind:value={diffSelA} onchange={() => diffResult = null}>
					{#each diffChapters as ch}
						<option value={ch.id}>Ch {ch.id} — {ch.label} ({ch.start_at.slice(0,7)})</option>
					{/each}
				</select>
				<span class="vs">vs</span>
				<select class="diff-select" bind:value={diffSelB} onchange={() => diffResult = null}>
					{#each diffChapters as ch}
						<option value={ch.id}>Ch {ch.id} — {ch.label} ({ch.start_at.slice(0,7)})</option>
					{/each}
				</select>
				<button
					class="diff-btn"
					onclick={() => runDiff(false)}
					disabled={diffLoading || diffSelA === diffSelB}
				>
					{diffLoading ? 'Thinking…' : 'Compare'}
				</button>
				{#if diffResult?.cached}
					<button class="diff-btn-ghost" onclick={() => runDiff(true)} disabled={diffLoading}>
						Regenerate
					</button>
				{/if}
			</div>

			{#if diffSelA === diffSelB}
				<p class="status">Choose two different chapters.</p>
			{:else if diffLoading}
				<p class="status">Calling GPT-4o… this takes ~5 seconds.</p>
			{:else if diffError}
				<p class="error">{diffError}</p>
			{:else if diffResult}
				<DiffView
					a={diffResult.chapter_a_data}
					b={diffResult.chapter_b_data}
					narrative={diffResult.narrative}
					model={diffResult.model}
					cached={diffResult.cached}
				/>
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

	<!-- ── Chapters view ──────────────────────────────────────────────── -->
	{#if selectedView === 'chapters'}
		<section>
			<div class="view-header">
				<h2>Chapters</h2>
				{#if chaptersLoaded}
					<span class="count">{chapters.length} chapters</span>
				{/if}
			</div>

			{#if chaptersLoading}
				<p class="status">Loading…</p>
			{:else if chaptersError}
				<p class="error">{chaptersError}</p>
			{:else}
				<div class="chapter-grid">
					{#each chapters as ch}
						<div
							class="chapter-card"
							class:expanded={expandedChapter === ch.id}
							onclick={() => expandedChapter = expandedChapter === ch.id ? null : ch.id}
							role="button"
							tabindex="0"
							onkeydown={e => e.key === 'Enter' && (expandedChapter = expandedChapter === ch.id ? null : ch.id)}
						>
							<div class="ch-header">
								<span class="ch-num">Ch {ch.id}</span>
								<span class="ch-label">{ch.label}</span>
							</div>
							<p class="ch-dates">{fmtDate(ch.start_at)} – {fmtDate(ch.end_at)}</p>

							<div class="ch-stats">
								<span title="Night watch ratio">🌙 {pct(ch.night_ratio)}</span>
								<span title="Peak hour IST">⏰ {ch.modal_hour ?? '—'}h</span>
								<span title="Long-form ratio">📺 {pct(ch.long_form_ratio)}</span>
							</div>

							{#if ch.top_categories && Object.keys(ch.top_categories).length > 0}
								<div class="ch-cats">
									{#each Object.entries(ch.top_categories).slice(0, 3) as [cat]}
										<span class="cat-tag">{cat}</span>
									{/each}
								</div>
							{/if}

							{#if expandedChapter === ch.id && ch.reflection}
								<p class="ch-reflection">{ch.reflection}</p>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
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

	.month-controls { display: flex; align-items: center; gap: 0.75rem; }
	input[type="month"] {
		background: #111827;
		border: 1px solid #1f2937;
		color: #d1d5db;
		padding: 0.3rem 0.5rem;
		border-radius: 5px;
		font-size: 0.8rem;
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

	.diff-controls {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 1.25rem;
		flex-wrap: wrap;
	}

	.diff-select {
		flex: 1;
		min-width: 180px;
		background: #111827;
		border: 1px solid #374151;
		color: #d1d5db;
		padding: 0.45rem 0.6rem;
		border-radius: 6px;
		font-size: 0.8rem;
		cursor: pointer;
	}

	.vs {
		font-size: 0.75rem;
		color: #4b5563;
		font-weight: 600;
		flex-shrink: 0;
	}

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

	.chapter-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
		gap: 0.75rem;
	}

	.chapter-card {
		background: #0d1117;
		border: 1px solid #1f2937;
		border-radius: 8px;
		padding: 0.85rem;
		cursor: pointer;
		transition: border-color 0.15s, background 0.15s;
	}
	.chapter-card:hover { border-color: #374151; background: #111827; }
	.chapter-card.expanded { border-color: #4f46e5; }

	.ch-header { display: flex; align-items: baseline; gap: 0.5rem; margin-bottom: 0.2rem; }
	.ch-num { font-size: 0.65rem; color: #6b7280; font-weight: 600; }
	.ch-label { font-size: 0.85rem; font-weight: 600; color: #e5e7eb; }
	.ch-dates { margin: 0 0 0.5rem; font-size: 0.7rem; color: #6b7280; }

	.ch-stats { display: flex; gap: 0.75rem; font-size: 0.75rem; color: #9ca3af; margin-bottom: 0.5rem; }

	.ch-cats { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.5rem; }
	.cat-tag {
		font-size: 0.65rem;
		padding: 1px 6px;
		border-radius: 3px;
		background: #1f2937;
		color: #9ca3af;
	}

	.ch-reflection {
		margin: 0.75rem 0 0;
		font-size: 0.78rem;
		line-height: 1.55;
		color: #d1d5db;
		border-top: 1px solid #1f2937;
		padding-top: 0.75rem;
	}
</style>
