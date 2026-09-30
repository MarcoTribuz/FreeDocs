import { describe, expect, it } from 'vitest';
import type { Finding } from './engine';
import { ORDER, keptSpanFor, reachable } from './steps';

const nothing = { files: 0, results: 0, restored: false, textScrubbed: false };

describe('text mode', () => {
	it('has the scrub steps, file first', () => {
		expect(ORDER.text).toEqual(['file', 'review', 'result']);
	});

	it('reaches review once a paste was inspected, and result once it was scrubbed', () => {
		expect(reachable('text', nothing)).toEqual({ file: true, review: false, result: false });
		expect(reachable('text', { ...nothing, files: 1 })).toMatchObject({ review: true, result: false });
		expect(reachable('text', { ...nothing, files: 1, textScrubbed: true }).result).toBe(true);
	});

	it('does not reach a result from a file scrub', () => {
		expect(reachable('text', { ...nothing, files: 1, results: 3 }).result).toBe(false);
	});
});

describe('the other modes', () => {
	it('restoring never reaches review', () => {
		expect(reachable('restore', { ...nothing, files: 4, restored: true })).toEqual({
			file: true,
			review: false,
			result: true
		});
	});

	it('scrubbing reaches result only with results', () => {
		expect(reachable('scrub', { ...nothing, files: 1, textScrubbed: true }).result).toBe(false);
		expect(reachable('scrub', { ...nothing, files: 1, results: 1 }).result).toBe(true);
	});
});

describe('keptSpanFor', () => {
	it('sends the engine offsets past an emoji, not the UTF-16 ones', () => {
		// "😀 Mario" - the engine says 2..7 (code points); UTF-16 would say 3..8.
		const finding: Finding = {
			start: 2,
			end: 7,
			entity: 'PERSON',
			action: 'redact',
			confidence: 1,
			detector: 'human',
			layer: 'H',
			country: null,
			part: 'pasted.txt',
			text: 'Mario'
		};
		expect(keptSpanFor('pasted.txt', finding)).toEqual({
			start: 2,
			end: 7,
			text: 'Mario',
			path: 'pasted.txt'
		});
	});
});
