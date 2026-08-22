import type { Finding, Part } from './engine';

/**
 * Turning an extracted document plus its findings into something renderable.
 *
 * Pure on purpose, and the only file in the frontend with unit tests: this is
 * where an off-by-one is silent and serious. A wrong offset does not throw — it
 * highlights the wrong characters, and then `keep_spans` sends those wrong
 * offsets back and the engine either refuses the decision as stale or keeps
 * whatever moved into that range. Neither failure looks like a bug on screen.
 *
 * Nothing here decides anything about confidentiality. It is arithmetic over
 * spans the engine already resolved.
 */

export interface Block {
	index: number;
	/** The page, sheet or slide this came from. Empty for separator text. */
	part: string;
	/** UTF-16 offsets into the document text. */
	start: number;
	end: number;
	/** Indices into the findings array, in document order. */
	findings: number[];
}

export interface Segment {
	text: string;
	/** Index into the findings array, or -1 for untouched text. */
	finding: number;
}

/**
 * Translate the engine's code-point offsets into UTF-16 offsets.
 *
 * Python counts code points; JavaScript counts UTF-16 code units. Inside the
 * BMP the two agree and there is nothing to do, which is almost always. With an
 * emoji, a rare CJK character or a mathematical letter, they diverge by the
 * number of surrogate pairs before the offset — and then every highlight after
 * the first such character is drawn in the wrong place, and every span sent back
 * describes text the user never saw.
 *
 * Returns null when there is nothing to correct, so the common case costs one
 * regex test. The detection is deliberately not `[...text]`: spreading a 400 000
 * character string allocates 400 000 one-character strings to answer a yes/no
 * question.
 */
export function codePointOffsets(text: string): {
	toUtf16: (offset: number) => number;
	toCodePoint: (offset: number) => number;
} | null {
	if (!/[\uD800-\uDBFF]/.test(text)) return null;

	// The code-point index of each surrogate pair, ascending.
	const pairs: number[] = [];
	let cp = 0;
	for (let i = 0; i < text.length; ) {
		const code = text.charCodeAt(i);
		const low = i + 1 < text.length ? text.charCodeAt(i + 1) : 0;
		// A high surrogate with no low surrogate after it is a lone surrogate: one
		// code point, one code unit, and counting it as a pair would shift every
		// offset after it.
		const wide = code >= 0xd800 && code <= 0xdbff && low >= 0xdc00 && low <= 0xdfff;
		if (wide) pairs.push(cp);
		i += wide ? 2 : 1;
		cp += 1;
	}
	const index = Int32Array.from(pairs);

	/** How many pairs begin strictly before this code-point index. */
	const before = (value: number): number => {
		let lo = 0;
		let hi = index.length;
		while (lo < hi) {
			const mid = (lo + hi) >> 1;
			if (index[mid] < value) lo = mid + 1;
			else hi = mid;
		}
		return lo;
	};

	return {
		toUtf16: (offset) => offset + before(offset),
		toCodePoint: (offset) => {
			// f(c) = c + before(c) is non-decreasing, so the largest c whose UTF-16
			// position is still at or before `offset` is a binary search away.
			let lo = 0;
			let hi = offset;
			while (lo < hi) {
				const mid = (lo + hi + 1) >> 1;
				if (mid + before(mid) <= offset) lo = mid;
				else hi = mid - 1;
			}
			return lo;
		}
	};
}

/**
 * The ranges of the text, part by part, with the gaps between them included.
 *
 * The gaps are the separator text `core/stream.py` inserted between pages,
 * cells and slides. They belong to no part, and they are rendered anyway: an
 * extraction the user cannot see all of is not a preview.
 */
function ranges(text: string, parts: Part[]): { part: string; start: number; end: number }[] {
	const out: { part: string; start: number; end: number }[] = [];
	let cursor = 0;
	for (const part of parts) {
		if (part.start > cursor) out.push({ part: '', start: cursor, end: part.start });
		out.push({ part: part.part, start: Math.max(part.start, cursor), end: part.end });
		cursor = Math.max(cursor, part.end);
	}
	if (cursor < text.length) out.push({ part: '', start: cursor, end: text.length });
	return out.filter((range) => range.end > range.start);
}

function inDocumentOrder(findings: Finding[]): number[] {
	return findings
		.map((_, index) => index)
		.sort(
			(a, b) => findings[a].start - findings[b].start || findings[a].end - findings[b].end
		);
}

/**
 * Cut the document into rendering units.
 *
 * Whole lines, grouped up to `min` characters, never split mid-line and never
 * split across a part: a block is the granularity at which the review pane skips
 * work, and a block straddling two pages cannot carry one page's heading.
 *
 * A finding that would fall off the end **grows the block** instead of being
 * cut. Half a mark is two clickable things where the user sees one value, and
 * the offsets either half would send back describe neither.
 *
 * `min` trades DOM nodes against how much text the browser must lay out to show
 * one finding. 800 puts a 400 000-character document at roughly five hundred
 * blocks.
 */
export function blocks(text: string, parts: Part[], findings: Finding[], min = 800): Block[] {
	const order = inDocumentOrder(findings);
	const out: Block[] = [];
	let next = 0;
	let cursor = 0;

	for (const range of ranges(text, parts)) {
		if (range.end <= cursor) continue;
		let start = Math.max(cursor, range.start);

		while (start < range.end) {
			let end = start;
			while (end < range.end && end - start < min) {
				const newline = text.indexOf('\n', end);
				end = newline === -1 || newline >= range.end ? range.end : newline + 1;
			}

			const ids: number[] = [];
			while (next < order.length && findings[order[next]].start < end) {
				const id = order[next];
				next += 1;
				// Already inside an earlier block, which grew to contain it. Blocks
				// are contiguous, so there is nowhere else it could have gone.
				if (findings[id].start < start) continue;
				ids.push(id);
				if (findings[id].end > end) end = findings[id].end;
			}

			out.push({ index: out.length, part: range.part, start, end, findings: ids });
			start = end;
			cursor = end;
		}
	}

	if (cursor < text.length) {
		out.push({ index: out.length, part: '', start: cursor, end: text.length, findings: [] });
	}
	return out;
}

/**
 * One block as alternating plain and highlighted pieces.
 *
 * Findings do not overlap by construction: `detect/registry.py` resolves
 * overlaps by layer precedence before anything reaches the wire, and the
 * pipeline's rule is that two edits may never touch the same characters. So an
 * overlap here is a contract violation rather than a case to merge, and the
 * later one is dropped — rendering it would emit some characters twice, and a
 * span sent back for "keep this one" would describe text nobody saw.
 */
export function segment(text: string, block: Block, findings: Finding[]): Segment[] {
	const out: Segment[] = [];
	let cursor = block.start;

	for (const id of block.findings) {
		const { start, end } = findings[id];
		if (start < cursor || end <= start) continue;
		if (start > cursor) out.push({ text: text.slice(cursor, start), finding: -1 });
		out.push({ text: text.slice(start, end), finding: id });
		cursor = end;
	}
	if (cursor < block.end) out.push({ text: text.slice(cursor, block.end), finding: -1 });
	return out;
}

/**
 * Re-assign findings to the blocks that already exist, after a re-inspection.
 *
 * The block layout is a function of the text, and the text does not change when
 * the user excuses one occurrence — the same file is read again. Rebuilding the
 * blocks would throw away every memoised segmentation and the scroll position
 * with it, for a document that is byte-identical.
 *
 * Returns null when a new finding straddles a block boundary, because honouring
 * the old layout would cut that highlight in half. The caller rebuilds. That is
 * rare and worth a rebuild; guessing is not.
 *
 * A block whose findings did not change is returned as the *same object*, which
 * is what lets the caller keep its per-block segmentation cache.
 */
export function rebucket(blocks: Block[], findings: Finding[]): Block[] | null {
	const order = inDocumentOrder(findings);
	let next = 0;
	const out: Block[] = [];

	for (const block of blocks) {
		const ids: number[] = [];
		while (next < order.length && findings[order[next]].start < block.end) {
			const id = order[next];
			if (findings[id].end > block.end) return null;
			ids.push(id);
			next += 1;
		}
		const unchanged =
			ids.length === block.findings.length && ids.every((id, at) => id === block.findings[at]);
		out.push(unchanged ? block : { ...block, findings: ids });
	}

	// A finding past the last block cannot be shown at all, which means the
	// layout does not describe this text.
	return next === order.length ? out : null;
}

/**
 * Move the selection.
 *
 * Pure so the review screen's keyboard map is testable without a DOM — which is
 * the discipline that replaces component tests: push the logic out until the
 * component is too dumb to be worth testing.
 */
export function nextFinding(
	current: number | null,
	count: number,
	delta: number
): number | null {
	if (count === 0) return null;
	if (current === null) return delta > 0 ? 0 : count - 1;
	return Math.min(count - 1, Math.max(0, current + delta));
}
