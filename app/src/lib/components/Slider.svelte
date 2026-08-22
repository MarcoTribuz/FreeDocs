<script lang="ts">
	import Field from './Field.svelte';

	interface Props {
		value: number;
		min?: number;
		max?: number;
		step?: number;
		label: string;
		hint?: string;
		/** How the number reads on screen. */
		format?: (value: number) => string;
		/**
		 * How the number is spoken. Defaults to `format`.
		 *
		 * Separate because "0.50" is not a useful announcement: a threshold wants a
		 * word next to it, and the word is the part that says what raising it does.
		 */
		describe?: (value: number) => string;
		onchange?: () => void;
	}

	let {
		value = $bindable(),
		min = 0,
		max = 1,
		step = 0.05,
		label,
		hint,
		format = (v) => v.toFixed(2),
		describe,
		onchange
	}: Props = $props();

	const spoken = $derived((describe ?? format)(value));
</script>

<Field {label} {hint} inline>
	{#snippet children({ id, describedBy })}
		<input
			{id}
			type="range"
			class="range"
			{min}
			{max}
			{step}
			aria-describedby={describedBy}
			aria-valuetext={spoken}
			bind:value
			{onchange}
		/>
		<output class="value" for={id}>{format(value)}</output>
	{/snippet}
</Field>

<style>
	.range {
		accent-color: var(--accent);
		min-width: 10rem;
	}

	.value {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		color: var(--text-2);
		min-width: 3ch;
	}
</style>
