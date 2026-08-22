<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { open } from '@tauri-apps/plugin-dialog';
	import { getCurrentWebview } from '@tauri-apps/api/webview';
	import {
		type Capabilities,
		type EntityInfo,
		type Finding,
		type Inspection,
		type Progress,
		type ScrubResult,
		MISSING_DEPENDENCY,
		NEEDS_OCR,
		UNSUPPORTED_FORMAT,
		capabilities,
		engineStatus,
		entities,
		inspect,
		onNotify,
		reviewModels,
		scrub,
		type KeptSpan,
		type RemovedValue
	} from '$lib/engine';
	import { announce } from '$lib/announce.svelte';
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

	let engineProblem = $state<string | null>(null);
	let caps = $state<Capabilities | null>(null);
	let entityList = $state<EntityInfo[]>([]);

	let files = $state<string[]>([]);
	let inspections = $state<Record<string, Inspection>>({});
	let busy = $state<string | null>(null);
	let progress = $state<Progress | null>(null);
	let results = $state<ScrubResult[]>([]);
	let problem = $state<string | null>(null);

	/** Entity types the user has chosen to leave alone. */
	let kept = $state<Set<string>>(new Set());
	/**
	 * Single occurrences the user has excused, per file. A different control from
	 * `kept` above and deliberately so: that one says "no location in this
	 * document is confidential", this one says "not *this* one". The same city is
	 * confidential in a party's address and not in a jurisdiction clause, which is
	 * a judgement only the person reading the preview can make.
	 */
	let keptSpans = $state<Record<string, KeptSpan[]>>({});
	/** Values the user says to remove that no detector found, per file. */
	let extraValues = $state<Record<string, RemovedValue[]>>({});
	/** What is typed in the "also remove" box, per file, before it is added. */
	let pending = $state<Record<string, string>>({});
	/**
	 * Countries to look for identifiers in. Empty means every supported one,
	 * which is why this is a set of *exclusions* to send rather than a set of
	 * inclusions: nothing selected has to mean "all", never "none".
	 */
	let dropped = $state<Set<string>>(new Set());
	/** Prefilled from capabilities, because the default is the engine's to pick. */
	let placeholderLanguage = $state('');
	let minConfidence = $state(0.5);
	/** Empty means no review. Off by default: it is slow and changes nothing. */
	let reviewModel = $state('');
	/**
	 * Where to look for Ollama, and what was found there.
	 *
	 * Kept separate from `caps.review_models` rather than editing that in place:
	 * the capabilities are what the engine reported at startup, and overwriting
	 * them would lose the ability to tell "the default host has nothing" from
	 * "the host I typed has nothing".
	 */
	let reviewHost = $state('');
	let models = $state<string[] | null>(null);
	let modelsProblem = $state<string | null>(null);
	let modelsBusy = $state(false);
	/**
	 * Open when there is a choice to make.
	 *
	 * Seeded once from the startup report rather than bound to it: expanding a panel
	 * the user has just collapsed is worse than the click it saves. Closed when
	 * Ollama has nothing, because an empty control is a distraction, and the label
	 * stays visible either way — being invisible was the original complaint.
	 */
	let settingsOpen = $state(false);

	/** What the dropdown offers: the typed host's answer, else the startup one. */
	const offeredModels = $derived(models ?? caps?.review_models ?? []);

	// Collected here rather than returned from onMount: an async callback cannot
	// hand Svelte a cleanup function, and both subscriptions are set up after an
	// await.
	let unsubscribes: (() => void)[] = [];

	onMount(() => {
		void start();
	});

	onDestroy(() => {
		for (const unsubscribe of unsubscribes) unsubscribe();
		unsubscribes = [];
	});

	async function start() {
		engineProblem = await engineStatus();
		if (engineProblem) return;
		unsubscribes.push(
			await onNotify({
				progress: (value) => {
					// Announced per file, which is what the engine reports. Announcing
					// anything finer would be inventing a number it does not have.
					if (value.file !== progress?.file) {
						announce(`${basename(value.file)}, ${value.index + 1} of ${value.total}`);
					}
					progress = value;
				},
				ready: adoptCaps
			})
		);
		try {
			adoptCaps(await capabilities());
			entityList = (await entities()).entities;
		} catch (error) {
			fail(describe(error));
		}
		unsubscribes.push(
			await getCurrentWebview().onDragDropEvent((event) => {
				if (event.payload.type === 'drop') addFiles(event.payload.paths);
			})
		);
	}

	/**
	 * Take the engine's report, and seed the review host from it the first time.
	 *
	 * Seeded rather than defaulted in this file: the address Ollama listens on is
	 * the engine's business, and a second copy here is a second thing to be wrong.
	 * Only when the field is untouched, so a re-announced `ready` cannot discard
	 * what the user typed.
	 */
	function adoptCaps(value: Capabilities) {
		const first = caps === null;
		caps = value;
		if (!reviewHost) reviewHost = value.review_host;
		if (!placeholderLanguage) placeholderLanguage = value.placeholder_language;
		if (first) settingsOpen = value.review_models.length > 0;
	}

	/** Ask a specific Ollama what it has, and say so where the host was typed. */
	async function refreshModels() {
		modelsBusy = true;
		modelsProblem = null;
		try {
			const found = (await reviewModels(reviewHost)).models;
			models = found;
			// A model the new host does not have would otherwise stay selected and
			// fail at scrub time, pointing at the wrong thing entirely.
			if (reviewModel && !found.includes(reviewModel)) reviewModel = '';
		} catch (error) {
			models = [];
			modelsProblem = describe(error);
		} finally {
			modelsBusy = false;
		}
	}

	function describe(error: unknown): string {
		const code = (error as { code?: number | null })?.code ?? null;
		const message = error instanceof Error ? error.message : String(error);
		if (code === NEEDS_OCR) {
			return `${message}`;
		}
		if (code === UNSUPPORTED_FORMAT) {
			return `This format is not supported. ${message}`;
		}
		if (code === MISSING_DEPENDENCY) {
			return `A component is missing. ${message}`;
		}
		return message;
	}

	function addFiles(paths: string[]) {
		const merged = new Set([...files, ...paths]);
		files = [...merged];
		for (const path of paths) void loadInspection(path);
	}

	async function pickFiles() {
		const chosen = await open({ multiple: true, directory: false });
		if (!chosen) return;
		addFiles(Array.isArray(chosen) ? chosen : [chosen]);
	}

	async function loadInspection(path: string) {
		busy = path;
		problem = null;
		try {
			const inspection = await inspect(path, {
				keep: [...kept],
				keepSpans: keptSpans[path] ?? [],
				remove: extraValues[path] ?? [],
				minConfidence,
				countries: activeCountries()
			});
			inspections[path] = inspection;
			// Nothing here moves focus, so without this the result of a decision is
			// silent: the table simply has a different number of rows.
			announce(`${basename(path)}: ${inspection.findings.length} values found`);
		} catch (error) {
			fail(`${basename(path)}: ${describe(error)}`);
		} finally {
			busy = null;
		}
	}

	async function reinspectAll() {
		for (const path of files) await loadInspection(path);
	}

	/**
	 * Excuse or re-include one occurrence.
	 *
	 * The span carries the text it covered, which is what lets the engine refuse
	 * the decision if the file changes underneath it: the offsets would then point
	 * at something the user never saw, and honouring them would keep whatever
	 * moved into that range.
	 */
	function toggleSpan(path: string, finding: Finding) {
		const current = keptSpans[path] ?? [];
		const already = current.some((s) => s.start === finding.start && s.end === finding.end);
		keptSpans = {
			...keptSpans,
			[path]: already
				? current.filter((s) => !(s.start === finding.start && s.end === finding.end))
				: [...current, { start: finding.start, end: finding.end, text: finding.text, path }]
		};
		void loadInspection(path);
	}

	function addValue(path: string) {
		const value = (pending[path] ?? '').trim();
		if (!value) return;
		const current = extraValues[path] ?? [];
		if (!current.some((item) => item.value === value)) {
			extraValues = { ...extraValues, [path]: [...current, { value, path }] };
		}
		pending = { ...pending, [path]: '' };
		void loadInspection(path);
	}

	function dropValue(path: string, value: string) {
		extraValues = {
			...extraValues,
			[path]: (extraValues[path] ?? []).filter((item) => item.value !== value)
		};
		void loadInspection(path);
	}

	/** A finding the user put there, rather than one a detector nominated. */
	function isMine(finding: Finding): boolean {
		return finding.detector === 'human';
	}

	function toggleKeep(name: string) {
		const next = new Set(kept);
		next.has(name) ? next.delete(name) : next.add(name);
		kept = next;
		void reinspectAll();
	}

	/**
	 * Undefined when nothing is switched off, so the engine hears no opinion and
	 * uses every country. Sending the full list would mean the same thing, but it
	 * would also make the request claim a choice nobody made.
	 */
	function activeCountries(): string[] | undefined {
		if (!caps || dropped.size === 0) return undefined;
		return caps.countries.filter((code) => !dropped.has(code));
	}

	function toggleCountry(code: string) {
		const next = new Set(dropped);
		next.has(code) ? next.delete(code) : next.add(code);
		// Never all of them: an empty selection is refused by the engine, and it
		// would mean scrubbing with the whole checksum layer switched off.
		if (caps && next.size === caps.countries.length) return;
		dropped = next;
		void reinspectAll();
	}

	async function runScrub() {
		const target = await open({ directory: true, multiple: false, title: 'Where to write the scrubbed copies' });
		if (!target || Array.isArray(target)) return;
		busy = 'scrub';
		problem = null;
		results = [];
		try {
			results = (
				await scrub(files, target, {
					keep: [...kept],
					// Every file's decisions in one request, each carrying its own
					// path. The engine scopes them per document, because a span is
					// an offset into one extraction and would be stale anywhere
					// else - see Override.for_path.
					keepSpans: files.flatMap((path) => keptSpans[path] ?? []),
					remove: files.flatMap((path) => extraValues[path] ?? []),
					minConfidence,
					countries: activeCountries(),
					placeholderLanguage,
					review: reviewModel || null,
					reviewHost
				})
			).results;
			const failed = results.filter((result) => !result.ok).length;
			announce(
				failed === 0
					? `Finished. ${results.length} files written.`
					: `Finished with ${failed} of ${results.length} files not written.`,
				{ assertive: failed > 0 }
			);
		} catch (error) {
			fail(describe(error));
		} finally {
			busy = null;
			progress = null;
		}
	}

	/** Counts per entity type, which is what a preview is actually for. */
	function summary(inspection: Inspection): [string, number, string][] {
		const counts = new Map<string, [number, string]>();
		for (const finding of inspection.findings) {
			const [count] = counts.get(finding.entity) ?? [0, finding.action];
			counts.set(finding.entity, [count + 1, finding.action]);
		}
		return [...counts.entries()]
			.map(([entity, [count, action]]) => [entity, count, action] as [string, number, string])
			.sort((a, b) => a[0].localeCompare(b[0]));
	}

	/**
	 * The reader's language, for names and numbers only.
	 *
	 * Read from the webview rather than asked of the OS through a plugin:
	 * `navigator.language` is the system preference here, and a Rust dependency
	 * to learn something already in the window is a dependency for nothing. This
	 * is not the interface language — that arrives with the message catalogues.
	 */
	const locale = $derived(navigator.language || 'en');

	const languageOptions = $derived(
		(caps?.placeholder_languages ?? []).map((code) => ({
			value: code,
			label: languageName(code, locale)
		}))
	);

	/** A failure the user must not miss, said once and shown until it is replaced. */
	function fail(message: string) {
		problem = message;
		announce(message, { assertive: true });
	}

	const totalFindings = $derived(
		files.reduce((sum, path) => sum + (inspections[path]?.findings.length ?? 0), 0)
	);
</script>

<main id="main">
	<header>
		<h1>FreeDocs</h1>
		<p class="lead">
			Removes confidential data from a document so it can be handed to an AI service without
			handing over the data. Everything runs on this machine.
		</p>
	</header>

	{#if engineProblem}
		<Callout tone="danger" title="The engine did not start" live verbatim>
			<p>{engineProblem}</p>
		</Callout>
	{:else}
		{#if caps}
			<section class="status" aria-label="What this build can do">
				<Badge>engine {caps.version}</Badge>
				<Badge>{caps.layers.join(' + ')}</Badge>
				<Badge tone={caps.ocr_available ? 'neutral' : 'warn'}>
					{caps.ocr_available ? 'OCR available' : 'OCR not installed'}
				</Badge>
				<!-- The premise of the tool, stated where the capabilities are, because
				     it is a capability: nothing here reaches a network. -->
				<Badge tone="success">nothing leaves this machine</Badge>
			</section>

			{#if !caps.ocr_available && caps.ocr_unavailable_reason}
				<!-- The engine has always sent the reason and the window has always
				     thrown it away, so a scanned PDF was refused with an explanation
				     the user could only see in a terminal. -->
				<Callout tone="warn" title="Scanned pages cannot be read" verbatim>
					<p>{caps.ocr_unavailable_reason}</p>
				</Callout>
			{/if}

			{#if caps.limitations.length}
				<!-- A missing layer must be visible. A build that quietly finds less is
				     the failure this project refuses. -->
				<Callout tone="warn" title="What this build is not detecting" verbatim>
					{#each caps.limitations as limitation}<p>{limitation}</p>{/each}
				</Callout>
			{/if}
		{/if}

		{#if caps}
			<!-- Outside the file list on purpose: this was only reachable once a
			     document was loaded, so an empty window looked like a build with no
			     review layer at all. -->
			<Disclosure bind:open={settingsOpen} summary="Second opinion (Ollama)">
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
						bind:value={reviewHost}
						oninput={() => {
							// The old list came from the old host. Keeping it on screen
							// would credit this host with models it may not have.
							models = null;
							modelsProblem = null;
						}}
					/>
					<Button onclick={refreshModels} loading={modelsBusy} disabled={!reviewHost}>
						{modelsBusy ? 'Looking…' : 'Find models'}
					</Button>
					<Select
						label="Model"
						inline
						bind:value={reviewModel}
						options={[
							{ value: '', label: 'no review' },
							...offeredModels.map((model) => ({ value: model, label: model }))
						]}
					/>
				</div>
				{#if modelsProblem}
					<p class="warnline" lang="en">{modelsProblem}</p>
				{:else if offeredModels.length === 0}
					<p class="warnline">
						No models at {reviewHost}. Is Ollama running there, and has anything been pulled?
					</p>
				{:else}
					<p class="hint">{offeredModels.length} available.</p>
				{/if}
			</Disclosure>
		{/if}

		<!--
			A real button, not a section wearing role="button". The hand-rolled
			handler it replaces listened for Enter only, so Space — which every
			button responds to — did nothing at all.
		-->
		<button type="button" class="dropzone" class:busy={busy !== null} onclick={pickFiles}>
			<p class="dropline"><strong>Drop documents here</strong>, or click to choose.</p>
			{#if caps}<p class="formats">{caps.formats.join(' · ')}</p>{/if}
		</button>

		{#if problem}
			<Callout tone="danger" live verbatim>
				<p>{problem}</p>
			</Callout>
		{/if}

		{#if files.length}
			<section class="controls">
				<Slider
					label="Minimum confidence"
					bind:value={minConfidence}
					onchange={reinspectAll}
					describe={(value) => `${value.toFixed(2)}, ${confidenceBand(value)}`}
				/>
				{#if reviewModel}
					<!-- Stated next to the button that acts on it: the choice was made
					     further up the page and is easy to forget by the time you scrub. -->
					<Badge tone="accent">review: {reviewModel}</Badge>
				{/if}
				<Button
					variant="primary"
					onclick={runScrub}
					loading={busy === 'scrub'}
					disabled={busy !== null || totalFindings === 0}
				>
					{busy === 'scrub' ? 'Scrubbing…' : `Scrub ${files.length} files`}
				</Button>
			</section>

			<section class="entities">
				<Select
					label="Placeholder language"
					bind:value={placeholderLanguage}
					options={languageOptions}
					hint="The wording written into the output in place of what was removed. Only the words change; nothing about what gets removed depends on this."
				/>
			</section>

			<section class="entities">
				<h2 id="countries-heading">Countries to look for</h2>
				<p class="hint" id="countries-hint">
					All of them unless you say otherwise. Narrowing raises precision and can
					hide an identifier from a country you did not expect in the file.
				</p>
				<div
					class="chips"
					role="group"
					aria-labelledby="countries-heading"
					aria-describedby="countries-hint"
				>
					{#each caps?.countries ?? [] as code}
						<Chip
							pressed={!dropped.has(code)}
							label={countryName(code, locale)}
							onchange={() => toggleCountry(code)}
						/>
					{/each}
				</div>
			</section>

			<section class="entities">
				<h2 id="keep-heading">Leave untouched</h2>
				<div class="chips" role="group" aria-labelledby="keep-heading">
					{#each entityList as entity}
						<Chip
							pressed={kept.has(entity.name)}
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
				{#each files as path}
					{@const inspection = inspections[path]}
					<article>
						<h3>{basename(path)}</h3>
						{#if busy === path}
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
											<Badge tone="entity" category={categoryOf(entity)}>
												{entity}
											</Badge>
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
									bind:value={pending[path]}
									onEnter={() => addValue(path)}
								/>
								<Button
									icon="plus"
									onclick={() => addValue(path)}
									disabled={!(pending[path] ?? '').trim()}
								>
									Add
								</Button>
							</div>
							{#if (keptSpans[path] ?? []).length > 0}
								<p class="muted">
									{(keptSpans[path] ?? []).length} kept on purpose.
									<Button
										variant="link"
										onclick={() => {
											keptSpans = { ...keptSpans, [path]: [] };
											void loadInspection(path);
										}}
									>
										undo all
									</Button>
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

		{#if progress}
			<section class="progress">
				<!--
					The bar counts files, because that is the only unit the engine
					reports. It says so in words rather than showing a percentage the
					engine cannot know: how long detect takes next to extract on an
					unseen document is not a fact anyone here has.
				-->
				<ProgressBar
					label="Scrubbing"
					value={progress.index}
					max={progress.total}
					valueText={`${basename(progress.file)} — file ${progress.index + 1} of ${progress.total}`}
				/>
			</section>
		{/if}

		{#if results.length}
			<section class="results">
				<h2>Result</h2>
				{#each results as result}
					<article class:failed={!result.ok}>
						<h3>{basename(result.path)}</h3>
						{#if result.ok}
							<p>
								{result.removed} removed{result.flagged ? `, ${result.flagged} flagged for review` : ''}
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
												<span class="why">{concern.why}</span>
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

		{#if caps?.caveats.length}
			<!-- The engine's own words about what this tool does not guarantee. Quoted
			     rather than paraphrased: report.CAVEATS is where they are maintained,
			     and a second wording here would drift from the one on disk. -->
			<footer lang="en">
				{#each caps.caveats as caveat}<p>{caveat}</p>{/each}
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
