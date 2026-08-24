import { open } from '@tauri-apps/plugin-dialog';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import {
	type Capabilities,
	type CountryCoverage,
	type Doctor,
	type EntityInfo,
	type Finding,
	type Inspection,
	type KeptSpan,
	type Progress,
	type Stage,
	type RemovedValue,
	type RestoreResult,
	type ScrubResult,
	MISSING_DEPENDENCY,
	NEEDS_OCR,
	UNSUPPORTED_FORMAT,
	capabilities,
	countries as fetchCoverage,
	doctor as fetchDoctor,
	engineStatus,
	entities,
	inspect,
	onNotify,
	restore,
	reviewModels,
	scrub
} from './engine';
import { announce } from './announce.svelte';
import { basename } from './format';
import { i18n } from './i18n/index.svelte';
import { resetReview } from './review.svelte';

/**
 * The window's session: what the engine said, what the user picked, and the
 * actions that move between the two.
 *
 * Extracted from `+page.svelte`, which was doing this as well as layout,
 * presentation and copywriting in one 936-line file. Nothing here decides
 * anything about confidentiality — it collects spans and strings and sends
 * them, and the engine decides what happens to them. That constraint is the
 * reason this module can exist at all: there is no rule in it to duplicate.
 *
 * One `$state` object rather than a dozen exported variables, because a module
 * cannot export reassignable state — an importer would see the value as it was
 * at import time. Fields of a reactive object stay live, and they stay
 * bindable, which is what `bind:value={session.reviewHost}` needs.
 */
export type Step = 'file' | 'review' | 'result';

/**
 * Which direction the window is working in.
 *
 * A mode rather than a fourth step. A document comes back from a model days after
 * the scrub that produced it, so restoring is not the continuation of a wizard
 * state — there is nothing in the session to continue from. Each mode owns its own
 * step order, which keeps the rule above intact: reachability stays derived, and a
 * step that means nothing in this mode is simply not in its order.
 */
export type Mode = 'scrub' | 'restore';

/** The steps each mode has, in the order the rail shows them. */
export const ORDER: Record<Mode, Step[]> = {
	scrub: ['file', 'review', 'result'],
	restore: ['file', 'result']
};

export const session = $state({
	mode: 'scrub' as Mode,
	/**
	 * Which of the three steps is showing.
	 *
	 * Reachability is *not* stored beside it: a step the user cannot be on cannot
	 * be the current one, and two sources for that fact is a window showing the
	 * review screen with nothing to review. The page derives it.
	 */
	step: 'file' as Step,
	/** Which document the review screen is looking at. */
	activePath: null as string | null,

	/** Why the engine did not start. Null when it did. */
	engineProblem: null as string | null,
	caps: null as Capabilities | null,
	entityList: [] as EntityInfo[],
	/**
	 * What each country gets at the current threshold, and what a narrowed
	 * selection costs. Asked of the engine rather than assembled here: which
	 * numbers have a checksum behind them is a judgement, and this window holds
	 * none.
	 */
	coverage: null as CountryCoverage | null,
	/** What this machine can do, and how to repair what it cannot. */
	diagnostics: null as Doctor | null,

	files: [] as string[],
	inspections: {} as Record<string, Inspection>,
	/** The path being read, or 'scrub' during a run, or null. */
	busy: null as string | null,
	progress: null as Progress | null,
	/**
	 * Which stage of one file is running. Cleared when the run ends, because a
	 * stale stage on screen is a claim that something is still happening.
	 */
	stage: null as Stage | null,
	results: [] as ScrubResult[],
	problem: null as string | null,

	/** Entity types the user has chosen to leave alone, everywhere. */
	kept: new Set<string>(),
	/**
	 * Single occurrences the user has excused, per file. A different control from
	 * `kept` above and deliberately so: that one says "no location in this
	 * document is confidential", this one says "not *this* one". The same city is
	 * confidential in a party's address and not in a jurisdiction clause, which is
	 * a judgement only the person reading the preview can make.
	 */
	keptSpans: {} as Record<string, KeptSpan[]>,
	/** Values the user says to remove that no detector found, per file. */
	extraValues: {} as Record<string, RemovedValue[]>,
	/** What is typed in the "also remove" box, per file, before it is added. */
	pending: {} as Record<string, string>,
	/**
	 * Countries switched *off*. Empty means every supported one, which is why
	 * this is a set of exclusions rather than inclusions: nothing selected has to
	 * mean "all", never "none".
	 */
	dropped: new Set<string>(),
	/** Prefilled from capabilities, because the default is the engine's to pick. */
	placeholderLanguage: '',
	minConfidence: 0.5,
	/** Empty means no review. Off by default: it is slow and changes nothing. */
	reviewModel: '',
	/**
	 * Where to look for Ollama, and what was found there.
	 *
	 * `models` is kept separate from `caps.review_models` rather than editing
	 * that in place: the capabilities are what the engine reported at startup,
	 * and overwriting them would lose the ability to tell "the default host has
	 * nothing" from "the host I typed has nothing".
	 */
	reviewHost: '',
	models: null as string[] | null,
	modelsProblem: null as string | null,
	modelsBusy: false,
	settingsOpen: false,

	/**
	 * Whether to also write an encrypted key file, and what opens it.
	 *
	 * Collected before the run, not after, because the engine writes the key file
	 * inside the `scrub` request — which is what keeps the mapping from ever
	 * crossing the pipe into this window.
	 *
	 * `keyPassphrase` and `keyConfirm` are cleared in a `finally` after every run.
	 * A secret that stays in memory because the run finished is a secret nobody
	 * decided to keep, and there is nowhere for it to be persisted to: no
	 * `localStorage`, unlike the theme and the locale.
	 */
	keyWanted: false,
	keyDir: null as string | null,
	keyPassphrase: '',
	keyConfirm: '',
	/** Where the engine put each key file, by document. Shown on the result step. */
	keyFiles: {} as Record<string, string>,

	/** The returned document, its key file, and what opens it. */
	restoreFile: null as string | null,
	restoreMap: null as string | null,
	restorePassphrase: '',
	restoreResult: null as RestoreResult | null
});

/** What the model dropdown offers: the typed host's answer, else the startup one. */
export function offeredModels(): string[] {
	return session.models ?? session.caps?.review_models ?? [];
}

export function totalFindings(): number {
	return session.files.reduce(
		(sum, path) => sum + (session.inspections[path]?.findings.length ?? 0),
		0
	);
}

/** A finding the user put there, rather than one a detector nominated. */
export function isMine(finding: Finding): boolean {
	return finding.detector === 'human';
}

/** Counts per entity type, which is what a preview is actually for. */
export function summary(inspection: Inspection): [string, number, string][] {
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
 * The engine's message, with the window's sentence in front of it where one
 * helps.
 *
 * NEEDS_OCR is passed through untouched: that message already names the pages
 * and what to install, and a preamble in front of it would be the window
 * competing with an answer that is complete.
 */
export function describe(error: unknown): string {
	const code = (error as { code?: number | null })?.code ?? null;
	const message = error instanceof Error ? error.message : String(error);
	if (code === NEEDS_OCR) return message;
	if (code === UNSUPPORTED_FORMAT) return i18n.m.errorUnsupportedFormat({ message });
	if (code === MISSING_DEPENDENCY) return i18n.m.errorMissingComponent({ message });
	return message;
}

/** A failure the user must not miss: said once, shown until it is replaced. */
function fail(message: string): void {
	session.problem = message;
	announce(message, { assertive: true });
}

/**
 * Start the engine conversation and the drag-and-drop subscription.
 *
 * Returns the teardown rather than registering it, because an async function
 * cannot hand Svelte a cleanup callback: both subscriptions are set up after an
 * await, so `onMount` has already returned by the time they exist.
 */
export async function start(): Promise<() => void> {
	const unsubscribes: (() => void)[] = [];

	session.engineProblem = await engineStatus();
	if (session.engineProblem) return () => {};

	unsubscribes.push(
		await onNotify({
			progress: (value) => {
				// Announced per file, which is what the engine reports. Announcing
				// anything finer would be inventing a number it does not have.
				if (value.file !== session.progress?.file) {
					announce(
						i18n.m.progressFile({
							file: basename(value.file),
							index: value.index + 1,
							total: value.total
						})
					);
				}
				session.progress = value;
			},
			// Subscribed, and it had not been: the notification was emitted,
			// forwarded, typed, translated in four catalogues and rendered by the
			// page, with nothing on this line to receive it. `session.stage` was
			// written null twice and never anything else, so the inner bar had
			// never drawn. Nothing in the toolchain could see it - the field is
			// declared, written and read, and the catalogue check proves the keys
			// exist, not that anyone consumes them.
			stage: (value) => {
				session.stage = value;
			},
			ready: adoptCaps
		})
	);

	try {
		adoptCaps(await capabilities());
		session.entityList = (await entities(session.placeholderLanguage)).entities;
		await Promise.all([refreshCoverage(), refreshDiagnostics()]);
	} catch (error) {
		fail(describe(error));
	}

	unsubscribes.push(
		await getCurrentWebview().onDragDropEvent((event) => {
			if (event.payload.type === 'drop') addFiles(event.payload.paths);
		})
	);

	return () => {
		for (const unsubscribe of unsubscribes) unsubscribe();
	};
}

/**
 * Take the engine's report, and seed the review host from it the first time.
 *
 * Seeded rather than defaulted here: the address Ollama listens on is the
 * engine's business, and a second copy in the window is a second thing to be
 * wrong. Only when the field is untouched, so a re-announced `ready` cannot
 * discard what the user typed.
 */
function adoptCaps(value: Capabilities): void {
	const first = session.caps === null;
	session.caps = value;
	if (!session.reviewHost) session.reviewHost = value.review_host;
	if (!session.placeholderLanguage) session.placeholderLanguage = value.placeholder_language;
	/*
	 * Open when there is a choice to make.
	 *
	 * Seeded once from the startup report rather than bound to it: expanding a
	 * panel the user has just collapsed is worse than the click it saves. Closed
	 * when Ollama has nothing, because an empty control is a distraction, and the
	 * label stays visible either way — being invisible was the original
	 * complaint.
	 */
	if (first) session.settingsOpen = value.review_models.length > 0;
}

/**
 * Re-ask what the current country selection and threshold add up to.
 *
 * Cheap — it reads the rule table, loads no model — and worth re-asking on every
 * change, because the answer is what makes the threshold slider legible: it
 * names the rules that just went silent.
 */
export async function refreshCoverage(): Promise<void> {
	try {
		session.coverage = await fetchCoverage({
			countries: activeCountries(),
			minConfidence: session.minConfidence
		});
	} catch {
		// A missing explanation must not break the panel it explains.
		session.coverage = null;
	}
}

export async function refreshDiagnostics(): Promise<void> {
	try {
		session.diagnostics = await fetchDoctor(session.reviewHost || undefined);
	} catch {
		session.diagnostics = null;
	}
}

/**
 * Change the placeholder language, and re-ask what it writes.
 *
 * The example placeholders come from the engine, composed by the allocator that
 * writes the document. Deriving them here from the locale code would be the
 * window inventing the wording, which is the one thing the placeholder table is
 * for.
 */
export async function setPlaceholderLanguage(locale: string): Promise<void> {
	session.placeholderLanguage = locale;
	try {
		session.entityList = (await entities(locale)).entities;
	} catch (error) {
		fail(describe(error));
	}
}

/** Ask a specific Ollama what it has, and say so where the host was typed. */
export async function refreshModels(): Promise<void> {
	session.modelsBusy = true;
	session.modelsProblem = null;
	try {
		const found = (await reviewModels(session.reviewHost)).models;
		session.models = found;
		// A model the new host does not have would otherwise stay selected and
		// fail at scrub time, pointing at the wrong thing entirely.
		if (session.reviewModel && !found.includes(session.reviewModel)) session.reviewModel = '';
	} catch (error) {
		session.models = [];
		session.modelsProblem = describe(error);
	} finally {
		session.modelsBusy = false;
	}
}

/** The typed host's answer is about that host, so a new host invalidates it. */
export function forgetModels(): void {
	session.models = null;
	session.modelsProblem = null;
}

export function addFiles(paths: string[]): void {
	session.files = [...new Set([...session.files, ...paths])];
	// Reviewing is the default, not a gate: the user lands on the preview and can
	// scrub straight from it. Nobody is made to read anything.
	if (!session.activePath) select(paths[0] ?? null);
	if (paths.length) session.step = 'review';
	for (const path of paths) void loadInspection(path);
}

/** Show one document in the review pane, dropping the previous selection. */
export function select(path: string | null): void {
	session.activePath = path;
	resetReview();
}

export function removeFile(path: string): void {
	session.files = session.files.filter((item) => item !== path);
	delete session.inspections[path];
	// The decisions went with the file. Keeping them would apply a span from a
	// document nobody is looking at to whatever is opened next.
	const { [path]: _keptSpans, ...spans } = session.keptSpans;
	const { [path]: _values, ...values } = session.extraValues;
	session.keptSpans = spans;
	session.extraValues = values;
	if (session.activePath === path) select(session.files[0] ?? null);
	if (!session.files.length) session.step = 'file';
}

export function clearFiles(): void {
	session.files = [];
	session.inspections = {};
	session.keptSpans = {};
	session.extraValues = {};
	session.results = [];
	session.keyFiles = {};
	select(null);
	session.step = 'file';
	forgetSecrets();
}

export function goTo(step: Step): void {
	session.step = step;
}

/**
 * Change direction, and land on the first step of the new mode.
 *
 * Not `goTo('file')` plus a flag: `step` is shared between the modes, and
 * arriving in restore mode on a step that mode has never had is exactly the
 * "showing Review with nothing to review" failure the derived reachability rule
 * exists to prevent.
 */
export function setMode(mode: Mode): void {
	if (session.mode === mode) return;
	session.mode = mode;
	session.step = 'file';
	session.problem = null;
	// The two directions do not share a secret. Leaving one mode's passphrase in
	// memory while the other is on screen is a secret nobody decided to keep.
	forgetSecrets();
}

/** Every passphrase this window is holding, gone. Called on every exit path. */
function forgetSecrets(): void {
	session.keyPassphrase = '';
	session.keyConfirm = '';
	session.restorePassphrase = '';
}

/** Whether the key-file controls can do anything, which is the engine's answer. */
export function keyFileAvailable(): boolean {
	return session.caps?.mapping_available ?? false;
}

/**
 * What is still missing before a key file can be written.
 *
 * Returned as a key rather than a sentence so the screen translates it: these are
 * the window's own preconditions, not the engine's prose. Null means ready.
 */
export function keyFileBlocker(): 'directory' | 'passphrase' | 'mismatch' | null {
	if (!session.keyWanted) return null;
	if (!session.keyDir) return 'directory';
	if (session.keyPassphrase.length < passphraseMinimum()) return 'passphrase';
	if (session.keyPassphrase !== session.keyConfirm) return 'mismatch';
	return null;
}

/**
 * The engine's floor, asked for rather than restated.
 *
 * This was `const MIN_PASSPHRASE = 8`, and it was the one rule this window held.
 * Raising the floor in `core/mapping.py` left the window still accepting eight
 * characters: the engine refused inside the `scrub` request and the failure
 * arrived after the scrubbed copies were written. Published by `capabilities` the
 * way `preview_max_characters` is, for the same reason.
 *
 * `Infinity` with no answer yet is deliberate, and it is not a second copy of the
 * rule: it leaves the button disabled rather than promising a run the engine
 * would refuse. It is unreachable in practice - the passphrase field lives behind
 * `keyFileAvailable()`, which is false until capabilities arrive.
 */
export function passphraseMinimum(): number {
	return session.caps?.passphrase_min_characters ?? Infinity;
}

export async function pickKeyDirectory(): Promise<void> {
	const chosen = await open({
		directory: true,
		multiple: false,
		title: i18n.m.chooseKeyDirectory()
	});
	if (!chosen || Array.isArray(chosen)) return;
	session.keyDir = chosen;
}

export async function pickRestoreFile(): Promise<void> {
	const chosen = await open({ multiple: false, directory: false });
	if (!chosen || Array.isArray(chosen)) return;
	session.restoreFile = chosen;
	session.restoreResult = null;
}

export async function pickRestoreMap(): Promise<void> {
	const chosen = await open({
		multiple: false,
		directory: false,
		title: i18n.m.chooseKeyFile(),
		filters: [{ name: i18n.m.keyFileFilter(), extensions: ['fdmap'] }]
	});
	if (!chosen || Array.isArray(chosen)) return;
	session.restoreMap = chosen;
	session.restoreResult = null;
}

export function clearRestore(): void {
	session.restoreFile = null;
	session.restoreMap = null;
	session.restoreResult = null;
	session.step = 'file';
	forgetSecrets();
}

/** What is still missing before a restore can run. Null means ready. */
export function restoreBlocker(): 'document' | 'key' | 'passphrase' | null {
	if (!session.restoreFile) return 'document';
	if (!session.restoreMap) return 'key';
	if (!session.restorePassphrase) return 'passphrase';
	return null;
}

/**
 * Put the values back, and show what did not come back.
 *
 * `ok: false` is not a failure of this call and does not go through `fail()`: the
 * engine wrote the file either way, and the result screen names every placeholder
 * that did not make it. A half-restored document is still the user's best
 * artifact — the opposite of a scrub that leaked, where nothing is written.
 */
export async function runRestore(): Promise<void> {
	const document = session.restoreFile;
	const key = session.restoreMap;
	if (!document || !key || !session.restorePassphrase) return;

	const target = await open({
		directory: true,
		multiple: false,
		title: i18n.m.chooseOutputDirectory()
	});
	if (!target || Array.isArray(target)) return;

	session.busy = 'restore';
	session.problem = null;
	session.restoreResult = null;
	try {
		const result = await restore(document, key, session.restorePassphrase, target);
		session.restoreResult = result;
		session.step = 'result';
		announce(
			result.ok
				? i18n.m.announceRestored({
						count: result.restored.reduce((sum, entry) => sum + entry.occurrences, 0)
					})
				: i18n.m.announceRestoredWithProblems({ count: result.problems.length }),
			{ assertive: !result.ok }
		);
	} catch (error) {
		fail(describe(error));
	} finally {
		session.busy = null;
		session.stage = null;
		// Held for the call and no longer. Retyping it is the correct cost of a
		// secret this window is not allowed to keep.
		forgetSecrets();
	}
}

export async function pickFiles(): Promise<void> {
	const chosen = await open({ multiple: true, directory: false });
	if (!chosen) return;
	addFiles(Array.isArray(chosen) ? chosen : [chosen]);
}

export async function loadInspection(path: string): Promise<void> {
	session.busy = path;
	session.problem = null;
	try {
		const inspection = await inspect(path, {
			keep: [...session.kept],
			keepSpans: session.keptSpans[path] ?? [],
			remove: session.extraValues[path] ?? [],
			minConfidence: session.minConfidence,
			countries: activeCountries(),
			// The review pane renders the document, so it asks for it. Opt-in on the
			// wire because this text contains the confidential values no layer
			// detected, which is more than the findings alone.
			includeText: true
		});
		session.inspections[path] = inspection;
		// Nothing here moves focus, so without this the result of a decision is
		// silent: the table simply has a different number of rows.
		announce(
			i18n.m.announceValuesFound({
				file: basename(path),
				count: inspection.findings.length
			})
		);
	} catch (error) {
		fail(i18n.m.errorInFile({ file: basename(path), message: describe(error) }));
	} finally {
		session.busy = null;
		session.stage = null;
	}
}

export async function reinspectAll(): Promise<void> {
	for (const path of session.files) await loadInspection(path);
}

/**
 * Excuse or re-include one occurrence.
 *
 * The span carries the text it covered, which is what lets the engine refuse
 * the decision if the file changes underneath it: the offsets would then point
 * at something the user never saw, and honouring them would keep whatever moved
 * into that range.
 */
export function toggleSpan(path: string, finding: Finding): void {
	const current = session.keptSpans[path] ?? [];
	const already = current.some((span) => span.start === finding.start && span.end === finding.end);
	session.keptSpans = {
		...session.keptSpans,
		[path]: already
			? current.filter((span) => !(span.start === finding.start && span.end === finding.end))
			: [...current, { start: finding.start, end: finding.end, text: finding.text, path }]
	};
	void loadInspection(path);
}

export function clearSpans(path: string): void {
	session.keptSpans = { ...session.keptSpans, [path]: [] };
	void loadInspection(path);
}

export function addValue(path: string): void {
	const value = (session.pending[path] ?? '').trim();
	if (!value) return;
	const current = session.extraValues[path] ?? [];
	if (!current.some((item) => item.value === value)) {
		session.extraValues = { ...session.extraValues, [path]: [...current, { value, path }] };
	}
	session.pending = { ...session.pending, [path]: '' };
	void loadInspection(path);
}

export function dropValue(path: string, value: string): void {
	session.extraValues = {
		...session.extraValues,
		[path]: (session.extraValues[path] ?? []).filter((item) => item.value !== value)
	};
	void loadInspection(path);
}

export function toggleKeep(name: string): void {
	const next = new Set(session.kept);
	if (next.has(name)) next.delete(name);
	else next.add(name);
	session.kept = next;
	void reinspectAll();
}

/** The threshold changed: re-inspect, and re-ask what it silenced. */
export function applyConfidence(): void {
	void refreshCoverage();
	void reinspectAll();
}

/**
 * Undefined when nothing is switched off, so the engine hears no opinion and
 * uses every country. Sending the full list would mean the same thing, but it
 * would also make the request claim a choice nobody made.
 */
export function activeCountries(): string[] | undefined {
	if (!session.caps || session.dropped.size === 0) return undefined;
	return session.caps.countries.filter((code) => !session.dropped.has(code));
}

export function toggleCountry(code: string): void {
	const next = new Set(session.dropped);
	if (next.has(code)) next.delete(code);
	else next.add(code);
	// Never all of them: an empty selection is refused by the engine, and it
	// would mean scrubbing with the whole checksum layer switched off.
	if (session.caps && next.size === session.caps.countries.length) return;
	session.dropped = next;
	void refreshCoverage();
	void reinspectAll();
}

export async function runScrub(): Promise<void> {
	const target = await open({
		directory: true,
		multiple: false,
		title: i18n.m.chooseOutputDirectory()
	});
	if (!target || Array.isArray(target)) return;

	session.busy = 'scrub';
	session.problem = null;
	session.results = [];
	try {
		session.results = (
			await scrub(session.files, target, {
				keep: [...session.kept],
				// Every file's decisions in one request, each carrying its own path.
				// The engine scopes them per document, because a span is an offset
				// into one extraction and would be stale anywhere else — see
				// Override.for_path.
				keepSpans: session.files.flatMap((path) => session.keptSpans[path] ?? []),
				remove: session.files.flatMap((path) => session.extraValues[path] ?? []),
				minConfidence: session.minConfidence,
				countries: activeCountries(),
				placeholderLanguage: session.placeholderLanguage,
				review: session.reviewModel || null,
				reviewHost: session.reviewHost,
				// Both or neither, which `toParams` enforces: the engine refuses a key
				// file with no passphrase rather than quietly writing nothing.
				map: session.keyWanted ? session.keyDir : null,
				mapPassphrase: session.keyWanted ? session.keyPassphrase : null
			})
		).results;

		// Where each key went, collected here so the result screen has one place to
		// read it from rather than reaching into each result.
		session.keyFiles = Object.fromEntries(
			session.results
				.filter((result) => result.key_file)
				.map((result) => [result.path, result.key_file as string])
		);
		session.step = 'result';
		const failed = session.results.filter((result) => !result.ok).length;
		announce(
			failed === 0
				? i18n.m.announceFinished({ files: session.results.length })
				: i18n.m.announceFinishedWithFailures({
						failed,
						files: session.results.length
					}),
			{ assertive: failed > 0 }
		);
	} catch (error) {
		fail(describe(error));
	} finally {
		session.busy = null;
		session.progress = null;
		session.stage = null;
		// The passphrase existed for this request. Emptying the fields after a
		// successful scrub is deliberate: the next run is a new decision.
		forgetSecrets();
	}
}
