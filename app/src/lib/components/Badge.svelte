<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { EntityCategory } from '$lib/entities';

	interface Props {
		tone?: 'neutral' | 'accent' | 'success' | 'warn' | 'danger' | 'entity';
		/** Required when `tone` is 'entity'; ignored otherwise. */
		category?: EntityCategory;
		mono?: boolean;
		children: Snippet;
	}

	let { tone = 'neutral', category, mono = false, children }: Props = $props();
</script>

<!--
	Static text. If a badge conveys state, the state is in the words: a tone is a
	second channel, never the only one. "OCR" in amber says nothing to a reader
	who cannot see the amber, which is why the label reads "OCR not installed".
-->
<span
	class="badge {tone}"
	class:mono
	style:--badge-tint={category ? `var(--e-${category}-tint)` : undefined}
	style:--badge-text={category ? `var(--e-${category}-text)` : undefined}
	style:--badge-line={category ? `var(--e-${category}-line)` : undefined}
>
	{@render children()}
</span>

<style>
	.badge {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: var(--space-1) var(--space-3);
		border: 1px solid var(--border);
		border-radius: var(--radius-full);
		background: var(--surface);
		color: var(--text-2);
		font-size: var(--text-xs);
		line-height: var(--lh-xs);
		white-space: nowrap;
	}
	.mono {
		font-family: var(--font-mono);
	}

	.accent {
		border-color: var(--accent-border);
		background: var(--accent-soft);
		color: var(--accent-text);
	}
	.success {
		border-color: var(--success-border);
		background: var(--success-soft);
		color: var(--success-text);
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
	.entity {
		border-color: var(--badge-line);
		background: var(--badge-tint);
		color: var(--badge-text);
	}
</style>
