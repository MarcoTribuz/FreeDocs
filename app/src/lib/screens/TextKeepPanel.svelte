<script lang="ts">
	import {
		keyFileAvailable,
		passphraseMinimum,
		pickKeyDirectory,
		session,
		setTextKeep,
		textKeepBlocker
	} from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Card from '$lib/components/Card.svelte';
	import TextField from '$lib/components/TextField.svelte';

	/**
	 * What becomes of the mapping, chosen per text before the scrub: nothing (the
	 * default, irreversible like every scrub), held by the engine until the text is
	 * closed, or sealed into a key file. The engine enforces it through
	 * `keep_map` and `map`; this only relays the choice, and never remembers it -
	 * a remembered "keep" is a default nobody chose.
	 */

	const m = $derived(i18n.m);
	const blocker = $derived(textKeepBlocker());
	const passphraseError = $derived(
		blocker === 'passphrase'
			? m.keyFileNeedsPassphrase({ min: passphraseMinimum() })
			: blocker === 'mismatch'
				? m.keyFileMismatch()
				: undefined
	);

	const choices = $derived([
		{ id: 'none' as const, label: m.textKeepNone(), hint: m.textKeepNoneHint(), on: true },
		{ id: 'memory' as const, label: m.textKeepMemory(), hint: m.textKeepMemoryHint(), on: true },
		{
			id: 'file' as const,
			label: m.textKeepFile(),
			hint: m.textKeepFileHint(),
			on: keyFileAvailable()
		}
	]);
</script>

<Card padding="tight">
	{#snippet header()}
		<h3 id="text-keep">{m.textKeepTitle()}</h3>
	{/snippet}

	<div class="choices" role="radiogroup" aria-labelledby="text-keep">
		{#each choices as choice (choice.id)}
			<label class="choice" class:off={!choice.on}>
				<input
					type="radio"
					name="text-keep"
					value={choice.id}
					checked={session.textKeep === choice.id}
					disabled={!choice.on}
					onchange={() => setTextKeep(choice.id)}
				/>
				<span>
					<span class="name">{choice.label}</span>
					<span class="hint">{choice.hint}</span>
				</span>
			</label>
		{/each}
	</div>

	{#if session.textKeep === 'memory'}
		<!-- Said where the choice is made: this is the one mapping the engine keeps
		     past the request that made it. -->
		<Callout tone="info"><p>{m.textKeepMemoryWarning()}</p></Callout>
	{:else if session.textKeep === 'file'}
		<Callout tone="warn"><p>{m.keyFileDanger()}</p></Callout>
		<div class="where">
			<span class="label">{m.keyFileWhere()}</span>
			{#if session.keyDir}<span class="mono path">{session.keyDir}</span>{/if}
			<Button variant="secondary" icon="folder-open" onclick={pickKeyDirectory}>
				{m.keyFileChooseWhere()}
			</Button>
		</div>
		{#if blocker === 'directory'}<p class="error">{m.textKeyNeedsDirectory()}</p>{/if}
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
</Card>

<style>
	.choices {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
	}

	.choice {
		display: flex;
		align-items: flex-start;
		gap: var(--space-2);
		cursor: pointer;
	}

	.choice.off {
		cursor: not-allowed;
		color: var(--text-3);
	}

	.choice input {
		margin-top: 0.2rem;
	}

	.name {
		display: block;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}

	.hint {
		display: block;
		font-size: var(--text-xs);
		color: var(--text-2);
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
