import { describe, expect, it } from 'vitest';
import { plural } from './plural';
import { de } from './de';
import { en } from './en';
import { fr } from './fr';
import { it as italian } from './it';
import type { Messages } from './messages';

describe('plural', () => {
	it('puts zero in the singular in French and in the plural everywhere else', () => {
		// The whole justification for this helper. "0 valeur trouvée" is correct
		// French; "0 valeurs trouvées" is not, and the "(s)" suffix could not
		// express the difference at all.
		const forms = { one: '{n} valeur', other: '{n} valeurs' };
		expect(plural('fr', 0, forms)).toBe('0 valeur');
		expect(plural('en', 0, forms)).toBe('0 valeurs');
		expect(plural('it', 0, forms)).toBe('0 valeurs');
		expect(plural('de', 0, forms)).toBe('0 valeurs');
	});

	it('selects the singular only for one', () => {
		const forms = { one: '{n} file', other: '{n} files' };
		for (const locale of ['en', 'it', 'de', 'fr']) {
			expect(plural(locale, 1, forms)).toBe('1 file');
			for (const n of [2, 5, 11, 21, 101]) {
				expect(plural(locale, n, forms)).toBe(`${n} files`);
			}
		}
	});

	it('groups the number the way the locale groups numbers', () => {
		expect(plural('en', 12345, { other: '{n} x' })).toBe('12,345 x');
		expect(plural('de', 12345, { other: '{n} x' })).toBe('12.345 x');
	});

	it('replaces every occurrence of the placeholder', () => {
		expect(plural('en', 2, { other: '{n} of {n}' })).toBe('2 of 2');
	});

	it('falls back to other when a locale never selects the form given', () => {
		expect(plural('it', 0, { zero: 'nessuno', other: '{n} valori' })).toBe('0 valori');
	});
});

describe('the catalogues', () => {
	const catalogues: [string, Messages][] = [
		['en', en],
		['it', italian],
		['de', de],
		['fr', fr]
	];

	/**
	 * Plausible arguments for every message that takes some.
	 *
	 * The types already reject a missing key, a misspelled extra one and a wrong
	 * argument shape — `satisfies Messages` on an object literal does all three —
	 * so there is no runtime key-set test here: it would be testing the type
	 * checker. What types cannot catch is an empty string left by accident or a
	 * plural whose `other` form is still a placeholder, and that is what this is.
	 */
	const args: Record<string, unknown> = {
		engineVersion: { version: '0.1.0' },
		reviewNoModelsAt: { host: 'http://127.0.0.1:11434' },
		reviewModelsAvailable: { count: 2 },
		reviewBadge: { model: 'qwen3:latest' },
		confidenceBand: { value: 0.5 },
		fileSummary: { format: 'docx', characters: 4210 },
		showValues: { count: 3 },
		tableCaption: { file: 'contratto.docx' },
		stopRemoving: { value: 'Mario Rossi' },
		keepThisOneFor: { value: 'Mario Rossi' },
		keptOnPurpose: { count: 2 },
		scrub: { files: 2 },
		progressFile: { file: 'contratto.docx', index: 1, total: 3 },
		removedAndFlagged: { removed: 4, flagged: 1 },
		announceValuesFound: { file: 'contratto.docx', count: 7 },
		announceFinished: { files: 3 },
		announceFinishedWithFailures: { failed: 1, files: 3 },
		errorUnsupportedFormat: { message: 'no handler for .zip' },
		errorMissingComponent: { message: 'PyMuPDF is required' },
		errorInFile: { file: 'contratto.docx', message: 'boom' }
	};

	for (const [name, catalogue] of catalogues) {
		it(`${name} answers every message with something`, () => {
			for (const [key, value] of Object.entries(catalogue)) {
				if (typeof value !== 'function') continue;
				const produced = (value as (a?: unknown) => string)(args[key]);
				expect(produced, `${name}.${key}`).toBeTruthy();
				expect(produced, `${name}.${key}`).not.toContain('{n}');
				expect(produced, `${name}.${key}`).not.toContain('undefined');
			}
		});

		it(`${name} names every entity type and every action`, () => {
			for (const [key, produce] of Object.entries(catalogue.entity)) {
				expect(produce(), `${name}.entity.${key}`).toBeTruthy();
			}
			for (const [key, produce] of Object.entries(catalogue.action)) {
				expect(produce(), `${name}.action.${key}`).toBeTruthy();
			}
		});

		it(`${name} covers the same entity types as English`, () => {
			// A type missing from one catalogue falls back to the wire name, which
			// is a visible inconsistency rather than a hole — but there is no reason
			// to have one, and this is where it would be noticed.
			expect(Object.keys(catalogue.entity).sort()).toEqual(Object.keys(en.entity).sort());
		});
	}
});
