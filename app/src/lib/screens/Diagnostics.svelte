<script lang="ts">
	import { recheck, session } from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { announce } from '$lib/announce.svelte';
	import { copyText } from '$lib/clipboard';
	import { buildDate } from '$lib/format';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import Icon from '$lib/components/Icon.svelte';

	const m = $derived(i18n.m);

	/**
	 * Which fix was just copied, so one row can say so without the others doing it.
	 *
	 * Keyed by check name, which is already this list's `{#each}` key.
	 */
	let copiedFix = $state<string | null>(null);
	let copyFailed = $state<string | null>(null);

	async function copyFix(name: string, fix: string): Promise<void> {
		const worked = await copyText(fix);
		copyFailed = worked ? null : name;
		copiedFix = worked ? name : null;
		if (worked) {
			announce(m.copied());
			setTimeout(() => {
				if (copiedFix === name) copiedFix = null;
			}, 1500);
		}
	}

	async function askAgain(): Promise<void> {
		await recheck();
		announce(m.announceRechecked());
	}

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
		<!--
			Which engine is answering, shown whether or not anything failed. A stale
			sidecar is not a failing check — it is the wrong engine answering
			correctly, which is exactly why nothing here calls it stale. Both builds
			in the incident this was written for reported version 0.1.0; the route
			and the date are the only facts that tell them apart, and the reader
			draws the conclusion.

			The version comes from the engine and the rest from the shell that
			started it, because only the shell knows which file it launched.
		-->
		<div class="engine">
			<p class="identity">
				<span class="label">{m.engineBuild()}</span>
				<span>{session.diagnostics.version}</span>
				{#if session.engineIdentity}
					<span class="sep">·</span>
					<span>{m.engineSource[session.engineIdentity.source]()}</span>
					<span class="sep">·</span>
					<span>
						{session.engineIdentity.modified === null
							? m.engineBuildDateUnknown()
							: m.engineBuiltOn({
									when: buildDate(session.engineIdentity.modified, i18n.locale)
								})}
					</span>
				{/if}
			</p>
			{#if session.engineIdentity}
				<p class="where" lang="en">{session.engineIdentity.executable}</p>
			{/if}
			<!--
				Inside the body rather than beside the summary: a button within the
				disclosure's trigger button is nested interactive content.
			-->
			<Button
				variant="secondary"
				size="sm"
				loading={session.rechecking}
				onclick={askAgain}
			>
				{m.diagnosticsRecheck()}
			</Button>
		</div>
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

								The fixes are `sys.frozen`-aware in Python: inside a packaged
								build one that would name a virtualenv becomes *absent* rather
								than being rewritten into advice the engine cannot know is
								right. The OCR fix is the exception and deliberately so — a
								system package installs the same way whatever build asked, so
								the engine detects the package manager this machine has and
								names the command.

								Quoted in English and copyable, not run. Spawning a package
								manager from here would put a network call outside everything
								`core/egress.py` can see while `capabilities` went on reporting
								that outbound connections are blocked.
							-->
							<p class="fix">
								<span class="label">{m.diagnosticsFix()}</span>
								<code lang="en">{check.fix}</code>
								<Button
									variant="ghost"
									size="sm"
									onclick={() => copyFix(check.name, check.fix ?? '')}
								>
									{copyFailed === check.name
										? m.copyUnavailable()
										: copiedFix === check.name
											? m.copied()
											: m.copyFix()}
								</Button>
							</p>
						{/if}
					</div>
				</li>
			{/each}
		</ul>
	</Disclosure>
{/if}

<style>
	.engine {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2);
		margin-bottom: var(--space-3);
		padding-bottom: var(--space-3);
		border-bottom: 1px solid var(--border-subtle);
	}

	.identity {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-1);
		font-size: var(--text-xs);
		color: var(--text-2);
	}

	.identity .label {
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	.identity .sep {
		color: var(--text-3);
	}

	.where {
		flex-basis: 100%;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-3);
		overflow-wrap: anywhere;
	}

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
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1);
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
