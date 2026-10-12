<script lang="ts">
	import { goTo, locateTesseract, pickFiles, session, totalFindings } from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Logo from '$lib/components/Logo.svelte';
	import AdvancedPanel from './AdvancedPanel.svelte';
	import TermListPanel from './TermListPanel.svelte';
	import Diagnostics from './Diagnostics.svelte';

	const m = $derived(i18n.m);
	let heading: HTMLHeadingElement | undefined = $state();
</script>

<h2 bind:this={heading} tabindex="-1"><Logo size={36} />{m.appName()}</h2>
<p class="lead">{m.tagline()}</p>

{#if session.caps}
	<section class="status" aria-label={m.capabilitiesLabel()}>
		<Badge>{m.engineVersion({ version: session.caps.version })}</Badge>
		<Badge>{session.caps.layers.join(' + ')}</Badge>
		<Badge tone={session.caps.ocr_available ? 'neutral' : 'warn'}>
			{session.caps.ocr_available ? m.ocrAvailable() : m.ocrMissing()}
		</Badge>
		<!-- The premise of the tool, stated where the capabilities are, because it
		     is one: nothing here reaches a network. -->
		<Badge tone="success">{m.nothingLeaves()}</Badge>
		{#if session.caps.model_source === 'bundled'}
			<!-- Only the bundled case. The engine decides which it is; reading the
			     shape of a path here would be the window holding a rule about how
			     the app was packaged. -->
			<Badge tone="success">{m.modelBundled()}</Badge>
		{/if}
	</section>

	{#if !session.caps.ocr_available && session.caps.ocr_unavailable_reason}
		<!-- The engine has always sent the reason and the window always threw it
		     away, so a scanned PDF was refused with an explanation the user could
		     only see in a terminal. -->
		<Callout tone="warn" title={m.ocrReasonTitle()} verbatim>
			<p>{session.caps.ocr_unavailable_reason}</p>
		</Callout>
		<!--
			Outside the callout above, deliberately: `verbatim` puts `lang="en"` on
			that body, and a translated button label inside it would be announced as
			English.

			Gated on the engine's own `ocr_available`, never on a name match against
			a check — reading `check.name === 'OCR'` would be the window holding a
			rule about the engine's wording, which is the mistake it already made
			once reading a colon in a detector string.
		-->
		<div class="locate">
			<Button
				variant="secondary"
				size="sm"
				loading={session.rechecking}
				onclick={locateTesseract}
			>
				{m.locateTesseract()}
			</Button>
			<p class="hint">{m.locateTesseractHint()}</p>
		</div>
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
	{/if}

	{#if session.caps.limitations.length}
		<!-- A missing layer must be visible. A build that quietly finds less is the
		     failure this project refuses. -->
		<Callout tone="warn" title={m.limitationsTitle()} verbatim>
			{#each session.caps.limitations as limitation (limitation)}<p>{limitation}</p>{/each}
		</Callout>
	{/if}
{/if}

<!--
	A real button, not a section wearing role="button". The hand-rolled handler it
	replaces listened for Enter only, so Space — which every button answers — did
	nothing at all. The drop target is the whole window either way: the Tauri
	drag-and-drop event is subscribed once, in the session.
-->
<button type="button" class="dropzone" class:busy={session.busy !== null} onclick={pickFiles}>
	<p class="dropline"><strong>{m.dropTitle()}</strong>, {m.dropHint()}</p>
	{#if session.caps}<p class="formats">{session.caps.formats.join(' · ')}</p>{/if}
</button>

{#if session.files.length}
	<div class="next">
		<Button variant="primary" icon="arrow-right" onclick={() => goTo('review')}>
			{m.continueToReview()}
		</Button>
		<span class="found">{m.findingCount({ count: totalFindings() })}</span>
	</div>
{/if}

<!--
	Reachable before a document is loaded, which is the whole reason it is here as
	well as on the review screen. The panel it replaced was inside the file list,
	so an empty window looked like a build with no review layer in it at all —
	that was the original complaint, and moving the controls must not reintroduce
	it. Same component, same state: the two are one panel in two places.
-->
<div class="advanced">
	<!-- What this machine can do, with the engine's own fix beside each thing it
	     cannot. Every `Check.fix` was written to be read by a person and until now
	     only a terminal could show one. -->
	<Diagnostics />
	<!-- Before a file is loaded, so the first preview can already use it. -->
	<TermListPanel />
	<AdvancedPanel />
</div>

<style>
	h2 {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		font-size: var(--text-2xl);
		line-height: var(--lh-2xl);
		letter-spacing: var(--tracking-tight);
	}

	.locate {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-2);
	}

	.locate .hint {
		flex: 1 1 20rem;
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.lead {
		max-width: 42rem;
		margin: var(--space-2) 0 var(--space-4);
		color: var(--text-2);
	}

	.status {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin-bottom: var(--space-4);
	}

	.dropzone {
		display: block;
		width: 100%;
		border: 2px dashed var(--border-strong);
		border-radius: var(--radius-4);
		background: var(--surface);
		color: inherit;
		font: inherit;
		text-align: center;
		padding: var(--space-8) var(--space-4);
		cursor: pointer;
		transition:
			border-color var(--dur-2) var(--ease-out),
			background var(--dur-2) var(--ease-out);
	}
	.dropzone:hover {
		border-color: var(--accent-line);
		background: var(--accent-soft);
	}
	.dropzone.busy {
		border-style: solid;
		cursor: default;
	}

	.formats {
		margin-top: var(--space-2);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.next {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-4);
	}

	.found {
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	.advanced {
		margin-top: var(--space-5);
	}
</style>
