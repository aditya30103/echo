<script lang="ts">
	const RATES: Record<string, { in: number; out: number }> = {
		'claude-sonnet-4-6':         { in: 3.00,  out: 15.00 },
		'claude-opus-4-7':           { in: 15.00, out: 75.00 },
		'claude-haiku-4-5-20251001': { in: 0.80,  out: 4.00  },
		'gpt-4o':                    { in: 5.00,  out: 15.00 },
		'gpt-4o-mini':               { in: 0.15,  out: 0.60  },
	};

	let { totalInputTokens, totalOutputTokens, model, primaryFindingCount }: {
		totalInputTokens: number;
		totalOutputTokens: number;
		model: string;
		primaryFindingCount: number;
	} = $props();

	let cost = $derived(
		(totalInputTokens  / 1_000_000) * (RATES[model]?.in  ?? 3.00) +
		(totalOutputTokens / 1_000_000) * (RATES[model]?.out ?? 15.00)
	);

	let costPerFinding = $derived(
		primaryFindingCount > 0
			? Math.round((totalInputTokens + totalOutputTokens) / primaryFindingCount)
			: 0
	);
</script>

<div class="cost-footer">
	<span>{totalInputTokens.toLocaleString()} in</span>
	<span class="sep">·</span>
	<span>{totalOutputTokens.toLocaleString()} out</span>
	<span class="sep">·</span>
	<span class="dollars">${cost.toFixed(4)}</span>
	{#if costPerFinding > 0}
		<span class="sep">·</span>
		<span>{costPerFinding.toLocaleString()} tokens / finding</span>
	{/if}
</div>

<style>
	.cost-footer {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.35rem 0.8rem;
		border: 1px solid #1f2937;
		border-radius: 6px;
		background: #0d1117;
		font-size: 0.63rem;
		color: #4b5563;
		font-family: monospace;
	}

	.sep { color: #374151; }
	.dollars { color: #6b7280; }
</style>
