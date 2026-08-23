<script lang="ts">
	interface Props {
		/** How many lines to stand in for. */
		lines?: number;
		label: string;
	}

	let { lines = 6, label }: Props = $props();
</script>

<!--
	A shape where the text will be, rather than the word "Reading…".

	Reading a scanned page takes seconds per page, and a single line of text gives
	no sense of whether anything is happening. The shape does, and it also holds
	the layout still so the document does not jump when it arrives.

	`aria-hidden` on the shapes and one `role="status"` for the fact: a screen
	reader wants to be told the document is being read, not to be read eight
	rectangles.
-->
<div class="skeleton">
	<p class="sr-only" role="status">{label}</p>
	<div aria-hidden="true">
		{#each Array(lines) as _, index (index)}
			<span class="line" style:width={`${92 - ((index * 37) % 45)}%`}></span>
		{/each}
	</div>
</div>

<style>
	.skeleton {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.line {
		display: block;
		height: 0.85rem;
		margin-bottom: var(--space-2);
		border-radius: var(--radius-1);
		background: linear-gradient(
			90deg,
			var(--bg-subtle) 0%,
			var(--surface-hover) 50%,
			var(--bg-subtle) 100%
		);
		background-size: 200% 100%;
		animation: shimmer 1.4s var(--ease-in-out) infinite;
	}

	@keyframes shimmer {
		from {
			background-position: 200% 0;
		}
		to {
			background-position: -200% 0;
		}
	}
</style>
