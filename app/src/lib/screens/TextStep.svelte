<script lang="ts">
	import { inspectPaste, pastedLength, pasteTooLong, session } from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import Button from '$lib/components/Button.svelte';
	import AdvancedPanel from './AdvancedPanel.svelte';
	import TermListPanel from './TermListPanel.svelte';

	/**
	 * Paste in. The first step of text mode, and the only screen of it that is new:
	 * after Inspect the paste is the review screen's one "file", read through
	 * `inspect_text`, and everything from there is the scrub's own review.
	 *
	 * The count is code points, which is what the engine counts and what its
	 * ceiling is in; `text.length` would disagree by one per emoji.
	 */

	const m = $derived(i18n.m);
	let heading: HTMLHeadingElement | undefined = $state();
	const tooLong = $derived(pasteTooLong());
</script>

<h2 bind:this={heading} tabindex="-1">{m.textTitle()}</h2>
<p class="lead">{m.textHint()}</p>

<label class="paste">
	<span class="label">{m.textLabel()}</span>
	<!-- Held in the window's memory only, never in localStorage; cleared by New
	     text, a mode change and the end of the session. -->
	<textarea
		bind:value={session.pastedText}
		rows="14"
		spellcheck="false"
		placeholder={m.textPlaceholder()}
		aria-invalid={tooLong}
	></textarea>
</label>

<div class="go">
	<span class="count" class:error={tooLong}>
		{tooLong && session.caps
			? m.textTooLong({ max: session.caps.text_max_characters })
			: m.textCount({ count: pastedLength() })}
	</span>
	<Button
		variant="primary"
		icon="search"
		loading={session.busy !== null}
		disabled={!session.pastedText.trim() || tooLong || session.busy !== null}
		onclick={inspectPaste}
	>
		{m.textInspect()}
	</Button>
</div>

<div class="advanced">
	<TermListPanel />
	<AdvancedPanel />
</div>

<style>
	h2 {
		font-size: var(--text-2xl);
		line-height: var(--lh-2xl);
		letter-spacing: var(--tracking-tight);
	}

	.lead {
		max-width: 42rem;
		margin: var(--space-2) 0 var(--space-4);
		color: var(--text-2);
	}

	.paste {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.label {
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
	}

	textarea {
		width: 100%;
		min-height: 14rem;
		resize: vertical;
		padding: var(--space-3);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-3);
		background: var(--surface);
		color: inherit;
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		line-height: 1.5;
	}

	.go {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--space-3);
		margin: var(--space-3) 0 var(--space-5);
	}

	.count {
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	.count.error {
		color: var(--danger-text);
	}

	.advanced {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
</style>
