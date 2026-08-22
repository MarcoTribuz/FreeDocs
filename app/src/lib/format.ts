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
