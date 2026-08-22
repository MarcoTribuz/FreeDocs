<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons';

	interface Props {
		tone: 'info' | 'warn' | 'danger' | 'success';
		title?: string;
		/**
		 * Whether the body is prose the engine wrote.
		 *
		 * Engine messages are English, composed in Python from f-strings, and are
		 * quoted rather than translated: they are asserted on by the test suite,
		 * they reach the CLI and a report on disk as well as this window, and a
		 * mistranslated "not installed" that reads as "not required" is a build
		 * that quietly finds less. So the container is in the user's language and
		 * the content carries `lang="en"` — a screen reader then pronounces it
		 * correctly instead of reading English with Italian phonemes.
		 */
		verbatim?: boolean;
		/**
		 * Whether this appeared in response to something the user just did.
		 *
		 * A danger callout that arrives after an action interrupts; the same tone
		 * shown at startup does not. Limitations reported by the engine on launch
		 * are facts about the build, and shouting them on every open trains the
		 * user to dismiss the channel that also carries a refused override.
		 */
		live?: boolean;
		children: Snippet;
	}

	let { tone, title, verbatim = false, live = false, children }: Props = $props();

	const icons: Record<Props['tone'], IconName> = {
		info: 'info',
		warn: 'alert-triangle',
		danger: 'alert-triangle',
		success: 'shield-check'
	};

	const role = $derived(
		live ? (tone === 'danger' ? 'alert' : 'status') : undefined
	);
</script>

<aside class="callout {tone}" {role}>
	<span class="glyph" aria-hidden="true"><Icon name={icons[tone]} size={16} /></span>
	<div class="body">
		{#if title}<p class="title">{title}</p>{/if}
		<div class="content" lang={verbatim ? 'en' : undefined}>{@render children()}</div>
	</div>
</aside>

<style>
	.callout {
		display: flex;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--border);
		border-radius: var(--radius-3);
		margin-bottom: var(--space-4);
		font-size: var(--text-sm);
		line-height: var(--lh-sm);
	}

	.glyph {
		margin-top: 2px;
	}

	.body {
		min-width: 0;
	}

	.title {
		margin-bottom: var(--space-1);
		font-weight: var(--weight-semibold);
	}

	.content :global(p) {
		margin: var(--space-1) 0;
	}

	.info {
		border-color: var(--info-border);
		background: var(--info-soft);
		color: var(--info-text);
	}
	.warn {
		border-color: var(--warn-border);
		background: var(--warn-soft);
		color: var(--warn-text);
	}
	.danger {
		border-color: var(--danger-border);
		background: var(--danger-soft);
		color: var(--danger-text);
	}
	.success {
		border-color: var(--success-border);
		background: var(--success-soft);
		color: var(--success-text);
	}
</style>
