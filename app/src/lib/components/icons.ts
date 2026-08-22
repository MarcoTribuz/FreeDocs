/**
 * The icon names Icon.svelte can draw.
 *
 * A module rather than an export from the component, so a consumer can type a
 * prop as an icon name without importing the component that renders it — and
 * because a Svelte instance script cannot export a type at all.
 */
export type IconName =
	| 'check'
	| 'chevron-right'
	| 'chevron-down'
	| 'x'
	| 'plus'
	| 'alert-triangle'
	| 'info'
	| 'shield-check'
	| 'file-text'
	| 'folder-open'
	| 'search'
	| 'arrow-right'
	| 'sun'
	| 'moon'
	| 'monitor';
