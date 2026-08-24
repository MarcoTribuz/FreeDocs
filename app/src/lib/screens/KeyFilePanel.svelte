<script lang="ts">
	import {
		MIN_PASSPHRASE,
		keyFileAvailable,
		keyFileBlocker,
		pickKeyDirectory,
		session
	} from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Card from '$lib/components/Card.svelte';
	import TextField from '$lib/components/TextField.svelte';

	/**
	 * The one control in this window that makes a scrub reversible.
	 *
	 * Collected here, before the run, rather than offered on the result screen:
	 * the engine writes the key file inside the `scrub` request, which is what
	 * keeps the placeholder-to-value mapping from ever crossing the pipe into the
	 * window. So the choice has to exist before the request is sent.
	 *
	 * Holds no rules. Whether a key file is possible comes from
	 * `capabilities.mapping_available`, whether the passphrase is long enough is
	 * re-checked and refused by the engine, and where the file may go is the
	 * engine's `refuse_inside`. The checks below only stop the user reaching a
	 * refusal they could have been told about first.
	 */

	const m = $derived(i18n.m);

	const available = $derived(keyFileAvailable());
	const blocker = $derived(keyFileBlocker());
	const passphraseError = $derived(
		blocker === 'passphrase'
			? m.keyFileNeedsPassphrase({ min: MIN_PASSPHRASE })
			: blocker === 'mismatch'
				? m.keyFileMismatch()
				: undefined
	);
</script>

<Card padding="tight">
	{#snippet header()}
		<h3>{m.keyFileTitle()}</h3>
	{/snippet}

	<p class="hint">{m.keyFileHint()}</p>

	{#if available}
		<label class="toggle">
			<input type="checkbox" bind:checked={session.keyWanted} />
			<span>{m.keyFileEnable()}</span>
		</label>

		{#if session.keyWanted}
			<!--
				Said where the decision is made, not on the result screen afterwards.
				A warning that arrives after the file exists is a warning about
				something the reader has already done.
			-->
			<Callout tone="warn">
				<p>{m.keyFileDanger()}</p>
			</Callout>

			<div class="where">
				<span class="label">{m.keyFileWhere()}</span>
				{#if session.keyDir}
					<span class="mono path">{session.keyDir}</span>
				{/if}
				<Button variant="secondary" icon="folder-open" onclick={pickKeyDirectory}>
					{m.keyFileChooseWhere()}
				</Button>
			</div>
			{#if blocker === 'directory'}
				<p class="error">{m.keyFileNeedsDirectory()}</p>
			{/if}

			<!--
				type="password" through `...rest`, which TextField spreads last. The
				two fields are separate because a mistyped passphrase on a file
				nothing else can open is unrecoverable, and the engine cannot check it
				for us: it never sees the value again.
			-->
			<TextField
				type="password"
				autocomplete="new-password"
				label={m.keyFilePassphrase()}
				bind:value={session.keyPassphrase}
			/>
			<TextField
				type="password"
				autocomplete="new-password"
				label={m.keyFileConfirm()}
				error={passphraseError}
				bind:value={session.keyConfirm}
			/>
		{/if}
	{:else}
		<!-- Disabled rather than offered and then refused, which is the failure
		     `ocr_unavailable_reason` exists to prevent one feature over. The engine's
		     own sentence says which half is missing, so it is quoted. -->
		<p class="error">{m.keyFileUnavailable()}</p>
		{#if session.caps?.mapping_unavailable_reason}
			<p class="hint" lang="en">{session.caps.mapping_unavailable_reason}</p>
		{/if}
	{/if}
</Card>

<style>
	.hint {
		font-size: var(--text-sm);
		color: var(--text-2);
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

	.where {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: var(--space-3) 0;
	}

	.label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
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

	.error {
		font-size: var(--text-sm);
		color: var(--danger-text);
	}

	.mono {
		font-family: var(--font-mono);
	}
</style>
