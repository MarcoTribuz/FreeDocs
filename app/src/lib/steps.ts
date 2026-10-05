/**
 * Which step each mode has, and which of them may be reached. Pure, so it can be
 * tested in Node, and so the rule has one home: `+page.svelte` derives the
 * current step from it and the rail draws from it.
 *
 * Reachability is derived, never stored. A step the user cannot be on cannot be
 * the current one, and two sources for that fact is a window showing Review with
 * nothing to review.
 */

import type { Finding, KeptSpan } from './engine';

export type Step = 'file' | 'review' | 'result';

/**
 * Which direction the window is working in. A mode rather than a fourth step:
 * a document comes back from a model days after the scrub, so restoring is not
 * the continuation of a wizard. Pasted text is a third mode because its first
 * step is a text area rather than a file picker, and everything after it is the
 * scrub's own review.
 */
export type Mode = 'scrub' | 'restore' | 'text';

export const ORDER: Record<Mode, Step[]> = {
	scrub: ['file', 'review', 'result'],
	restore: ['file', 'result'],
	text: ['file', 'review', 'result']
};

/** What the reachability of a step depends on, and nothing else. */
export interface Progress {
	files: number;
	results: number;
	restored: boolean;
	textScrubbed: boolean;
}

export function reachable(mode: Mode, state: Progress): Record<Step, boolean> {
	if (mode === 'restore') {
		// No review step: the decisions were made by the scrub that wrote the key.
		return { file: true, review: false, result: state.restored };
	}
	if (mode === 'text') {
		return { file: true, review: state.files > 0, result: state.textScrubbed };
	}
	return { file: true, review: state.files > 0, result: state.results > 0 };
}

/**
 * The span a "keep this one" sends, built from the engine's own offsets.
 *
 * Moved out of the component so it can be tested, because the mistake it
 * prevents looks like nothing at all: the highlighter slices with UTF-16
 * offsets and the engine counts code points, so a span built from the rendering
 * copy describes other characters once the text contains an emoji - and pasted
 * text is where emoji are.
 */
export function keptSpanFor(path: string, finding: Finding): KeptSpan {
	return { start: finding.start, end: finding.end, text: finding.text, path };
}
