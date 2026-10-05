<script lang="ts">
	import { revealItemInDir } from '@tauri-apps/plugin-opener';
	import { clearFiles, goTo, session } from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import { categoryOf } from '$lib/entities';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Card from '$lib/components/Card.svelte';
	import Icon from '$lib/components/Icon.svelte';

	const m = $derived(i18n.m);
	let heading: HTMLHeadingElement | undefined = $state();
</script>

<div class="head">
	<h2 bind:this={heading} tabindex="-1">{m.resultTitle()}</h2>
	<div class="actions">
		<Button variant="secondary" onclick={() => goTo('review')}>{m.back()}</Button>
		<Button variant="ghost" onclick={clearFiles}>{m.scrubAgain()}</Button>
	</div>
</div>

{#each session.results as result (result.path)}
	<Card tone={result.ok ? 'default' : 'danger'}>
		{#snippet header()}
			<h3>{basename(result.path)}</h3>
			{#if result.ok && result.report}
				<!--
					Verification is the feature that earns the trust, so it is stated as a
					fact rather than left in a JSON blob the window never rendered. In
					strict mode a survivor means nothing was written at all — so a green
					line here is "the output was searched", not "we think it is fine".
				-->
				<span class="verified">
					<Icon name="shield-check" size={14} />
					{m.verificationPassed()}
				</span>
			{/if}
		{/snippet}

		{#if result.ok}
			<p>
				{m.removedAndFlagged({
					removed: result.removed ?? 0,
					flagged: result.flagged ?? 0
				})}
			</p>
			{#if result.report}
				<p class="hint">
					{m.verificationPassedHint({ checked: result.report.verification.values_checked })}
				</p>
				{#if result.report.terms}
					<!-- Counts from the report. The entries that matched nothing are
					     named nowhere, which is the point of the section. -->
					<p class="hint">{m.termsMatched(result.report.terms)}</p>
				{/if}
			{/if}

			<p class="path">
				<span class="mono">{result.output}</span>
				{#if result.output}
					<Button
						variant="link"
						icon="folder-open"
						onclick={() => revealItemInDir(result.output!)}
					>
						{m.openFolder()}
					</Button>
				{/if}
			</p>

			{#if result.report}
				<ul class="tally">
					{#each Object.entries(result.report.entities) as [entity, counts] (entity)}
						<li>
							<Badge tone="entity" category={categoryOf(entity)}>
								{m.entity[entity]?.() ?? entity}
							</Badge>
							<span class="mono">{counts.removed}</span>
							{#if counts.countries?.length}
								<span class="countries mono">{counts.countries.join(' ')}</span>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}

			{#if result.key_file}
				<!-- Said again here, after the fact, because this is the screen the
				     reader is on when they go looking for the file. The warning is not
				     repeated: it was made at the moment of the decision, which is where
				     a warning belongs. -->
				<p class="path">
					<span class="keylabel">{m.keyFileWritten()}</span>
					<span class="mono">{result.key_file}</span>
					<Button
						variant="link"
						icon="folder-open"
						onclick={() => revealItemInDir(result.key_file!)}
					>
						{m.openFolder()}
					</Button>
				</p>
			{/if}

			{#if result.hidden_removed?.length}
				<!-- What the user never saw in the first place, which is where the leaks
				     they do not expect actually live. -->
				<h4>{m.hiddenRemovedTitle()}</h4>
				<ul class="hidden" lang="en">
					{#each result.hidden_removed as item (item.part + item.kind)}
						<li><span class="mono">{item.part}</span> — {item.kind}: {item.detail}</li>
					{/each}
				</ul>
			{/if}

			{#each result.warnings ?? [] as warning (warning)}
				<p class="warnline" lang="en">{warning}</p>
			{/each}

			{#if result.review}
				<!-- Advisory. The quotes come from the scrubbed text, so showing them
				     reveals nothing the output does not already. -->
				<h4>
					{m.reviewTitle()}
					<!-- "Ollama was not running" and "the reviewer had no objection" are
					     different facts, and the second one is reassuring. Collapsing them
					     lets a skipped review read as a clean bill of health. -->
					{#if !result.review.ran}
						<Badge tone="warn">{m.reviewDidNotRun()}</Badge>
					{:else if result.review.partial}
						<Badge tone="warn">{m.reviewPartial()}</Badge>
					{:else}
						<Badge tone="success">{m.reviewRan()}</Badge>
					{/if}
				</h4>
				<p class="hint" lang="en">{result.review.summary}</p>
				{#if result.review.concerns.length}
					<ul class="concerns">
						{#each result.review.concerns as concern (concern.quote + concern.why)}
							<li>
								<span class="kind">{concern.kind.split('_').join(' ')}</span>
								<code>{concern.quote}</code>
								<span class="why" lang="en">{concern.why}</span>
							</li>
						{/each}
					</ul>
				{/if}
			{/if}
		{:else}
			<p class="failed">
				{m.nothingWritten()} <span lang="en">{result.error?.message}</span>
			</p>
		{/if}
	</Card>
{/each}

{#if session.caps?.caveats.length}
	<!-- The engine's own words about what this tool does not guarantee. Quoted
	     rather than paraphrased: report.CAVEATS is where they are maintained, and a
	     second wording here would drift from the one on disk. -->
	<Callout tone="info" verbatim>
		{#each session.caps.caveats as caveat (caveat)}<p>{caveat}</p>{/each}
	</Callout>
{/if}

<style>
	.head {
		display: flex;
		align-items: center;
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

	h3 {
		font-size: var(--text-lg);
	}

	h4 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: var(--space-3) 0 var(--space-1);
		font-size: var(--text-sm);
	}

	.actions {
		display: flex;
		gap: var(--space-2);
	}

	.verified {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		color: var(--success-text);
	}

	.hint {
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	.keylabel {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}

	.path {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin: var(--space-2) 0;
	}

	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-3);
		overflow-wrap: anywhere;
	}

	.tally {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: var(--space-2) 0;
	}

	.tally li {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}

	.countries {
		text-transform: uppercase;
	}

	.hidden {
		list-style: none;
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.hidden li {
		margin: var(--space-1) 0;
	}

	.warnline {
		margin: var(--space-1) 0;
		font-size: var(--text-sm);
		color: var(--warn-text);
	}

	.concerns {
		list-style: none;
		margin-top: var(--space-2);
	}

	.concerns li {
		margin: var(--space-2) 0;
		padding-left: var(--space-2);
		border-left: 2px solid var(--warn-border);
	}

	.kind {
		display: inline-block;
		margin-right: var(--space-1);
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	.why {
		display: block;
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.failed {
		color: var(--danger-text);
	}
</style>
