import type { Finding, Inspection } from './engine';
import { blocks, codePointOffsets, rebucket, segment, type Block, type Segment } from './highlight';

/**
 * What the review pane is looking at, and what the person looking at it chose.
 *
 * Separate from the session because it is all discardable: a selection, a filter,
 * a rendering cache. Nothing here is sent to the engine. The one rule it holds
 * is the one about offsets, and it holds it by construction — see `View.marks`.
 */

export interface View {
	/** The extracted text, or empty when the preview was not requested. */
	text: string;
	/**
	 * The findings with UTF-16 offsets, for slicing this string.
	 *
	 * A *rendering copy*, never sent anywhere. The engine's own code-point
	 * offsets stay in `inspection.findings` at the same index, and that is what a
	 * kept span is built from. Converting back before sending would work too, and
	 * would be one more place to get the arithmetic wrong.
	 */
	marks: Finding[];
	blocks: Block[];
	truncated: boolean;
	shown: number;
}

const views = new WeakMap<Inspection, View>();
const segments = new WeakMap<View, Map<number, Segment[]>>();

/** How big a document has to be before the untouched text is folded away. */
const FOLD_ABOVE_CHARS = 300_000;

export const review = $state({
	/** Index into the inspection's findings, not into the filtered list. */
	selected: null as number | null,
	query: '',
	/** An entity type name, or empty for all of them. */
	filter: '',
	/** Null means "decide from the size of the document". */
	onlyFindings: null as boolean | null,
	/** Blocks the user asked to see inside a folded stretch. */
	expanded: new Set<number>(),
	/** Document or list. Both show the same findings. */
	mode: 'document' as 'document' | 'list'
});

export function resetReview(): void {
	review.selected = null;
	review.query = '';
	review.filter = '';
	review.expanded = new Set();
}

/**
 * The renderable view of one inspection, built once and kept.
 *
 * Keyed on the inspection object rather than on the path: a re-inspection hands
 * back a new object, which is exactly when the view has to be rebuilt. A
 * `WeakMap` so the old ones go when the old inspections do.
 */
export function viewOf(inspection: Inspection, previous?: Inspection): View {
	const existing = views.get(inspection);
	if (existing) return existing;

	const text = inspection.text ?? '';
	const map = codePointOffsets(text);
	const marks = map
		? inspection.findings.map((finding) => ({
				...finding,
				start: map.toUtf16(finding.start),
				end: map.toUtf16(finding.end)
			}))
		: inspection.findings;

	// The text does not change when the user excuses an occurrence — the same
	// file is read again — so the block layout can be reused, and reusing it is
	// what keeps the scroll position and the segmentation cache. `rebucket`
	// refuses when a new finding would be cut by the old layout.
	const before = previous ? views.get(previous) : undefined;
	const reused =
		before && before.text === text ? rebucket(before.blocks, marks) : null;

	const view: View = {
		text,
		marks,
		blocks: reused ?? blocks(text, inspection.parts ?? [], marks),
		truncated: inspection.text_truncated === true,
		shown: inspection.text_end ?? text.length
	};

	if (reused && before) {
		// Carry over the segmentation of every block `rebucket` handed back
		// unchanged. Those are the same object, so the cache is still valid.
		const old = segments.get(before);
		if (old) {
			const kept = new Map<number, Segment[]>();
			view.blocks.forEach((block, at) => {
				if (block === before.blocks[at] && old.has(block.index)) {
					kept.set(block.index, old.get(block.index)!);
				}
			});
			segments.set(view, kept);
		}
	}

	views.set(inspection, view);
	return view;
}

/**
 * The last inspection seen for each path, so a re-inspection can reuse the
 * layout of the one before it. Held here rather than in the component: it is
 * bookkeeping about identity, and a component that re-mounts would forget it and
 * rebuild every block for a document that did not change.
 */
const lastByPath = new Map<string, Inspection>();

export function viewFor(path: string, inspection: Inspection): View {
	const view = viewOf(inspection, lastByPath.get(path));
	lastByPath.set(path, inspection);
	return view;
}

/** One block's alternating plain and marked pieces, computed once. */
export function segmentsOf(view: View, block: Block): Segment[] {
	let cache = segments.get(view);
	if (!cache) segments.set(view, (cache = new Map()));
	const hit = cache.get(block.index);
	if (hit) return hit;
	const made = segment(view.text, block, view.marks);
	cache.set(block.index, made);
	return made;
}

/**
 * Whether to fold the stretches with nothing in them.
 *
 * On by default above `FOLD_ABOVE_CHARS`, because that bounds the rendered DOM
 * by the number of *findings* rather than by the size of the document — and it
 * matches the task: the user is reviewing decisions, not proofreading.
 */
export function folding(view: View): boolean {
	return review.onlyFindings ?? view.text.length > FOLD_ABOVE_CHARS;
}

/** Which findings the filter and the search leave visible, as indices. */
export function visibleFindings(inspection: Inspection): number[] {
	const query = review.query.trim().toLowerCase();
	return inspection.findings
		.map((_, index) => index)
		.filter((index) => {
			const finding = inspection.findings[index];
			if (review.filter && finding.entity !== review.filter) return false;
			if (query && !finding.text.toLowerCase().includes(query)) return false;
			return true;
		});
}

/** Every entity type present, so the filter offers only what is there. */
export function typesPresent(inspection: Inspection): string[] {
	return [...new Set(inspection.findings.map((finding) => finding.entity))].sort();
}
