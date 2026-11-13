import { describe, expect, it } from 'vitest';
import { groupHidden, hiddenLabel, HIDDEN_KINDS, regionLabel, REGION_KINDS } from './readable';
import { en } from './i18n/en';
import { it as itMessages } from './i18n/it';

const item = (part: string, kind: string, detail = 'x') => ({ part, kind, detail });

describe('groupHidden', () => {
	it('folds the parts of one kind into one line, in the order first seen', () => {
		const groups = groupHidden([
			item('word/document.xml', 'revision-save-ids'),
			item('docProps/core.xml', 'metadata'),
			item('word/header1.xml', 'revision-save-ids'),
			item('word/footer1.xml', 'revision-save-ids')
		]);
		expect(groups.map((g) => [g.kind, g.parts, g.items.length])).toEqual([
			['revision-save-ids', 3, 3],
			['metadata', 1, 1]
		]);
	});

	it('counts a part once when it holds the same kind twice', () => {
		const [group] = groupHidden([
			item('docProps/app.xml', 'extended-metadata', 'company'),
			item('docProps/app.xml', 'extended-metadata', 'template')
		]);
		expect(group.parts).toBe(1);
		expect(group.items).toHaveLength(2);
	});

	it('keeps a kind this window has no words for, as its slug', () => {
		const [group] = groupHidden([item('x', 'from-a-newer-engine')]);
		expect(hiddenLabel(en, group.kind)).toBe('from-a-newer-engine');
	});
});

describe('labels', () => {
	it('has words for every kind and region', () => {
		for (const kind of HIDDEN_KINDS) expect(hiddenLabel(itMessages, kind)).not.toBe(kind);
		for (const kind of REGION_KINDS)
			expect(regionLabel(itMessages, { kind, number: null })).not.toBe(kind);
	});

	it('gives a number only where the engine sent one', () => {
		expect(regionLabel(itMessages, { kind: 'page', number: 3 })).toBe('pagina 3');
		expect(regionLabel(itMessages, { kind: 'slide', number: null })).toBe('diapositiva');
		expect(regionLabel(en, { kind: 'header', number: null })).toBe('header');
	});
});
