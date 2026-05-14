<script lang="ts">
	type PillRound = {
		round: number;
		tool: string;
		done: boolean;
	};

	const TOOL_COLOR: Record<string, string> = {
		'run_sql':        '#3b82f6',
		'execute_python': '#14b8a6',
		'vector_search':  '#eab308',
		'run_pelt':       '#f97316',
		'run_clustering': '#f97316',
		'youtube_lookup': '#6b7280',
		'web_search':     '#6b7280',
		'finish':         '#8b5cf6',
	};

	let { rounds, onSelect }: {
		rounds: PillRound[];
		onSelect: (round: number) => void;
	} = $props();
</script>

<div class="pill-strip">
	{#each rounds as r (r.round)}
		<button
			class="pill"
			class:done={r.done}
			class:active={!r.done}
			style="--color: {TOOL_COLOR[r.tool] ?? '#6b7280'}"
			onclick={() => onSelect(r.round)}
			title="Round {r.round}: {r.tool || 'thinking…'}"
		>
			{r.round}
		</button>
	{/each}
</div>

<style>
	.pill-strip {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
		padding: 0.4rem 0;
	}

	.pill {
		width: 1.75rem;
		height: 1.75rem;
		border-radius: 50%;
		border: 1.5px solid var(--color);
		background: none;
		color: var(--color);
		font-size: 0.65rem;
		font-weight: 700;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
		display: flex;
		align-items: center;
		justify-content: center;
		line-height: 1;
		padding: 0;
	}

	.pill.done:hover {
		background: var(--color);
		color: #0d1117;
	}

	.pill.active {
		animation: pulse-pill 1.2s ease-in-out infinite;
	}

	@keyframes pulse-pill {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.35; }
	}
</style>
