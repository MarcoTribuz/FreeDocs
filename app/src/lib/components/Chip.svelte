<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { EntityCategory } from '$lib/entities';
	import Icon from './Icon.svelte';

	interface Props {
		/** The toggle state. Reported, never owned: the parent holds the set. */
		pressed: boolean;
		/** Accessible name. Required, because `children` may render a glyph too. */
		label: string;
		/** Extra explanation. Reaches the accessible description, not just a title. */
		hint?: string;
		/** Tints the chip with an entity category's colour when it names one. */
		category?: EntityCategory;
		disabled?: boolean;
		onchange: (pressed: boolean) => void;
		children?: Snippet;
	}

	let {
		pressed,
		label,
		hint,
		category,
		disabled = false,
		onchange,
		children
	}: Props = $props();

	// $props.id() rather than a counter: stable across re-renders, so the
	// aria-describedby link survives the list being reordered.
	const hintId = $props.id();
</script>

<button
	type="button"
	class="chip"
	class:on={pressed}
	style:--chip-line={category ? `var(--e-${category}-line)` : 'var(--accent-line)'}
	style:--chip-tint={category ? `var(--e-${category}-tint)` : 'var(--accent-soft)'}
	aria-pressed={pressed}
	aria-describedby={hint ? hintId : undefined}
	{disabled}
	onclick={() => onchange(!pressed)}
>
	<!--
		The state has a shape as well as a colour. A chip whose only difference is
		its background cannot be read by anyone colour-blind, and that was the
		previous window's real defect: on/off was `background-color` alone.
	-->
	<span class="mark" aria-hidden="true">
		{#if pressed}<Icon name="check" size={12} />{/if}
	</span>
	{#if children}{@render children()}{:else}{label}{/if}
</button>
{#if hint}<span id={hintId} class="sr-only">{hint}</span>{/if}

<style>
	.chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-3) var(--space-1) var(--space-2);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-full);
		background: var(--surface);
		color: var(--text-2);
		font-family: var(--font-sans);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		line-height: var(--lh-xs);
		cursor: pointer;
		transition:
			background var(--dur-1) var(--ease-out),
			border-color var(--dur-1) var(--ease-out),
			color var(--dur-1) var(--ease-out),
			transform var(--dur-1) var(--ease-out);
	}
	.chip:hover:not(:disabled) {
		background: var(--surface-hover);
		color: var(--text);
	}
	.chip:active:not(:disabled) {
		transform: scale(0.97);
	}

	.chip.on {
		background: var(--chip-tint);
		border-color: var(--chip-line);
		color: var(--text);
		box-shadow: inset 0 0 0 1px var(--chip-line);
	}

	/* Reserved width, so pressing a chip does not reflow the row it sits in. */
	.mark {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 12px;
		color: var(--chip-line);
	}
	.chip.on .mark {
		animation: pop var(--dur-2) var(--ease-spring);
	}

	.chip:disabled {
		cursor: default;
		color: var(--text-3);
		border-style: dashed;
	}

	@keyframes pop {
		from {
			transform: scale(0.4);
			opacity: 0;
		}
		to {
			transform: scale(1);
			opacity: 1;
		}
	}
</style>
