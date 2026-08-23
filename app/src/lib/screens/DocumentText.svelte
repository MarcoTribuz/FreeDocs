<script lang="ts">
	import type { Inspection } from '$lib/engine';
	import type { Block } from '$lib/highlight';
	import { nextFinding } from '$lib/highlight';
	import { addValue, isMine, session, toggleSpan } from '$lib/app.svelte';
	import { folding, review, segmentsOf, viewFor } from '$lib/review.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import { categoryOf } from '$lib/entities';
	import EmptyState from '$lib/components/EmptyState.svelte';

	interface Props {
		path: string;
		inspection: Inspection;
		/** Focus the "also remove" field. Owned by the parent, which renders it. */
		focusAddValue: () => void;
	}

	let { path, inspection, focusAddValue }: Props = $props();

	const m = $derived(i18n.m);
	const view = $derived(viewFor(path, inspection));

	/**
	 * The rows to render: a block, or a run of blocks with nothing in them.
	 *
	 * Folding the empty runs bounds the DOM by the number of findings rather than
	 * by the size of the document, and it matches the task — the person is
	 * reviewing decisions, not proofreading. The runs stay reachable, because a
	 * preview that silently hides text is not a preview.
	 */
	type Row =
		| { kind: 'block'; block: Block; heading: string | null }
		| { kind: 'gap'; key: number; blocks: Block[] };

	const rows = $derived.by<Row[]>(() => {
		const out: Row[] = [];
		let gap: Block[] = [];
		// The part heading is decided while the rows are built, not while they are
		// rendered: a heading is "the part changed since the previous row", which is
		// a fact about the list and not about any one row.
		let previous = '';
		const fold = folding(view);

		const emit = (block: Block) => {
			const heading = block.part && block.part !== previous ? block.part : null;
			if (block.part) previous = block.part;
			out.push({ kind: 'block', block, heading });
		};
		const flush = () => {
			if (!gap.length) return;
			if (gap.length === 1 || review.expanded.has(gap[0].index)) gap.forEach(emit);
			else out.push({ kind: 'gap', key: gap[0].index, blocks: gap });
			gap = [];
		};

		for (const block of view.blocks) {
			if (!fold || block.findings.length) {
				flush();
				emit(block);
			} else {
				gap.push(block);
			}
		}
		flush();
		return out;
	});

	/**
	 * The one mark that is in the tab order.
	 *
	 * Roving tabindex: hundreds of buttons in the tab order makes Tab useless, so
	 * the group is one stop and the arrows move inside it. When nothing is
	 * selected that stop has to be the first mark — otherwise every mark is
	 * `tabindex="-1"` and the document cannot be entered from the keyboard at all,
	 * which is what the first version of this did.
	 */
	const tabbable = $derived(
		review.selected ?? view.blocks.find((block) => block.findings.length)?.findings[0] ?? null
	);

	/** Which blocks must be laid out for real, so scrolling lands where it aimed. */
	let pinned = $state<Set<number>>(new Set());

	let container: HTMLElement | undefined = $state();

	function blockOf(index: number): Block | undefined {
		return view.blocks.find((block) => block.findings.includes(index));
	}

	/**
	 * Select a finding, and bring it into view.
	 *
	 * `content-visibility: auto` reserves an *estimated* box for a block that has
	 * never been laid out, so scrolling straight to a distant one lands in the
	 * wrong place once the real box arrives. Pinning the target and its
	 * neighbours forces them to be laid out first, and the scroll happens a frame
	 * later.
	 */
	function choose(index: number | null, scroll = true) {
		review.selected = index;
		if (index === null || !scroll) return;
		const block = blockOf(index);
		if (!block) return;
		pinned = new Set([block.index - 1, block.index, block.index + 1]);
		requestAnimationFrame(() => {
			const mark = container?.querySelector<HTMLElement>(`[data-f="${index}"]`);
			mark?.scrollIntoView({ block: 'center', behavior: reduced() ? 'auto' : 'smooth' });
			mark?.focus();
		});
	}

	function reduced(): boolean {
		return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
	}

	function move(delta: number) {
		choose(nextFinding(review.selected, inspection.findings.length, delta));
	}

	function keptSpan(index: number): boolean {
		const finding = inspection.findings[index];
		return (session.keptSpans[path] ?? []).some(
			(span) => span.start === finding.start && span.end === finding.end
		);
	}

	/**
	 * Toggle the selected occurrence.
	 *
	 * The span is built from `inspection.findings`, never from `view.marks`: the
	 * marks carry UTF-16 offsets so this string can be sliced, and the engine
	 * counts code points. Sending a rendering offset back is the one mistake in
	 * this screen that would look like nothing at all.
	 */
	function toggleSelected() {
		if (review.selected === null) return;
		const finding = inspection.findings[review.selected];
		if (isMine(finding)) addValue(path); // no-op unless something is typed
		else toggleSpan(path, finding);
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.metaKey || event.ctrlKey || event.altKey) return;
		const target = event.target as HTMLElement | null;
		if (
			target &&
			(target.tagName === 'INPUT' ||
				target.tagName === 'TEXTAREA' ||
				target.tagName === 'SELECT' ||
				target.isContentEditable)
		) {
			return;
		}

		switch (event.key) {
			case 'ArrowDown':
			case 'ArrowRight':
			case 'j':
			case 'n':
				event.preventDefault();
				move(1);
				break;
			case 'ArrowUp':
			case 'ArrowLeft':
			case 'k':
			case 'p':
				event.preventDefault();
				move(-1);
				break;
			case 'Home':
				event.preventDefault();
				choose(inspection.findings.length ? 0 : null);
				break;
			case 'End':
				event.preventDefault();
				choose(inspection.findings.length ? inspection.findings.length - 1 : null);
				break;
			// Not `k`, despite the mnemonic: anyone who uses vim will press it for
			// "previous", and the two would fight. `x` is "cross this one out".
			case 'x':
				event.preventDefault();
				toggleSelected();
				break;
			case 'a':
				event.preventDefault();
				focusAddValue();
				break;
			case 'f':
				event.preventDefault();
				review.onlyFindings = !folding(view);
				break;
			case 'Escape':
				choose(null, false);
				break;
		}
	}

	const keysId = $props.id();
</script>

{#if !view.text}
	<EmptyState icon="file-text" title={m.noPreview()} />
{:else}
	{#if view.truncated}
		<p class="truncated">
			{m.previewTruncated({ shown: view.shown, total: inspection.characters })}
		</p>
	{/if}

	<!--
		One tab stop, not one per mark. A document with four hundred highlights in
		the tab order makes Tab useless; the group is entered once and the arrow
		keys move inside it. The key list is a real element the group points at, so
		the contract is discoverable instead of folklore.
	-->
	<!--
		svelte-ignore a11y_no_noninteractive_element_interactions
		The handler is on the group, not on a control, because this is a composite
		widget: the keys arrive by bubbling from whichever mark inside it has focus,
		and putting the same handler on every one of several hundred buttons would
		be several hundred copies of one behaviour.
	-->
	<div
		class="doc"
		bind:this={container}
		role="group"
		aria-label={m.documentLabel({ file: basename(path) })}
		aria-describedby={keysId}
		onkeydown={onKeydown}
	>
		{#each rows as row (row.kind === 'gap' ? `gap-${row.key}` : `block-${row.block.index}`)}
			{#if row.kind === 'gap'}
				<button
					type="button"
					class="gap"
					onclick={() => (review.expanded = new Set([...review.expanded, row.key]))}
				>
					{m.skippedParagraphs({ count: row.blocks.length })}
				</button>
			{:else}
				{@const block = row.block}
				{#if row.heading}
					<h3 class="part">{row.heading}</h3>
				{/if}
				<p
					class="block"
					data-pinned={pinned.has(block.index) ? 'true' : undefined}
					style:contain-intrinsic-size={`auto ${Math.max(
						26,
						Math.ceil((block.end - block.start) / 90) * 26
					)}px`}
				>
					{#each segmentsOf(view, block) as piece}
						{#if piece.finding === -1}{piece.text}{:else}
							{@const finding = inspection.findings[piece.finding]}
							{@const kept = keptSpan(piece.finding)}
							<button
								type="button"
								class="mark"
								data-f={piece.finding}
								data-action={finding.action}
								data-kept={kept ? 'true' : undefined}
								data-mine={isMine(finding) ? 'true' : undefined}
								style:--e-line={`var(--e-${categoryOf(finding.entity)}-line)`}
								style:--e-tint={`var(--e-${categoryOf(finding.entity)}-tint)`}
								tabindex={piece.finding === tabbable ? 0 : -1}
								aria-current={piece.finding === review.selected ? 'true' : undefined}
								onclick={() => choose(piece.finding, false)}
							>
								<!--
									A hidden prefix rather than aria-label: a label on a button that
									contains text *replaces* that text, so the value itself would
									stop being announced. This adds the state and keeps the value.
								-->
								<span class="sr-only">
									{m.markName({
										entity: m.entity[finding.entity]?.() ?? finding.entity,
										action: m.action[finding.action]?.() ?? finding.action,
										kept
									})} —
								</span><mark>{piece.text}</mark>
							</button>
						{/if}
					{/each}
				</p>
			{/if}
		{/each}
	</div>

	<p class="sr-only" id={keysId}>{m.keyboardHelp()}</p>
{/if}

<style>
	.truncated {
		margin-bottom: var(--space-3);
		font-size: var(--text-sm);
		color: var(--warn-text);
	}

	.doc {
		font-family: var(--font-sans);
		font-size: var(--text-doc);
		line-height: var(--lh-doc);
		white-space: pre-wrap;
		overflow-wrap: break-word;
	}

	.part {
		margin: var(--space-4) 0 var(--space-1);
		font-size: var(--text-xs);
		font-family: var(--font-mono);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
		white-space: normal;
	}
	.part:first-child {
		margin-top: 0;
	}

	.block {
		/* Skips layout and paint for what is off screen. Ignored by an older
		   webview, which then renders correctly and more slowly — never wrongly. */
		content-visibility: auto;
	}
	.block[data-pinned] {
		content-visibility: visible;
	}

	.gap {
		display: block;
		width: 100%;
		margin: var(--space-2) 0;
		padding: var(--space-1) var(--space-3);
		border: 1px dashed var(--border-strong);
		border-radius: var(--radius-2);
		background: var(--bg-subtle);
		color: var(--text-3);
		font: inherit;
		font-size: var(--text-xs);
		text-align: left;
		cursor: pointer;
	}
	.gap:hover {
		color: var(--text);
		border-color: var(--accent-line);
	}

	/*
	 * Every state has a channel that is not colour. redact fills and underlines;
	 * report only underlines, dotted — flagged and not removed, which is the
	 * semantic difference; kept is struck through with a dashed outline; a value
	 * the user added is bracketed by thin spaces. The tint alone would be
	 * unreadable for anyone colour-blind, which was the previous window's defect.
	 */
	.mark {
		display: inline;
		padding: 0 1px;
		border: 0;
		border-radius: var(--radius-1);
		background: var(--e-tint);
		box-shadow: inset 0 -2px 0 var(--e-line);
		color: inherit;
		font: inherit;
		cursor: pointer;
		transition: background var(--dur-1) var(--ease-out);
	}
	.mark mark {
		background: none;
		color: inherit;
	}
	.mark:hover {
		background: var(--surface-active);
	}
	.mark[data-action='report'] {
		background: none;
		border-bottom: 1px dotted var(--e-line);
		box-shadow: none;
	}
	.mark[data-kept] {
		background: none;
		box-shadow: none;
		outline: 1px dashed var(--border-strong);
		text-decoration: line-through;
		text-decoration-color: var(--text-3);
	}
	.mark[data-mine] {
		box-shadow: inset 0 -2px 0 var(--accent);
	}
	.mark[data-mine] mark::before,
	.mark[data-mine] mark::after {
		content: '\2009';
	}
	.mark[aria-current='true'] {
		box-shadow:
			inset 0 -2px 0 var(--e-line),
			0 0 0 2px var(--accent);
	}
</style>
