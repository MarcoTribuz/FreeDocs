<script lang="ts">
	import { onMount } from 'svelte';
	import { session } from '$lib/app.svelte';
	import { eta, megabytes } from '$lib/download';
	import { i18n } from '$lib/i18n/index.svelte';
	import { closeModel, deferModel, fetchModel, model } from '$lib/model.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import Logo from '$lib/components/Logo.svelte';
	import ProgressBar from '$lib/components/Progress.svelte';
	import SetupList from './SetupList.svelte';

	/**
	 * The first thing a new user sees, and the one screen that reaches the
	 * network. It is built against one failure: a window that goes quiet for
	 * minutes - or, on Windows, a console nobody explained - reads as broken, and
	 * the user closes it. So every state says what is happening, how much is
	 * left, and what does not happen: no document is read or sent.
	 *
	 * The bar fills in proportion because the engine reports bytes, a real unit.
	 * The time left is worked out from the rate actually observed and shown only
	 * once there is one; see `download.ts`.
	 */

	const m = $derived(i18n.m);
	let heading: HTMLHeadingElement | undefined = $state();

	// A phase change is a new screen: focus moves to its heading, as the steps do.
	$effect(() => {
		void model.phase;
		requestAnimationFrame(() => heading?.focus());
	});

	onMount(() => heading?.focus());

	const left = $derived(eta(model.samples, model.of));
	const progressText = $derived.by(() => {
		if (model.of <= 0) return m.modelDownloadingTitle();
		const bytes = m.modelBytes({
			done: megabytes(model.done, i18n.locale),
			of: megabytes(model.of, i18n.locale)
		});
		if (left === null) return bytes;
		const time =
			left === 'under-minute' ? m.modelEtaUnderMinute() : m.modelEtaMinutes(left);
		return `${bytes} · ${time}`;
	});

	/**
	 * The example's placeholders, from the engine's allocator through the entity
	 * list, so the screen cannot promise a placeholder the scrub will not write.
	 * Without the list the example is not shown at all rather than guessed.
	 */
	const sample = $derived.by(() => {
		const placeholder = (name: string) =>
			session.entityList.find((entity) => entity.name === name)?.placeholder;
		const person = placeholder('PERSON');
		const organisation = placeholder('ORGANISATION');
		const address = placeholder('ADDRESS');
		if (!person || !organisation || !address) return null;
		return { before: m.modelSampleBefore(), after: m.modelSampleAfter({ person, organisation, address }) };
	});
</script>

<div class="first-run">
	<div class="card">
		<p class="eyebrow"><Logo size={28} /><span>{m.firstRunEyebrow()}</span></p>

		{#if model.phase === 'ask'}
			<h2 bind:this={heading} tabindex="-1">{m.modelAskTitle()}</h2>
			<p class="lead">{m.modelAskLead()}</p>
			<ul class="facts">
				<li><Icon name="info" size={16} /><span>{m.modelFactSize()}</span></li>
				<li><Icon name="shield-check" size={16} /><span>{m.modelFactPrivate()}</span></li>
				<li><Icon name="check" size={16} /><span>{m.modelFactOffline()}</span></li>
			</ul>
			<div class="actions">
				<!-- Disabled during a Tesseract install: the engine serves one request
				     at a time, so a download pressed now would only queue behind it. -->
				<Button variant="primary" disabled={session.installing} onclick={fetchModel}>
					{m.modelDownload()}
				</Button>
				<Button variant="ghost" disabled={session.installing} onclick={deferModel}>
					{m.modelNotNow()}
				</Button>
			</div>
			<p class="note">{m.modelWithout()}</p>
			<SetupList />
		{:else if model.phase === 'downloading'}
			<h2 bind:this={heading} tabindex="-1">{m.modelDownloadingTitle()}</h2>
			<ProgressBar
				label={m.modelDownloadingTitle()}
				value={model.done}
				max={model.of || 1}
				indeterminate={model.of <= 0}
				valueText={progressText}
			/>
			<p class="note">{m.modelKeepOpen()}</p>
			{#if sample}
				<!-- Something worth reading while the bar moves: what the wait is for. -->
				<figure class="sample">
					<figcaption>{m.modelSampleTitle()}</figcaption>
					<p><span class="tag">{m.modelBefore()}</span>{sample.before}</p>
					<p><span class="tag after">{m.modelAfter()}</span>{sample.after}</p>
				</figure>
			{/if}
		{:else if model.phase === 'preparing'}
			<h2 bind:this={heading} tabindex="-1">{m.modelPreparingTitle()}</h2>
			<ProgressBar
				label={m.modelPreparingTitle()}
				indeterminate
				valueText={m.modelPreparingLead()}
			/>
		{:else if model.phase === 'failed'}
			<h2 bind:this={heading} tabindex="-1">{m.modelFailedTitle()}</h2>
			<p class="lead">{m.modelFailedLead()}</p>
			<p class="note">{m.modelFailedProxy()}</p>
			{#if model.problem}
				<Callout tone="danger" verbatim><p>{model.problem}</p></Callout>
			{/if}
			<div class="actions">
				{#if model.retryable}
					<Button variant="primary" onclick={fetchModel}>{m.modelRetry()}</Button>
				{/if}
				<Button variant={model.retryable ? 'ghost' : 'primary'} onclick={deferModel}>
					{m.modelNotNow()}
				</Button>
			</div>
		{:else if model.phase === 'ready'}
			<h2 bind:this={heading} tabindex="-1">{m.modelReadyTitle()}</h2>
			<p class="lead">{m.modelReadyLead()}</p>
			<SetupList />
			<div class="actions">
				<Button variant="primary" icon="arrow-right" onclick={closeModel}>
					{m.modelChooseDocument()}
				</Button>
			</div>
		{:else if model.phase === 'setup'}
			<!-- The model is here; something else is not. Opened once, never again
			     after Continue - see `offerSetup`. -->
			<h2 bind:this={heading} tabindex="-1">{m.setupTitle()}</h2>
			<p class="lead">{m.setupLead()}</p>
			<SetupList />
			<div class="actions">
				<Button
					variant="primary"
					icon="arrow-right"
					disabled={session.installing}
					onclick={closeModel}
				>
					{m.setupContinue()}
				</Button>
			</div>
		{/if}
	</div>
</div>

<style>
	.first-run {
		display: grid;
		place-items: center;
		min-height: calc(100vh - 3rem);
		padding: var(--space-6) var(--space-4);
	}

	.card {
		width: 100%;
		max-width: 38rem;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.eyebrow {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		color: var(--text-2);
		font-size: var(--text-sm);
	}

	h2 {
		margin: 0;
		outline: none;
	}

	.lead {
		margin: 0;
		color: var(--text-2);
	}

	.facts {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.facts li {
		display: flex;
		gap: var(--space-2);
		align-items: flex-start;
	}

	.facts :global(svg) {
		flex: none;
		margin-top: 3px;
		color: var(--accent);
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.note {
		margin: 0;
		color: var(--text-2);
		font-size: var(--text-sm);
	}

	.sample {
		margin: 0;
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--border);
		border-radius: var(--radius-3);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}

	.sample figcaption {
		font-weight: 600;
	}

	.sample p {
		margin: 0;
		display: flex;
		gap: var(--space-2);
		align-items: baseline;
	}

	.tag {
		flex: none;
		min-width: 4.5rem;
		color: var(--text-2);
	}

	.tag.after {
		color: var(--accent);
	}
</style>
