import { browser } from '$app/environment';
import type { Messages } from './messages';
import { de } from './de';
import { en } from './en';
import { fr } from './fr';
import { it } from './it';

/**
 * Which language the window speaks, and how it decided.
 *
 * The four candidates are the four the engine's NER layer reads, which is not a
 * coincidence worth breaking: a person scrubbing an Italian contract is the
 * person who wants an Italian window.
 *
 * The OS preference comes from `navigator.languages`, which in WKWebView and
 * WebView2 reflects the system's ordered list. `@tauri-apps/plugin-os` would be
 * a Rust dependency and a capability entry to learn something already present in
 * the window.
 */
export const LOCALES = ['en', 'it', 'de', 'fr'] as const;
export type Locale = (typeof LOCALES)[number];

const KEY = 'freedocs.locale';

const catalogues: Record<Locale, Messages> = { en, it, de, fr };

function known(value: string | null): value is Locale {
	return value !== null && (LOCALES as readonly string[]).includes(value);
}

function detect(): Locale {
	if (!browser) return 'en';
	const stored = localStorage.getItem(KEY);
	if (known(stored)) return stored;
	for (const tag of navigator.languages ?? [navigator.language]) {
		// The primary subtag only: `de-CH` is a German window, and a Swiss German
		// catalogue is not something this project has or needs.
		const primary = tag.toLowerCase().split('-')[0];
		if (known(primary)) return primary;
	}
	return 'en';
}

let locale = $state<Locale>(detect());

function applyLang(): void {
	if (browser) document.documentElement.lang = locale;
}

// At module load, so <html lang> is right before the first render rather than
// after an effect: assistive technology reads the attribute, not a later update.
applyLang();

export const i18n = {
	get locale(): Locale {
		return locale;
	},
	/** The catalogue. Read through a getter so a locale change re-renders. */
	get m(): Messages {
		return catalogues[locale];
	},
	set(next: Locale): void {
		locale = next;
		if (browser) localStorage.setItem(KEY, next);
		applyLang();
	}
};

/*
 * One locale governs everything the window says: the catalogue, the country and
 * language names from `Intl.DisplayNames`, the plural rules, and the number
 * grouping. Splitting them — a German catalogue with Swiss number formatting,
 * say — was considered and dropped: it makes every message's output depend on
 * two settings, and the second one is invisible.
 *
 * The machine's locale is consulted exactly once, to pick the default.
 */

