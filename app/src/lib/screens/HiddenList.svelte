<script lang="ts">
	import type { HiddenItem } from '$lib/engine';
	import { groupHidden, hiddenLabel } from '$lib/readable';
	import { i18n } from '$lib/i18n/index.svelte';
	import Button from '$lib/components/Button.svelte';

	let { items }: { items: HiddenItem[] } = $props();

	const m = $derived(i18n.m);
	const groups = $derived(groupHidden(items));
	let details = $state(false);
	const id = $props.id();
</script>

<!--
	What was (or will be) taken out that the reader never saw, one line per kind
	in the reader's language. The engine reports one item per part, and Word
	keeps revision ids in nine of them: nine identical lines is how the reader
	stops before the one that matters. The per-part lines are still here, behind
	a toggle, quoted in the engine's English — `detail` is an f-string.
-->
<ul class="groups">
	{#each groups as group (group.kind)}
		<li>
			{hiddenLabel(m, group.kind)}
			{#if group.parts > 1}
				<span class="parts">· {m.hiddenParts({ count: group.parts })}</span>
			{/if}
		</li>
	{/each}
</ul>
<Button
	variant="link"
	aria-expanded={details}
	aria-controls={id}
	onclick={() => (details = !details)}
>
	{details ? m.hiddenDetailsHide() : m.hiddenDetailsShow()}
</Button>
{#if details}
	<div {id}>
		<p class="note">{m.hiddenDetailsNote()}</p>
		<ul class="details" lang="en">
			{#each items as item, index (index)}
				<li><span class="mono">{item.part}</span> — {item.kind}: {item.detail}</li>
			{/each}
		</ul>
	</div>
{/if}

<style>
	ul {
		list-style: none;
		margin: var(--space-2) 0;
		padding: 0;
		display: grid;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}

	.groups {
		color: var(--text);
	}

	.parts,
	.note,
	.details {
		color: var(--text-2);
	}

	.note {
		margin: var(--space-2) 0 0;
		font-size: var(--text-sm);
	}

	.details {
		font-size: var(--text-xs);
		line-height: 1.5;
	}

	.mono {
		font-family: var(--font-mono);
	}
</style>
