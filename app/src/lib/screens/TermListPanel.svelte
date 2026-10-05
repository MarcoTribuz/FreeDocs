<script lang="ts">
	import {
		addTerm,
		armExport,
		cancelNewTerms,
		closeTerms,
		dismissImported,
		exportTerms,
		importTerms,
		lockTerms,
		passphraseMinimum,
		pickNewTermsFile,
		pickTermsFile,
		refreshTerms,
		rekeyBlocker,
		rekeyTerms,
		removeTerm,
		session,
		setTermsUse,
		startRekey,
		termsAvailable,
		termsBlocker,
		unlockTerms
	} from '$lib/app.svelte';
	import { basename } from '$lib/format';
	import { i18n } from '$lib/i18n/index.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Card from '$lib/components/Card.svelte';
	import Select from '$lib/components/Select.svelte';
	import TextField from '$lib/components/TextField.svelte';

	/**
	 * The firm's term list: open or create it, unlock it once, edit it, and say
	 * whether this run uses it.
	 *
	 * Holds no rules. Whether a list can be opened is `capabilities.terms_available`,
	 * the passphrase floor and the entry limits are the engine's and re-checked
	 * there, and what an entry matches is decided in `core/overrides.py`. The
	 * entries never live here beyond the slice on screen: the engine holds the
	 * list, and a search asks it again rather than filtering a copy.
	 *
	 * One panel in two places, like the advanced settings: before a file is loaded,
	 * so the first preview can already use the list, and on the review screen,
	 * where its effect is visible.
	 */

	const m = $derived(i18n.m);

	const available = $derived(termsAvailable());
	const blocker = $derived(termsBlocker());
	const passphraseError = $derived(
		session.termsPassphrase && blocker === 'passphrase'
			? m.termsNeedsPassphrase({ min: passphraseMinimum() })
			: session.termsConfirm && blocker === 'mismatch'
				? m.termsMismatch()
				: undefined
	);

	/**
	 * Every entity type the engine publishes, with OTHER named for what it means
	 * here. Its ordinary label is "yours", which is right in the findings table
	 * and wrong in a picker asking what a value is.
	 */
	const entityOptions = $derived(
		session.entityList.map((entity) => ({
			value: entity.name,
			label:
				entity.name === 'OTHER'
					? m.termsEntityUnspecified()
					: (m.entity[entity.name]?.() ?? entity.name)
		}))
	);

	const rekey = $derived(rekeyBlocker());
	const rekeyError = $derived(
		session.termsNext && rekey === 'passphrase'
			? m.termsNeedsPassphrase({ min: passphraseMinimum() })
			: session.termsNextConfirm && rekey === 'mismatch'
				? m.termsMismatch()
				: undefined
	);

	function entityLabel(name: string): string {
		return name === 'OTHER' ? m.termsEntityUnspecified() : (m.entity[name]?.() ?? name);
	}

	/** A search asks the engine again; a keystroke per request is fine at 10 000 entries. */
	let searchTimer: ReturnType<typeof setTimeout> | undefined;
	function search(): void {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => void refreshTerms(), 150);
	}
</script>

<Card padding="tight">
	{#snippet header()}
		<h3>{m.termsTitle()}</h3>
	{/snippet}

	<p class="hint">{m.termsHint()}</p>

	{#if !available}
		<!-- Disabled rather than offered and refused. The engine's sentence says
		     which half is missing, so it is quoted. -->
		<p class="error">{m.termsUnavailable()}</p>
		{#if session.caps?.terms_unavailable_reason}
			<p class="hint" lang="en">{session.caps.terms_unavailable_reason}</p>
		{/if}
	{:else if !session.termsUnlocked}
		<div class="row">
			{#if session.termsPath}
				<span class="mono path" title={session.termsPath}>{basename(session.termsPath)}</span>
			{/if}
			<Button variant="secondary" icon="folder-open" onclick={pickTermsFile}>{m.termsOpen()}</Button>
			<Button variant="secondary" icon="plus" onclick={pickNewTermsFile}>{m.termsNew()}</Button>
		</div>

		{#if session.termsPath}
			{#if session.termsCreating}
				<!-- Said before the file exists. Nothing recovers a forgotten
				     passphrase, and the second field is here for the same reason. -->
				<Callout tone="warn"><p>{m.termsNewWarning()}</p></Callout>
			{/if}
			<!-- Held for the life of the unlock and never stored: see
			     `session.termsPassphrase`. -->
			<TextField
				type="password"
				autocomplete={session.termsCreating ? 'new-password' : 'current-password'}
				label={m.termsPassphrase()}
				error={session.termsCreating ? undefined : passphraseError}
				bind:value={session.termsPassphrase}
				onEnter={session.termsCreating ? undefined : unlockTerms}
			/>
			{#if session.termsCreating}
				<TextField
					type="password"
					autocomplete="new-password"
					label={m.termsConfirm()}
					error={passphraseError}
					bind:value={session.termsConfirm}
					onEnter={unlockTerms}
				/>
			{/if}
			<div class="row">
				<Button
					variant="primary"
					loading={session.termsBusy}
					disabled={blocker !== null}
					onclick={unlockTerms}
				>
					{session.termsCreating ? m.termsCreate() : m.termsUnlock()}
				</Button>
				{#if session.termsCreating}
					<Button variant="ghost" onclick={cancelNewTerms}>{m.termsCancel()}</Button>
				{:else}
					<Button variant="ghost" onclick={closeTerms}>{m.termsForget()}</Button>
				{/if}
			</div>
		{/if}
	{:else}
		<div class="row">
			<span class="mono path" title={session.termsPath ?? ''}>
				{session.termsPath ? basename(session.termsPath) : ''}
			</span>
			<span class="count">{m.termsCount({ count: session.termsCount })}</span>
			<Button variant="secondary" onclick={lockTerms}>{m.termsLock()}</Button>
			<Button variant="ghost" onclick={closeTerms}>{m.termsForget()}</Button>
		</div>

		<label class="toggle">
			<input
				type="checkbox"
				checked={session.termsUse}
				onchange={(event) => setTermsUse(event.currentTarget.checked)}
			/>
			<span>{m.termsUse()}</span>
		</label>

		<div class="add">
			<TextField
				label={m.termsNewValue()}
				bind:value={session.termsNewValue}
				maxlength={session.caps?.term_max_characters}
				onEnter={addTerm}
			/>
			<Select label={m.termsEntity()} bind:value={session.termsNewEntity} options={entityOptions} />
			<Button
				variant="secondary"
				icon="plus"
				loading={session.termsBusy}
				disabled={session.termsNewValue.trim().length < (session.caps?.term_min_characters ?? 1)}
				onclick={addTerm}
			>
				{m.termsAdd()}
			</Button>
		</div>

		<TextField
			type="search"
			label={m.termsSearch()}
			bind:value={session.termsQuery}
			oninput={search}
		/>

		{#if session.termsShown.length}
			<ul class="terms">
				{#each session.termsShown as term (term.value)}
					<li>
						<code>{term.value}</code>
						<span class="entity">{entityLabel(term.entity)}</span>
						<Button
							variant="ghost"
							size="sm"
							icon="x"
							label={m.termsRemoveOne({ value: term.value })}
							disabled={session.termsBusy}
							onclick={() => removeTerm(term.value)}
						/>
					</li>
				{/each}
			</ul>
		{:else}
			<p class="hint">{session.termsQuery.trim() ? m.termsNoMatch() : m.termsEmpty()}</p>
		{/if}

		<div class="row">
			<Button variant="secondary" disabled={session.termsBusy} onclick={importTerms}>
				{m.termsImport()}
			</Button>
			{#if !session.termsRekeying}
				<Button variant="ghost" disabled={session.termsBusy} onclick={() => startRekey(true)}>
					{m.termsRekey()}
				</Button>
			{/if}
			{#if !session.termsExportArmed}
				<Button variant="ghost" disabled={session.termsBusy} onclick={() => armExport(true)}>
					{m.termsExport()}
				</Button>
			{/if}
		</div>

		{#if session.termsRekeying}
			<!-- The current passphrase is asked again, not taken from the held one:
			     an unlocked window is not the owner. The warning is the new-list
			     one, because the consequence of forgetting is the same. -->
			<div class="rekey">
				<Callout tone="warn"><p>{m.termsNewWarning()}</p></Callout>
				<TextField
					type="password"
					autocomplete="current-password"
					label={m.termsCurrentPassphrase()}
					bind:value={session.termsOld}
				/>
				<TextField
					type="password"
					autocomplete="new-password"
					label={m.termsNextPassphrase()}
					bind:value={session.termsNext}
				/>
				<TextField
					type="password"
					autocomplete="new-password"
					label={m.termsConfirm()}
					error={rekeyError}
					bind:value={session.termsNextConfirm}
					onEnter={rekeyTerms}
				/>
				<div class="row">
					<Button
						variant="primary"
						loading={session.termsBusy}
						disabled={rekey !== null}
						onclick={rekeyTerms}
					>
						{m.termsRekeyConfirm()}
					</Button>
					<Button variant="ghost" onclick={() => startRekey(false)}>{m.termsCancel()}</Button>
				</div>
			</div>
		{/if}

		{#if session.termsExportArmed}
			<!-- Two clicks, and the cost is named between them. This is the one way
			     the list leaves its encryption. -->
			<Callout tone="danger">
				<p>{m.termsExportWarning()}</p>
				<div class="row">
					<Button variant="danger" onclick={exportTerms}>{m.termsExportConfirm()}</Button>
					<Button variant="ghost" onclick={() => armExport(false)}>{m.termsCancel()}</Button>
				</div>
			</Callout>
		{/if}

		{#if session.termsImported}
			<Callout tone="warn" title={m.termsImportedTitle(session.termsImported)} live>
				<p>{m.termsDeleteSource({ file: basename(session.termsImported.source) })}</p>
				<p class="mono path">{session.termsImported.source}</p>
				<Button variant="secondary" size="sm" onclick={dismissImported}>{m.termsDismiss()}</Button>
			</Callout>
		{/if}

		{#if session.termsExported}
			<Callout tone="warn" title={m.termsExportedTitle()} verbatim live>
				<p>{session.termsExported.warning}</p>
				<p class="mono path">{session.termsExported.output}</p>
			</Callout>
		{/if}
	{/if}

	{#if session.termsProblem}
		<Callout tone="danger" verbatim live>
			<p>{session.termsProblem}</p>
		</Callout>
	{/if}
</Card>

<style>
	.hint {
		font-size: var(--text-sm);
		color: var(--text-2);
		margin-bottom: var(--space-3);
	}

	.row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: var(--space-3) 0;
	}

	.add {
		display: flex;
		align-items: flex-end;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	.add > :global(:first-child) {
		flex: 1;
		min-width: 12rem;
	}

	.rekey {
		margin-bottom: var(--space-3);
	}

	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		cursor: pointer;
		margin-bottom: var(--space-3);
	}

	.path {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.count {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.terms {
		list-style: none;
		margin: var(--space-2) 0 0;
		padding: 0;
		max-height: 16rem;
		overflow-y: auto;
	}

	.terms li {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-1) 0;
		border-bottom: 1px solid var(--border);
	}

	.terms code {
		flex: 1;
		min-width: 0;
		overflow-wrap: anywhere;
		font-size: var(--text-sm);
	}

	.entity {
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.error {
		font-size: var(--text-sm);
		color: var(--danger-text);
	}

	.mono {
		font-family: var(--font-mono);
	}
</style>
