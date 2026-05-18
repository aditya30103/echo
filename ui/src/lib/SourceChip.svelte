<script lang="ts">
	let { label, color = 'var(--text-secondary)' }: { label: string; color?: string } = $props();
</script>

<span class="source-chip" style="color:{color}">{label}</span>

<style>
	.source-chip {
		font-size: 0.65rem;
		font-weight: 700;
		border: 1px solid var(--signal-cold-dim);
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
	}
</style>
