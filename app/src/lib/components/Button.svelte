<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons';

	interface Props extends HTMLButtonAttributes {
		variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'link';
		size?: 'sm' | 'md';
		/** Shows a busy state without leaving the tab order. See below. */
		loading?: boolean;
		icon?: IconName;
		/**
		 * Accessible name, required when there is no visible text. A button whose
		 * only content is a glyph has no name at all without it.
		 */
		label?: string;
		children?: Snippet;
	}

	let {
		variant = 'secondary',
		size = 'md',
		loading = false,
		disabled = false,
		icon,
		label,
		children,
		...rest
	}: Props = $props();
</script>

<!--
	`loading` sets aria-busy and keeps the button enabled rather than disabling it.
	Disabling the element the user just activated drops focus to the document, so
	the next Tab starts from the top of the window — in the middle of an action
	they are waiting on. The click is guarded instead.
-->
<button
	type="button"
	class="btn {variant} {size}"
	class:icon-only={!children && !!icon}
	aria-busy={loading ? 'true' : undefined}
	aria-label={children ? undefined : label}
	aria-disabled={loading ? 'true' : undefined}
	{disabled}
	{...rest}
	onclick={(event) => {
		if (loading) {
			event.preventDefault();
			return;
		}
		rest.onclick?.(event);
	}}
>
	{#if icon}<Icon name={icon} size={size === 'sm' ? 14 : 16} />{/if}
	{#if children}{@render children()}{/if}
</button>

<style>
	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		border: 1px solid transparent;
		border-radius: var(--radius-2);
		font-family: var(--font-sans);
		font-weight: var(--weight-medium);
		cursor: pointer;
		transition:
			background var(--dur-1) var(--ease-out),
			border-color var(--dur-1) var(--ease-out),
			color var(--dur-1) var(--ease-out),
			transform var(--dur-1) var(--ease-out);
	}
	.btn:active:not(:disabled):not([aria-disabled='true']) {
		transform: scale(0.98);
	}

	.md {
		padding: var(--space-2) var(--space-4);
		font-size: var(--text-md);
	}
	.sm {
		padding: var(--space-1) var(--space-3);
		font-size: var(--text-sm);
	}
	.icon-only.md {
		padding: var(--space-2);
	}
	.icon-only.sm {
		padding: var(--space-1);
	}

	.primary {
		background: var(--accent);
		color: var(--on-accent);
	}
	.primary:hover:not(:disabled):not([aria-disabled='true']) {
		background: var(--accent-hover);
	}

	.secondary {
		border-color: var(--border-strong);
		background: var(--surface);
		color: var(--text);
	}
	.secondary:hover:not(:disabled):not([aria-disabled='true']) {
		background: var(--surface-hover);
	}

	.ghost {
		background: none;
		color: var(--text-2);
	}
	.ghost:hover:not(:disabled):not([aria-disabled='true']) {
		background: var(--surface-hover);
		color: var(--text);
	}

	.danger {
		background: var(--danger);
		color: var(--on-danger);
	}

	/*
	 * An in-context action, not a call to action: it must not compete with the
	 * button that acts on the whole document, because the common case is not
	 * touching it at all.
	 */
	.link {
		padding: 0;
		background: none;
		color: var(--accent-text);
		font-size: var(--text-sm);
		font-weight: var(--weight-normal);
		text-decoration: underline;
	}
	.link:hover:not(:disabled) {
		color: var(--accent-hover);
	}

	/* A colour and a cursor, never a transparency: an opacity swap dims the
	   border until the control stops reading as one. */
	.btn:disabled {
		color: var(--text-3);
		background: var(--bg-subtle);
		border-color: var(--border);
		cursor: default;
	}
	.link:disabled,
	.ghost:disabled {
		background: none;
	}
</style>
