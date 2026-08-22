<script lang="ts">
	// Imported for its side effect as well as its API: the module stamps
	// `data-theme` on <html> while it loads, which is before any of this markup
	// exists, so there is no frame painted in the wrong theme.
	import { theme, type ThemePreference } from '$lib/theme.svelte';
	import { live } from '$lib/announce.svelte';
	import '../app.css';

	let { children } = $props();

	const choices: { value: ThemePreference; label: string }[] = [
		{ value: 'system', label: 'Auto' },
		{ value: 'light', label: 'Light' },
		{ value: 'dark', label: 'Dark' }
	];
</script>

<!-- First focusable element in the document, and the only reason <main> has an
     id. Without it, reaching the file list by keyboard means tabbing through
     every control in the chrome. -->
<a class="skip" href="#main">Skip to content</a>

<div class="chrome">
	<div class="segmented" role="group" aria-label="Appearance">
		{#each choices as choice}
			<button
				type="button"
				class="segment"
				class:on={theme.preference === choice.value}
				aria-pressed={theme.preference === choice.value}
				onclick={() => theme.set(choice.value)}
			>
				{choice.label}
			</button>
		{/each}
	</div>
</div>

{@render children()}

<!--
	The two live regions, empty until something is announced.

	Separate elements rather than one with a switchable `aria-live`: changing the
	politeness of a region is not reliably picked up, and the two queues are
	independent — a refused override must not wait behind a progress message.
-->
<div class="sr-only" role="status" aria-live="polite" aria-atomic="true">{live.polite}</div>
<div class="sr-only" role="alert" aria-atomic="true">{live.assertive}</div>

<style>
	.skip {
		position: absolute;
		top: var(--space-2);
		left: var(--space-2);
		z-index: var(--z-tooltip);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-2);
		background: var(--surface);
		box-shadow: var(--shadow-2);
		color: var(--accent-text);
		font-size: var(--text-sm);
		/* Off-screen rather than hidden: `display: none` would take it out of the
		   tab order, which is the one thing it exists for. */
		transform: translateY(-200%);
		transition: transform var(--dur-2) var(--ease-out);
	}
	.skip:focus {
		transform: translateY(0);
	}

	.chrome {
		display: flex;
		justify-content: flex-end;
		padding: var(--space-3) var(--space-5) 0;
	}

	.segmented {
		display: inline-flex;
		padding: 2px;
		border: 1px solid var(--border);
		border-radius: var(--radius-full);
		background: var(--bg-subtle);
	}

	.segment {
		padding: var(--space-1) var(--space-3);
		border: 0;
		border-radius: var(--radius-full);
		background: none;
		color: var(--text-3);
		font: var(--weight-medium) var(--text-xs) / var(--lh-xs) var(--font-sans);
		cursor: pointer;
		transition:
			background var(--dur-1) var(--ease-out),
			color var(--dur-1) var(--ease-out);
	}
	.segment:hover {
		color: var(--text);
	}
	.segment.on {
		background: var(--surface);
		color: var(--text);
		box-shadow: var(--shadow-1);
	}
</style>
