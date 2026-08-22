<script lang="ts">
	/**
	 * The icon set, as inline paths.
	 *
	 * A dependency-free switch rather than an icon package: the CSP forbids
	 * fetching anything, so an icon font is out, and a tree-shaken SVG library
	 * would still be a build-time dependency for fourteen paths. `currentColor`
	 * throughout, so an icon inherits whatever the text around it is.
	 *
	 * Decorative by default. An icon that carries meaning nothing else carries
	 * must be given a `label`, which turns it into an image with a name.
	 */
	import type { IconName } from './icons';

	interface Props {
		name: IconName;
		size?: number;
		label?: string;
	}

	let { name, size = 16, label }: Props = $props();
</script>

<svg
	class="icon"
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width="2"
	stroke-linecap="round"
	stroke-linejoin="round"
	aria-hidden={label ? undefined : 'true'}
	role={label ? 'img' : undefined}
>
	{#if label}<title>{label}</title>{/if}
	{#if name === 'check'}
		<path d="M20 6 9 17l-5-5" />
	{:else if name === 'chevron-right'}
		<path d="m9 18 6-6-6-6" />
	{:else if name === 'chevron-down'}
		<path d="m6 9 6 6 6-6" />
	{:else if name === 'x'}
		<path d="M18 6 6 18M6 6l12 12" />
	{:else if name === 'plus'}
		<path d="M12 5v14M5 12h14" />
	{:else if name === 'alert-triangle'}
		<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
		<path d="M12 9v4M12 17h.01" />
	{:else if name === 'info'}
		<circle cx="12" cy="12" r="10" />
		<path d="M12 16v-4M12 8h.01" />
	{:else if name === 'shield-check'}
		<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
		<path d="m9 12 2 2 4-4" />
	{:else if name === 'file-text'}
		<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" />
		<path d="M14 2v5h6M8 13h8M8 17h5" />
	{:else if name === 'folder-open'}
		<path d="M6 14l1.5-4.5A2 2 0 0 1 9.4 8H21l-2.3 7.4A2 2 0 0 1 16.8 17H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4l2 3h6a2 2 0 0 1 2 2v0" />
	{:else if name === 'search'}
		<circle cx="11" cy="11" r="7" />
		<path d="m20 20-4.3-4.3" />
	{:else if name === 'arrow-right'}
		<path d="M5 12h14M13 5l7 7-7 7" />
	{:else if name === 'sun'}
		<circle cx="12" cy="12" r="4" />
		<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
	{:else if name === 'moon'}
		<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
	{:else if name === 'monitor'}
		<rect x="2" y="4" width="20" height="13" rx="2" />
		<path d="M8 21h8M12 17v4" />
	{/if}
</svg>

<style>
	.icon {
		display: block;
		flex: none;
	}
</style>
