<script lang="ts">
	import { session } from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import OcrRepair from './OcrRepair.svelte';

	/**
	 * What else this computer has, on the first-run screen, beside the model the
	 * rest of that screen is about.
	 *
	 * Two rows, and each state is the engine's answer: `ocr_available` for the
	 * first, the models a running Ollama reported for the second. The review row
	 * has no action on purpose - it is optional, it is gigabytes, and the window
	 * never installs it - so it says what it would add and nothing more.
	 */

	const m = $derived(i18n.m);
	const ocrReady = $derived(session.caps?.ocr_available ?? false);
	const reviewReady = $derived((session.caps?.review_models.length ?? 0) > 0);
</script>

{#if session.caps}
	<section class="deps" aria-labelledby="deps-title">
		<h3 id="deps-title">{m.setupListTitle()}</h3>
		<ul>
			<li>
				<span class="mark" class:ok={ocrReady}>
					<Icon name={ocrReady ? 'check' : 'alert-triangle'} size={14} />
				</span>
				<div class="body">
					<p class="name">
						{m.depOcr()}
						<Badge tone={ocrReady ? 'success' : 'warn'}>
							{ocrReady ? m.depReady() : m.depMissing()}
						</Badge>
					</p>
					{#if !ocrReady}
						<p class="why">{m.depOcrWhy()}</p>
						<OcrRepair />
					{/if}
				</div>
			</li>
			<li>
				<span class="mark" class:ok={reviewReady}>
					<Icon name={reviewReady ? 'check' : 'info'} size={14} />
				</span>
				<div class="body">
					<p class="name">
						{m.depReview()}
						<Badge tone={reviewReady ? 'success' : 'neutral'}>
							{reviewReady ? m.depReady() : m.depOptional()}
						</Badge>
					</p>
					{#if !reviewReady}
						<p class="why">{m.depReviewWhy()}</p>
					{/if}
				</div>
			</li>
		</ul>
	</section>
{/if}

<style>
	.deps {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-top: var(--space-4);
		border-top: 1px solid var(--border);
	}

	h3 {
		margin: 0;
		font-size: var(--text-sm);
		font-weight: var(--weight-semibold);
		color: var(--text-2);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
	}

	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	li {
		display: flex;
		gap: var(--space-2);
		align-items: flex-start;
	}

	.mark {
		flex: none;
		margin-top: 3px;
		color: var(--warn-text);
	}

	.mark.ok {
		color: var(--success-text);
	}

	.body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.name {
		margin: 0;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		font-weight: var(--weight-medium);
	}

	.why {
		margin: 0;
		font-size: var(--text-sm);
		color: var(--text-2);
	}
</style>
