import { open, save } from '@tauri-apps/plugin-dialog';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import {
	type Capabilities,
	type CountryCoverage,
	type Doctor,
	type EngineIdentity,
	type EntityInfo,
	type Finding,
	type Inspection,
	type KeptSpan,
	type Progress,
	type Stage,
	type RemovedValue,
	type RestoreResult,
	type ScrubResult,
	type TesseractRefusal,
	type Term,
	type TextRestoreResult,
	type TextScrubResult,
	MISSING_DEPENDENCY,
	NEEDS_OCR,
	UNSUPPORTED_FORMAT,
	capabilities,
	countries as fetchCoverage,
	doctor as fetchDoctor,
	engineStatus,
	useTesseract,
	entities,
	forget as forgetExtractions,
	inspect,
	onNotify,
	restore,
	reviewModels,
	scrub,
	termsCreate,
	termsExport,
	termsImport,
	termsList,
	termsLock,
	termsRekey,
	termsUnlock,
	termsUpdate,
	forgetTextMaps,
	inspectText,
	restoreText,
	scrubText
} from './engine';
import { announce } from './announce.svelte';
import { basename } from './format';
import { i18n } from './i18n/index.svelte';
import { resetReview } from './review.svelte';
import { keptSpanFor, type Mode, type Step } from './steps';
import { checkModel, detectorSpec, onDownload } from './model.svelte';

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
export { ORDER, type Mode, type Step } from './steps';

/**
 * What a paste goes by in the window: the engine's own name for it, used as the
 * one "file" of text mode so the review screen needs no second code path.
 * Every inspection, kept span and added value for the paste is keyed on it.
 */
export const PASTED = 'pasted.txt';

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
	/**
	 * Which engine is answering. From the shell, not the engine — see
	 * `EngineIdentity`. Shown always, not only on a failure: a stale sidecar is
	 * not a failing check, it is the wrong engine answering correctly.
	 */
	engineIdentity: null as EngineIdentity | null,
	/** A re-check in flight, so the button can say so without leaving the tab order. */
	rechecking: false,
	/** Why the engine refused a chosen Tesseract. An enum, so it is translated. */
	tesseractRefusal: null as TesseractRefusal | null,
	/**
	 * The engine's code for `problem`, when it had one.
	 *
	 * Held so the failure callout can offer the repair for a refused scan. It
	 * decides which controls appear, never what the message says.
	 */
	problemCode: null as number | null,

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
	restoreResult: null as RestoreResult | null,

	/**
	 * The firm's term list: which file, whether the engine holds it unlocked, and
	 * what opens it.
	 *
	 * The entries themselves live in the engine, not here — this holds only the
	 * slice the editor is showing. `termsPath` is remembered in `localStorage`
	 * like the Tesseract path; the passphrase and the entries never are.
	 *
	 * `termsPassphrase` is the one secret this window keeps past a single call,
	 * and it is deliberate: every save re-opens the file with it (see
	 * `termsUpdate`), so dropping it after the unlock would mean retyping it for
	 * every entry added. It lives exactly as long as the unlock — cleared by
	 * `lockTerms`, which a mode change and closing the list both go through — and
	 * `forgetSecrets` leaves it alone, because a scrub finishing is not the list
	 * being closed.
	 */
	termsPath: null as string | null,
	termsUnlocked: false,
	termsCount: 0,
	termsPassphrase: '',
	/** Only for a new list: a mistyped passphrase on it is unrecoverable. */
	termsConfirm: '',
	/** Whether a new list is being set up, which needs the confirm field. */
	termsCreating: false,
	/** Send `use_terms` with every inspect and scrub. On by default once unlocked. */
	termsUse: true,
	termsQuery: '',
	termsShown: [] as Term[],
	termsNewValue: '',
	termsNewEntity: 'OTHER',
	termsBusy: false,
	/** The engine's refusal, quoted. Kept beside the panel rather than in `problem`. */
	termsProblem: null as string | null,
	/** The last import's counts and the file to delete. Shown until dismissed. */
	termsImported: null as { source: string; added: number; skipped: number } | null,
	/** Export is two clicks on purpose: the first says what it costs. */
	termsExportArmed: false,
	/**
	 * Text mode. The paste, what became of it, and the reply.
	 *
	 * None of it touches `localStorage`, and all of it goes on "New text", a mode
	 * change and the end of the session. `textKeep` is chosen per text and not
	 * remembered: a remembered "keep" is a default nobody chose, and the engine's
	 * own default is irreversible.
	 */
	pastedText: '',
	textKeep: 'none' as 'none' | 'memory' | 'file',
	textResult: null as TextScrubResult | null,
	replyText: '',
	/** Only to open a key file this text was sealed into; cleared after each try. */
	textRestorePassphrase: '',
	textRestored: null as TextRestoreResult | null,

	/** Where the last export went, with the engine's warning beside it. */
	termsExported: null as { output: string; warning: string } | null,
	/**
	 * Changing the passphrase. The current one is typed again rather than taken
	 * from `termsPassphrase`: an unlocked window left on a desk should not be
	 * enough to lock its owner out of the list. Cleared with the rest by
	 * `lockTerms` and after every attempt.
	 */
	termsRekeying: false,
	termsOld: '',
	termsNext: '',
	termsNextConfirm: ''
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

/**
 * A finding the term list put there. Layer `H` like the user's own - both are
 * instructions - but told apart by the engine's detector name, which is its
 * answer to "who claimed this" and not a rule about its naming.
 */
export function isFromTerms(finding: Finding): boolean {
	return finding.detector === 'terms';
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

/**
 * A failure the user must not miss: said once, shown until it is replaced.
 *
 * The code is kept beside the message because one failure has a repair the window
 * can offer. A refused scan is the moment the user cares about OCR, and until now
 * that message was a dead end with the fix behind a disclosure on another screen.
 * `describe` still returns the engine's sentence untouched — the code decides
 * which controls appear beneath it, never what it says.
 */
function fail(message: string, code: number | null = null): void {
	session.problem = message;
	session.problemCode = code;
	announce(message, { assertive: true });
}

/** The engine's code for a failure, when it carried one. */
function codeOf(error: unknown): number | null {
	return (error as { code?: number | null })?.code ?? null;
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

	const status = await engineStatus();
	session.engineProblem = status.problem;
	session.engineIdentity = status.identity;
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
			ready: adoptCaps,
			download: onDownload
		})
	);

	try {
		adoptCaps(await capabilities());
		// Before `refreshDiagnostics`, so the doctor is asked once and after the
		// adoption. The badge may paint "OCR missing" for a few milliseconds first;
		// that is honest — it is what the engine said at that moment.
		await applyRememberedTesseract();
		applyRememberedTerms();
		session.entityList = (await entities(session.placeholderLanguage)).entities;
		// After the entity list, which the first-run screen's example is drawn from.
		await checkModel();
		await Promise.all([refreshCoverage(), refreshDiagnostics()]);
	} catch (error) {
		fail(describe(error), codeOf(error));
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

/**
 * Where a chosen Tesseract is remembered, and why here.
 *
 * `localStorage`, like the theme and the locale, with the same limit stated the
 * same way: it lives in the webview profile, so it is not portable. A path is a
 * preference and a machine-specific one at that; passphrases stay out of here for
 * the opposite reason.
 *
 * Not in `Launch.env` on the Rust side. That is resolved once at startup on
 * purpose, and a store there would be a second place deciding where Tesseract is
 * — holding the choice *before* anything validated it, which is Rust holding a
 * rule about what counts as a Tesseract.
 *
 * What is remembered is the user's **choice**, never the engine's verdict. The
 * path goes back through `use_tesseract` on the next launch and is validated
 * again, so a Tesseract since uninstalled is refused rather than silently
 * trusted.
 */
const TESSERACT_KEY = 'freedocs.tesseract';

/**
 * Re-apply the remembered choice, but only where the engine says it is needed.
 *
 * The guard is `caps.ocr_available` — the engine's own answer, not a rule about
 * Tesseract — and it is what preserves the precedence `portable_env`'s `set()`
 * establishes. A `FREEDOCS_TESSERACT` from the launcher, a binary on `PATH`, or
 * one of the usual install locations all resolve before this runs, and a path
 * remembered from a previous session must not overrule any of them: a current
 * statement beats a memory.
 *
 * Startup only. `recheck()` deliberately does not call this — a user who has just
 * installed Tesseract and pressed Re-check must not have last month's choice
 * reasserted over it.
 */
async function applyRememberedTesseract(): Promise<void> {
	if (!browserStorage()) return;
	if (session.caps?.ocr_available !== false) return;
	const remembered = safeRead(TESSERACT_KEY);
	if (!remembered) return;
	try {
		const choice = await useTesseract(remembered);
		if (choice.accepted) {
			session.caps = { ...session.caps, ...ocrFields(choice) };
			return;
		}
	} catch {
		// Fall through: a remembered path that cannot be applied is not an error
		// the user needs at startup.
	}
	// Refused, so forget it and say nothing. `ocr_unavailable_reason` already
	// reports that nothing was found, which is true, and a warning about a
	// dropped preference is noise on a screen whose warnings are about documents.
	safeRemove(TESSERACT_KEY);
}

/** The two capability fields `use_tesseract` answers with, and only those. */
function ocrFields(choice: {
	ocr_available: boolean;
	ocr_unavailable_reason: string | null;
}): Pick<Capabilities, 'ocr_available' | 'ocr_unavailable_reason'> {
	return {
		ocr_available: choice.ocr_available,
		ocr_unavailable_reason: choice.ocr_unavailable_reason
	};
}

function browserStorage(): boolean {
	try {
		return typeof localStorage !== 'undefined';
	} catch {
		return false;
	}
}

function safeRead(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

function safeWrite(key: string, value: string): void {
	try {
		localStorage.setItem(key, value);
	} catch {
		// A preference that cannot be stored is a preference that does not survive
		// the session. Nothing else depends on it.
	}
}

function safeRemove(key: string): void {
	try {
		localStorage.removeItem(key);
	} catch {
		// As above.
	}
}

/**
 * Ask the engine again what this machine can do.
 *
 * Both questions, because the window shows both: `capabilities` drives the OCR
 * badge and the reason callout, `doctor` drives the pane. Until this existed the
 * only way to see a machine that had gained Tesseract was to restart the app —
 * and a *stale sidecar* looked identical to a machine with no Tesseract, which is
 * the defect this whole change is about.
 *
 * Cheap to ask: neither call loads the model.
 */
export async function recheck(): Promise<void> {
	session.rechecking = true;
	try {
		adoptCaps(await capabilities());
		await refreshDiagnostics();
	} catch (error) {
		fail(describe(error), codeOf(error));
	} finally {
		session.rechecking = false;
	}
}

/**
 * Let the user point the window at a Tesseract, and let the engine judge it.
 *
 * No filters on the dialog, deliberately. What counts as runnable differs by
 * platform — a permission bit here, a `PATHEXT` suffix on Windows — and the
 * engine already owns that question. A filter would be the window holding a rule
 * about what a Tesseract looks like, and on macOS an `exe` filter would hide the
 * only file that works.
 *
 * The window re-asks rather than merging the response into `session.caps`
 * wholesale: one code path shared with the Re-check button, and no chance of a
 * half-updated capabilities object.
 */
export async function locateTesseract(): Promise<void> {
	const picked = await open({ multiple: false, directory: false, title: i18n.m.chooseTesseract() });
	if (typeof picked !== 'string') return;
	session.rechecking = true;
	try {
		const choice = await useTesseract(picked);
		session.tesseractRefusal = choice.refused;
		if (!choice.accepted) return;
		if (browserStorage()) safeWrite(TESSERACT_KEY, picked);
		// A NEEDS_OCR failure from before this adoption is now stale. That
		// staleness is window state, not an engine judgement, so clearing it here
		// is a control and not a rule.
		if (session.problemCode === NEEDS_OCR) {
			session.problem = null;
			session.problemCode = null;
		}
		announce(i18n.m.tesseractAccepted());
	} catch (error) {
		fail(describe(error), codeOf(error));
	} finally {
		session.rechecking = false;
		await recheck();
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
		fail(describe(error), codeOf(error));
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
	// Text mode borrows `files` for its one paste; a file dropped on the window
	// there would join a list that is not a batch. Ignored rather than switching
	// mode under the person's hands.
	if (session.mode === 'text') return;
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
	// And in the engine, which is holding the extracted text — a superset of the
	// findings, since it contains whatever no layer detected. The window dropping
	// its copy while the sidecar keeps one is half a tidy-up.
	forgetExtractions([path]);
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
	forgetExtractions(session.files);
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
	if (session.mode === 'text') {
		endText();
		unstashFiles();
	}
	if (mode === 'text') stashFiles();
	session.mode = mode;
	session.step = 'file';
	session.problem = null;
	// Nothing from the scrub direction is reachable from the restore one, so
	// whatever the engine is still holding for it is being held for nobody.
	forgetExtractions();
	// The two directions do not share a secret. Leaving one mode's passphrase in
	// memory while the other is on screen is a secret nobody decided to keep.
	forgetSecrets();
	// Restoring uses no term list, so the list is locked on the way in rather
	// than merely forgotten: an unlocked list with no passphrase in the window is
	// a list that can be read and not saved. Text mode uses it, so it stays.
	if (mode === 'restore') void lockTerms();
}

/**
 * The scrub mode's documents, set aside while text mode borrows the review
 * screen. Borrowing is what lets the paste reuse `ReviewStep` unchanged - it
 * reads `files`, `activePath` and `inspections` - and setting aside rather than
 * clearing is what keeps a batch the person loaded from vanishing because they
 * pasted a paragraph in between. Module state, not `session`: nothing renders it.
 */
type Stash = Pick<
	typeof session,
	'files' | 'inspections' | 'keptSpans' | 'extraValues' | 'pending' | 'activePath' | 'results'
>;
let stashed: Stash | null = null;

function clearReview(): void {
	session.files = [];
	session.inspections = {};
	session.keptSpans = {};
	session.extraValues = {};
	session.pending = {};
	session.results = [];
	select(null);
}

function stashFiles(): void {
	stashed = {
		files: session.files,
		inspections: session.inspections,
		keptSpans: session.keptSpans,
		extraValues: session.extraValues,
		pending: session.pending,
		activePath: session.activePath,
		results: session.results
	};
	clearReview();
}

function unstashFiles(): void {
	clearReview();
	if (!stashed) return;
	const { activePath, ...rest } = stashed;
	Object.assign(session, rest);
	select(activePath);
	stashed = null;
}

/**
 * Every single-call passphrase this window is holding, gone. Called on every exit
 * path. The term list's is not one of them: it lives as long as the unlock, and
 * `lockTerms` is what ends it.
 */
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
		fail(describe(error), codeOf(error));
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
		const options = {
			keep: [...session.kept],
			keepSpans: session.keptSpans[path] ?? [],
			remove: session.extraValues[path] ?? [],
			minConfidence: session.minConfidence,
			countries: activeCountries(),
			// Checksums only while the model is missing; see `detectorSpec`.
			detectors: detectorSpec(),
			// The review pane renders the document, so it asks for it. Opt-in on the
			// wire because this text contains the confidential values no layer
			// detected, which is more than the findings alone.
			includeText: true,
			useTerms: termsInUse()
		};
		// A paste is the one "file" of text mode, and it has no path on disk.
		const inspection =
			session.mode === 'text' && path === PASTED
				? await inspectText(session.pastedText, options)
				: await inspect(path, options);
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
		fail(i18n.m.errorInFile({ file: basename(path), message: describe(error) }), codeOf(error));
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
			: [...current, keptSpanFor(path, finding)]
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
	if (session.mode === 'text') return runScrubText();
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
				detectors: detectorSpec(),
				placeholderLanguage: session.placeholderLanguage,
				review: session.reviewModel || null,
				reviewHost: session.reviewHost,
				// Both or neither, which `toParams` enforces: the engine refuses a key
				// file with no passphrase rather than quietly writing nothing.
				map: session.keyWanted ? session.keyDir : null,
				mapPassphrase: session.keyWanted ? session.keyPassphrase : null,
				useTerms: termsInUse()
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
		fail(describe(error), codeOf(error));
	} finally {
		session.busy = null;
		session.progress = null;
		session.stage = null;
		// The passphrase existed for this request. Emptying the fields after a
		// successful scrub is deliberate: the next run is a new decision.
		forgetSecrets();
	}
}

// ---- the term list ----------------------------------------------------------

/**
 * Where the term list is remembered. The path, never the passphrase and never
 * an entry: the path says where a firm keeps its register, which this machine's
 * own profile already knows, and anything more would be a plaintext copy of the
 * thing the file encrypts.
 */
const TERMS_KEY = 'freedocs.terms';

/**
 * Put the remembered path back, locked. Validated by the unlock, not here: the
 * engine is the one that can say whether a file is a term list, and a file that
 * has since moved is refused with its own message when the person tries.
 */
function applyRememberedTerms(): void {
	if (!browserStorage() || !termsAvailable()) return;
	const remembered = safeRead(TERMS_KEY);
	if (remembered) session.termsPath = remembered;
}

export function termsAvailable(): boolean {
	return session.caps?.terms_available ?? false;
}

/** Whether inspect and scrub should ask for the list, which is the person's toggle. */
export function termsInUse(): boolean {
	return session.termsUnlocked && session.termsUse;
}

/**
 * What stops the unlock or create button, as a key the panel translates. The
 * floor is the engine's, read from capabilities; the engine refuses anyway.
 */
export function termsBlocker(): 'file' | 'passphrase' | 'mismatch' | null {
	if (!session.termsPath) return 'file';
	if (session.termsPassphrase.length < passphraseMinimum()) return 'passphrase';
	if (session.termsCreating && session.termsPassphrase !== session.termsConfirm) return 'mismatch';
	return null;
}

const TERMS_FILTER = () => [{ name: i18n.m.termsFilter(), extensions: ['fdterms'] }];

/** Choose an existing list. Whatever was unlocked is locked first: one list at a time. */
export async function pickTermsFile(): Promise<void> {
	const chosen = await open({
		multiple: false,
		directory: false,
		title: i18n.m.termsChooseFile(),
		filters: TERMS_FILTER()
	});
	if (!chosen || Array.isArray(chosen)) return;
	await lockTerms();
	session.termsPath = chosen;
	session.termsCreating = false;
}

/** Name a new list. Nothing is written until the passphrase is given twice. */
export async function pickNewTermsFile(): Promise<void> {
	const chosen = await save({
		title: i18n.m.termsChooseNew(),
		defaultPath: 'firm.fdterms',
		filters: TERMS_FILTER()
	});
	if (!chosen) return;
	await lockTerms();
	session.termsPath = chosen;
	session.termsCreating = true;
}

/** Leave "new list" without creating it, back to whatever was remembered. */
export function cancelNewTerms(): void {
	session.termsCreating = false;
	session.termsPassphrase = '';
	session.termsConfirm = '';
	session.termsProblem = null;
	session.termsPath = browserStorage() ? safeRead(TERMS_KEY) : null;
}

/**
 * Create or unlock, then re-inspect.
 *
 * Re-inspecting is what makes the list visible: the preview that was on screen
 * was computed without it, and a toggle that changes nothing until the next file
 * is loaded reads as a toggle that does nothing.
 */
export async function unlockTerms(): Promise<void> {
	const path = session.termsPath;
	if (!path || termsBlocker()) return;
	session.termsBusy = true;
	session.termsProblem = null;
	try {
		const held = session.termsCreating
			? await termsCreate(path, session.termsPassphrase)
			: await termsUnlock(path, session.termsPassphrase);
		session.termsUnlocked = true;
		session.termsCreating = false;
		session.termsConfirm = '';
		session.termsCount = held.count;
		session.termsUse = true;
		if (browserStorage()) safeWrite(TERMS_KEY, held.path);
		announce(i18n.m.termsUnlocked({ count: held.count }));
		await refreshTerms();
		if (session.files.length) await reinspectAll();
	} catch (error) {
		// A wrong passphrase is the ordinary case, so the field is emptied: the
		// person retypes it either way, and a rejected secret has no reason to stay.
		session.termsPassphrase = '';
		session.termsConfirm = '';
		termsFailed(error);
	} finally {
		session.termsBusy = false;
	}
}

/**
 * Lock the list in the engine and drop everything the window held for it.
 *
 * Safe to call when nothing is unlocked, which is how a mode change and choosing
 * another file use it. The passphrase goes here, in the one place, whatever the
 * engine answers: a lock that failed is still a list this window should stop
 * being able to save.
 */
export async function lockTerms(): Promise<void> {
	const was = session.termsUnlocked;
	session.termsPassphrase = '';
	session.termsConfirm = '';
	session.termsUnlocked = false;
	session.termsCount = 0;
	session.termsShown = [];
	session.termsQuery = '';
	session.termsNewValue = '';
	session.termsImported = null;
	session.termsExported = null;
	session.termsExportArmed = false;
	session.termsProblem = null;
	forgetRekey();
	if (!was) return;
	try {
		await termsLock();
	} catch {
		// The engine's copy ends with the process at worst. Nothing on screen
		// depends on this answer.
	}
	announce(i18n.m.termsLocked());
	if (session.files.length) await reinspectAll();
}

/** Stop remembering the file too. The list itself is untouched on disk. */
export async function closeTerms(): Promise<void> {
	await lockTerms();
	session.termsPath = null;
	session.termsCreating = false;
	if (browserStorage()) safeRemove(TERMS_KEY);
}

export async function refreshTerms(): Promise<void> {
	if (!session.termsUnlocked) return;
	try {
		const listed = await termsList(session.termsQuery.trim() || undefined);
		session.termsShown = listed.terms;
		session.termsCount = listed.count;
	} catch (error) {
		termsFailed(error);
	}
}

/** The person's toggle changed what inspect sends, so the preview is stale. */
export function setTermsUse(value: boolean): void {
	session.termsUse = value;
	if (session.files.length) void reinspectAll();
}

export async function addTerm(): Promise<void> {
	const value = session.termsNewValue.trim();
	if (!value || !session.termsUnlocked) return;
	await changeTerms({ add: [{ value, entity: session.termsNewEntity }] }, (done) =>
		done.added ? i18n.m.termsAdded({ count: done.added }) : i18n.m.termsAlreadyThere()
	);
	if (!session.termsProblem) session.termsNewValue = '';
}

export async function removeTerm(value: string): Promise<void> {
	await changeTerms({ remove: [value] }, (done) => i18n.m.termsRemoved({ count: done.removed }));
}

async function changeTerms(
	change: { add?: Term[]; remove?: string[] },
	said: (done: { added: number; removed: number }) => string
): Promise<void> {
	session.termsBusy = true;
	session.termsProblem = null;
	try {
		const done = await termsUpdate(session.termsPassphrase, change);
		session.termsCount = done.count;
		announce(said(done));
		await refreshTerms();
		if (termsInUse() && session.files.length) await reinspectAll();
	} catch (error) {
		termsFailed(error);
	} finally {
		session.termsBusy = false;
	}
}

/**
 * Read a plaintext or CSV file into the list, and tell the person to delete it.
 *
 * The window never deletes the source, and neither does the engine: a plaintext
 * copy beside the encrypted list undoes the encryption, and deleting somebody's
 * file is not this tool's decision. The notice stays until dismissed.
 */
export async function importTerms(): Promise<void> {
	const chosen = await open({
		multiple: false,
		directory: false,
		title: i18n.m.termsChooseImport(),
		filters: [{ name: i18n.m.termsImportFilter(), extensions: ['txt', 'csv'] }]
	});
	if (!chosen || Array.isArray(chosen)) return;
	session.termsBusy = true;
	session.termsProblem = null;
	try {
		const done = await termsImport(chosen, session.termsPassphrase);
		session.termsCount = done.count;
		session.termsImported = done.delete_source
			? { source: chosen, added: done.added, skipped: done.skipped }
			: null;
		announce(i18n.m.termsImportedAnnounce({ count: done.added }), { assertive: true });
		await refreshTerms();
		if (termsInUse() && session.files.length) await reinspectAll();
	} catch (error) {
		termsFailed(error);
	} finally {
		session.termsBusy = false;
	}
}

export function dismissImported(): void {
	session.termsImported = null;
}

/** First click: say what an export costs. Nothing is written. */
export function armExport(armed: boolean): void {
	session.termsExportArmed = armed;
}

/** Second click: choose where, and write the list out unencrypted. */
export async function exportTerms(): Promise<void> {
	if (!session.termsExportArmed) return;
	const chosen = await save({ title: i18n.m.termsChooseExport(), defaultPath: 'terms.txt' });
	session.termsExportArmed = false;
	if (!chosen) return;
	session.termsBusy = true;
	session.termsProblem = null;
	try {
		const done = await termsExport(chosen);
		session.termsExported = { output: done.output, warning: done.warning };
		announce(i18n.m.termsExportedAnnounce({ count: done.count }), { assertive: true });
	} catch (error) {
		termsFailed(error);
	} finally {
		session.termsBusy = false;
	}
}

function termsFailed(error: unknown): void {
	const message = describe(error);
	session.termsProblem = message;
	announce(message, { assertive: true });
}

/** What stops the change-passphrase button. The floor is the engine's. */
export function rekeyBlocker(): 'current' | 'passphrase' | 'mismatch' | null {
	if (!session.termsOld) return 'current';
	if (session.termsNext.length < passphraseMinimum()) return 'passphrase';
	if (session.termsNext !== session.termsNextConfirm) return 'mismatch';
	return null;
}

export function startRekey(open: boolean): void {
	forgetRekey();
	session.termsRekeying = open;
}

function forgetRekey(): void {
	session.termsRekeying = false;
	session.termsOld = '';
	session.termsNext = '';
	session.termsNextConfirm = '';
}

/**
 * Re-seal the list under a new passphrase, and hold the new one.
 *
 * The held passphrase is replaced only on success: every later save re-opens the
 * file with it, and holding the new one after a refused change would make the
 * next save fail against a file still under the old one.
 */
export async function rekeyTerms(): Promise<void> {
	if (!session.termsUnlocked || rekeyBlocker()) return;
	session.termsBusy = true;
	session.termsProblem = null;
	try {
		const held = await termsRekey(session.termsOld, session.termsNext);
		session.termsPassphrase = session.termsNext;
		session.termsCount = held.count;
		announce(i18n.m.termsRekeyed());
		forgetRekey();
	} catch (error) {
		// Every field emptied, including the new passphrase: retyping it is the
		// cost of a secret that was refused, and a wrong current one is the usual
		// cause.
		session.termsOld = '';
		session.termsNext = '';
		session.termsNextConfirm = '';
		termsFailed(error);
	} finally {
		session.termsBusy = false;
	}
}

// ---- pasted text ------------------------------------------------------------

/** How long the paste is as the engine counts it: code points, not UTF-16 units. */
export function pastedLength(): number {
	let count = 0;
	for (const _ of session.pastedText) count++;
	return count;
}

/** Past the engine's ceiling, read from capabilities. The engine refuses anyway. */
export function pasteTooLong(): boolean {
	const max = session.caps?.text_max_characters;
	return max !== undefined && pastedLength() > max;
}

/** Read the paste, and land on the review screen with it as the one "file". */
export async function inspectPaste(): Promise<void> {
	if (!session.pastedText.trim() || pasteTooLong()) return;
	// A new reading is a new text: what was decided about the old one's offsets
	// does not describe this one, and a result for it is a result for other words.
	releaseHandle();
	session.keptSpans = {};
	session.extraValues = {};
	session.textResult = null;
	session.textRestored = null;
	session.files = [PASTED];
	select(PASTED);
	session.step = 'review';
	await loadInspection(PASTED);
}

/** What stops the text scrub: only a key file needs more than the paste. */
export function textKeepBlocker(): 'directory' | 'passphrase' | 'mismatch' | null {
	if (session.textKeep !== 'file') return null;
	return keyFileBlocker();
}

/** Choose where the mapping goes. The key-file fields are the scrub's own. */
export function setTextKeep(choice: 'none' | 'memory' | 'file'): void {
	session.textKeep = choice;
	session.keyWanted = choice === 'file';
}

async function runScrubText(): Promise<void> {
	if (textKeepBlocker()) return;
	session.busy = 'scrub';
	session.problem = null;
	// Whatever this text held before is replaced, so it is released first.
	releaseHandle();
	session.textResult = null;
	session.textRestored = null;
	try {
		const result = await scrubText(session.pastedText, {
			keep: [...session.kept],
			keepSpans: session.keptSpans[PASTED] ?? [],
			remove: session.extraValues[PASTED] ?? [],
			minConfidence: session.minConfidence,
			countries: activeCountries(),
			detectors: detectorSpec(),
			placeholderLanguage: session.placeholderLanguage,
			review: session.reviewModel || null,
			reviewHost: session.reviewHost,
			useTerms: termsInUse(),
			keepMap: session.textKeep === 'memory',
			map: session.textKeep === 'file' ? session.keyDir : null,
			mapPassphrase: session.textKeep === 'file' ? session.keyPassphrase : null
		});
		session.textResult = result;
		session.step = 'result';
		announce(
			result.ok
				? i18n.m.announceTextScrubbed({ count: result.removed ?? 0 })
				: i18n.m.textNothingProduced(),
			{ assertive: !result.ok }
		);
	} catch (error) {
		fail(describe(error), codeOf(error));
	} finally {
		session.busy = null;
		session.stage = null;
		forgetSecrets();
	}
}

/** Whether the reply can be restored, and from what. */
export function textRestoreSource(): 'handle' | 'file' | null {
	if (session.textResult?.handle) return 'handle';
	if (session.textResult?.key_file) return 'file';
	return null;
}

/**
 * Put the values back into the pasted reply.
 *
 * `ok: false` is not a failure of this call: the restored text is shown either
 * way with every placeholder that did not come back, as the file restore does.
 */
export async function runRestoreText(): Promise<void> {
	const source = textRestoreSource();
	const result = session.textResult;
	if (!source || !result || !session.replyText.trim()) return;
	if (source === 'file' && !session.textRestorePassphrase) return;
	session.busy = 'restore';
	session.problem = null;
	session.textRestored = null;
	try {
		const restored = await restoreText(
			session.replyText,
			source === 'handle'
				? { handle: result.handle as string }
				: { map: result.key_file as string, passphrase: session.textRestorePassphrase }
		);
		session.textRestored = restored;
		announce(
			restored.ok
				? i18n.m.announceRestored({
						count: restored.restored.reduce((sum, entry) => sum + entry.occurrences, 0)
					})
				: i18n.m.announceRestoredWithProblems({ count: restored.problems.length }),
			{ assertive: !restored.ok }
		);
	} catch (error) {
		fail(describe(error), codeOf(error));
	} finally {
		session.busy = null;
		session.stage = null;
		session.textRestorePassphrase = '';
	}
}

/** Tell the engine to drop this text's mapping. Fire and forget. */
function releaseHandle(): void {
	const handle = session.textResult?.handle;
	if (handle) forgetTextMaps([handle]);
}

/** Everything text mode held, gone: in the engine and in the window. */
function endText(): void {
	releaseHandle();
	session.pastedText = '';
	session.replyText = '';
	session.textResult = null;
	session.textRestored = null;
	session.textRestorePassphrase = '';
	session.textKeep = 'none';
	session.keyWanted = false;
}

/** "New text": start over on an empty paste, in the same mode. */
export function newText(): void {
	endText();
	clearReview();
	session.step = 'file';
}
