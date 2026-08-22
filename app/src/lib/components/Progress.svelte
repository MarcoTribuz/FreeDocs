<script lang="ts">
	interface Props {
		value?: number;
		max?: number;
		/**
		 * What the bar says when asked. Not what it announces continuously.
		 *
		 * The bar is deliberately outside any live region: a running commentary on
		 * every file of a batch makes the window unusable with a screen reader.
		 * Whoever advances the bar announces the parts worth interrupting for —
		 * the file changing, the run ending — through `announce()`.
		 */
		valueText: string;
		/** For work whose size the engine cannot honestly know yet. */
		indeterminate?: boolean;
		label: string;
	}

	let { value = 0, max = 1, valueText, indeterminate = false, label }: Props = $props();

	const fraction = $derived(max > 0 ? Math.min(1, Math.max(0, value / max)) : 0);
</script>

<div class="wrap">
	<div
		class="track"
		role="progressbar"
		aria-label={label}
		aria-valuenow={indeterminate ? undefined : value}
		aria-valuemin={indeterminate ? undefined : 0}
		aria-valuemax={indeterminate ? undefined : max}
		aria-valuetext={valueText}
	>
		<div
			class="fill"
			class:indeterminate
			style:width={indeterminate ? undefined : `${fraction * 100}%`}
		></div>
	</div>
	<p class="text">{valueText}</p>
</div>

<style>
	.wrap {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.track {
		height: 6px;
		border-radius: var(--radius-full);
		background: var(--bg-subtle);
		overflow: hidden;
	}

	.fill {
		height: 100%;
		border-radius: var(--radius-full);
		background: var(--accent);
		transition: width var(--dur-3) var(--ease-out);
	}

	.indeterminate {
		width: 35%;
		animation: slide 1.4s var(--ease-in-out) infinite;
	}

	.text {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	@keyframes slide {
		from {
			transform: translateX(-100%);
		}
		to {
			transform: translateX(350%);
		}
	}
</style>
