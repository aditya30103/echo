<script lang="ts">
	type ChapterData = {
		id: number;
		label: string;
		start_at: string;
		end_at: string;
		night_ratio: number | null;
		modal_hour: number | null;
		long_form_ratio: number | null;
		shorts_ratio: number | null;
		channel_density_score: number | null;
		median_duration_seconds: number | null;
		top_categories: Record<string, number>;
		reflection?: string | null;
	};

	type Props = {
		a: ChapterData;
		b: ChapterData;
		narrative: string;
		model: string;
		cached: boolean;
	};

	import { fmtDate } from '$lib/fmt';

	let { a, b, narrative, model, cached }: Props = $props();

	function pct(n: number | null) { return n != null ? `${(n * 100).toFixed(0)}%` : '—'; }
	function fmtDur(s: number | null) {
		if (!s) return '—';
		return s >= 60 ? `${(s / 60).toFixed(0)} min` : `${s.toFixed(0)} s`;
	}

	const METRICS = [
		{ key: 'night_ratio',          label: '🌙 Night watching',     fmt: pct,    max: 1   },
		{ key: 'long_form_ratio',      label: '📺 Long-form (>20 min)',fmt: pct,    max: 1   },
		{ key: 'shorts_ratio',         label: '⚡ Shorts',             fmt: pct,    max: 1   },
		{ key: 'channel_density_score',label: '🎯 Channel focus',      fmt: pct,    max: 1   },
	] as const;

	function barWidth(val: number | null, max: number): string {
		if (val == null) return '0%';
		return `${Math.min((val / max) * 100, 100).toFixed(1)}%`;
	}

	// Colour the bar by relative magnitude
	function barColor(valA: number | null, valB: number | null, isA: boolean): string {
		if (valA == null || valB == null) return '#374151';
		const higher = isA ? valA > valB : valB > valA;
		return higher ? '#6366f1' : '#374151';
	}
</script>

<div class="diff-wrap">
	<!-- ── Side-by-side fingerprint ─────────────────────────────────── -->
	<div class="chapters-row">
		{#each [{ ch: a, isA: true }, { ch: b, isA: false }] as { ch, isA }}
			<div class="chapter-col">
				<div class="ch-head">
					<span class="ch-num">Ch {ch.id}</span>
					<span class="ch-label">{ch.label}</span>
				</div>
				<p class="ch-dates">{fmtDate(ch.start_at)} – {fmtDate(ch.end_at)}</p>
				<p class="ch-hour">Peak hour: <strong>{ch.modal_hour ?? '—'}:00 IST</strong></p>
				<p class="ch-dur">Median watch: <strong>{fmtDur(ch.median_duration_seconds)}</strong></p>

				<div class="bars">
					{#each METRICS as m}
						{@const val = ch[m.key] as number | null}
						<div class="bar-row">
							<span class="bar-label">{m.label}</span>
							<div class="bar-track">
								<div
									class="bar-fill"
									style="width:{barWidth(val, m.max)};background:{barColor(a[m.key] as number | null, b[m.key] as number | null, isA)}"
								></div>
							</div>
							<span class="bar-val">{m.fmt(val)}</span>
						</div>
					{/each}
				</div>

				{#if ch.top_categories && Object.keys(ch.top_categories).length > 0}
					<div class="cats">
						{#each Object.entries(ch.top_categories).slice(0, 4) as [cat, pctVal]}
							<span class="cat-tag">{cat} <span class="cat-pct">{(pctVal as number).toFixed(0)}%</span></span>
						{/each}
					</div>
				{/if}
			</div>
		{/each}
	</div>

	<!-- ── Narrative ──────────────────────────────────────────────────── -->
	<div class="narrative-wrap">
		<div class="narrative-meta">
			<span>Psyche diff</span>
			<span class="dim">{model}{cached ? ' · cached' : ''}</span>
		</div>
		<p class="narrative">{narrative}</p>
	</div>
</div>

<style>
	.diff-wrap {
		border: 1px solid #1f2937;
		border-radius: 8px;
		overflow: hidden;
	}

	.chapters-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		border-bottom: 1px solid #1f2937;
	}

	.chapter-col {
		padding: 1rem;
	}
	.chapter-col:first-child {
		border-right: 1px solid #1f2937;
	}

	.ch-head {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		margin-bottom: 0.2rem;
	}
	.ch-num { font-size: 0.65rem; color: #6b7280; font-weight: 600; }
	.ch-label { font-size: 0.9rem; font-weight: 700; color: #e5e7eb; }

	.ch-dates { margin: 0 0 0.5rem; font-size: 0.7rem; color: #6b7280; }
	.ch-hour, .ch-dur {
		margin: 0 0 0.2rem;
		font-size: 0.75rem;
		color: #9ca3af;
	}
	.ch-hour strong, .ch-dur strong { color: #d1d5db; }

	.bars { margin: 0.75rem 0; display: flex; flex-direction: column; gap: 0.4rem; }

	.bar-row {
		display: grid;
		grid-template-columns: 9rem 1fr 2.5rem;
		align-items: center;
		gap: 0.5rem;
	}

	.bar-label { font-size: 0.68rem; color: #6b7280; white-space: nowrap; }

	.bar-track {
		height: 6px;
		background: #111827;
		border-radius: 3px;
		overflow: hidden;
	}

	.bar-fill {
		height: 100%;
		border-radius: 3px;
		transition: width 0.4s ease;
	}

	.bar-val { font-size: 0.68rem; color: #9ca3af; text-align: right; font-variant-numeric: tabular-nums; }

	.cats {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
		margin-top: 0.5rem;
	}

	.cat-tag {
		font-size: 0.65rem;
		padding: 2px 6px;
		border-radius: 3px;
		background: #1f2937;
		color: #9ca3af;
	}
	.cat-pct { color: #6b7280; }

	.narrative-wrap { padding: 1.25rem; background: #0d1117; }

	.narrative-meta {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.75rem;
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: #6b7280;
	}
	.dim { color: #374151; font-weight: 400; text-transform: none; letter-spacing: 0; }

	.narrative {
		margin: 0;
		font-size: 0.85rem;
		line-height: 1.65;
		color: #d1d5db;
		white-space: pre-wrap;
	}
</style>
