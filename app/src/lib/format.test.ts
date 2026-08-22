import { describe, expect, it } from 'vitest';
import { basename, countryName, languageName } from './format';

describe('basename', () => {
	it('takes the filename on either platform separator', () => {
		expect(basename('/Users/x/contratto.docx')).toBe('contratto.docx');
		expect(basename('C:\\Users\\x\\contratto.docx')).toBe('contratto.docx');
	});

	it('returns a bare filename unchanged', () => {
		expect(basename('contratto.docx')).toBe('contratto.docx');
	});

	it('does not throw on an empty path', () => {
		expect(basename('')).toBe('');
	});
});

describe('display names', () => {
	it('names a country in the reader language', () => {
		expect(countryName('ch', 'en')).toBe('Switzerland');
		expect(countryName('ch', 'it')).toBe('Svizzera');
	});

	it('names a language in its own language, for the picker', () => {
		expect(languageName('de', 'de')).toBe('Deutsch');
	});

	it('falls back to the code the engine sent when it cannot name one', () => {
		// `Intl.DisplayNames` arrived in Safari 14.1 and the app claims macOS 11,
		// so the fallback is reachable and has to be the code — which is what the
		// window showed before these names existed.
		//
		// Not `ZZ`: that is a *valid* region subtag, and CLDR names it "Unknown
		// Region", which is a name and not a fallback. A code that is not a
		// well-formed subtag at all is what exercises this path.
		expect(countryName('q1', 'en')).toBe('Q1');
	});
});
