import { browser } from '$app/environment';

/**
 * Which theme the window uses, and where that choice is kept.
 *
 * `system` is a real third state rather than "no preference": the media query is
 * listened to, so changing the OS theme while the window is open follows it.
 * Because a resolved value is always written to `data-theme`, the stylesheet
 * needs exactly two blocks and a manual choice wins in both directions by
 * construction — forcing light on a dark OS is the same code path as the
 * reverse, which a `prefers-color-scheme` block cannot do without a second copy
 * of the palette.
 *
 * The preference lives in `localStorage`, not in `@tauri-apps/plugin-store`:
 * that would add a Rust dependency, a capability entry, and an *async* read at
 * boot — which reintroduces the flash of the wrong theme that stamping the
 * attribute before the first render exists to avoid. Two enum values do not
 * need a file format.
 */

export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

const KEY = 'freedocs.theme';

const query = browser ? window.matchMedia('(prefers-color-scheme: dark)') : null;

function read(): ThemePreference {
	if (!browser) return 'system';
	const raw = localStorage.getItem(KEY);
	return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system';
}

let preference = $state<ThemePreference>(read());
let systemDark = $state(query?.matches ?? false);

const resolved = $derived<ResolvedTheme>(
	preference === 'system' ? (systemDark ? 'dark' : 'light') : preference
);

/**
 * Written from an explicit call rather than from an `$effect`.
 *
 * The attribute has to be correct before the first component renders, and an
 * effect only runs after one. So this is called once at module load — which is
 * during `+layout.svelte`'s import, before any markup exists — and again
 * whenever the preference or the OS answer changes.
 */
function apply(): void {
	if (!browser) return;
	document.documentElement.dataset.theme =
		preference === 'system' ? (query?.matches ? 'dark' : 'light') : preference;
}

if (query) {
	query.addEventListener('change', (event) => {
		systemDark = event.matches;
		apply();
	});
}

apply();

export const theme = {
	get preference(): ThemePreference {
		return preference;
	},
	/** What is actually on screen, which is what a toggle's label should read. */
	get resolved(): ResolvedTheme {
		return resolved;
	},
	set(next: ThemePreference): void {
		preference = next;
		if (browser) localStorage.setItem(KEY, next);
		apply();
	}
};
