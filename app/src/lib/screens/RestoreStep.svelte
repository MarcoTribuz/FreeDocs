<script lang="ts">
	import {
		pickRestoreFile,
		pickRestoreMap,
		restoreBlocker,
		runRestore,
		session
	} from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import Button from '$lib/components/Button.svelte';
	import Card from '$lib/components/Card.svelte';
	import TextField from '$lib/components/TextField.svelte';

	/**
	 * Pick what came back from the model, and the key file that opens it.
	 *
	 * One document, not a list, because a key file describes one document. Sending
	 * a batch would either apply one map to several documents — the mistake
	 * `Override.for_path` exists to prevent one feature over — or need a map per
	 * path and stop being one request.
	 */

	const m = $derived(i18n.m);
	const blocker = $derived(restoreBlocker());
	let heading: HTMLHeadingElement | undefined = $state();
</script>

<div class="head">
	<h2 bind:this={heading} tabindex="-1">{m.restoreTitle()}</h2>
</div>

<p class="lede">{m.restoreHint()}</p>

<Card>
	<div class="row">
		<span class="label">{m.restoreDocument()}</span>
		{#if session.restoreFile}
			<span class="chosen" title={session.restoreFile}>{basename(session.restoreFile)}</span>
		{:else}
			<span class="missing">{m.restoreNeedsDocument()}</span>
		{/if}
		<Button variant="secondary" icon="file-text" onclick={pickRestoreFile}>
			{m.restoreChooseDocument()}
		</Button>
	</div>

	<div class="row">
		<span class="label">{m.restoreKey()}</span>
		{#if session.restoreMap}
			<span class="chosen" title={session.restoreMap}>{basename(session.restoreMap)}</span>
		{:else}
			<span class="missing">{m.restoreNeedsKey()}</span>
		{/if}
		<Button variant="secondary" icon="folder-open" onclick={pickRestoreMap}>
			{m.restoreChooseKey()}
		</Button>
	</div>

	<!-- Held for the request and cleared in a `finally`. There is nowhere for it to
	     be persisted to: unlike the theme and the locale, this never touches
	     localStorage. -->
	<TextField
		type="password"
		autocomplete="off"
		label={m.restorePassphrase()}
		error={blocker === 'passphrase' && session.restoreMap ? m.restoreNeedsPassphrase() : undefined}
		bind:value={session.restorePassphrase}
		onEnter={() => !blocker && runRestore()}
	/>

	<div class="go">
		<Button icon="shield-check" disabled={blocker !== null || session.busy !== null} onclick={runRestore}>
			{session.busy === 'restore' ? m.restoring() : m.restoreRun()}
		</Button>
	</div>
</Card>

{#if session.caps?.restore_caveats.length}
	<!-- The engine's own words, quoted rather than paraphrased: report.RESTORE_CAVEATS
	     is where they are maintained, and a second wording here would drift from the
	     one that reaches the JSON report. -->
	<section class="caveats">
		<h3>{m.restoreCaveatsTitle()}</h3>
		<p class="quoted">{m.quotedFromEngine()}</p>
		<ul lang="en">
			{#each session.caps.restore_caveats as caveat (caveat)}
				<li>{caveat}</li>
			{/each}
		</ul>
	</section>
{/if}

<style>
	.head {
		margin-bottom: var(--space-2);
	}

	.lede {
		max-width: 42rem;
		margin-bottom: var(--space-4);
		color: var(--text-2);
	}

	.row {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: var(--space-3);
		padding-bottom: var(--space-3);
		margin-bottom: var(--space-3);
		border-bottom: 1px solid var(--border);
	}

	.label {
		min-width: 12rem;
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}

	.chosen {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
	}

	.missing {
		flex: 1;
		min-width: 0;
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	.go {
		margin-top: var(--space-4);
	}

	.caveats {
		margin-top: var(--space-5);
		max-width: 46rem;
	}

	.caveats h3 {
		font-size: var(--text-sm);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
		margin-bottom: var(--space-2);
	}

	.quoted {
		font-size: var(--text-xs);
		color: var(--text-3);
		margin-bottom: var(--space-2);
	}

	.caveats ul {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-left: var(--space-4);
		font-size: var(--text-sm);
		color: var(--text-2);
	}
</style>
