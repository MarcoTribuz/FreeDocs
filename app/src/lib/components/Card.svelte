<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		/** 0 flat, 1 raised, 2 floating. Dark mode carries this with surface, not shadow. */
		elevation?: 0 | 1 | 2;
		padding?: 'none' | 'tight' | 'normal';
		tone?: 'default' | 'danger';
		/** Put the heading in here: it becomes the region's accessible name. */
		header?: Snippet;
		footer?: Snippet;
		children: Snippet;
	}

	let {
		elevation = 1,
		padding = 'normal',
		tone = 'default',
		header,
		footer,
		children
	}: Props = $props();

	const headerId = $props.id();
</script>

<!--
	A section when it has a header, a div when it does not.

	A region with no accessible name is worse than no region: a screen reader
	announces "group" and moves on. So the header snippet is wired to
	aria-labelledby, and a card without one is not a landmark at all.
-->
<svelte:element
	this={header ? 'section' : 'div'}
	class="card e{elevation} p-{padding} {tone}"
	aria-labelledby={header ? headerId : undefined}
>
	{#if header}
		<div class="header" id={headerId}>{@render header()}</div>
	{/if}
	{@render children()}
	{#if footer}<div class="footer">{@render footer()}</div>{/if}
</svelte:element>

<style>
	.card {
		border: 1px solid var(--border);
		border-radius: var(--radius-3);
		background: var(--surface);
	}
	.e0 {
		box-shadow: none;
	}
	.e1 {
		box-shadow: var(--shadow-1);
	}
	.e2 {
		box-shadow: var(--shadow-2);
	}
	.danger {
		border-color: var(--danger-border);
	}

	.p-none {
		padding: 0;
	}
	.p-tight {
		padding: var(--space-3);
	}
	.p-normal {
		padding: var(--space-4);
	}

	.header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
		flex-wrap: wrap;
		margin-bottom: var(--space-3);
	}

	.footer {
		margin-top: var(--space-3);
		padding-top: var(--space-3);
		border-top: 1px solid var(--border);
	}
</style>
