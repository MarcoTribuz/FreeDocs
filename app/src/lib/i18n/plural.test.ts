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
		errorInFile: { file: 'contratto.docx', message: 'boom' },
		stepAnnounce: { position: 2, total: 3, name: 'Review' },
		removeFile: { file: 'contratto.docx' },
		reviewOf: { file: 'contratto.docx' },
		findingCount: { count: 12 },
		documentLabel: { file: 'contratto.docx' },
		markName: { entity: 'Person', action: 'will be removed', kept: false },
		skippedParagraphs: { count: 48 },
		previewTruncated: { shown: 500000, total: 812345 },
		foundBy: { detector: 'it_codice_fiscale' },
		keepEveryOne: { entity: 'Place' },
		verificationPassedHint: { checked: 9 },
		rulesSilenced: { count: 7 },
		stageOf: { name: 'reading the document', index: 2, count: 6 },
		stagePages: { done: 3, of: 12 },
		placeholderExample: { example: '[PERSON_1]' },
		modeAnnounce: { name: 'Put back' },
		keyFileNeedsPassphrase: { min: 8 },
		restoredSummary: { values: 3, occurrences: 7 },
		restoreIncomplete: { count: 2 },
		announceRestored: { count: 5 },
		announceRestoredWithProblems: { count: 1 },
		engineBuiltOn: { when: '23 August 2026 at 16:34' },
		termsNeedsPassphrase: { min: 8 },
		termsCount: { count: 40 },
		termsRemoveOne: { value: 'Nordwind Holding' },
		termsImportedTitle: { added: 38, skipped: 2 },
		termsDeleteSource: { file: 'clients.csv' },
		termsUnlocked: { count: 40 },
		termsAdded: { count: 1 },
		termsRemoved: { count: 1 },
		termsImportedAnnounce: { count: 38 },
		termsExportedAnnounce: { count: 40 },
		termsMatched: { matched: 3, loaded: 50 },
		textCount: { count: 1204 },
		textTooLong: { max: 2000000 },
		announceTextScrubbed: { count: 3 }
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

		it(`${name} words a count of one as a singular`, () => {
			// The plural-rule tests above cover `Intl.PluralRules`; these are the
			// messages that branch on the count themselves. French puts zero in the
			// singular and the other three do not, which is why one is asserted here
			// and zero is not.
			const ones = {
				restoredSummary: catalogue.restoredSummary({ values: 1, occurrences: 1 }),
				restoreIncomplete: catalogue.restoreIncomplete({ count: 1 }),
				announceRestored: catalogue.announceRestored({ count: 1 }),
				announceRestoredWithProblems: catalogue.announceRestoredWithProblems({ count: 1 }),
				termsCount: catalogue.termsCount({ count: 1 }),
				termsImportedTitle: catalogue.termsImportedTitle({ added: 1, skipped: 1 }),
				termsMatched: catalogue.termsMatched({ matched: 1, loaded: 1 }),
				textCount: catalogue.textCount({ count: 1 }),
				announceTextScrubbed: catalogue.announceTextScrubbed({ count: 1 })
			};
			for (const [key, produced] of Object.entries(ones)) {
				expect(produced, `${name}.${key}`).toBeTruthy();
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

		it(`${name} names every stage the engine can report`, () => {
			// Stage names are enumerable on the wire, so they are translated rather
			// than quoted — and a stage with no name would render as its wire string
			// in the middle of a sentence.
			expect(Object.keys(catalogue.stage).sort()).toEqual(Object.keys(en.stage).sort());
			for (const [key, produce] of Object.entries(catalogue.stage)) {
				expect(produce(), `${name}.stage.${key}`).toBeTruthy();
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
