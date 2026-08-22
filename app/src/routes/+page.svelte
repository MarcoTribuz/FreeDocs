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
				progress: (value) => (progress = value),
				ready: adoptCaps
			})
		);
		try {
			adoptCaps(await capabilities());
			entityList = (await entities()).entities;
		} catch (error) {
			problem = describe(error);
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
			inspections[path] = await inspect(path, {
				keep: [...kept],
				keepSpans: keptSpans[path] ?? [],
				remove: extraValues[path] ?? [],
				minConfidence,
				countries: activeCountries()
			});
		} catch (error) {
			problem = `${basename(path)}: ${describe(error)}`;
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
		} catch (error) {
			problem = describe(error);
		} finally {
			busy = null;
			progress = null;
		}
	}

	function basename(path: string): string {
		return path.split(/[\\/]/).pop() ?? path;
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
		<section class="alert error">
			<h2>The engine did not start</h2>
			<p>{engineProblem}</p>
		</section>
	{:else}
		{#if caps}
			<section class="status">
				<span class="pill">engine {caps.version}</span>
				<span class="pill">{caps.layers.join(' + ')}</span>
				<span class="pill" class:warn={!caps.ocr_available}>
					OCR {caps.ocr_available ? 'available' : 'not installed'}
				</span>
			</section>

			{#if caps.limitations.length}
				<!-- A missing layer must be visible. A build that quietly finds less is
				     the failure this project refuses. -->
				<section class="alert warn">
					{#each caps.limitations as limitation}<p>{limitation}</p>{/each}
				</section>
			{/if}
		{/if}

		{#if caps}
			<!-- Outside the file list on purpose: this was only reachable once a
			     document was loaded, so an empty window looked like a build with no
			     review layer at all. -->
			<details class="settings" bind:open={settingsOpen}>
				<summary>Second opinion (Ollama)</summary>
				<p class="muted">
					A local model reads the scrubbed text and says what still worries it. Advisory: it
					changes nothing in the output.
				</p>
				<div class="row">
					<label>
						Host
						<input
							type="text"
							class="mono host"
							spellcheck="false"
							bind:value={reviewHost}
							oninput={() => {
								// The old list came from the old host. Keeping it on screen
								// would credit this host with models it may not have.
								models = null;
								modelsProblem = null;
							}}
						/>
					</label>
					<button onclick={refreshModels} disabled={modelsBusy || !reviewHost}>
						{modelsBusy ? 'Looking…' : 'Find models'}
					</button>
					<label>
						Model
						<select bind:value={reviewModel}>
							<option value="">no review</option>
							{#each offeredModels as model}<option value={model}>{model}</option>{/each}
						</select>
					</label>
				</div>
				{#if modelsProblem}
					<p class="warnline">{modelsProblem}</p>
				{:else if offeredModels.length === 0}
					<p class="warnline">
						No models at {reviewHost}. Is Ollama running there, and has anything been pulled?
					</p>
				{:else}
					<p class="muted">{offeredModels.length} model(s) available.</p>
				{/if}
			</details>
		{/if}

		<section
			class="dropzone"
			class:busy={busy !== null}
			role="button"
			tabindex="0"
			onclick={pickFiles}
			onkeydown={(event) => event.key === 'Enter' && pickFiles()}
		>
			<p><strong>Drop documents here</strong>, or click to choose.</p>
			{#if caps}<p class="muted">{caps.formats.join('  ')}</p>{/if}
		</section>

		{#if problem}
			<section class="alert error"><p>{problem}</p></section>
		{/if}

		{#if files.length}
			<section class="controls">
				<label>
					Minimum confidence
					<input
						type="range"
						min="0"
						max="1"
						step="0.05"
						bind:value={minConfidence}
						onchange={reinspectAll}
					/>
					<span class="mono">{minConfidence.toFixed(2)}</span>
				</label>
				{#if reviewModel}
					<!-- Stated next to the button that acts on it: the choice was made
					     further up the page and is easy to forget by the time you scrub. -->
					<span class="pill">review: {reviewModel}</span>
				{/if}
				<button onclick={runScrub} disabled={busy !== null || totalFindings === 0}>
					{busy === 'scrub' ? 'Scrubbing…' : `Scrub ${files.length} file(s)`}
				</button>
			</section>

			<section class="entities">
				<h2>Placeholder language</h2>
				<p class="hint">
					The wording written into the output in place of what was removed. Only
					the words change; nothing about what gets removed depends on this.
				</p>
				<select bind:value={placeholderLanguage}>
					{#each caps?.placeholder_languages ?? [] as code}
						<option value={code}>{code}</option>
					{/each}
				</select>
			</section>

			<section class="entities">
				<h2>Countries to look for</h2>
				<p class="hint">
					All of them unless you say otherwise. Narrowing raises precision and can
					hide an identifier from a country you did not expect in the file.
				</p>
				<div class="chips">
					{#each caps?.countries ?? [] as code}
						<button
							class="chip"
							class:on={!dropped.has(code)}
							onclick={() => toggleCountry(code)}
						>
							{code.toUpperCase()}
						</button>
					{/each}
				</div>
			</section>

			<section class="entities">
				<h2>Leave untouched</h2>
				<div class="chips">
					{#each entityList as entity}
						<button
							class="chip"
							class:on={kept.has(entity.name)}
							title={entity.report_only ? 'Flagged for review, never removed' : ''}
							onclick={() => toggleKeep(entity.name)}
						>
							{entity.name}{entity.report_only ? ' (flag only)' : ''}
						</button>
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
							<p class="muted">{inspection.format} · {inspection.characters} characters</p>
							{#if inspection.findings.length === 0}
								<p class="muted">Nothing matched.</p>
							{:else}
								<ul class="counts">
									{#each summary(inspection) as [entity, count, action]}
										<li><span class="mono">{count}</span> {entity} <em>{action}</em></li>
									{/each}
								</ul>
								<details>
									<summary>Show the {inspection.findings.length} values</summary>
									<table>
										<tbody>
											{#each inspection.findings as finding}
												<tr>
													<td class="mono">{finding.part}</td>
													<td>{finding.entity}{#if isMine(finding)} <em>yours</em>{/if}</td>
													<td><code>{finding.text}</code></td>
													<td class="mono">{finding.action}</td>
													<td>
														{#if isMine(finding)}
															<button
																class="linkish"
																onclick={() => dropValue(path, finding.text)}
																>don't remove</button
															>
														{:else}
															<button
																class="linkish"
																onclick={() => toggleSpan(path, finding)}
																title="Leave this one occurrence alone. Every other
occurrence of the same value is still removed.">keep this one</button
															>
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
								<input
									type="text"
									placeholder="Also remove this value..."
									bind:value={pending[path]}
									onkeydown={(event) => event.key === 'Enter' && addValue(path)}
								/>
								<button onclick={() => addValue(path)} disabled={!(pending[path] ?? '').trim()}>
									Add
								</button>
							</div>
							{#if (keptSpans[path] ?? []).length > 0}
								<p class="muted">
									{(keptSpans[path] ?? []).length} occurrence(s) kept on purpose.
									<button class="linkish" onclick={() => { keptSpans = { ...keptSpans, [path]: [] }; void loadInspection(path); }}>
										undo all
									</button>
								</p>
							{/if}
							{#each inspection.warnings as warning}
								<p class="warnline">{warning}</p>
							{/each}
						{/if}
					</article>
				{/each}
			</section>
		{/if}

		{#if progress}
			<section class="progress">
				<p>{basename(progress.file)} — {progress.index + 1} of {progress.total}</p>
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
								<p class="warnline">{warning}</p>
							{/each}
							{#if result.review}
								<!-- Advisory. The quotes come from the scrubbed text, so showing
								     them reveals nothing the output does not already. -->
								<h4>Second opinion</h4>
								<p class="muted">{result.review.summary}</p>
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
							<p class="failed-msg">Nothing was written. {result.error?.message}</p>
						{/if}
					</article>
				{/each}
			</section>
		{/if}

		{#if caps?.caveats.length}
			<footer>
				{#each caps.caveats as caveat}<p>{caveat}</p>{/each}
			</footer>
		{/if}
	{/if}
</main>

<style>
	/*
	 * Layout and local shape only. Every colour, space, radius and duration is a
	 * token from app.css.
	 *
	 * Two things left this file when the tokens arrived. The `:global(body)`
	 * rules, because a component styling the document is a component that cannot
	 * be moved. And both `prefers-color-scheme` blocks, because dark mode is now
	 * one attribute on <html> — which is also what lets a manual choice override
	 * the OS in either direction.
	 *
	 * The old hierarchy was `opacity` — twelve of them, 0.6 to 0.75. Opacity
	 * cannot be measured for contrast and dims a border along with the text it
	 * surrounds, so secondary text is now --text-2 / --text-3, which have their
	 * measured ratios written beside them.
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

	.pill {
		padding: var(--space-1) var(--space-3);
		border: 1px solid var(--border);
		border-radius: var(--radius-full);
		background: var(--surface);
		color: var(--text-2);
		font-size: var(--text-xs);
	}

	.pill.warn {
		border-color: var(--warn-border);
		background: var(--warn-soft);
		color: var(--warn-text);
	}

	.alert {
		padding: var(--space-3) var(--space-4);
		border-radius: var(--radius-3);
		margin-bottom: var(--space-4);
	}

	.alert p {
		margin: var(--space-1) 0;
	}

	.alert.warn {
		border: 1px solid var(--warn-border);
		background: var(--warn-soft);
		color: var(--warn-text);
	}

	.alert.error {
		border: 1px solid var(--danger-border);
		background: var(--danger-soft);
		color: var(--danger-text);
	}

	.settings {
		border: 1px solid var(--border);
		border-radius: var(--radius-3);
		background: var(--surface);
		box-shadow: var(--shadow-1);
		padding: var(--space-3) var(--space-4);
		margin-bottom: var(--space-4);
	}

	.settings summary {
		cursor: pointer;
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	.settings p {
		margin: var(--space-2) 0;
		font-size: var(--text-sm);
	}

	.settings .row {
		display: flex;
		align-items: center;
		gap: var(--space-4);
		flex-wrap: wrap;
		margin: var(--space-3) 0;
	}

	.settings label {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
	}

	input[type='text'] {
		font: inherit;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-1);
		border: 1px solid var(--border-strong);
		background: var(--surface);
		color: inherit;
	}

	input[type='text']:focus {
		border-color: var(--accent-line);
	}

	.host {
		width: 16rem;
	}

	.dropzone {
		border: 2px dashed var(--border-strong);
		border-radius: var(--radius-4);
		background: var(--surface);
		padding: var(--space-7) var(--space-4);
		text-align: center;
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

	.controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		margin: var(--space-5) 0 var(--space-2);
		flex-wrap: wrap;
	}

	.controls label {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	button {
		font: inherit;
		padding: var(--space-2) var(--space-4);
		border-radius: var(--radius-2);
		border: 1px solid var(--border-strong);
		background: var(--surface);
		color: var(--text);
		cursor: pointer;
		transition:
			background var(--dur-1) var(--ease-out),
			border-color var(--dur-1) var(--ease-out);
	}

	button:hover:not(:disabled) {
		background: var(--surface-hover);
	}

	button:active:not(:disabled) {
		background: var(--surface-active);
	}

	/* Disabled is a colour and a cursor, not a transparency: an opacity swap
	   dims the border to the point where the control stops looking like one. */
	button:disabled {
		color: var(--text-3);
		border-color: var(--border);
		cursor: default;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
	}

	.chip {
		font-size: var(--text-xs);
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-full);
		color: var(--text-2);
	}

	.chip.on {
		border-color: var(--accent-line);
		background: var(--accent-soft);
		color: var(--accent-text);
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

	/* An in-table action, not a call to action: the button must not compete with
	   Scrub for attention, because the common case is not touching it at all. */
	.linkish {
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		font-size: var(--text-sm);
		color: var(--accent-text);
		text-decoration: underline;
		cursor: pointer;
	}

	.linkish:hover {
		background: none;
		color: var(--accent-hover);
	}

	.addrow {
		display: flex;
		gap: var(--space-2);
		margin-top: var(--space-3);
	}

	.addrow input {
		flex: 1;
		min-width: 0;
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

	select {
		font: inherit;
		padding: var(--space-1);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-1);
		background: var(--surface);
		color: inherit;
	}

	.counts em {
		color: var(--text-3);
		font-style: normal;
		font-size: 0.85em;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	td {
		padding: var(--space-1) var(--space-2);
		border-top: 1px solid var(--border);
		vertical-align: top;
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
