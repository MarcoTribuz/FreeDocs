import { browser } from '$app/environment';

/**
 * Motion, with the one thing CSS gets for free and JavaScript does not.
 *
 * The stylesheet honours `prefers-reduced-motion` in one rule. A Svelte
 * transition does not: it animates in JavaScript, so the media query has to be
 * asked here or the setting is quietly ignored by exactly the animations a
 * person who set it would notice most.
 *
 * Read on every call rather than cached: the setting can change while the window
 * is open, and a cached answer would keep animating for the rest of the session.
 */
export function reduced(): boolean {
	return browser && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** A duration in milliseconds, or zero for someone who asked for less. */
export function duration(ms: number): number {
	return reduced() ? 0 : ms;
}

/** The token durations, so a transition and a CSS rule cannot drift apart. */
export const DUR = { fast: 90, base: 160, slow: 240 } as const;
