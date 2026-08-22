<script lang="ts">
	import type { Snippet } from 'svelte';

	interface Props {
		label: string;
		hint?: string;
		error?: string;
		/** Lays the label beside the control instead of above it. */
		inline?: boolean;
		children: Snippet<[{ id: string; describedBy: string | undefined }]>;
	}

	let { label, hint, error, inline = false, children }: Props = $props();

	/*
	 * The wrapper owns the id and hands it to the control.
	 *
	 * This is the point of the component. The old window associated labels by
	 * wrapping, which works — until a control is not wrapped, and then it has no
	 * label at all: the placeholder-language <select> had none, only a nearby
	 * heading. Owning the id here makes the `for`/`id` pair structurally
	 * impossible to forget, and gives hints and errors somewhere to be announced
	 * from rather than merely displayed.
	 */
	const id = $props.id();
	const hintId = `${id}-hint`;
	const errorId = `${id}-error`;

	const describedBy = $derived(
		[hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined
	);
</script>

<div class="field" class:inline>
	<label class="label" for={id}>{label}</label>
	<div class="control">
		{@render children({ id, describedBy })}
	</div>
	{#if hint}<p class="hint" id={hintId}>{hint}</p>{/if}
	{#if error}<p class="error" id={errorId}>{error}</p>{/if}
</div>

<style>
	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	.inline {
		flex-direction: row;
		align-items: center;
		gap: var(--space-2);
		flex-wrap: wrap;
	}

	.label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		color: var(--text-2);
	}

	.control {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
	}

	.hint {
		font-size: var(--text-xs);
		line-height: var(--lh-xs);
		color: var(--text-3);
		max-width: 42rem;
	}

	.error {
		font-size: var(--text-xs);
		color: var(--danger-text);
	}

	.inline .hint,
	.inline .error {
		flex-basis: 100%;
	}
</style>
