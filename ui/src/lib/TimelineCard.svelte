<script lang="ts">
	type Props = {
		item: {
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
	};

	import { fmtDate } from '$lib/fmt';

	let { item }: Props = $props();

	const CHAPTER_COLORS = [
		'#6366f1', '#8b5cf6', '#ec4899', '#f43f5e',
		'#f97316', '#eab308', '#22c55e', '#14b8a6',
		'#3b82f6', '#06b6d4', '#a855f7', '#d946ef',
		'#84cc16', '#f59e0b', '#10b981', '#0ea5e9',
	];

	function chapterColor(id: number | null): string {
		if (id === null) return '#6b7280';
		return CHAPTER_COLORS[(id - 1) % CHAPTER_COLORS.length];
	}

	function formatTime(ist: string): string { return ist.slice(11, 16); }

	let title = $derived(item.title ?? item.video_id);
	let channel = $derived(item.channel || '');
	let hourStr = $derived(formatTime(item.watched_at_ist));
	let dateStr = $derived(fmtDate(item.watched_at_ist));
	let isRewatch = $derived(item.is_rewatch === 1);
	let isDeepSession = $derived((item.session_depth ?? 0) > 3);
</script>

<div class="card">
	<img
		class="thumb"
		src={item.thumbnail_url}
		alt=""
		loading="lazy"
		onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
	/>

	<div class="body">
		<div class="meta">
			<span class="time">{hourStr}</span>
			<span class="date">{dateStr}</span>
			{#if item.chapter_label}
				<span
					class="chapter-badge"
					style="background:{chapterColor(item.chapter_id)}"
				>{item.chapter_label}</span>
			{/if}
		</div>

		<p class="title">{title}</p>
		{#if channel}
			<p class="channel">{channel}</p>
		{/if}

		<div class="badges">
			{#if isRewatch}<span class="badge rewatch">rewatched</span>{/if}
			{#if isDeepSession}<span class="badge deep">deep session</span>{/if}
			{#if item.is_search_driven === 1}<span class="badge search">searched</span>{/if}
		</div>
	</div>
</div>

<style>
	.card {
		display: flex;
		gap: 0.75rem;
		padding: 0.75rem;
		border-bottom: 1px solid #1f2937;
		transition: background 0.1s;
	}
	.card:hover { background: #111827; }

	.thumb {
		width: 80px;
		height: 60px;
		object-fit: cover;
		border-radius: 4px;
		flex-shrink: 0;
		background: #1f2937;
	}

	.body { flex: 1; min-width: 0; }

	.meta {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.25rem;
		flex-wrap: wrap;
	}

	.time {
		font-size: 1rem;
		font-weight: 700;
		color: #a78bfa;
		font-variant-numeric: tabular-nums;
	}

	.date { font-size: 0.75rem; color: #6b7280; }

	.chapter-badge {
		font-size: 0.65rem;
		padding: 2px 6px;
		border-radius: 999px;
		color: #fff;
		font-weight: 600;
		opacity: 0.9;
	}

	.title {
		margin: 0;
		font-size: 0.875rem;
		color: #f3f4f6;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.channel { margin: 2px 0 0; font-size: 0.75rem; color: #9ca3af; }

	.badges {
		display: flex;
		gap: 0.35rem;
		margin-top: 0.3rem;
		flex-wrap: wrap;
	}

	.badge {
		font-size: 0.65rem;
		padding: 1px 6px;
		border-radius: 3px;
		font-weight: 500;
	}
	.rewatch { background: #1e3a5f; color: #93c5fd; }
	.deep    { background: #2d1b69; color: #c4b5fd; }
	.search  { background: #1a2e1a; color: #86efac; }
</style>
