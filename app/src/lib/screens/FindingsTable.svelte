<script lang="ts">
	import type { Inspection } from '$lib/engine';
	import { dropValue, isMine, session, toggleSpan } from '$lib/app.svelte';
	import { review, visibleFindings } from '$lib/review.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import { categoryOf } from '$lib/entities';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';

	interface Props {
		path: string;
		inspection: Inspection;
	}

	let { path, inspection }: Props = $props();

	const m = $derived(i18n.m);
	const rows = $derived(visibleFindings(inspection));

	function kept(index: number): boolean {
		const finding = inspection.findings[index];
		return (session.keptSpans[path] ?? []).some(
			(span) => span.start === finding.start && span.end === finding.end
		);
	}
</script>

<!--
	The same findings as the document view, as a table. Not a fallback: on a
	spreadsheet with four hundred cells the document reads as noise and the list
	reads as work, and which of the two is useful is the user's call.
-->
{#if rows.length === 0}
	<p class="muted">{m.nothingForThisFilter()}</p>
{:else}
	<table>
		<caption class="sr-only">{m.tableCaption({ file: basename(path) })}</caption>
		<thead>
			<tr>
				<th scope="col">{m.columnType()}</th>
				<th scope="col">{m.columnValue()}</th>
				<th scope="col">{m.columnWhere()}</th>
				<th scope="col">{m.columnAction()}</th>
				<th scope="col"><span class="sr-only">{m.columnDecision()}</span></th>
			</tr>
		</thead>
		<tbody>
			{#each rows as index (index)}
				{@const finding = inspection.findings[index]}
				<tr
					class:selected={review.selected === index}
					class:kept={kept(index)}
					onclick={() => (review.selected = index)}
				>
					<td>
						<Badge tone="entity" category={categoryOf(finding.entity)}>
							{m.entity[finding.entity]?.() ?? finding.entity}
						</Badge>
						{#if isMine(finding)}<em>{m.mine()}</em>{/if}
					</td>
					<th scope="row" class="value"><code>{finding.text}</code></th>
					<td class="mono">{finding.part}</td>
					<td>{m.action[finding.action]?.() ?? finding.action}</td>
					<td>
						{#if isMine(finding)}
							<Button
								variant="link"
								label={m.stopRemoving({ value: finding.text })}
								onclick={() => dropValue(path, finding.text)}
							>
								{m.stopRemovingShort()}
							</Button>
						{:else}
							<Button
								variant="link"
								label={m.keepThisOneFor({ value: finding.text })}
								title={m.keepThisOneWhy()}
								onclick={() => toggleSpan(path, finding)}
							>
								{kept(index) ? m.stopKeeping() : m.keepThisOne()}
							</Button>
						{/if}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

<style>
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	thead th {
		padding: var(--space-1) var(--space-2);
		border-bottom: 1px solid var(--border-strong);
		text-align: left;
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	td,
	tbody th {
		padding: var(--space-2);
		border-top: 1px solid var(--border);
		vertical-align: top;
		text-align: left;
		font-weight: var(--weight-normal);
	}

	tbody tr:hover {
		background: var(--surface-hover);
	}
	tbody tr.selected {
		background: var(--accent-soft);
	}
	tbody tr.kept .value code {
		text-decoration: line-through;
		text-decoration-color: var(--text-3);
	}

	.value code {
		font-family: var(--font-mono);
		word-break: break-all;
	}

	.mono {
		font-family: var(--font-mono);
		font-size: 0.9em;
		color: var(--text-3);
	}

	em {
		font-style: normal;
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.muted {
		padding: var(--space-4) 0;
		font-size: var(--text-sm);
		color: var(--text-3);
	}
</style>
