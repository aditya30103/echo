<script lang="ts">
	const RATES: Record<string, { in: number; out: number }> = {
		'claude-sonnet-4-6':         { in: 3.00,  out: 15.00 },
		'claude-opus-4-7':           { in: 15.00, out: 75.00 },
		'claude-haiku-4-5-20251001': { in: 0.80,  out: 4.00  },
		'gpt-4o':                    { in: 5.00,  out: 15.00 },
		'gpt-4o-mini':               { in: 0.15,  out: 0.60  },
	};

	let { totalInputTokens, totalOutputTokens, totalCacheReadTokens = 0, totalCacheCreationTokens = 0, model, primaryFindingCount }: {
		totalInputTokens: number;
		totalOutputTokens: number;
		totalCacheReadTokens?: number;
		totalCacheCreationTokens?: number;
		model: string;
		primaryFindingCount: number;
	} = $props();

	const inRate  = RATES[model]?.in  ?? 3.00;
	const outRate = RATES[model]?.out ?? 15.00;

	// Anthropic pricing: cache reads = 10% of base; cache writes = 125% of base.
	// input_tokens includes cache_read and cache_creation tokens, so we subtract
	// cache_read to rerate it at 10%, then add the extra 25% for cache_creation.
	let cost = $derived(
		((totalInputTokens - totalCacheReadTokens) / 1_000_000) * inRate +
		(totalCacheReadTokens                      / 1_000_000) * inRate * 0.10 +
		(totalCacheCreationTokens                  / 1_000_000) * inRate * 0.25 +
		(totalOutputTokens                         / 1_000_000) * outRate
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
	{#if totalCacheReadTokens > 0}
		<span class="sep">·</span>
		<span class="cache-hit">{totalCacheReadTokens.toLocaleString()} cached</span>
	{/if}
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
	.cache-hit { color: #3b82f6; }
</style>
