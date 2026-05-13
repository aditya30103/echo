<script lang="ts">
	type Props = {
		result: {
			similarity: number;
			// reflections
			chapter_id?: number;
			start_at?: string;
			end_at?: string;
			text?: string;
			// videos
			video_id?: string;
			title?: string;
			channel?: string;
			watch_count?: number;
			// searches
			query?: string;
			count?: number;
			first_seen?: string;
			last_seen?: string;
		};
		table: 'reflections' | 'videos' | 'searches';
	};

	let { result, table }: Props = $props();

	function pct(n: number) { return `${(n * 100).toFixed(0)}%`; }
	function fmtDate(d: string | undefined) { return d ? d.slice(0, 7) : ''; }

	// Similarity colour: green > 40%, yellow > 25%, grey otherwise
	function simColor(s: number): string {
		if (s >= 0.40) return '#22c55e';
		if (s >= 0.25) return '#eab308';
		return '#6b7280';
	}
</script>

<div class="result">
	<span class="sim" style="color:{simColor(result.similarity)}">{pct(result.similarity)}</span>

	{#if table === 'reflections'}
		<div class="body">
			<p class="label">Ch {result.chapter_id} &nbsp;·&nbsp; {fmtDate(result.start_at)} – {fmtDate(result.end_at)}</p>
			<p class="text">{result.text}</p>
		</div>

	{:else if table === 'videos'}
		<div class="body">
			<div class="video-row">
				{#if result.video_id}
					<img
						class="thumb"
						src="https://i.ytimg.com/vi/{result.video_id}/default.jpg"
						alt=""
						loading="lazy"
						onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
					/>
				{/if}
				<div>
					<p class="title">{result.title ?? result.video_id}</p>
					{#if result.channel}
						<p class="label">{result.channel} &nbsp;·&nbsp; watched {result.watch_count}×</p>
					{/if}
				</div>
			</div>
		</div>

	{:else if table === 'searches'}
		<div class="body">
			<p class="query">"{result.query}"</p>
			<p class="label">searched {result.count}× &nbsp;·&nbsp; {fmtDate(result.first_seen)} – {fmtDate(result.last_seen)}</p>
		</div>
	{/if}
</div>

<style>
	.result {
		display: flex;
		gap: 0.75rem;
		align-items: flex-start;
		padding: 0.75rem;
		border-bottom: 1px solid #1f2937;
	}
	.result:hover { background: #111827; }

	.sim {
		font-size: 0.75rem;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		min-width: 2.5rem;
		padding-top: 2px;
		flex-shrink: 0;
	}

	.body { flex: 1; min-width: 0; }

	.label {
		margin: 0 0 0.25rem;
		font-size: 0.7rem;
		color: #6b7280;
	}

	.text {
		margin: 0;
		font-size: 0.8rem;
		color: #d1d5db;
		line-height: 1.5;
		display: -webkit-box;
		-webkit-line-clamp: 4;
		-webkit-box-orient: vertical;
		overflow: hidden;
	}

	.video-row {
		display: flex;
		gap: 0.6rem;
		align-items: center;
	}

	.thumb {
		width: 64px;
		height: 48px;
		object-fit: cover;
		border-radius: 3px;
		flex-shrink: 0;
		background: #1f2937;
	}

	.title {
		margin: 0 0 0.2rem;
		font-size: 0.85rem;
		color: #f3f4f6;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.query {
		margin: 0 0 0.2rem;
		font-size: 0.85rem;
		color: #f3f4f6;
		font-style: italic;
	}
</style>
