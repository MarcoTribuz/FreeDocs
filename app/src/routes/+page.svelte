<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import {
		addValue,
		clearSpans,
		dropValue,
		forgetModels,
		isMine,
		offeredModels,
		pickFiles,
		refreshModels,
		reinspectAll,
		runScrub,
		session,
		summary,
		toggleCountry,
		toggleKeep,
		toggleSpan,
		totalFindings,
		start
	} from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { basename, countryName, languageName } from '$lib/format';
	import { categoryOf } from '$lib/entities';
	import Badge from '$lib/components/Badge.svelte';
	import Button from '$lib/components/Button.svelte';
	import Callout from '$lib/components/Callout.svelte';
	import Chip from '$lib/components/Chip.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	// Aliased: `Progress` is already the engine's per-file progress notification,
	// and the wire type keeps that name because that is what the protocol calls it.
	import ProgressBar from '$lib/components/Progress.svelte';
	import Select from '$lib/components/Select.svelte';
	import Slider from '$lib/components/Slider.svelte';
	import TextField from '$lib/components/TextField.svelte';

	const m = $derived(i18n.m);

	let teardown: (() => void) | null = null;

	onMount(() => {
		void start().then((stop) => (teardown = stop));
	});

	onDestroy(() => {
		teardown?.();
		teardown = null;
	});

	const languageOptions = $derived(
		(session.caps?.placeholder_languages ?? []).map((code) => ({
			value: code,
			label: languageName(code, i18n.locale)
		}))
	);

	const modelOptions = $derived([
		{ value: '', label: m.reviewNone() },
		...offeredModels().map((model) => ({ value: model, label: model }))
	]);

	/**
	 * An entity type as a word, falling back to the wire name.
	 *
	 * The fallback is not politeness: a build of the engine that gained a type
	 * this catalogue has not heard of must still show the finding, because the
	 * value is about to be removed either way.
	 */
	function entityLabel(name: string): string {
		return m.entity[name]?.() ?? name;
	}

	function actionLabel(action: 'redact' | 'surrogate' | 'report' | 'keep'): string {
		return m.action[action]?.() ?? action;
	}
</script>

<main id="main">
	<header>
		<h1>{m.appName()}</h1>
		<p class="lead">{m.tagline()}</p>
	</header>

	{#if session.engineProblem}
		<Callout tone="danger" title={m.engineNotStarted()} live verbatim>
			<p>{session.engineProblem}</p>
		</Callout>
	{:else}
		{#if session.caps}
			<section class="status" aria-label={m.capabilitiesLabel()}>
				<Badge>{m.engineVersion({ version: session.caps.version })}</Badge>
				<Badge>{session.caps.layers.join(' + ')}</Badge>
				<Badge tone={session.caps.ocr_available ? 'neutral' : 'warn'}>
					{session.caps.ocr_available ? m.ocrAvailable() : m.ocrMissing()}
				</Badge>
				<!-- The premise of the tool, stated where the capabilities are, because
				     it is a capability: nothing here reaches a network. -->
				<Badge tone="success">{m.nothingLeaves()}</Badge>
			</section>

			{#if !session.caps.ocr_available && session.caps.ocr_unavailable_reason}
				<!-- The engine has always sent the reason and the window has always
				     thrown it away, so a scanned PDF was refused with an explanation
				     the user could only see in a terminal. -->
				<Callout tone="warn" title={m.ocrReasonTitle()} verbatim>
					<p>{session.caps.ocr_unavailable_reason}</p>
				</Callout>
			{/if}

			{#if session.caps.limitations.length}
				<!-- A missing layer must be visible. A build that quietly finds less is
				     the failure this project refuses. -->
				<Callout tone="warn" title={m.limitationsTitle()} verbatim>
					{#each session.caps.limitations as limitation}<p>{limitation}</p>{/each}
				</Callout>
			{/if}

			<!-- Outside the file list on purpose: this was only reachable once a
			     document was loaded, so an empty window looked like a build with no
			     review layer at all. -->
			<Disclosure bind:open={session.settingsOpen} summary={m.reviewTitle()}>
				<p class="hint">{m.reviewHint()}</p>
				<div class="row">
					<TextField
						label={m.reviewHost()}
						mono
						inline
						spellcheck="false"
						bind:value={session.reviewHost}
						oninput={forgetModels}
					/>
					<Button
						onclick={refreshModels}
						loading={session.modelsBusy}
						disabled={!session.reviewHost}
					>
						{session.modelsBusy ? m.reviewLooking() : m.reviewFindModels()}
					</Button>
					<Select label={m.reviewModel()} inline bind:value={session.reviewModel} options={modelOptions} />
				</div>
				{#if session.modelsProblem}
					<p class="warnline" lang="en">{session.modelsProblem}</p>
				{:else if offeredModels().length === 0}
					<p class="warnline">{m.reviewNoModelsAt({ host: session.reviewHost })}</p>
				{:else}
					<p class="hint">{m.reviewModelsAvailable({ count: offeredModels().length })}</p>
				{/if}
			</Disclosure>
		{/if}

		<!--
			A real button, not a section wearing role="button". The hand-rolled
			handler it replaces listened for Enter only, so Space — which every
			button responds to — did nothing at all.
		-->
		<button type="button" class="dropzone" class:busy={session.busy !== null} onclick={pickFiles}>
			<p class="dropline"><strong>{m.dropTitle()}</strong>, {m.dropHint()}</p>
			{#if session.caps}<p class="formats">{session.caps.formats.join(' · ')}</p>{/if}
		</button>

		{#if session.problem}
			<Callout tone="danger" live verbatim>
				<p>{session.problem}</p>
			</Callout>
		{/if}

		{#if session.files.length}
			<section class="controls">
				<Slider
					label={m.minConfidence()}
					bind:value={session.minConfidence}
					onchange={reinspectAll}
					describe={(value) => `${value.toFixed(2)}, ${m.confidenceBand({ value })}`}
				/>
				{#if session.reviewModel}
					<!-- Stated next to the button that acts on it: the choice was made
					     further up the page and is easy to forget by the time you scrub. -->
					<Badge tone="accent">{m.reviewBadge({ model: session.reviewModel })}</Badge>
				{/if}
				<Button
					variant="primary"
					onclick={runScrub}
					loading={session.busy === 'scrub'}
					disabled={session.busy !== null || totalFindings() === 0}
				>
					{session.busy === 'scrub' ? m.scrubbing() : m.scrub({ files: session.files.length })}
				</Button>
			</section>

			<section class="entities">
				<Select
					label={m.placeholderLanguage()}
					bind:value={session.placeholderLanguage}
					options={languageOptions}
					hint={m.placeholderLanguageHint()}
				/>
			</section>

			<section class="entities">
				<h2 id="countries-heading">{m.countriesTitle()}</h2>
				<p class="hint" id="countries-hint">{m.countriesHint()}</p>
				<div
					class="chips"
					role="group"
					aria-labelledby="countries-heading"
					aria-describedby="countries-hint"
				>
					{#each session.caps?.countries ?? [] as code}
						<Chip
							pressed={!session.dropped.has(code)}
							label={countryName(code, i18n.locale)}
							onchange={() => toggleCountry(code)}
						/>
					{/each}
				</div>
			</section>

			<section class="entities">
				<h2 id="keep-heading">{m.keepTitle()}</h2>
				<div class="chips" role="group" aria-labelledby="keep-heading">
					{#each session.entityList as entity}
						<Chip
							pressed={session.kept.has(entity.name)}
							label={entityLabel(entity.name)}
							category={categoryOf(entity.name)}
							hint={entity.report_only ? m.flagOnlyHint() : undefined}
							onchange={() => toggleKeep(entity.name)}
						>
							{entityLabel(entity.name)}{entity.report_only ? ` (${m.flagOnly()})` : ''}
						</Chip>
					{/each}
				</div>
			</section>

			<section class="files">
				{#each session.files as path}
					{@const inspection = session.inspections[path]}
					<article>
						<h3>{basename(path)}</h3>
						{#if session.busy === path}
							<p class="muted">{m.reading()}</p>
						{:else if inspection}
							<p class="muted">
								{m.fileSummary({
									format: inspection.format,
									characters: inspection.characters
								})}
							</p>
							{#if inspection.findings.length === 0}
								<p class="muted">{m.nothingMatched()}</p>
							{:else}
								<ul class="counts">
									{#each summary(inspection) as [entity, total, action]}
										<li>
											<Badge tone="entity" category={categoryOf(entity)}>
												{entityLabel(entity)}
											</Badge>
											<span class="mono">{total}</span>
											<em>{actionLabel(action as 'redact')}</em>
										</li>
									{/each}
								</ul>
								<details>
									<summary>{m.showValues({ count: inspection.findings.length })}</summary>
									<table>
										<!-- A header row, and a scope on every cell that names one.
										     Five bare <td> columns read as five unlabelled strings,
										     and the action button read as "keep this one" with no
										     way to tell which value it belonged to. -->
										<caption class="sr-only">
											{m.tableCaption({ file: basename(path) })}
										</caption>
										<thead>
											<tr>
												<th scope="col">{m.columnWhere()}</th>
												<th scope="col">{m.columnType()}</th>
												<th scope="col">{m.columnValue()}</th>
												<th scope="col">{m.columnAction()}</th>
												<th scope="col"><span class="sr-only">{m.columnDecision()}</span></th>
											</tr>
										</thead>
										<tbody>
											{#each inspection.findings as finding}
												<tr>
													<td class="mono">{finding.part}</td>
													<td>
														<Badge tone="entity" category={categoryOf(finding.entity)}>
															{entityLabel(finding.entity)}
														</Badge>
														{#if isMine(finding)}<em>{m.mine()}</em>{/if}
													</td>
													<th scope="row" class="value"><code>{finding.text}</code></th>
													<td>{actionLabel(finding.action)}</td>
													<td>
														{#if isMine(finding)}
															<Button
																variant="link"
																label={m.stopRemoving({ value: finding.text })}
																onclick={() => dropValue(path, finding.text)}
															>
																{m.stopRemovingShort()}
															</Button>
														{:else}
															<Button
																variant="link"
																label={m.keepThisOneFor({ value: finding.text })}
																title={m.keepThisOneWhy()}
																onclick={() => toggleSpan(path, finding)}
															>
																{m.keepThisOne()}
															</Button>
														{/if}
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</details>
							{/if}

							<!-- The other half of the loop. Detection is measured, not
							     complete, so the person reading the preview is the only
							     one who can add what it missed - and the engine, not
							     this window, decides what happens to it. -->
							<div class="addrow">
								<TextField
									label={m.addValueLabel()}
									placeholder={m.addValuePlaceholder()}
									bind:value={session.pending[path]}
									onEnter={() => addValue(path)}
								/>
								<Button
									icon="plus"
									onclick={() => addValue(path)}
									disabled={!(session.pending[path] ?? '').trim()}
								>
									{m.add()}
								</Button>
							</div>
							{#if (session.keptSpans[path] ?? []).length > 0}
								<p class="muted">
									{m.keptOnPurpose({ count: (session.keptSpans[path] ?? []).length })}
									<Button variant="link" onclick={() => clearSpans(path)}>{m.undoAll()}</Button>
								</p>
							{/if}
							{#each inspection.warnings as warning}
								<p class="warnline" lang="en">{warning}</p>
							{/each}
						{/if}
					</article>
				{/each}
			</section>
		{/if}

		{#if session.progress}
			<section class="progress">
				<!--
					The bar counts files, because that is the only unit the engine
					reports. It says so in words rather than showing a percentage the
					engine cannot know: how long detect takes next to extract on an
					unseen document is not a fact anyone here has.
				-->
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
			</section>
		{/if}

		{#if session.results.length}
			<section class="results">
				<h2>{m.resultTitle()}</h2>
				{#each session.results as result}
					<article class:failed={!result.ok}>
						<h3>{basename(result.path)}</h3>
						{#if result.ok}
							<p>
								{m.removedAndFlagged({
									removed: result.removed ?? 0,
									flagged: result.flagged ?? 0
								})}
							</p>
							<p class="muted mono">{result.output}</p>
							{#if result.hidden_removed?.length}
								<!-- What the user never saw in the first place, which is where
								     the leaks they do not expect actually live. -->
								<h4>{m.hiddenRemovedTitle()}</h4>
								<ul>
									{#each result.hidden_removed as item}
										<li lang="en">
											<span class="mono">{item.part}</span> — {item.kind}: {item.detail}
										</li>
									{/each}
								</ul>
							{/if}
							{#each result.warnings ?? [] as warning}
								<p class="warnline" lang="en">{warning}</p>
							{/each}
							{#if result.review}
								<!-- Advisory. The quotes come from the scrubbed text, so showing
								     them reveals nothing the output does not already. -->
								<h4>
									{m.reviewTitle()}
									<!--
										"Ollama was not running" and "the reviewer had no objection"
										are different facts, and the second one is reassuring. The
										summary sentence distinguishes them; these say so at a
										glance, so an empty concern list cannot be read as a clean
										bill of health for a review that never ran.
									-->
									{#if !result.review.ran}
										<Badge tone="warn">{m.reviewDidNotRun()}</Badge>
									{:else if result.review.partial}
										<Badge tone="warn">{m.reviewPartial()}</Badge>
									{:else}
										<Badge tone="success">{m.reviewRan()}</Badge>
									{/if}
								</h4>
								<p class="muted" lang="en">{result.review.summary}</p>
								{#if result.review.concerns.length}
									<ul class="concerns">
										{#each result.review.concerns as concern}
											<li>
												<span class="kind">{concern.kind.replace('_', ' ')}</span>
												<code>{concern.quote}</code>
												<span class="why" lang="en">{concern.why}</span>
											</li>
										{/each}
									</ul>
								{/if}
							{/if}
						{:else}
							<p class="failed-msg">
								{m.nothingWritten()} <span lang="en">{result.error?.message}</span>
							</p>
						{/if}
					</article>
				{/each}
			</section>
		{/if}

		{#if session.caps?.caveats.length}
			<!-- The engine's own words about what this tool does not guarantee. Quoted
			     rather than paraphrased: report.CAVEATS is where they are maintained,
			     and a second wording here would drift from the one on disk. -->
			<footer lang="en">
				{#each session.caps.caveats as caveat}<p>{caveat}</p>{/each}
			</footer>
		{/if}
	{/if}
</main>

<style>
	/*
	 * Layout and local shape only.
	 *
	 * Every colour, space, radius and duration is a token from app.css, and every
	 * rule that described a control — the pill, the alert, the chip, the bare
	 * `button`, the link-shaped action, the text input, the select — left with the
	 * component that now owns it. What is left is this page's arrangement, which
	 * is the part that is genuinely local.
	 */

	main {
		max-width: 60rem;
		margin: 0 auto;
		padding: var(--space-4) var(--space-5) var(--space-8);
	}

	h1 {
		font-size: var(--text-2xl);
		line-height: var(--lh-2xl);
		letter-spacing: var(--tracking-tight);
	}

	h2 {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	h3 {
		margin-bottom: var(--space-1);
		font-size: var(--text-lg);
		line-height: var(--lh-lg);
	}

	h4 {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: var(--space-3) 0 var(--space-1);
		font-size: var(--text-sm);
	}

	.lead {
		max-width: 42rem;
		margin-top: var(--space-2);
		color: var(--text-2);
	}

	.muted {
		color: var(--text-3);
		font-size: var(--text-sm);
	}

	.hint {
		margin: 0 0 var(--space-2);
		max-width: 42rem;
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	.mono {
		font-family: var(--font-mono);
		font-size: 0.85em;
	}

	.status {
		display: flex;
		gap: var(--space-2);
		flex-wrap: wrap;
		margin: var(--space-4) 0;
	}

	.row {
		display: flex;
		align-items: flex-end;
		gap: var(--space-4);
		flex-wrap: wrap;
		margin: var(--space-3) 0;
	}

	/*
	 * The dropzone is a button, so it inherits none of the furniture a button
	 * usually brings and needs its own reset. It is the page's primary target and
	 * the only place a drop can land, which is why it is this large.
	 */
	.dropzone {
		display: block;
		width: 100%;
		border: 2px dashed var(--border-strong);
		border-radius: var(--radius-4);
		background: var(--surface);
		color: inherit;
		font: inherit;
		text-align: center;
		padding: var(--space-7) var(--space-4);
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

	.dropline {
		font-size: var(--text-md);
	}

	.formats {
		margin-top: var(--space-2);
		font-family: var(--font-mono);
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		margin: var(--space-5) 0 var(--space-2);
		flex-wrap: wrap;
	}

	.entities {
		margin: var(--space-4) 0;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
	}

	article {
		border: 1px solid var(--border);
		border-radius: var(--radius-3);
		background: var(--surface);
		box-shadow: var(--shadow-1);
		padding: var(--space-4);
		margin: var(--space-3) 0;
	}

	article.failed {
		border-color: var(--danger-border);
	}

	.failed-msg {
		color: var(--danger-text);
	}

	.addrow {
		display: flex;
		align-items: flex-end;
		gap: var(--space-2);
		margin-top: var(--space-3);
	}

	.addrow :global(.field) {
		flex: 1;
	}

	.warnline {
		margin: var(--space-1) 0;
		font-size: var(--text-sm);
		color: var(--warn-text);
	}

	.counts {
		list-style: none;
		margin: var(--space-2) 0;
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.counts li {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		font-size: var(--text-sm);
	}

	.counts em {
		color: var(--text-3);
		font-style: normal;
		font-size: 0.9em;
	}

	.concerns {
		list-style: none;
		margin: var(--space-2) 0 0;
	}

	.concerns li {
		margin: var(--space-2) 0;
		padding-left: var(--space-2);
		border-left: 2px solid var(--warn-border);
	}

	.kind {
		display: inline-block;
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
		margin-right: var(--space-1);
	}

	.why {
		display: block;
		font-size: var(--text-sm);
		color: var(--text-2);
	}

	details summary {
		cursor: pointer;
		font-size: var(--text-sm);
		color: var(--text-2);
		margin: var(--space-2) 0;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	thead th {
		padding: var(--space-1) var(--space-2);
		border-bottom: 1px solid var(--border-strong);
		text-align: left;
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	td,
	tbody th {
		padding: var(--space-1) var(--space-2);
		border-top: 1px solid var(--border);
		vertical-align: top;
		text-align: left;
		font-weight: var(--weight-normal);
	}

	.value code {
		word-break: break-all;
	}

	.progress {
		margin: var(--space-4) 0;
	}

	footer {
		margin-top: var(--space-6);
		padding-top: var(--space-4);
		border-top: 1px solid var(--border);
		font-size: var(--text-sm);
		color: var(--text-3);
	}

	footer p {
		margin: var(--space-2) 0;
	}
</style>
