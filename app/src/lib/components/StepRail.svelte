<script lang="ts">
	import { clearFiles, goTo, removeFile, select, session, type Step } from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename } from '$lib/format';
	import Button from './Button.svelte';
	import Icon from './Icon.svelte';

	interface Props {
		/** Which steps can be entered. Derived by the page, never stored. */
		reachable: Record<Step, boolean>;
		current: Step;
	}

	let { reachable, current }: Props = $props();

	const m = $derived(i18n.m);

	const steps = $derived<{ id: Step; label: string; locked?: string }[]>([
		{ id: 'file', label: m.stepFile() },
		{ id: 'review', label: m.stepReview(), locked: m.stepReviewLocked() },
		{ id: 'result', label: m.stepResult(), locked: m.stepResultLocked() }
	]);
</script>

<nav class="rail" aria-label={m.stepsLabel()}>
	<ol class="steps">
		{#each steps as step, index (step.id)}
			{@const open = reachable[step.id]}
			<li>
				<!--
					An unreachable step stays visible and says why. Hiding it would make
					the shape of the task unlearnable from an empty window, which is the
					one moment a person is trying to learn it.
				-->
				<button
					type="button"
					class="step"
					class:on={current === step.id}
					aria-current={current === step.id ? 'step' : undefined}
					aria-disabled={open ? undefined : 'true'}
					aria-describedby={open ? undefined : `locked-${step.id}`}
					onclick={() => open && goTo(step.id)}
				>
					<span class="number" aria-hidden="true">{index + 1}</span>
					<span class="label">{step.label}</span>
				</button>
				{#if !open && step.locked}
					<p class="locked" id={`locked-${step.id}`}>{step.locked}</p>
				{/if}
			</li>
		{/each}
	</ol>

	{#if session.files.length}
		<div class="files">
			<h2 class="heading">
				{m.filesTitle()}
				{#if session.files.length > 1}
					<Button variant="link" onclick={clearFiles}>{m.clearFiles()}</Button>
				{/if}
			</h2>
			<!--
				One document at a time in the review pane, with this as the selector.
				That is the engine's model, not a simplification of it: a kept span is
				an offset into one extraction, so "this occurrence" only means anything
				within one file. See Override.for_path.
			-->
			<ul class="filelist">
				{#each session.files as path (path)}
					{@const inspection = session.inspections[path]}
					<li>
						<button
							type="button"
							class="file"
							class:on={session.activePath === path}
							aria-current={session.activePath === path ? 'true' : undefined}
							onclick={() => {
								select(path);
								goTo('review');
							}}
						>
							<span class="name">{basename(path)}</span>
							<span class="count">
								{#if session.busy === path}
									…
								{:else if inspection}
									{inspection.findings.length}
								{/if}
							</span>
						</button>
						<button
							type="button"
							class="drop"
							aria-label={m.removeFile({ file: basename(path) })}
							onclick={() => removeFile(path)}
						>
							<Icon name="x" size={12} />
						</button>
					</li>
				{/each}
			</ul>
		</div>
	{/if}
</nav>

<style>
	.rail {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		padding: var(--space-4);
		border-right: 1px solid var(--border);
		background: var(--bg-subtle);
		min-height: 100%;
	}

	.steps {
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.step {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding: var(--space-2) var(--space-3);
		border: 0;
		border-radius: var(--radius-2);
		background: none;
		color: var(--text-2);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		font-weight: var(--weight-medium);
		text-align: left;
		cursor: pointer;
		transition:
			background var(--dur-1) var(--ease-out),
			color var(--dur-1) var(--ease-out);
	}
	.step:hover:not([aria-disabled='true']) {
		background: var(--surface-hover);
		color: var(--text);
	}
	.step.on {
		background: var(--surface);
		color: var(--text);
		box-shadow: var(--shadow-1);
	}
	.step[aria-disabled='true'] {
		color: var(--text-3);
		cursor: default;
	}

	.number {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.25rem;
		height: 1.25rem;
		border-radius: var(--radius-full);
		background: var(--surface-active);
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
	}
	.step.on .number {
		background: var(--accent);
		color: var(--on-accent);
	}

	.locked {
		margin: 0 0 var(--space-1) calc(var(--space-3) + 1.75rem);
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.heading {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-2);
		margin-bottom: var(--space-2);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	.filelist {
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.filelist li {
		display: flex;
		align-items: center;
		gap: 2px;
	}

	.file {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-2);
		flex: 1;
		min-width: 0;
		padding: var(--space-1) var(--space-2);
		border: 0;
		border-radius: var(--radius-1);
		background: none;
		color: var(--text-2);
		font-family: var(--font-sans);
		font-size: var(--text-sm);
		text-align: left;
		cursor: pointer;
	}
	.file:hover {
		background: var(--surface-hover);
		color: var(--text);
	}
	.file.on {
		background: var(--surface);
		color: var(--text);
		box-shadow: inset 0 0 0 1px var(--accent-border);
	}

	.name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.count {
		font-variant-numeric: tabular-nums;
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.drop {
		display: flex;
		padding: var(--space-1);
		border: 0;
		border-radius: var(--radius-1);
		background: none;
		color: var(--text-3);
		cursor: pointer;
	}
	.drop:hover {
		background: var(--danger-soft);
		color: var(--danger-text);
	}
</style>
