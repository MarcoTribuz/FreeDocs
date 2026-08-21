<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { open } from '@tauri-apps/plugin-dialog';
	import { getCurrentWebview } from '@tauri-apps/api/webview';
	import {
		type Capabilities,
		type EntityInfo,
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
		scrub
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
	 * Countries to look for identifiers in. Empty means every supported one,
	 * which is why this is a set of *exclusions* to send rather than a set of
	 * inclusions: nothing selected has to mean "all", never "none".
	 */
	let dropped = $state<Set<string>>(new Set());
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
					minConfidence,
					countries: activeCountries(),
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

<main>
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
													<td>{finding.entity}</td>
													<td><code>{finding.text}</code></td>
													<td class="mono">{finding.action}</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</details>
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
	:global(body) {
		margin: 0;
		font: 15px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
		color: #1b1b1f;
		background: #f7f7f8;
	}
	@media (prefers-color-scheme: dark) {
		:global(body) {
			color: #e8e8ea;
			background: #16161a;
		}
	}

	main {
		max-width: 60rem;
		margin: 0 auto;
		padding: 2rem 1.5rem 4rem;
	}
	h1 {
		margin: 0;
		font-size: 1.6rem;
	}
	h2 {
		font-size: 1rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		opacity: 0.7;
	}
	h3 {
		margin: 0 0 0.25rem;
		font-size: 1rem;
	}
	h4 {
		margin: 0.75rem 0 0.25rem;
		font-size: 0.85rem;
	}
	.lead {
		max-width: 42rem;
		opacity: 0.75;
	}
	.muted {
		opacity: 0.6;
	}
	.hint {
		margin: 0 0 0.5rem;
		max-width: 42rem;
		font-size: 0.85rem;
		opacity: 0.7;
	}
	.mono {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.85em;
	}

	.status {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
		margin-bottom: 1rem;
	}
	.pill {
		padding: 0.2rem 0.6rem;
		border-radius: 999px;
		background: rgba(127, 127, 127, 0.15);
		font-size: 0.8rem;
	}
	.pill.warn {
		background: rgba(200, 140, 0, 0.25);
	}

	.alert {
		padding: 0.75rem 1rem;
		border-radius: 0.5rem;
		margin-bottom: 1rem;
	}
	.alert p {
		margin: 0.25rem 0;
	}
	.alert.warn {
		background: rgba(200, 140, 0, 0.15);
		border: 1px solid rgba(200, 140, 0, 0.4);
	}
	.alert.error {
		background: rgba(200, 60, 60, 0.12);
		border: 1px solid rgba(200, 60, 60, 0.4);
	}

	.settings {
		border: 1px solid rgba(127, 127, 127, 0.25);
		border-radius: 0.5rem;
		padding: 0.6rem 1rem;
		margin-bottom: 1rem;
	}
	.settings summary {
		cursor: pointer;
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		opacity: 0.7;
	}
	.settings p {
		margin: 0.5rem 0;
		font-size: 0.85rem;
	}
	.settings .row {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-wrap: wrap;
		margin: 0.6rem 0;
	}
	.settings label {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-size: 0.85rem;
	}
	input[type='text'] {
		font: inherit;
		padding: 0.3rem 0.45rem;
		border-radius: 0.35rem;
		border: 1px solid rgba(127, 127, 127, 0.4);
		background: rgba(127, 127, 127, 0.08);
		color: inherit;
	}
	.host {
		width: 16rem;
	}

	.dropzone {
		border: 2px dashed rgba(127, 127, 127, 0.5);
		border-radius: 0.75rem;
		padding: 2.5rem 1rem;
		text-align: center;
		cursor: pointer;
	}
	.dropzone.busy {
		opacity: 0.6;
	}

	.controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		margin: 1.5rem 0 0.5rem;
		flex-wrap: wrap;
	}
	.controls label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}
	button {
		font: inherit;
		padding: 0.5rem 1rem;
		border-radius: 0.5rem;
		border: 1px solid rgba(127, 127, 127, 0.4);
		background: rgba(127, 127, 127, 0.1);
		cursor: pointer;
	}
	button:disabled {
		opacity: 0.5;
		cursor: default;
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}
	.chip {
		font-size: 0.78rem;
		padding: 0.2rem 0.5rem;
	}
	.chip.on {
		background: rgba(60, 140, 200, 0.3);
		border-color: rgba(60, 140, 200, 0.6);
	}

	article {
		border: 1px solid rgba(127, 127, 127, 0.25);
		border-radius: 0.5rem;
		padding: 0.9rem 1rem;
		margin: 0.6rem 0;
	}
	article.failed {
		border-color: rgba(200, 60, 60, 0.5);
	}
	.failed-msg {
		color: #b03a3a;
	}
	.warnline {
		margin: 0.35rem 0;
		font-size: 0.85rem;
		color: #8a6100;
	}
	@media (prefers-color-scheme: dark) {
		.warnline {
			color: #d3a44a;
		}
	}

	.counts {
		list-style: none;
		padding: 0;
		margin: 0.5rem 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
	}
	.concerns {
		list-style: none;
		padding: 0;
		margin: 0.4rem 0 0;
	}
	.concerns li {
		margin: 0.45rem 0;
		padding-left: 0.6rem;
		border-left: 2px solid rgba(200, 140, 0, 0.5);
	}
	.kind {
		display: inline-block;
		font-size: 0.72rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		opacity: 0.7;
		margin-right: 0.4rem;
	}
	.why {
		display: block;
		font-size: 0.85rem;
		opacity: 0.75;
	}
	select {
		font: inherit;
		padding: 0.25rem;
	}

	.counts em {
		opacity: 0.6;
		font-style: normal;
		font-size: 0.85em;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.85rem;
	}
	td {
		padding: 0.2rem 0.4rem;
		border-top: 1px solid rgba(127, 127, 127, 0.2);
		vertical-align: top;
	}

	footer {
		margin-top: 2.5rem;
		padding-top: 1rem;
		border-top: 1px solid rgba(127, 127, 127, 0.25);
		font-size: 0.82rem;
		opacity: 0.7;
	}
</style>
