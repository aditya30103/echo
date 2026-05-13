<script lang="ts">
	import { onMount } from 'svelte';
	import TimelineCard from '$lib/TimelineCard.svelte';
	import SearchResult from '$lib/SearchResult.svelte';

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
	type View = 'night' | 'month' | 'chapters' | 'search';
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

	// ── lifecycle ─────────────────────────────────────────────────────────────────
	onMount(() => loadNight());

	function switchView(v: View) {
		selectedView = v;
		if (v === 'night' && !nightLoaded) loadNight();
		if (v === 'month') loadMonth(true);
		if (v === 'chapters' && !chaptersLoaded) loadChapters();
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

	.result-section { margin-bottom: 1.5rem; }

	.result-label {
		margin: 0 0 0.4rem;
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #6b7280;
	}

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
