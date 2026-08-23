import { describe, expect, it } from 'vitest';
import type { Finding, Part } from './engine';
import { blocks, codePointOffsets, nextFinding, rebucket, segment } from './highlight';

/**
 * The offset arithmetic, which is the one thing in this frontend that fails
 * silently. A wrong span does not throw: it highlights the wrong characters and
 * then sends those offsets back to the engine.
 */

function finding(start: number, end: number, text: string): Finding {
	return {
		start,
		end,
		text,
		entity: 'PERSON',
		action: 'redact',
		confidence: 1,
		detector: 'test',
		layer: 'L1',
		country: null,
		part: ''
	};
}

function onePart(text: string, name = 'page:1'): Part[] {
	return [{ part: name, start: 0, end: text.length }];
}

/** Every character of the document appears exactly once, in order. */
function reassemble(text: string, built: ReturnType<typeof blocks>, found: Finding[]): string {
	return built.map((block) => segment(text, block, found).map((s) => s.text).join('')).join('');
}

describe('blocks', () => {
	it('handles an empty document', () => {
		expect(blocks('', [], [])).toEqual([]);
	});

	it('covers the whole text when there are no findings', () => {
		const text = 'una riga\naltra riga\n';
		const built = blocks(text, onePart(text), []);
		expect(reassemble(text, built, [])).toBe(text);
	});

	it('renders text that no part claims', () => {
		// Separator text between two pages belongs to neither, and dropping it
		// would show the user a document with holes in it.
		const text = 'pagina uno\n\npagina due';
		const parts: Part[] = [
			{ part: 'page:1', start: 0, end: 10 },
			{ part: 'page:2', start: 12, end: text.length }
		];
		expect(reassemble(text, blocks(text, parts, []), [])).toBe(text);
	});

	it('keeps a finding at the very start and one at the very end', () => {
		const text = 'Rossi paga a Bianchi';
		const found = [finding(0, 5, 'Rossi'), finding(13, 20, 'Bianchi')];
		const built = blocks(text, onePart(text), found);
		const marked = built.flatMap((block) =>
			segment(text, block, found).filter((s) => s.finding !== -1)
		);
		expect(marked.map((s) => s.text)).toEqual(['Rossi', 'Bianchi']);
	});

	it('grows a block rather than cutting a finding in half', () => {
		// Half a mark is two clickable things where the user sees one value, and
		// neither half's offsets describe the value.
		const text = 'a'.repeat(30) + '\n' + 'Mario Rossi' + '\n' + 'b'.repeat(30);
		const found = [finding(28, 36, text.slice(28, 36))];
		const built = blocks(text, onePart(text), found, 10);
		const owner = built.find((block) => block.findings.length > 0);
		expect(owner).toBeDefined();
		expect(owner!.start).toBeLessThanOrEqual(28);
		expect(owner!.end).toBeGreaterThanOrEqual(36);
		expect(reassemble(text, built, found)).toBe(text);
	});

	it('keeps a finding that overruns the last part', () => {
		const text = 'Mario Rossi e altro';
		const parts: Part[] = [{ part: 'page:1', start: 0, end: 8 }];
		const found = [finding(0, 11, 'Mario Rossi')];
		const built = blocks(text, parts, found, 4);
		expect(reassemble(text, built, found)).toBe(text);
		expect(built.some((block) => block.findings.includes(0))).toBe(true);
	});

	it('emits every character exactly once when findings overlap', () => {
		// A contract violation — the registry resolves overlaps before the wire —
		// so the later one is dropped rather than rendered twice.
		const text = 'Mario Rossi';
		const found = [finding(0, 11, text), finding(6, 11, 'Rossi')];
		const built = blocks(text, onePart(text), found);
		expect(reassemble(text, built, found)).toBe(text);
	});

	it('assigns every finding to exactly one block', () => {
		const text = Array.from({ length: 40 }, (_, i) => `riga ${i} Mario Rossi`).join('\n');
		const found: Finding[] = [];
		for (let at = text.indexOf('Mario'); at !== -1; at = text.indexOf('Mario', at + 1)) {
			found.push(finding(at, at + 11, 'Mario Rossi'));
		}
		const built = blocks(text, onePart(text), found, 80);
		const assigned = built.flatMap((block) => block.findings);
		expect(assigned).toEqual([...assigned].sort((a, b) => a - b));
		expect(new Set(assigned).size).toBe(found.length);
	});

	it('stays linear on a large document', () => {
		// Pins the complexity, which is the only performance property that can be
		// measured outside a browser.
		const line = 'Il cliente Mario Rossi ha pagato la fattura di marzo.\n';
		const text = line.repeat(8000); // ~424 000 characters
		const found: Finding[] = [];
		for (let at = text.indexOf('Mario'); at !== -1; at = text.indexOf('Mario', at + 1)) {
			found.push(finding(at, at + 11, 'Mario Rossi'));
			if (found.length === 2000) break;
		}
		const built = blocks(text, onePart(text), found);
		expect(built.length).toBeGreaterThan(400);
		expect(built.length).toBeLessThan(1200);
		expect(built[0].start).toBe(0);
		expect(built[built.length - 1].end).toBe(text.length);
	});
});

describe('rebucket', () => {
	it('returns the identical object for a block whose findings did not change', () => {
		// This is what preserves the per-block segmentation cache and the scroll
		// position across a re-inspection of a byte-identical document.
		const text = 'Mario Rossi\nAnna Bianchi\n';
		const found = [finding(0, 11, 'Mario Rossi'), finding(12, 24, 'Anna Bianchi')];
		const built = blocks(text, onePart(text), found, 12);
		const again = rebucket(built, found);
		expect(again).not.toBeNull();
		again!.forEach((block, at) => expect(block).toBe(built[at]));
	});

	it('produces a new object for a block whose findings changed', () => {
		const text = 'Mario Rossi\nAnna Bianchi\n';
		const found = [finding(0, 11, 'Mario Rossi'), finding(12, 24, 'Anna Bianchi')];
		const built = blocks(text, onePart(text), found, 12);
		const fewer = rebucket(built, [found[0]]);
		expect(fewer).not.toBeNull();
		expect(fewer!.some((block, at) => block !== built[at])).toBe(true);
	});

	it('refuses a layout a new finding would be cut by', () => {
		const text = 'Mario Rossi\nAnna Bianchi\n';
		const built = blocks(text, onePart(text), [], 12);
		// Spans the boundary the old blocks were cut on.
		expect(rebucket(built, [finding(6, 17, 'Rossi\nAnna')])).toBeNull();
	});
});

describe('codePointOffsets', () => {
	it('returns null for text with nothing outside the BMP', () => {
		// The fast path has to stay fast: this is almost every document.
		expect(codePointOffsets('Mario Rossi, Zürich, 8000')).toBeNull();
	});

	it('round-trips across an emoji', () => {
		const text = 'ok 😀 Mario';
		const map = codePointOffsets(text);
		expect(map).not.toBeNull();
		// Python counts "Mario" from code point 5; the same characters start at
		// UTF-16 index 6, because the emoji before them is two code units.
		expect(map!.toUtf16(5)).toBe(6);
		expect(text.slice(map!.toUtf16(5), map!.toUtf16(10))).toBe('Mario');
		expect(map!.toCodePoint(6)).toBe(5);
	});

	it('round-trips across two adjacent astral characters', () => {
		const text = '😀😀Mario';
		const map = codePointOffsets(text)!;
		expect(map.toUtf16(2)).toBe(4);
		expect(text.slice(map.toUtf16(2), map.toUtf16(7))).toBe('Mario');
		expect(map.toCodePoint(4)).toBe(2);
	});

	it('lands on the start of a surrogate pair, never inside it', () => {
		const text = 'a😀b';
		const map = codePointOffsets(text)!;
		expect(map.toUtf16(1)).toBe(1);
		// Offset 2 is the low surrogate: there is no code point there, so the
		// answer is the code point that owns it.
		expect(map.toCodePoint(2)).toBe(1);
		expect(map.toCodePoint(3)).toBe(2);
	});

	it('does not count a lone high surrogate as a pair', () => {
		// Invalid input, but reachable: OCR and PDF extraction produce odd bytes.
		// Counting it would shift every offset after it.
		const text = 'a\uD800b Mario';
		const map = codePointOffsets(text);
		if (map) expect(map.toUtf16(4)).toBe(4);
	});
});

describe('nextFinding', () => {
	it('has nowhere to go in an empty document', () => {
		expect(nextFinding(null, 0, 1)).toBeNull();
		expect(nextFinding(3, 0, -1)).toBeNull();
	});

	it('starts at either end depending on direction', () => {
		expect(nextFinding(null, 5, 1)).toBe(0);
		expect(nextFinding(null, 5, -1)).toBe(4);
	});

	it('stops at the ends rather than wrapping', () => {
		// Wrapping means a user holding the key jumps from the last value back to
		// the first without noticing they have been round once.
		expect(nextFinding(4, 5, 1)).toBe(4);
		expect(nextFinding(0, 5, -1)).toBe(0);
	});
});
