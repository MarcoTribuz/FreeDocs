<script lang="ts">
	import {
		goTo,
		newText,
		runRestoreText,
		session,
		textRestoreSource
	} from '$lib/app.svelte';
	import { announce } from '$lib/announce.svelte';
	import { copyText } from '$lib/clipboard';
	import { categoryOf } from '$lib/entities';
	import { i18n } from '$lib/i18n/index.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Card from '$lib/components/Card.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TextField from '$lib/components/TextField.svelte';

	/**
	 * The scrubbed text to copy, and the way back: paste the model's reply, get
	 * the values restored. Nothing here reaches disk unless a key file was chosen,
	 * and nothing reaches `localStorage` at all.
	 *
	 * The restore half is offered only when there is something to restore from -
	 * a held mapping or a key file - which is the engine's answer in the scrub
	 * response, not a judgement made here.
	 */

	const m = $derived(i18n.m);
	let heading: HTMLHeadingElement | undefined = $state();
	const result = $derived(session.textResult);
	const restored = $derived(session.textRestored);
	const source = $derived(textRestoreSource());

	async function copy(text: string): Promise<void> {
		// Said either way: a copy button that fails silently is a paste of the
		// previous clipboard into a model, which is the worst text to send.
		announce((await copyText(text)) ? m.textCopied() : m.textCopyFailed(), { assertive: true });
	}
</script>

<div class="head">
	<h2 bind:this={heading} tabindex="-1">{m.textResultTitle()}</h2>
	<div class="actions">
		<Button variant="secondary" onclick={() => goTo('review')}>{m.back()}</Button>
		<Button variant="ghost" onclick={newText}>{m.textNew()}</Button>
	</div>
</div>

{#if result}
	<Card tone={result.ok ? 'default' : 'danger'}>
		{#snippet header()}
			<h3>{m.textScrubbedTitle()}</h3>
			{#if result.ok && result.report}
				<span class="verified">
					<Icon name="shield-check" size={14} />
					{m.verificationPassed()}
				</span>
			{/if}
		{/snippet}

		{#if result.ok && result.text !== undefined}
			<p>{m.removedAndFlagged({ removed: result.removed ?? 0, flagged: result.flagged ?? 0 })}</p>
			{#if result.report}
				<p class="hint">
					{m.verificationPassedHint({ checked: result.report.verification.values_checked })}
				</p>
				{#if result.report.terms}
					<p class="hint">{m.termsMatched(result.report.terms)}</p>
				{/if}
			{/if}

			<!-- Read-only and selectable: the last resort when the clipboard is
			     refused needs no code at all. -->
			<textarea class="out" readonly rows="10" aria-label={m.textScrubbedTitle()} value={result.text}
			></textarea>
			<div class="row">
				<Button variant="primary" onclick={() => copy(result.text ?? '')}>{m.textCopy()}</Button>
			</div>

			{#if result.report}
				<ul class="tally">
					{#each Object.entries(result.report.entities) as [entity, counts] (entity)}
						<li>
							<Badge tone="entity" category={categoryOf(entity)}>
								{m.entity[entity]?.() ?? entity}
							</Badge>
							<span class="mono">{counts.removed}</span>
						</li>
					{/each}
				</ul>
			{/if}

			{#each result.warnings ?? [] as warning (warning)}
				<p class="warnline" lang="en">{warning}</p>
			{/each}

			{#if result.handle}
				<p class="hint">{m.textHeld()}</p>
			{:else if result.key_file}
				<p class="hint">
					<span>{m.keyFileWritten()}</span>
					<span class="mono">{result.key_file}</span>
				</p>
			{:else}
				<p class="hint">{m.textNotKept()}</p>
			{/if}
		{:else}
			<!-- No text at all on a failure: a nearly-clean paste gets sent. -->
			<p class="failed">
				{m.textNothingProduced()} <span lang="en">{result.error?.message}</span>
			</p>
		{/if}
	</Card>

	{#if result.ok && source}
		<Card>
			{#snippet header()}
				<h3>{m.textReplyTitle()}</h3>
			{/snippet}
			<label class="paste">
				<span class="label">{m.textReplyLabel()}</span>
				<textarea
					bind:value={session.replyText}
					rows="10"
					spellcheck="false"
					placeholder={m.textReplyPlaceholder()}
				></textarea>
			</label>
			{#if source === 'file'}
				<!-- Asked each time and cleared after: the key file is the one thing
				     that undoes the scrub, and its passphrase is not held here. -->
				<TextField
					type="password"
					autocomplete="current-password"
					label={m.restorePassphrase()}
					bind:value={session.textRestorePassphrase}
				/>
			{/if}
			<div class="row">
				<Button
					variant="primary"
					loading={session.busy === 'restore'}
					disabled={!session.replyText.trim() ||
						session.busy !== null ||
						(source === 'file' && !session.textRestorePassphrase)}
					onclick={runRestoreText}
				>
					{session.busy === 'restore' ? m.restoring() : m.textRestore()}
				</Button>
			</div>
		</Card>
	{/if}

	{#if restored}
		<Card tone={restored.ok ? 'default' : 'danger'}>
			{#snippet header()}
				<h3>{m.textRestoredTitle()}</h3>
			{/snippet}
			<textarea class="out" readonly rows="10" aria-label={m.textRestoredTitle()} value={restored.text}
			></textarea>
			<div class="row">
				<Button variant="primary" onclick={() => copy(restored.text)}>{m.textCopy()}</Button>
			</div>

			{#if !restored.ok}
				<h4>{m.restoreProblemsTitle()}</h4>
				<p class="failed">{m.restoreIncomplete({ count: restored.problems.length })}</p>
				<ul class="plain">
					{#each restored.problems as problem (problem.placeholder + problem.kind)}
						<li><code>{problem.placeholder}</code> <span class="mono">{problem.kind}</span></li>
					{/each}
				</ul>
			{/if}
			{#if restored.not_present.length}
				<h4>{m.restoreNotPresentTitle()}</h4>
				<p class="hint">{m.restoreNotPresentHint()}</p>
				<ul class="plain">
					{#each restored.not_present as placeholder (placeholder)}
						<li><code>{placeholder}</code></li>
					{/each}
				</ul>
			{/if}
			{#if restored.unknown_placeholders.length}
				<!-- Listed, never repaired: guessing which value a mangled token
				     meant puts somebody else's data in the text. -->
				<h4>{m.restoreUnknownTitle()}</h4>
				<p class="hint">{m.restoreUnknownHint()}</p>
				<ul class="plain">
					{#each restored.unknown_placeholders as placeholder (placeholder)}
						<li><code>{placeholder}</code></li>
					{/each}
				</ul>
			{/if}
			{#each restored.warnings as warning (warning)}
				<p class="warnline" lang="en">{warning}</p>
			{/each}
		</Card>
	{/if}
{/if}

{#if session.caps?.caveats.length}
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
		margin-top: var(--space-4);
		margin-bottom: var(--space-1);
		font-size: var(--text-sm);
	}

	.actions,
	.row {
		display: flex;
		gap: var(--space-2);
	}

	.row {
		margin: var(--space-2) 0 var(--space-3);
	}

	.verified {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-xs);
		color: var(--success-text);
	}

	.paste {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	.label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}

	textarea {
		width: 100%;
		resize: vertical;
		padding: var(--space-3);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-3);
		background: var(--surface);
		color: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		line-height: 1.5;
	}

	.out {
		margin-top: var(--space-3);
	}

	.tally {
		list-style: none;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
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

	.hint {
		font-size: var(--text-sm);
		color: var(--text-2);
		margin-bottom: var(--space-2);
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
