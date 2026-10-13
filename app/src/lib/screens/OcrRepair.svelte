<script lang="ts">
	import { installOcr, locateTesseract, recheck, session } from '$lib/app.svelte';
	import { announce } from '$lib/announce.svelte';
	import { copyText } from '$lib/clipboard';
	import { i18n } from '$lib/i18n/index.svelte';
	import { ocrAction } from '$lib/setup';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';

	/**
	 * Every way this window can get OCR working, in one place: Install where the
	 * engine will run the line, Copy where it will only name it, and Locate and
	 * Check again everywhere. Shared by the first-run list and the file step so the
	 * two cannot offer different repairs for the same missing binary.
	 *
	 * Which of those appears is `ocrAction`, read from three fields the engine
	 * published. Gated on those and never on a check's name - reading
	 * `check.name === 'OCR'` would be the window holding a rule about the engine's
	 * wording, the mistake it already made once with a colon in a detector string.
	 */

	const m = $derived(i18n.m);
	const action = $derived(session.caps ? ocrAction(session.caps) : 'locate');
	const command = $derived(session.caps?.ocr_install_command ?? null);
	const busy = $derived(session.installing || session.rechecking);

	let copied = $state(false);
	let copyFailed = $state(false);

	async function copyCommand(): Promise<void> {
		if (!command) return;
		const worked = await copyText(command);
		copyFailed = !worked;
		copied = worked;
		if (worked) {
			announce(m.copied());
			setTimeout(() => (copied = false), 1500);
		}
	}
</script>

{#if action !== 'ready'}
	<div class="repair">
		{#if command && (action === 'install' || action === 'copy')}
			<!-- The exact line, always visible before anything runs: the engine
			     executes these words and no others, and a button that ran something
			     the reader could not see is the shape M17 refused. -->
			<p class="command">
				<code lang="en">{command}</code>
				{#if action === 'install'}
					<Button
						variant="primary"
						size="sm"
						loading={session.installing}
						disabled={busy && !session.installing}
						onclick={installOcr}
					>
						{m.ocrInstall()}
					</Button>
				{:else}
					<Button variant="ghost" size="sm" onclick={copyCommand}>
						{copyFailed ? m.copyUnavailable() : copied ? m.copied() : m.copyFix()}
					</Button>
				{/if}
			</p>
			<p class="hint">{action === 'install' ? m.ocrInstallNote() : m.ocrCopyNote()}</p>
		{/if}
		<div class="actions">
			<Button
				variant="secondary"
				size="sm"
				loading={session.rechecking}
				disabled={session.installing}
				onclick={recheck}
			>
				{m.diagnosticsRecheck()}
			</Button>
			<Button variant="secondary" size="sm" disabled={busy} onclick={locateTesseract}>
				{m.locateTesseract()}
			</Button>
		</div>
		<p class="hint">{m.locateTesseractHint()}</p>
		{#if session.installFailure}
			<!-- The installer's own words, quoted: Homebrew's error is the only account
			     of what went wrong, and a translation would be a guess about it. -->
			<Callout tone="danger" title={m.ocrInstallFailedTitle()} live verbatim>
				<p class="failure">{session.installFailure}</p>
			</Callout>
		{/if}
		{#if session.tesseractRefusal}
			<!-- The engine's refusal, by key. An enum, so it is said in the reader's
			     language rather than quoted. -->
			<Callout tone="warn" live>
				<p>
					{session.tesseractRefusal in m.tesseractRefusal
						? m.tesseractRefusal[session.tesseractRefusal]()
						: m.tesseractRefusalOther()}
				</p>
			</Callout>
		{/if}
	</div>
{/if}

<style>
	.repair {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.command {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}

	code {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-1);
		background: var(--bg-subtle);
		overflow-wrap: anywhere;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.hint {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.failure {
		white-space: pre-wrap;
		font-family: var(--font-mono);
		font-size: var(--text-xs);
	}
</style>
