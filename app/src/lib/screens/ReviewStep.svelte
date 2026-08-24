<script lang="ts">
	import {
		addValue,
		clearSpans,
		runScrub,
		session,
		summary,
		totalFindings
	} from '$lib/app.svelte';
	import { folding, review, typesPresent, viewFor } from '$lib/review.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import { categoryOf } from '$lib/entities';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Card from '$lib/components/Card.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import Select from '$lib/components/Select.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import TextField from '$lib/components/TextField.svelte';
	import AdvancedPanel from './AdvancedPanel.svelte';
	import KeyFilePanel from './KeyFilePanel.svelte';
	import DocumentText from './DocumentText.svelte';
	import FindingDetail from './FindingDetail.svelte';
	import FindingsTable from './FindingsTable.svelte';

	const m = $derived(i18n.m);

	const path = $derived(session.activePath ?? session.files[0] ?? null);
	const inspection = $derived(path ? (session.inspections[path] ?? null) : null);

	let heading: HTMLHeadingElement | undefined = $state();
	let addField: HTMLInputElement | undefined = $state();

	const typeOptions = $derived([
		{ value: '', label: m.allTypes() },
		...(inspection ? typesPresent(inspection) : []).map((name) => ({
			value: name,
			label: m.entity[name]?.() ?? name
		}))
	]);
</script>

<div class="head">
	<div>
		<!-- tabindex so the page can move focus here on a step change: an SPA has no
		     page load, and without it a step change is silent and leaves focus
		     wherever the last click was. -->
		<h2 bind:this={heading} tabindex="-1">
			{path ? m.reviewOf({ file: basename(path) }) : m.stepReview()}
		</h2>
		{#if inspection}
			<p class="counts">
				{m.findingCount({ count: inspection.findings.length })}
				<span class="dot">·</span>
				{m.fileSummary({
					format: inspection.format,
					characters: inspection.characters
				})}
			</p>
		{/if}
	</div>

	<div class="actions">
		{#if session.reviewModel}
			<Badge tone="accent">{m.reviewBadge({ model: session.reviewModel })}</Badge>
		{/if}
		<Button
			variant="primary"
			onclick={runScrub}
			loading={session.busy === 'scrub'}
			disabled={session.busy !== null || totalFindings() === 0}
		>
			{session.busy === 'scrub' ? m.scrubbing() : m.scrub({ files: session.files.length })}
		</Button>
	</div>
</div>

{#if !path}
	<EmptyState icon="file-text" title={m.stepReviewLocked()} level={3} />
{:else if session.busy === path && !inspection}
	<Card>
		<Skeleton label={m.reading()} lines={8} />
	</Card>
{:else if inspection}
	<div class="toolbar">
		<div class="modes" role="group" aria-label={m.stepReview()}>
			<button
				type="button"
				class="mode"
				class:on={review.mode === 'document'}
				aria-pressed={review.mode === 'document'}
				onclick={() => (review.mode = 'document')}
			>
				{m.viewDocument()}
			</button>
			<button
				type="button"
				class="mode"
				class:on={review.mode === 'list'}
				aria-pressed={review.mode === 'list'}
				onclick={() => (review.mode = 'list')}
			>
				{m.viewList()}
			</button>
		</div>

		{#if review.mode === 'document' && inspection.text}
			{@const view = viewFor(path, inspection)}
			<button
				type="button"
				class="mode"
				class:on={folding(view)}
				aria-pressed={folding(view)}
				onclick={() => (review.onlyFindings = !folding(view))}
			>
				{folding(view) ? m.onlyFindings() : m.wholeDocument()}
			</button>
		{:else}
			<Select
				label={m.filterByType()}
				inline
				bind:value={review.filter}
				options={typeOptions}
			/>
			<TextField label={m.searchValues()} inline bind:value={review.query} />
		{/if}
	</div>

	{#if inspection.findings.length === 0}
		<Card>
			<EmptyState icon="shield-check" title={m.nothingMatched()} level={3} />
		</Card>
	{/if}

	<div class="pane">
		<Card padding="normal">
			{#if review.mode === 'document'}
				<DocumentText
					{path}
					{inspection}
					focusAddValue={() => {
						addField?.focus();
						addField?.scrollIntoView({ block: 'center' });
					}}
				/>
			{:else}
				<FindingsTable {path} {inspection} />
			{/if}
		</Card>

		<div class="side">
			<FindingDetail {path} {inspection} />

			<!-- The other half of the loop. Detection is measured, not complete, so
			     the person reading the preview is the only one who can add what it
			     missed — and the engine, not this window, decides what happens to
			     it. -->
			<Card padding="tight">
				<div class="addrow">
					<TextField
						bind:element={addField}
						label={m.addValueLabel()}
						placeholder={m.addValuePlaceholder()}
						bind:value={session.pending[path]}
						onEnter={() => addValue(path)}
					/>
					<Button
						icon="plus"
						onclick={() => addValue(path)}
						disabled={!(session.pending[path] ?? '').trim()}
					>
						{m.add()}
					</Button>
				</div>
				{#if (session.keptSpans[path] ?? []).length > 0}
					<p class="kept">
						{m.keptOnPurpose({ count: (session.keptSpans[path] ?? []).length })}
						<Button variant="link" onclick={() => clearSpans(path)}>{m.undoAll()}</Button>
					</p>
				{/if}
			</Card>

			<!-- The reverse path, decided before the run: the engine writes the key
			     file inside the scrub request, which is what keeps the mapping from
			     ever crossing the pipe into this window. -->
			<KeyFilePanel />

			{#if inspection.findings.length}
				<Card padding="tight">
					<ul class="tally">
						{#each summary(inspection) as [entity, total] (entity)}
							<li>
								<Badge tone="entity" category={categoryOf(entity)}>
									{m.entity[entity]?.() ?? entity}
								</Badge>
								<span class="mono">{total}</span>
							</li>
						{/each}
					</ul>
				</Card>
			{/if}
		</div>
	</div>

	{#if inspection.hidden?.length}
		<!-- The leak users do not expect, said before the scrub rather than after.
		     The terminal has named these since `15ee0e1` and this screen did not,
		     so the only place to learn that a thumbnail or a comment was going was
		     the result page — after the decision had been made.

		     `lang="en"` on the list: `kind` is a closed vocabulary and `detail` is
		     an engine f-string, and the window's rule is that enum-shaped things
		     get real words while sentences are quoted. Neither is a value, which
		     is the engine's own contract for this type and what makes showing it
		     here reasonable at all. -->
		<Card padding="tight">
			<h4>{m.hiddenPendingTitle()}</h4>
			<ul class="hidden-list" lang="en">
				{#each inspection.hidden as item (item.part + item.kind + item.detail)}
					<li><span class="mono">{item.part}</span> — {item.kind}: {item.detail}</li>
				{/each}
			</ul>
		</Card>
	{/if}

	{#if inspection.warnings.length}
		<Callout tone="warn" verbatim>
			{#each inspection.warnings as warning (warning)}<p>{warning}</p>{/each}
		</Callout>
	{/if}

	<AdvancedPanel />
{/if}

<style>
	.hidden-list {
		list-style: none;
		margin: var(--space-2) 0 0;
		padding: 0;
		display: grid;
		gap: var(--space-1);
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.hidden-list li {
		line-height: 1.5;
	}

	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-4);
		flex-wrap: wrap;
		margin-bottom: var(--space-4);
	}

	h2 {
		font-size: var(--text-xl);
		line-height: var(--lh-xl);
		letter-spacing: var(--tracking-tight);
	}

	.counts {
		margin-top: var(--space-1);
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	.dot {
		margin: 0 var(--space-1);
	}

	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.toolbar {
		display: flex;
		align-items: flex-end;
		gap: var(--space-3);
		flex-wrap: wrap;
		margin-bottom: var(--space-3);
	}

	.modes {
		display: inline-flex;
		padding: 2px;
		border: 1px solid var(--border);
		border-radius: var(--radius-full);
		background: var(--bg-subtle);
	}

	.mode {
		padding: var(--space-1) var(--space-3);
		border: 1px solid transparent;
		border-radius: var(--radius-full);
		background: none;
		color: var(--text-3);
		font: var(--weight-medium) var(--text-xs) / var(--lh-xs) var(--font-sans);
		cursor: pointer;
	}
	.mode:hover {
		color: var(--text);
	}
	.mode.on {
		background: var(--surface);
		color: var(--text);
		box-shadow: var(--shadow-1);
	}

	.pane {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 20rem;
		gap: var(--space-4);
		align-items: start;
	}

	/* One column below the width where a 20rem panel stops leaving room to read.
	   No container queries: the oldest webview this app claims does not have them. */
	@media (max-width: 62rem) {
		.pane {
			grid-template-columns: minmax(0, 1fr);
		}
	}

	.side {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		position: sticky;
		top: var(--space-4);
	}

	.addrow {
		display: flex;
		align-items: flex-end;
		gap: var(--space-2);
	}

	.addrow :global(.field) {
		flex: 1;
	}

	.kept {
		margin-top: var(--space-2);
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	.tally {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.tally li {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}

	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-3);
	}

</style>
