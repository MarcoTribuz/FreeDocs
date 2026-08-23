<script lang="ts">
	import { session } from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import Icon from '$lib/components/Icon.svelte';

	const m = $derived(i18n.m);

	/**
	 * Open when there is something wrong, closed when there is not.
	 *
	 * Seeded once rather than bound: expanding a panel the user has just collapsed
	 * is worse than the click it saves. Same reasoning as the Ollama panel, and
	 * the same failure it avoids — a build that can do less has to say so without
	 * being asked, and a build that can do everything should not nag.
	 */
	let open = $state(false);
	let seeded = false;
	$effect(() => {
		if (seeded || !session.diagnostics) return;
		seeded = true;
		open = !session.diagnostics.checks.every((check) => check.ok);
	});

	const problems = $derived(
		(session.diagnostics?.checks ?? []).filter((check) => !check.ok).length
	);
</script>

{#if session.diagnostics}
	<Disclosure bind:open summary={m.diagnosticsTitle()} count={problems || undefined}>
		{#if problems === 0}
			<p class="hint">{m.diagnosticsOk()}</p>
		{/if}
		<ul class="checks">
			{#each session.diagnostics.checks as check (check.name)}
				<li>
					<span class="mark" class:bad={!check.ok} class:degraded={check.degraded}>
						<Icon name={check.ok ? 'check' : 'alert-triangle'} size={13} />
					</span>
					<div>
						<p class="name">
							{check.name}
							{#if !check.ok}
								<!-- `degraded` is the engine's own distinction: not ok, but not
								     required. A machine with no Tesseract is a normal machine, and
								     a panel that calls that an error trains people to ignore the
								     panel. -->
								<Badge tone={check.degraded ? 'warn' : 'danger'}>
									{check.degraded ? m.diagnosticsDegraded() : m.diagnosticsBroken()}
								</Badge>
							{/if}
						</p>
						<!-- The engine's wording, quoted. It is composed from what this
						     machine actually has, so translating it would be inventing a
						     second answer about a fact only Python checked. -->
						<p class="detail" lang="en">{check.detail}</p>
						{#if check.fix}
							<!--
								`Check.fix` was written to tell a person what to run and, until
								this panel, only a terminal could see it.

								Known defect, stated rather than hidden: inside a packaged app
								`uv sync --extra ner` means nothing. It is still shown verbatim,
								because a second set of app-facing strings would be two answers
								to one question — making the fixes aware of a frozen build is a
								follow-up with its own test.
							-->
							<p class="fix">
								<span class="label">{m.diagnosticsFix()}</span>
								<code lang="en">{check.fix}</code>
							</p>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	</Disclosure>
{/if}

<style>
	.hint {
		margin-bottom: var(--space-2);
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	.checks {
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.checks li {
		display: flex;
		gap: var(--space-2);
	}

	.mark {
		display: flex;
		margin-top: 3px;
		color: var(--success-text);
	}
	.mark.degraded {
		color: var(--warn-text);
	}
	.mark.bad:not(.degraded) {
		color: var(--danger-text);
	}

	.name {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}

	.detail {
		font-size: var(--text-xs);
		color: var(--text-3);
		max-width: 46rem;
	}

	.fix {
		margin-top: var(--space-1);
		font-size: var(--text-xs);
	}

	.fix .label {
		margin-right: var(--space-1);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	.fix code {
		padding: 1px var(--space-1);
		border-radius: var(--radius-1);
		background: var(--bg-subtle);
		font-family: var(--font-mono);
	}
</style>
