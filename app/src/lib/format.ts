/**
 * Turning wire values into words.
 *
 * The window used to render the engine's identifiers raw: `it` in the
 * placeholder-language menu, `CH` on the country chips. Those are correct on the
 * wire and useless on screen, and the mapping is presentation, so it lives here
 * rather than being asked of Python.
 */

/**
 * Names for a language or region tag, in the reader's own language.
 *
 * `Intl.DisplayNames` arrived in Safari 14.1 and `minimumSystemVersion` is
 * 11.0, so a webview one point release older is possible. It is guarded rather
 * than assumed: the fallback is the code the engine sent, which is what the
 * window showed before this file existed. Degrading to the old behaviour is
 * acceptable; throwing while rendering a chip list is not.
 */
function displayName(code: string, type: 'language' | 'region', locale: string): string {
	try {
		const names = new Intl.DisplayNames([locale], { type, fallback: 'code' });
		return names.of(type === 'region' ? code.toUpperCase() : code) ?? code;
	} catch {
		return type === 'region' ? code.toUpperCase() : code;
	}
}

export function countryName(code: string, locale = 'en'): string {
	return displayName(code, 'region', locale);
}

export function languageName(code: string, locale = 'en'): string {
	return displayName(code, 'language', locale);
}

/** The filename, on either platform's separator. */
export function basename(path: string): string {
	return path.split(/[\\/]/).pop() ?? path;
}

/**
 * A character count, grouped the way the reader's locale groups numbers.
 *
 * `412003 characters` is a number nobody reads; `412,003` is.
 */
export function count(value: number, locale = 'en'): string {
	return new Intl.NumberFormat(locale).format(value);
}

/**
 * What a confidence threshold means, in words.
 *
 * The bands are the engine's, from `detect/validators.py`: STRONG_CHECK 0.55,
 * MEDIUM_CHECK 0.5, WEAK_CHECK 0.45, each measured by running the validator
 * against 20 000 format-plausible values. The words are the window's, and they
 * exist because "0.50" is not something a screen reader can usefully say and
 * not something a person can act on.
 */
export function confidenceBand(value: number): string {
	if (value <= 0) return 'everything, including the weakest rules';
	if (value < 0.45) return 'below every rule: nothing is filtered out';
	if (value < 0.5) return 'weak rules included';
	if (value < 0.55) return 'weak rules need a keyword nearby';
	if (value < 0.9) return 'only checksum-strong rules and the model';
	return 'almost nothing but a confirmed checksum';
}
