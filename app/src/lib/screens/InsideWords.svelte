<script lang="ts">
	import type { InsideWords } from '$lib/engine';
	import { regionLabel } from '$lib/readable';
	import { categoryOf } from '$lib/entities';
	import { i18n } from '$lib/i18n/index.svelte';
	import Badge from '$lib/components/Badge.svelte';

	let { items }: { items: InsideWords[] } = $props();

	const m = $derived(i18n.m);
</script>

<!--
	A removed value the engine left inside longer words — `Acteurs` taken out
	where it stood alone, `facteurs` left alone. Not a failure: said in the
	reader's language with the words themselves, so the reader can see at a
	glance that they are ordinary words and move on, or spot the one that is a
	username. The value and the words come down the local pipe; the report on
	disk counts them and names nothing.
-->
<h4>{m.insideWordsTitle()}</h4>
<p class="hint">{m.insideWordsHint()}</p>
<ul class="values">
	{#each items as item, index (index)}
		<li>
			<p class="lead">
				<Badge tone="entity" category={categoryOf(item.entity)}>
					{m.entity[item.entity]?.() ?? item.entity}
				</Badge>
				{m.insideWordsLead({ value: item.value, count: item.occurrences })}
			</p>
			<ul class="words">
				{#each item.words as word, w (w)}
					<li>
						<span class="word">{word.word}</span>
						<span class="where">— {regionLabel(m, word.region)}</span>
						{#if word.occurrences > 1}<span class="mono">×{word.occurrences}</span>{/if}
					</li>
				{/each}
			</ul>
		</li>
	{/each}
</ul>

<style>
	.hint {
		margin: var(--space-1) 0 var(--space-2);
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}

	.values > li {
		margin: var(--space-2) 0;
		padding-left: var(--space-2);
		border-left: 2px solid var(--warn-border);
	}

	.lead {
		margin: 0 0 var(--space-1);
		font-size: var(--text-sm);
	}

	.words {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-3);
		font-size: var(--text-sm);
	}

	.word {
		font-weight: 600;
	}

	.where,
	.mono {
		color: var(--text-2);
	}

	.mono {
		font-family: var(--font-mono);
	}
</style>
