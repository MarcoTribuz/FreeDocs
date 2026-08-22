<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import {
		addValue,
		clearSpans,
		dropValue,
		forgetModels,
		isMine,
		loadInspection,
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
	import { basename, confidenceBand, count, countryName, languageName } from '$lib/format';
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

	let teardown: (() => void) | null = null;

	onMount(() => {
		void start().then((stop) => (teardown = stop));
	});

	onDestroy(() => {
		teardown?.();
		teardown = null;
	});

	/**
	 * The reader's language, for names and numbers only.
	 *
	 * Read from the webview rather than asked of the OS through a plugin:
	 * `navigator.language` is the system preference here, and a Rust dependency to
	 * learn something already in the window is a dependency for nothing. This is
	 * not the interface language — that arrives with the message catalogues.
	 */
	const locale = $derived(navigator.language || 'en');

	const languageOptions = $derived(
		(session.caps?.placeholder_languages ?? []).map((code) => ({
			value: code,
			label: languageName(code, locale)
		}))
	);

	const modelOptions = $derived([
		{ value: '', label: 'no review' },
		...offeredModels().map((model) => ({ value: model, label: model }))
	]);
</script>

<main id="main">
	<header>
		<h1>FreeDocs</h1>
		<p class="lead">
			Removes confidential data from a document so it can be handed to an AI service without
			handing over the data. Everything runs on this machine.
		</p>
	</header>

	{#if session.engineProblem}
		<Callout tone="danger" title="The engine did not start" live verbatim>
			<p>{session.engineProblem}</p>
		</Callout>
	{:else}
		{#if session.caps}
			<section class="status" aria-label="What this build can do">
				<Badge>engine {session.caps.version}</Badge>
				<Badge>{session.caps.layers.join(' + ')}</Badge>
				<Badge tone={session.caps.ocr_available ? 'neutral' : 'warn'}>
					{session.caps.ocr_available ? 'OCR available' : 'OCR not installed'}
				</Badge>
				<!-- The premise of the tool, stated where the capabilities are, because
				     it is a capability: nothing here reaches a network. -->
				<Badge tone="success">nothing leaves this machine</Badge>
			</section>

			{#if !session.caps.ocr_available && session.caps.ocr_unavailable_reason}
				<!-- The engine has always sent the reason and the window has always
				     thrown it away, so a scanned PDF was refused with an explanation
				     the user could only see in a terminal. -->
				<Callout tone="warn" title="Scanned pages cannot be read" verbatim>
					<p>{session.caps.ocr_unavailable_reason}</p>
				</Callout>
			{/if}

			{#if session.caps.limitations.length}
				<!-- A missing layer must be visible. A build that quietly finds less is
				     the failure this project refuses. -->
				<Callout tone="warn" title="What this build is not detecting" verbatim>
					{#each session.caps.limitations as limitation}<p>{limitation}</p>{/each}
				</Callout>
			{/if}

			<!-- Outside the file list on purpose: this was only reachable once a
			     document was loaded, so an empty window looked like a build with no
			     review layer at all. -->
			<Disclosure bind:open={session.settingsOpen} summary="Second opinion (Ollama)">
				<p class="hint">
					A local model reads the scrubbed text and says what still worries it. Advisory: it
					changes nothing in the output.
				</p>
				<div class="row">
					<TextField
						label="Host"
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
						{session.modelsBusy ? 'Looking…' : 'Find models'}
					</Button>
					<Select label="Model" inline bind:value={session.reviewModel} options={modelOptions} />
				</div>
				{#if session.modelsProblem}
					<p class="warnline" lang="en">{session.modelsProblem}</p>
				{:else if offeredModels().length === 0}
					<p class="warnline">
						No models at {session.reviewHost}. Is Ollama running there, and has anything been
						pulled?
					</p>
				{:else}
					<p class="hint">{offeredModels().length} available.</p>
				{/if}
			</Disclosure>
		{/if}

		<!--
			A real button, not a section wearing role="button". The hand-rolled
			handler it replaces listened for Enter only, so Space — which every
			button responds to — did nothing at all.
		-->
		<button
			type="button"
			class="dropzone"
			class:busy={session.busy !== null}
			onclick={pickFiles}
		>
			<p class="dropline"><strong>Drop documents here</strong>, or click to choose.</p>
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
					label="Minimum confidence"
					bind:value={session.minConfidence}
					onchange={reinspectAll}
					describe={(value) => `${value.toFixed(2)}, ${confidenceBand(value)}`}
				/>
				{#if session.reviewModel}
					<!-- Stated next to the button that acts on it: the choice was made
					     further up the page and is easy to forget by the time you scrub. -->
					<Badge tone="accent">review: {session.reviewModel}</Badge>
				{/if}
				<Button
					variant="primary"
					onclick={runScrub}
					loading={session.busy === 'scrub'}
					disabled={session.busy !== null || totalFindings() === 0}
				>
					{session.busy === 'scrub' ? 'Scrubbing…' : `Scrub ${session.files.length} files`}
				</Button>
			</section>

			<section class="entities">
				<Select
					label="Placeholder language"
					bind:value={session.placeholderLanguage}
					options={languageOptions}
					hint="The wording written into the output in place of what was removed. Only the words change; nothing about what gets removed depends on this."
				/>
			</section>

			<section class="entities">
				<h2 id="countries-heading">Countries to look for</h2>
				<p class="hint" id="countries-hint">
					All of them unless you say otherwise. Narrowing raises precision and can hide an
					identifier from a country you did not expect in the file.
				</p>
				<div
					class="chips"
					role="group"
					aria-labelledby="countries-heading"
					aria-describedby="countries-hint"
				>
					{#each session.caps?.countries ?? [] as code}
						<Chip
							pressed={!session.dropped.has(code)}
							label={countryName(code, locale)}
							onchange={() => toggleCountry(code)}
						/>
					{/each}
				</div>
			</section>

			<section class="entities">
				<h2 id="keep-heading">Leave untouched</h2>
				<div class="chips" role="group" aria-labelledby="keep-heading">
					{#each session.entityList as entity}
						<Chip
							pressed={session.kept.has(entity.name)}
							label={entity.name}
							category={categoryOf(entity.name)}
							hint={entity.report_only
								? 'Flagged for review, never removed, whether or not this is on.'
								: undefined}
							onchange={() => toggleKeep(entity.name)}
						>
							{entity.name}{entity.report_only ? ' (flag only)' : ''}
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
							<p class="muted">Reading…</p>
						{:else if inspection}
							<p class="muted">
								{inspection.format} · {count(inspection.characters, locale)} characters
							</p>
							{#if inspection.findings.length === 0}
								<p class="muted">Nothing matched.</p>
							{:else}
								<ul class="counts">
									{#each summary(inspection) as [entity, total, action]}
										<li>
											<Badge tone="entity" category={categoryOf(entity)}>{entity}</Badge>
											<span class="mono">{total}</span>
											<em>{action}</em>
										</li>
									{/each}
								</ul>
								<details>
									<summary>Show the {inspection.findings.length} values</summary>
									<table>
										<!-- A header row, and a scope on every cell that names one.
										     Five bare <td> columns read as five unlabelled strings,
										     and the action button read as "keep this one" with no
										     way to tell which value it belonged to. -->
										<caption class="sr-only">
											Every value found in {basename(path)}, and what will happen to it
										</caption>
										<thead>
											<tr>
												<th scope="col">Where</th>
												<th scope="col">Type</th>
												<th scope="col">Value</th>
												<th scope="col">Action</th>
												<th scope="col"><span class="sr-only">Decision</span></th>
											</tr>
										</thead>
										<tbody>
											{#each inspection.findings as finding}
												<tr>
													<td class="mono">{finding.part}</td>
													<td>
														<Badge tone="entity" category={categoryOf(finding.entity)}>
															{finding.entity}
														</Badge>
														{#if isMine(finding)}<em>yours</em>{/if}
													</td>
													<th scope="row" class="value"><code>{finding.text}</code></th>
													<td class="mono">{finding.action}</td>
													<td>
														{#if isMine(finding)}
															<Button
																variant="link"
																label={`Stop removing ${finding.text}`}
																onclick={() => dropValue(path, finding.text)}
															>
																don't remove
															</Button>
														{:else}
															<Button
																variant="link"
																label={`Keep this one occurrence of ${finding.text}`}
																title="Leave this one occurrence alone. Every other occurrence of the same value is still removed."
																onclick={() => toggleSpan(path, finding)}
															>
																keep this one
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
									label="Also remove this value"
									placeholder="a name, a number, anything the detectors missed"
									bind:value={session.pending[path]}
									onEnter={() => addValue(path)}
								/>
								<Button
									icon="plus"
									onclick={() => addValue(path)}
									disabled={!(session.pending[path] ?? '').trim()}
								>
									Add
								</Button>
							</div>
							{#if (session.keptSpans[path] ?? []).length > 0}
								<p class="muted">
									{(session.keptSpans[path] ?? []).length} kept on purpose.
									<Button variant="link" onclick={() => clearSpans(path)}>undo all</Button>
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
					label="Scrubbing"
					value={session.progress.index}
					max={session.progress.total}
					valueText={`${basename(session.progress.file)} — file ${session.progress.index + 1} of ${session.progress.total}`}
				/>
			</section>
		{/if}

		{#if session.results.length}
			<section class="results">
				<h2>Result</h2>
				{#each session.results as result}
					<article class:failed={!result.ok}>
						<h3>{basename(result.path)}</h3>
						{#if result.ok}
							<p>
								{result.removed} removed{result.flagged
									? `, ${result.flagged} flagged for review`
									: ''}
							</p>
							<p class="muted mono">{result.output}</p>
							{#if result.hidden_removed?.length}
								<!-- What the user never saw in the first place, which is where
								     the leaks they do not expect actually live. -->
								<h4>Hidden content removed</h4>
								<ul>
									{#each result.hidden_removed as item}
										<li><span class="mono">{item.part}</span> — {item.kind}: {item.detail}</li>
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
									Second opinion
									<!--
										"Ollama was not running" and "the reviewer had no objection"
										are different facts, and the second one is reassuring. The
										summary sentence distinguishes them; these say so at a
										glance, so an empty concern list cannot be read as a clean
										bill of health for a review that never ran.
									-->
									{#if !result.review.ran}
										<Badge tone="warn">did not run</Badge>
									{:else if result.review.partial}
										<Badge tone="warn">first part of the document only</Badge>
									{:else}
										<Badge tone="success">ran</Badge>
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
								Nothing was written. <span lang="en">{result.error?.message}</span>
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
