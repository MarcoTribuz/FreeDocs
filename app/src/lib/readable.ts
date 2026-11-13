/**
 * Turning the engine's structured answers into what a person reads.
 *
 * The engine names hidden content by a closed `kind` and a package path, and a
 * place in the document by a closed `Region`. Both are enums, so by the
 * window's rule they get real words — but the grouping is also a fact worth
 * owning: Word stores revision ids in nine parts, and nine lines saying the
 * same thing is how the reader stops reading the list before the line that
 * matters. Pure, so it is tested without rendering anything.
 */
import type { HiddenItem, Region } from './engine';
import type { Messages } from './i18n/messages';

/** Every `HiddenItem.kind` the engine may send. Pinned by `tests/test_readable.py`. */
export const HIDDEN_KINDS = [
	'metadata',
	'extended-metadata',
	'custom-properties',
	'xmp-metadata',
	'titles-of-parts',
	'hyperlink-cache',
	'page-thumbnail',
	'custom-xml-store',
	'printer-settings',
	'macro-project',
	'data-connections',
	'comments',
	'comment-anchors',
	'comment-ids',
	'comment-metadata',
	'comment-shapes',
	'comment-threading',
	'commenter-directory',
	'revision-markup',
	'revision-save-ids',
	'revision-save-id-table',
	'tracked-deletions',
	'tracked-insertions',
	'hidden-cells',
	'hidden-sheet',
	'hidden-slide',
	'offscreen-shape',
	'pivot-cache',
	'external-link-cache',
	'annotations',
	'embedded-files',
	'form-fields',
	'form-widgets',
	'optional-content-layers',
	'outline'
] as const;
export type HiddenKind = (typeof HIDDEN_KINDS)[number];

export const REGION_KINDS = [
	'body',
	'header',
	'footer',
	'footnote',
	'endnote',
	'comment',
	'link',
	'metadata',
	'sheet',
	'chart',
	'slide',
	'notes',
	'page',
	'other'
] as const;
export type RegionKind = (typeof REGION_KINDS)[number];

export interface HiddenGroup {
	kind: string;
	/** Distinct parts the kind was found in. */
	parts: number;
	items: HiddenItem[];
}

/**
 * One group per kind, in the order the engine reported them.
 *
 * A kind with no words in this build — an engine newer than the window — is
 * still a group: shown as its slug rather than dropped, because a list of what
 * was removed that silently omits a line is worse than one with a slug in it.
 */
export function groupHidden(items: readonly HiddenItem[]): HiddenGroup[] {
	const groups = new Map<string, { parts: Set<string>; items: HiddenItem[] }>();
	for (const item of items) {
		let group = groups.get(item.kind);
		if (!group) groups.set(item.kind, (group = { parts: new Set(), items: [] }));
		group.parts.add(item.part);
		group.items.push(item);
	}
	return [...groups].map(([kind, group]) => ({
		kind,
		parts: group.parts.size,
		items: group.items
	}));
}

export function hiddenLabel(m: Messages, kind: string): string {
	return (m.hiddenKind as Record<string, (() => string) | undefined>)[kind]?.() ?? kind;
}

/** "the header", "page 3", "slide 2" — or the bare kind for an unknown one. */
export function regionLabel(m: Messages, region: Region | undefined): string {
	if (!region) return m.region.other({ number: null });
	const say = (m.region as Record<string, ((a: { number: number | null }) => string) | undefined>)[
		region.kind
	];
	return say?.({ number: region.number }) ?? region.kind;
}
