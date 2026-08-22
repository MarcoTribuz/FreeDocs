<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';

	interface Props {
		open: boolean;
		summary: string;
		/** Shown beside the summary, so a collapsed panel still says how much is in it. */
		count?: number;
		children: Snippet;
	}

	let { open = $bindable(), summary, count, children }: Props = $props();

	const id = $props.id();
</script>

<!--
	A button and a region rather than <details>/<summary>.

	Two reasons, both practical. <details> cannot be animated on the oldest
	webview this app claims to support, so a panel would snap open while every
	other transition eases. And its open state cannot be driven from outside
	without fighting the element: the settings panel needs to be seeded from what
	the engine reported at startup and then left alone, which is a value this
	component's parent owns.
-->
<section class="panel">
	<h2 class="head">
		<button
			type="button"
			class="trigger"
			aria-expanded={open}
			aria-controls={id}
			onclick={() => (open = !open)}
		>
			<span class="chevron" class:open aria-hidden="true">
				<Icon name="chevron-right" size={14} />
			</span>
			<span class="summary">{summary}</span>
			{#if count !== undefined}<span class="count">{count}</span>{/if}
		</button>
	</h2>
	<div {id} class="body" hidden={!open}>
		{@render children()}
	</div>
</section>

<style>
	.panel {
		border: 1px solid var(--border);
		border-radius: var(--radius-3);
		background: var(--surface);
		box-shadow: var(--shadow-1);
		margin-bottom: var(--space-4);
	}

	.head {
		margin: 0;
		font: inherit;
	}

	.trigger {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-3) var(--space-4);
		border: 0;
		border-radius: var(--radius-3);
		background: none;
		color: var(--text-3);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		text-align: left;
		cursor: pointer;
	}
	.trigger:hover {
		color: var(--text);
	}

	.chevron {
		display: inline-flex;
		transition: transform var(--dur-2) var(--ease-out);
	}
	.chevron.open {
		transform: rotate(90deg);
	}

	.count {
		margin-left: auto;
		font-variant-numeric: tabular-nums;
		letter-spacing: normal;
	}

	.body {
		padding: 0 var(--space-4) var(--space-4);
	}
	.body[hidden] {
		display: none;
	}
</style>
