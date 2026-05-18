<script lang="ts">
	import { fmtDate } from './fmt';

	export type Session = {
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

	let { session: s }: { session: Session } = $props();
</script>

<div class="session-card">
	<div class="session-left">
		<div class="session-depth">
			{s.depth}<span class="session-depth-label">videos</span>
		</div>
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

<style>
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

	/* Lora for the depth number — this is the emotional anchor, not a measurement */
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

	/* --accent fill: your time, your investment */
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

	/* Badge colors encode intent, not just category:
	   night/searched = cold signal (precision, agency)
	   autoplay = muted (it happened to you)
	   rewatch = data-amber (nostalgia, memory)
	   shorts = neutral chrome */
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

	.dim { color: var(--text-muted); font-weight: 400; }
</style>
