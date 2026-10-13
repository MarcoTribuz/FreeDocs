/**
 * What the first-run list offers for each dependency. PURE, so it is tested.
 *
 * Holds no rules about Tesseract or about package managers: every input is a
 * field the engine published. What lives here is only the mapping from those
 * answers to which control a row shows, pushed out of the component for the
 * reason `highlight.ts` exists - a component too dumb to be worth testing.
 */
import type { Capabilities } from './engine';

/**
 * The OCR row's control.
 *
 * `install` where the engine said it will run the line itself, `copy` where it
 * named a line but will not run it (it needs elevation), `locate` where it found
 * no package manager at all. Locate and Check again are offered under all three:
 * a Tesseract can be on the machine where none of this looked.
 */
export type OcrAction = 'ready' | 'install' | 'copy' | 'locate';

type OcrCaps = Pick<Capabilities, 'ocr_available' | 'ocr_install_command' | 'ocr_installable'>;

export function ocrAction(caps: OcrCaps): OcrAction {
	if (caps.ocr_available) return 'ready';
	if (!caps.ocr_install_command) return 'locate';
	return caps.ocr_installable ? 'install' : 'copy';
}

/**
 * Whether the first-run screen should open for the dependencies alone.
 *
 * The model has its own reason to open the screen and keeps it. This is the
 * other case: the model is here, OCR is not, and the user has not yet seen the
 * list. Seen once is enough - a machine that never reads scans is a normal
 * machine, and a screen that reopened every launch would train people to close
 * it unread. The diagnostics pane and the file step still say what is missing.
 */
export function offerSetup(
	caps: Pick<Capabilities, 'ocr_available'> | null,
	seen: boolean
): boolean {
	return !seen && caps !== null && !caps.ocr_available;
}
