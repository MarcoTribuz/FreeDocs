<script lang="ts">
	/**
	 * The FreeDocs mark, inline so it follows the theme without a second file.
	 * Decorative wherever it is used: it always sits beside the product name,
	 * and a label here would make a screen reader say "FreeDocs" twice.
	 * The geometry is assets/brand/mark.svg; change it there first.
	 */
	let { size = 32 }: { size?: number } = $props();
</script>

<svg
	class="logo"
	viewBox="280 200 464 624"
	width={(size * 464) / 624}
	height={size}
	aria-hidden="true"
	focusable="false"
>
	<path
		d="M330 220H604L724 340V774a30 30 0 0 1-30 30H330a30 30 0 0 1-30-30V250a30 30 0 0 1 30-30Z"
		fill="var(--accent)"
	/>
	<path d="M604 220V310a30 30 0 0 0 30 30H724Z" fill="var(--accent-border)" />
	<g fill="var(--on-accent)" fill-opacity="0.45">
		<rect x="360" y="350" width="200" height="36" rx="18" />
		<rect x="360" y="600" width="304" height="36" rx="18" />
		<rect x="360" y="680" width="220" height="36" rx="18" />
	</g>
	<g
		fill="none"
		stroke="var(--on-accent)"
		stroke-width="20"
		stroke-linecap="round"
		stroke-linejoin="round"
	>
		<path d="M386 446H360V540H386" />
		<path d="M638 446H664V540H638" />
	</g>
	<rect x="404" y="469" width="216" height="48" rx="12" fill="var(--on-accent)" />
</svg>

<style>
	/* The marks use --on-accent, which is white on the light theme's dark accent
	   and dark on the dark theme's light one — the same inversion a button label
	   makes, so the mark cannot drift from the contrast measured for it. */
	.logo {
		flex: none;
	}
</style>
