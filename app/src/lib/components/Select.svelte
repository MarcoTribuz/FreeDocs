<script lang="ts">
	import Field from './Field.svelte';
	import type { Option } from './types';

	interface Props {
		value: string;
		options: Option[];
		label: string;
		hint?: string;
		inline?: boolean;
		disabled?: boolean;
		/**
		 * For a choice whose consequence is not local — one that has to be sent to
		 * the engine before the window can say what it did. Two-way binding alone
		 * would leave the caller watching the value it already owns.
		 */
		onchange?: (value: string) => void;
	}

	let {
		value = $bindable(),
		options,
		label,
		hint,
		inline = false,
		disabled = false,
		onchange
	}: Props = $props();
</script>

<!--
	Options carry a label as well as a value, which is the whole reason this
	wrapper exists. The old window rendered the raw wire values: the placeholder
	language read `it`, `de`, `fr`, `en`, and the country chips read `CH`, `IT`.
	The value is what the engine needs; the label is what a person needs.
-->
<Field {label} {hint} {inline}>
	{#snippet children({ id, describedBy })}
		<select
			{id}
			class="select"
			aria-describedby={describedBy}
			{disabled}
			bind:value
			onchange={() => onchange?.(value)}
		>
			{#each options as option (option.value)}
				<option value={option.value}>{option.label}</option>
			{/each}
		</select>
	{/snippet}
</Field>

<style>
	.select {
		font: inherit;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-1);
		background: var(--surface);
		color: inherit;
		max-width: 100%;
	}
	.select:focus {
		border-color: var(--accent-line);
	}
	.select:disabled {
		color: var(--text-3);
		background: var(--bg-subtle);
	}
</style>
