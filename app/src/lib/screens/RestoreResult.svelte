<script lang="ts">
	import { revealItemInDir } from '@tauri-apps/plugin-opener';
	import { clearRestore, goTo, session } from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import { categoryOf } from '$lib/entities';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Card from '$lib/components/Card.svelte';
	import Icon from '$lib/components/Icon.svelte';

	/**
	 * What came back, and — the half that matters — what did not.
	 *
	 * `ok: false` does not mean nothing was written. The engine writes the restored
	 * document either way, deliberately: a scrub that leaks must write nothing
	 * because a nearly-clean file gets sent, while a half-restored one is still the
	 * user's best artifact and its defect is visible in it. So the path is always
	 * shown, and the failure is stated beside it rather than instead of it.
	 */

	const m = $derived(i18n.m);
	const result = $derived(session.restoreResult);
	let heading: HTMLHeadingElement | undefined = $state();
</script>

<div class="head">
	<h2 bind:this={heading} tabindex="-1">{m.restoreResultTitle()}</h2>
	<div class="actions">
		<Button variant="secondary" onclick={() => goTo('file')}>{m.back()}</Button>
		<Button variant="ghost" onclick={clearRestore}>{m.restoreAgain()}</Button>
	</div>
</div>

{#if result}
	<Card tone={result.ok ? 'default' : 'danger'}>
		{#snippet header()}
			<h3>{basename(result.path)}</h3>
			{#if result.ok}
				<span class="verified">
					<Icon name="shield-check" size={14} />
					{m.restoreVerified()}
				</span>
			{/if}
		{/snippet}

		{#if result.restored.length}
			<p>
				{m.restoredSummary({
					values: result.restored.length,
					occurrences: result.restored.reduce((sum, entry) => sum + entry.occurrences, 0)
				})}
			</p>
			<ul class="tally">
				{#each result.restored as entry (entry.placeholder)}
					<li>
						<Badge tone="entity" category={categoryOf(entry.entity)}>
							{m.entity[entry.entity]?.() ?? entry.entity}
						</Badge>
						<code>{entry.placeholder}</code>
						<span class="mono">{entry.occurrences}</span>
					</li>
				{/each}
			</ul>
		{:else}
			<p>{m.restoreNothingMatched()}</p>
		{/if}

		<p class="path">
			<span class="mono">{result.output}</span>
			<Button variant="link" icon="folder-open" onclick={() => revealItemInDir(result.output)}>
				{m.openFolder()}
			</Button>
		</p>

		{#if !result.ok}
			<!-- Named without their values: this text travels into a report and
			     through the pipe, and a message about a value that failed to be
			     written must not carry the value. -->
			<h4>{m.restoreProblemsTitle()}</h4>
			<p class="failed">{m.restoreIncomplete({ count: result.problems.length })}</p>
			<ul class="plain">
				{#each result.problems as problem (problem.placeholder + problem.kind)}
					<li><code>{problem.placeholder}</code> <span class="mono">{problem.kind}</span></li>
				{/each}
			</ul>
		{/if}

		{#if result.not_present.length}
			<h4>{m.restoreNotPresentTitle()}</h4>
			<p class="hint">{m.restoreNotPresentHint()}</p>
			<ul class="plain">
				{#each result.not_present as placeholder (placeholder)}
					<li><code>{placeholder}</code></li>
				{/each}
			</ul>
		{/if}

		{#if result.unknown_placeholders.length}
			<!-- The honest half of matching literally. Without this list a translated
			     stem leaves the document silently and the report reads clean. -->
			<h4>{m.restoreUnknownTitle()}</h4>
			<p class="hint">{m.restoreUnknownHint()}</p>
			<ul class="plain">
				{#each result.unknown_placeholders as placeholder (placeholder)}
					<li><code>{placeholder}</code></li>
				{/each}
			</ul>
		{/if}

		{#each result.warnings as warning (warning)}
			<p class="warnline" lang="en">{warning}</p>
		{/each}
	</Card>
{/if}

<style>
	.head {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: var(--space-4);
		margin-bottom: var(--space-4);
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
		color: var(--success-text);
	}

	.tally {
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: var(--space-3) 0;
	}

	.tally li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.plain {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	h4 {
		margin-top: var(--space-4);
		margin-bottom: var(--space-1);
		font-size: var(--text-sm);
	}

	.hint {
		font-size: var(--text-sm);
		color: var(--text-2);
		margin-bottom: var(--space-2);
		max-width: 46rem;
	}

	.path {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: var(--space-3) 0;
	}

	.failed {
		color: var(--danger-text);
		margin-bottom: var(--space-2);
	}

	.warnline {
		font-size: var(--text-sm);
		color: var(--warn-text);
	}

	.mono,
	code {
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
</style>
