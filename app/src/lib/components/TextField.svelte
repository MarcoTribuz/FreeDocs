<script lang="ts">
	import type { HTMLInputAttributes } from 'svelte/elements';
	import Field from './Field.svelte';

	interface Props extends Omit<HTMLInputAttributes, 'value'> {
		value: string;
		label: string;
		hint?: string;
		error?: string;
		mono?: boolean;
		inline?: boolean;
		/** Enter is a submit in every one of this window's text fields. */
		onEnter?: () => void;
	}

	let {
		value = $bindable(),
		label,
		hint,
		error,
		mono = false,
		inline = false,
		onEnter,
		...rest
	}: Props = $props();
</script>

<Field {label} {hint} {error} {inline}>
	{#snippet children({ id, describedBy })}
		<input
			{id}
			type="text"
			class="input"
			class:mono
			aria-describedby={describedBy}
			aria-invalid={error ? 'true' : undefined}
			bind:value
			onkeydown={(event) => {
				if (event.key === 'Enter' && onEnter) onEnter();
			}}
			{...rest}
		/>
	{/snippet}
</Field>

<style>
	.input {
		flex: 1;
		min-width: 0;
		font: inherit;
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-1);
		background: var(--surface);
		color: inherit;
		transition: border-color var(--dur-1) var(--ease-out);
	}
	.input:focus {
		border-color: var(--accent-line);
	}
	.input[aria-invalid='true'] {
		border-color: var(--danger-border);
	}
	.mono {
		font-family: var(--font-mono);
		font-size: 0.9em;
	}
</style>
