<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { fly } from 'svelte/transition';
	import { ORDER, goTo, locateTesseract, session, start, type Step } from '$lib/app.svelte';
	import { NEEDS_OCR } from '$lib/engine';
	import Button from '$lib/components/Button.svelte';
	import { announce } from '$lib/announce.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import { DUR, duration } from '$lib/motion';
	import Callout from '$lib/components/Callout.svelte';
	import ProgressBar from '$lib/components/Progress.svelte';
	import StepRail from '$lib/components/StepRail.svelte';
	import FileStep from '$lib/screens/FileStep.svelte';
	import ResultStep from '$lib/screens/ResultStep.svelte';
	import RestoreResult from '$lib/screens/RestoreResult.svelte';
	import RestoreStep from '$lib/screens/RestoreStep.svelte';
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
	const reachable = $derived<Record<Step, boolean>>(
		session.mode === 'restore'
			? // Restoring has no review step: the decisions were made in the scrub
				// that produced the key file, and there is nothing here to preview.
				{ file: true, review: false, result: session.restoreResult !== null }
			: {
					file: true,
					review: session.files.length > 0,
					result: session.results.length > 0
				}
	);

	const step = $derived<Step>(reachable[session.step] ? session.step : 'file');

	const labels = $derived<Record<Step, string>>({
		file: session.mode === 'restore' ? m.stepRestoreFile() : m.stepFile(),
		review: m.stepReview(),
		result: m.stepResult()
	});

	/**
	 * The steps of the mode showing. Per mode, so the position announced is the
	 * position in *this* task — "step 2 of 2" when restoring, not "2 of 3" with one
	 * step that does not exist.
	 */
	const order = $derived<Step[]>(ORDER[session.mode]);

	/*
	 * A step change is the SPA equivalent of a page load, and neither of the two
	 * things a page load does happens by itself: focus does not move, and nothing
	 * is announced. Both are done here, and the heading is found by query rather
	 * than by a ref threaded through three components — each screen owns its own
	 * <h2 tabindex="-1"> for exactly this.
	 */
	let announced: string | null = null;
	$effect(() => {
		// Keyed on the mode too: switching direction lands on `file` in both, so a
		// key of the step alone would announce nothing at the moment the whole task
		// changed.
		const now = `${session.mode}/${step}`;
		if (announced === now) return;
		announced = now;
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
		// `order` is shorter when restoring, so 3 addresses nothing there rather
		// than falling through to a step this mode does not have.
		if (!wanted || !reachable[wanted]) return;
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
					{#if session.problemCode === NEEDS_OCR}
						<!--
							The repair, offered where the failure happened. A refused scan is
							the moment the user cares about OCR, and until now this message
							was a dead end with the fix behind a disclosure on another
							screen.

							The code decides that the controls appear; it never touches what
							the message says. `describe()` still passes the engine's sentence
							through untouched, because that sentence already names the pages
							and what to install — a preamble in front of it would be the
							window competing with a complete answer.
						-->
						<div class="repair">
							<Button
								variant="secondary"
								size="sm"
								loading={session.rechecking}
								onclick={locateTesseract}
							>
								{i18n.m.locateTesseract()}
							</Button>
						</div>
					{/if}
				</Callout>
			{/if}

			{#if session.progress || session.stage}
				<!--
					Two bars, because the engine counts two different things and
					conflating them would mean inventing a number. The outer one counts
					files, which is what `progress` reports. The inner one counts stages
					inside one file, or pages inside the stage that has them — and it is
					`indeterminate` where the stage has no unit, rather than showing a
					fraction nobody measured.

					No percentage in either: how long detection takes next to extraction
					on an unseen document is not a fact anyone here has.
				-->
				<div class="progress">
					{#if session.progress}
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
					{/if}
					{#if session.stage}
						{@const stage = session.stage}
						{@const named = m.stage[stage.stage]?.() ?? stage.stage}
						<ProgressBar
							label={named}
							value={stage.done ?? stage.index}
							max={stage.of ?? stage.count}
							indeterminate={stage.done === undefined && stage.of === undefined}
							valueText={stage.of !== undefined && stage.done !== undefined
								? `${named} — ${m.stagePages({ done: stage.done, of: stage.of })}`
								: m.stageOf({ name: named, index: stage.index, count: stage.count })}
						/>
					{/if}
				</div>
			{/if}

			<!--
				One transition, on the thing that changed. `duration()` returns zero for
				a reader who asked for less motion — a Svelte transition animates in
				JavaScript, so the media query the stylesheet honours in one rule has to
				be asked explicitly here.

				Keyed on the step so the old screen leaves and the new one arrives,
				rather than the contents cross-fading in place.
			-->
			{#key `${session.mode}/${step}`}
				<div in:fly={{ y: 8, duration: duration(DUR.slow) }}>
					{#if session.mode === 'restore'}
						{#if step === 'result'}
							<RestoreResult />
						{:else}
							<RestoreStep />
						{/if}
					{:else if step === 'file'}
						<FileStep />
					{:else if step === 'review'}
						<ReviewStep />
					{:else}
						<ResultStep />
					{/if}
				</div>
			{/key}
		</main>
	</div>
{/if}

<style>
	/* The repair sits under the engine's sentence, which is quoted English; the
	   button's own label is in the reader's language and is outside that region. */
	.repair {
		margin-top: var(--space-2);
	}

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
