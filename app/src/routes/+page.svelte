<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { goTo, session, start, type Step } from '$lib/app.svelte';
	import { announce } from '$lib/announce.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import Callout from '$lib/components/Callout.svelte';
	import ProgressBar from '$lib/components/Progress.svelte';
	import StepRail from '$lib/components/StepRail.svelte';
	import FileStep from '$lib/screens/FileStep.svelte';
	import ResultStep from '$lib/screens/ResultStep.svelte';
	import ReviewStep from '$lib/screens/ReviewStep.svelte';

	/**
	 * The orchestrator: which step is showing, what may be reached, and the
	 * terminal failure. Everything else belongs to a screen or to the session.
	 *
	 * No route per step. The wizard state is not addressable — there is no
	 * document to deep-link to — and a route change would drop the in-memory
	 * Inspection, which cost a PDF extraction to obtain.
	 */

	const m = $derived(i18n.m);

	let teardown: (() => void) | null = null;
	let main: HTMLElement | undefined = $state();

	onMount(() => {
		void start().then((stop) => (teardown = stop));
	});

	onDestroy(() => {
		teardown?.();
		teardown = null;
	});

	/**
	 * Reachability is derived, never stored.
	 *
	 * A step the user cannot be on cannot be the current one, and two sources for
	 * that fact is a window showing the review screen with nothing to review.
	 */
	const reachable = $derived<Record<Step, boolean>>({
		file: true,
		review: session.files.length > 0,
		result: session.results.length > 0
	});

	const step = $derived<Step>(reachable[session.step] ? session.step : 'file');

	const labels = $derived<Record<Step, string>>({
		file: m.stepFile(),
		review: m.stepReview(),
		result: m.stepResult()
	});

	const order: Step[] = ['file', 'review', 'result'];

	/*
	 * A step change is the SPA equivalent of a page load, and neither of the two
	 * things a page load does happens by itself: focus does not move, and nothing
	 * is announced. Both are done here, and the heading is found by query rather
	 * than by a ref threaded through three components — each screen owns its own
	 * <h2 tabindex="-1"> for exactly this.
	 */
	let announced: Step | null = null;
	$effect(() => {
		if (announced === step) return;
		announced = step;
		announce(
			m.stepAnnounce({
				position: order.indexOf(step) + 1,
				total: order.length,
				name: labels[step]
			})
		);
		requestAnimationFrame(() => main?.querySelector<HTMLElement>('h2[tabindex="-1"]')?.focus());
	});

	/** 1, 2, 3 jump between steps. Ignored inside a field, and with a modifier. */
	function onKeydown(event: KeyboardEvent) {
		if (event.metaKey || event.ctrlKey || event.altKey) return;
		const target = event.target as HTMLElement | null;
		if (
			target &&
			(target.tagName === 'INPUT' ||
				target.tagName === 'TEXTAREA' ||
				target.tagName === 'SELECT' ||
				target.isContentEditable)
		) {
			return;
		}
		const at = ['1', '2', '3'].indexOf(event.key);
		if (at === -1) return;
		const wanted = order[at];
		if (!reachable[wanted]) return;
		event.preventDefault();
		goTo(wanted);
	}
</script>

<svelte:window onkeydown={onKeydown} />

{#if session.engineProblem}
	<!-- Terminal, and deliberately alone on the screen: every control below it
	     would be a control that cannot work. -->
	<div class="terminal">
		<Callout tone="danger" title={m.engineNotStarted()} live verbatim>
			<p>{session.engineProblem}</p>
		</Callout>
	</div>
{:else}
	<div class="shell">
		<StepRail {reachable} current={step} />

		<main id="main" bind:this={main}>
			{#if session.problem}
				<Callout tone="danger" live verbatim>
					<p>{session.problem}</p>
				</Callout>
			{/if}

			{#if session.progress}
				<!--
					The bar counts files, because that is the only unit the engine
					reports. No percentage: how long detect takes next to extract on an
					unseen document is not a fact anyone here has.
				-->
				<div class="progress">
					<ProgressBar
						label={m.progressLabel()}
						value={session.progress.index}
						max={session.progress.total}
						valueText={m.progressFile({
							file: basename(session.progress.file),
							index: session.progress.index + 1,
							total: session.progress.total
						})}
					/>
				</div>
			{/if}

			{#if step === 'file'}
				<FileStep />
			{:else if step === 'review'}
				<ReviewStep />
			{:else}
				<ResultStep />
			{/if}
		</main>
	</div>
{/if}

<style>
	.shell {
		display: grid;
		grid-template-columns: 15rem minmax(0, 1fr);
		align-items: start;
		min-height: calc(100vh - 3rem);
	}

	/* One column where a 15rem rail stops leaving room to read. No container
	   queries: the oldest webview this app claims does not have them. */
	@media (max-width: 52rem) {
		.shell {
			grid-template-columns: minmax(0, 1fr);
		}
	}

	main {
		padding: var(--space-5) var(--space-6) var(--space-8);
		max-width: 76rem;
	}

	.terminal {
		max-width: 42rem;
		margin: var(--space-8) auto;
		padding: 0 var(--space-4);
	}

	.progress {
		margin-bottom: var(--space-4);
	}
</style>
