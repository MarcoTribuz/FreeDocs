import { describe, expect, it } from 'vitest';
import { offerSetup, ocrAction } from './setup';

const brew = 'brew install tesseract';

describe('ocrAction', () => {
	it('offers nothing to do while OCR works, whatever else the engine sent', () => {
		expect(
			ocrAction({ ocr_available: true, ocr_install_command: brew, ocr_installable: true })
		).toBe('ready');
	});

	it('offers Install only where the engine said it will run the line', () => {
		expect(
			ocrAction({ ocr_available: false, ocr_install_command: brew, ocr_installable: true })
		).toBe('install');
	});

	it('offers Copy for a line that needs elevation', () => {
		expect(
			ocrAction({
				ocr_available: false,
				ocr_install_command: 'sudo apt install x',
				ocr_installable: false
			})
		).toBe('copy');
	});

	it('never offers Install without a line to show', () => {
		// A button that runs something the user could not read is the one shape refused.
		expect(
			ocrAction({ ocr_available: false, ocr_install_command: null, ocr_installable: true })
		).toBe('locate');
	});

	it('reads a sidecar older than the fields as "no package manager"', () => {
		expect(ocrAction({ ocr_available: false })).toBe('locate');
	});
});

describe('offerSetup', () => {
	it('opens once for a machine without OCR', () => {
		expect(offerSetup({ ocr_available: false }, false)).toBe(true);
		expect(offerSetup({ ocr_available: false }, true)).toBe(false);
	});

	it('never opens for a machine that has everything', () => {
		expect(offerSetup({ ocr_available: true }, false)).toBe(false);
	});

	it('does not open before the engine has answered', () => {
		expect(offerSetup(null, false)).toBe(false);
	});
});
