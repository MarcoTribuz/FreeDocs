import { describe, expect, it } from 'vitest';
import type { Finding, ScrubResult } from './engine';
import { survivors, writtenWithLeaks } from './leaks';

const finding = (start: number, end: number, text: string): Finding => ({
	start,
	end,
	entity: 'PERSON',
	action: 'redact',
	confidence: 0.9,
	detector: 'gliner2:person',
	layer: 'L2',
	country: null,
	part: 'word/document.xml',
	text
});

const refused: ScrubResult = {
	path: '/tmp/a.docx',
	ok: false,
	error: {
		code: 3,
		message: 'verification found 2 value(s) still present',
		data: {
			leaks: 2,
			detail: [
				{ entity: 'PERSON', detector: 'gliner2:person', occurrences: 3, allowed: 0, start: 10, end: 21 },
				{ entity: 'ORGANISATION', detector: 'gliner2:organization', occurrences: 1, allowed: 0, start: 99, end: 103 }
			]
		}
	}
};

describe('survivors', () => {
	it('names a survivor from the preview finding at the same offsets', () => {
		const found = survivors(refused, [finding(10, 21, 'Mario Rossi'), finding(30, 35, 'Bianchi')]);
		expect(found[0]).toEqual({
			entity: 'PERSON',
			detector: 'gliner2:person',
			occurrences: 3,
			value: 'Mario Rossi'
		});
	});

	it('leaves the value null rather than guessing when no finding matches', () => {
		expect(survivors(refused, [finding(10, 21, 'Mario Rossi')])[1].value).toBeNull();
	});

	it('reads a written report the same way', () => {
		const written: ScrubResult = {
			path: '/tmp/a.docx',
			ok: true,
			report: {
				verification: {
					passed: false,
					values_checked: 4,
					values_too_short_to_check: 0,
					leaks: [{ entity: 'PERSON', detector: 'x', occurrences: 1, start: 10, end: 21 }]
				}
			} as ScrubResult['report']
		};
		expect(survivors(written, [finding(10, 21, 'Mario Rossi')])[0].value).toBe('Mario Rossi');
		expect(writtenWithLeaks(written)).toBe(true);
	});

	it('has nothing to say about a failure that is not a leak', () => {
		const other: ScrubResult = { path: '/tmp/a.pdf', ok: false, error: { code: 7, message: 'scan' } };
		expect(survivors(other)).toEqual([]);
		expect(writtenWithLeaks(other)).toBe(false);
	});
});
