<script lang="ts">
	import type { Inspection } from '$lib/engine';
	import { dropValue, isMine, session, toggleKeep, toggleSpan } from '$lib/app.svelte';
	import { review } from '$lib/review.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { categoryOf } from '$lib/entities';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';

	interface Props {
		path: string;
		inspection: Inspection;
	}

	let { path, inspection }: Props = $props();

	const m = $derived(i18n.m);
	const finding = $derived(
		review.selected === null ? null : (inspection.findings[review.selected] ?? null)
	);

	const kept = $derived.by(() => {
		if (!finding) return false;
		return (session.keptSpans[path] ?? []).some(
			(span) => span.start === finding.start && span.end === finding.end
		);
	});

	/**
	 * Which layer claimed it, said in words.
	 *
	 * Derived from the detector name because that is what the wire carries today.
	 * The engine knows the layer outright — `Finding.layer` is L1, L2 or H — and
	 * once that crosses the wire this stops being a guess about a string.
	 */
	const provenance = $derived.by(() => {
		if (!finding) return '';
		if (isMine(finding)) return m.foundByYou();
		if (finding.detector.includes(':')) return m.foundByModel();
		return m.foundByChecksum();
	});

	const entityLabel = $derived(
		finding ? (m.entity[finding.entity]?.() ?? finding.entity) : ''
	);
</script>

<aside class="panel" aria-label={m.detailType()}>
	{#if !finding}
		<EmptyState
			icon="search"
			title={m.detailNothingSelected()}
			body={m.detailNothingSelectedHint()}
			level={3}
		/>
	{:else}
		<p class="value"><code>{finding.text}</code></p>

		<dl class="rows">
			<dt>{m.detailType()}</dt>
			<dd>
				<Badge tone="entity" category={categoryOf(finding.entity)}>{entityLabel}</Badge>
			</dd>

			<dt>{m.detailAction()}</dt>
			<dd>{m.action[finding.action]?.() ?? finding.action}</dd>

			<dt>{m.detailFound()}</dt>
			<dd>
				{provenance}
				<span class="detector mono">{m.foundBy({ detector: finding.detector })}</span>
			</dd>

			<dt>{m.detailConfidence()}</dt>
			<dd class="mono">{finding.confidence.toFixed(2)}</dd>

			{#if finding.part}
				<dt>{m.detailWhere()}</dt>
				<dd class="mono">{finding.part}</dd>
			{/if}
		</dl>

		{#if kept}<p class="kept">{m.detailKept()}</p>{/if}

		<!--
			Two controls, deliberately not one. The upper one says "not *this*
			occurrence"; the lower one says "no value of this type anywhere". The same
			city is confidential in a party's address and not in a jurisdiction
			clause, which is the whole reason the engine keeps `keep_spans` and `keep`
			apart — one control for both would collapse that distinction here.
		-->
		<div class="actions">
			{#if isMine(finding)}
				<Button variant="secondary" onclick={() => dropValue(path, finding.text)}>
					{m.stopRemoving({ value: finding.text })}
				</Button>
			{:else}
				<Button variant="secondary" onclick={() => toggleSpan(path, finding)}>
					{kept ? m.stopKeeping() : m.keepThisOccurrence()}
				</Button>
				<Button variant="link" onclick={() => toggleKeep(finding.entity)}>
					{m.keepEveryOne({ entity: entityLabel })}
				</Button>
			{/if}
		</div>
	{/if}
</aside>

<style>
	.panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
		border: 1px solid var(--border);
		border-radius: var(--radius-3);
		background: var(--surface);
		box-shadow: var(--shadow-1);
	}

	.value code {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		word-break: break-all;
	}

	.rows {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-1) var(--space-3);
		margin: 0;
		font-size: var(--text-sm);
	}

	dt {
		color: var(--text-3);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		padding-top: 2px;
	}

	dd {
		margin: 0;
		min-width: 0;
		overflow-wrap: anywhere;
	}

	.detector {
		display: block;
		color: var(--text-3);
		font-size: var(--text-xs);
	}

	.mono {
		font-family: var(--font-mono);
		font-size: 0.9em;
	}

	.kept {
		font-size: var(--text-sm);
		color: var(--accent-text);
	}

	.actions {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-2);
	}
</style>
