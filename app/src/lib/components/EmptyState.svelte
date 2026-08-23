<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons';

	interface Props {
		icon: IconName;
		title: string;
		body?: string;
		/** The heading level that fits where this is used. */
		level?: 2 | 3 | 4;
		action?: Snippet;
	}

	let { icon, title, body, level = 3, action }: Props = $props();
</script>

<div class="empty">
	<span class="glyph" aria-hidden="true"><Icon name={icon} size={22} /></span>
	<!-- A real heading at the level the surrounding page is at. An empty state
	     that is only styled text is invisible to anyone navigating by heading. -->
	<svelte:element this={`h${level}`} class="title">{title}</svelte:element>
	{#if body}<p class="body">{body}</p>{/if}
	{#if action}<div class="action">{@render action()}</div>{/if}
</div>

<style>
	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-7) var(--space-4);
		text-align: center;
		color: var(--text-2);
	}

	.glyph {
		color: var(--text-3);
	}

	.title {
		margin: 0;
		font-size: var(--text-lg);
		color: var(--text);
	}

	.body {
		max-width: 34rem;
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	.action {
		margin-top: var(--space-2);
	}
</style>
