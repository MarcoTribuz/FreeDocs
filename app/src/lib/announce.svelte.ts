/**
 * What a screen reader is told about things that happen without a click.
 *
 * Every asynchronous state change in this window used to be silent: a file
 * being read, a re-inspection landing, a scrub finishing, an error banner
 * appearing. None of them move focus, so none of them are announced unless
 * something writes into a live region.
 *
 * Two regions rather than one, because the two urgencies are not
 * interchangeable. `polite` waits for a pause: progress, counts, the outcome of
 * a decision. `assertive` interrupts: the engine failing, an override refused.
 * Putting a refused override in the polite queue behind a progress message
 * means the user acts on a decision that did not happen.
 *
 * Deliberately *not* announced: each tick of the progress bar. The bar carries
 * `aria-valuetext` for anyone who asks it, and a running commentary on every
 * file of a batch makes the window unusable with a screen reader.
 */

let polite = $state('');
let assertive = $state('');

/**
 * A counter appended to the message, invisible but present.
 *
 * Writing the same string twice announces nothing the second time — the region
 * only fires on a change — and "re-checking" landing twice in a row is exactly
 * the case that matters. The zero-width space carries the difference without
 * being spoken.
 */
let tick = 0;

/** A zero-width space, written as an escape so it is visible in the source. */
const ZWSP = '\u200B';

function stamp(text: string): string {
	tick += 1;
	return text + ZWSP.repeat(tick % 2);
}

export function announce(text: string, options: { assertive?: boolean } = {}): void {
	if (options.assertive) assertive = stamp(text);
	else polite = stamp(text);
}

export const live = {
	get polite(): string {
		return polite;
	},
	get assertive(): string {
		return assertive;
	}
};
