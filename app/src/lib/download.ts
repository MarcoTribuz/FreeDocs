/**
 * The arithmetic behind the model download's bar. Pure, so it is tested.
 *
 * The engine reports bytes and nothing else; the time left is worked out here
 * from the rate actually observed. It is presentation over the engine's numbers,
 * not a rule, and it says nothing until there is a rate to say it from - a
 * remaining time guessed in the first second is the number that makes people
 * close a window.
 */

export interface Sample {
	/** Milliseconds, from any monotonic clock. */
	at: number;
	done: number;
}

/** How far back the rate is measured. Long enough to smooth a burst, short
 * enough to follow a connection that changed speed. */
export const WINDOW_MS = 10_000;

/** No estimate until the samples span this long. */
export const SETTLE_MS = 3_000;

export type Eta = { minutes: number } | 'under-minute' | null;

/** Keep the samples inside the window, plus the newest one. */
export function record(samples: Sample[], next: Sample): Sample[] {
	// A count that went backwards is a new attempt, not negative speed: what was
	// measured before it describes a transfer that no longer exists.
	if (samples.some((sample) => sample.done > next.done)) return [next];
	const kept = samples.filter((sample) => next.at - sample.at <= WINDOW_MS && sample.at <= next.at);
	return [...kept, next];
}

export function eta(samples: Sample[], of: number): Eta {
	if (samples.length < 2) return null;
	const first = samples[0];
	const last = samples[samples.length - 1];
	const span = last.at - first.at;
	const moved = last.done - first.done;
	if (span < SETTLE_MS || moved <= 0) return null;
	const remaining = Math.max(0, of - last.done);
	const seconds = remaining / (moved / (span / 1000));
	if (seconds < 60) return 'under-minute';
	return { minutes: Math.ceil(seconds / 60) };
}

/** Bytes as whole megabytes in the reader's locale: "412 MB", "412 Mo". */
export function megabytes(bytes: number, locale: string): string {
	return new Intl.NumberFormat(locale, {
		style: 'unit',
		unit: 'megabyte',
		maximumFractionDigits: 0
	}).format(bytes / 1_000_000);
}
