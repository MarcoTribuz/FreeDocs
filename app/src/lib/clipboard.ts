/**
 * Put text on the clipboard, saying whether it worked.
 *
 * **No new Tauri permission and no CSP change.** `default-src 'self'` governs
 * what the page may *fetch*; the clipboard is not a fetch directive, so nothing
 * in `tauri.conf.json` moves. `@tauri-apps/plugin-clipboard-manager` was refused
 * for what it costs beside that: an npm dependency, a Cargo dependency, an entry
 * in the capability file that was deliberately narrowed, and a second exit from
 * the webview — for a copy button.
 *
 * Two routes rather than one, and the fallback is not superstition.
 * `navigator.clipboard.writeText` needs a secure context and a user gesture, and
 * the Tauri origins should qualify — `tauri://localhost` has a localhost host and
 * Windows' `http://tauri.localhost` ends in `.localhost`, which the specification
 * calls potentially trustworthy. But that is a webview property this project has
 * only ever verified on macOS, and its own rule is to say "builds" and not
 * "works" for the other two. So the older route stays.
 *
 * The real last resort needs no code at all: the element this copies from is
 * selectable text, and always was.
 */
export async function copyText(text: string): Promise<boolean> {
	try {
		if (navigator.clipboard?.writeText) {
			await navigator.clipboard.writeText(text);
			return true;
		}
	} catch {
		// Fall through to the older route rather than reporting failure: a
		// rejected promise here is a permissions decision, not a broken clipboard.
	}
	return legacyCopy(text);
}

/**
 * `document.execCommand('copy')`, which is deprecated and still the only thing
 * that works without a secure context.
 *
 * The textarea is positioned rather than hidden: `display: none` and
 * `visibility: hidden` both make the selection empty, so the copy silently
 * succeeds with nothing on the clipboard.
 */
function legacyCopy(text: string): boolean {
	try {
		const field = document.createElement('textarea');
		field.value = text;
		field.setAttribute('readonly', '');
		field.style.position = 'fixed';
		field.style.top = '-1000px';
		document.body.appendChild(field);
		field.select();
		const copied = document.execCommand('copy');
		document.body.removeChild(field);
		return copied;
	} catch {
		return false;
	}
}
