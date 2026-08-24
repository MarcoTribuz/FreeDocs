/**
 * The frontend's view of the engine.
 *
 * Every judgement about what is confidential, what gets removed and what the user
 * is warned about lives in the Python engine. This file only carries messages, and
 * deliberately holds no rules of its own: two places deciding what an IBAN looks
 * like is two answers that can disagree.
 */

import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

/** Error codes the engine uses for "this file cannot be processed". */
export const UNSUPPORTED_FORMAT = 1;
export const NEEDS_OCR = 2;
export const LEAK_DETECTED = 3;
export const MISSING_DEPENDENCY = 4;
/**
 * A restore that wrote its file and did not finish. Deliberately not a leak:
 * the output *is* there, with a placeholder still visible in it, which is the
 * opposite handling from a scrub that failed verification and wrote nothing.
 */
export const INCOMPLETE_RESTORE = 5;

export interface Capabilities {
	version: string;
	formats: string[];
	detector_specs: string[];
	layers: string[];
	/** What this build cannot do. Rendered, never hidden. */
	limitations: string[];
	ocr_available: boolean;
	/**
	 * Why OCR is unavailable, naming which half is missing — the Tesseract binary
	 * or its language data. The engine has always sent this; the interface never
	 * declared it, so the window showed "not installed" and dropped the answer to
	 * the only question that follows.
	 */
	ocr_unavailable_reason: string | null;
	/**
	 * Whether the NER weights travel with this build or are fetched on first use.
	 * An enum, so it is translated rather than quoted, and never a path: a local
	 * filesystem path tells the window nothing it can act on. The window cannot
	 * work this out — it is a property of how the app was packaged.
	 */
	model_source: 'bundled' | 'hub';
	/** Countries whose identifiers this build knows. The engine's list, not ours. */
	countries: string[];
	/** Languages the placeholder stems come in, and the one used by default. */
	placeholder_languages: string[];
	placeholder_language: string;
	/** Local Ollama models available for the optional review. Empty when Ollama is absent. */
	review_models: string[];
	/** Where the engine looks for Ollama. Prefilled from here, never hardcoded here. */
	review_host: string;
	/**
	 * How much of a document the reviewer reads. The only thing that makes
	 * `Review.partial` explicable: without it the window can say "first part
	 * only" and not say what part.
	 */
	review_max_characters: number;
	/** How much extracted text `inspect` will send when asked for a preview. */
	preview_max_characters: number;
	/** What each detector spec covers, so a menu of them is not three opaque strings. */
	detector_spec_notes: Record<string, string>;
	caveats: string[];
	/**
	 * Whether this build can write and read a key file.
	 *
	 * Asked rather than assumed, and the control is disabled when it is false. The
	 * cipher is an optional extra, and a window that offered the option and then
	 * failed on the first attempt is the bug `ocr_unavailable_reason` exists to
	 * prevent, one feature over.
	 */
	mapping_available: boolean;
	mapping_unavailable_reason: string | null;
	/**
	 * The shortest passphrase the engine will accept for a key file.
	 *
	 * Read from here rather than declared in the window. It was a `const` in
	 * `app.svelte.ts`, which is the one rule this window held: raise the floor in
	 * `core/mapping.py` and the window went on accepting eight characters, the
	 * engine refused inside the `scrub` request, and the failure arrived after the
	 * scrubbed copies were on disk.
	 */
	passphrase_min_characters: number;
	/**
	 * What a *restore* does not do. A separate list from `caveats`: a restore's
	 * limits are not a scrub's, and one merged list would show a reader of either
	 * screen sentences that do not apply to what they are looking at.
	 */
	restore_caveats: string[];
}

export interface Concern {
	kind: 'leftover' | 'quasi_identifier' | 'context' | string;
	/** From the *scrubbed* text, so showing it reveals nothing the output does not. */
	quote: string;
	why: string;
}

export interface Review {
	model: string;
	/** False when the review could not run. Not the same as finding nothing. */
	ran: boolean;
	unavailable: string | null;
	/** The document was longer than the reviewer reads, so this covers its start. */
	partial: boolean;
	summary: string;
	concerns: Concern[];
}

export interface Finding {
	start: number;
	end: number;
	entity: string;
	action: 'redact' | 'surrogate' | 'report' | 'keep';
	confidence: number;
	detector: string;
	/**
	 * Which layer claimed it: `L1` a checksum, `L2` the model, `H` you.
	 *
	 * The engine's own answer. The window used to derive this by string-matching
	 * the detector name, which was the app holding a rule about the engine's
	 * naming.
	 */
	layer: string;
	/** Lowercase ISO code for a country-issued identifier, null otherwise. */
	country: string | null;
	part: string;
	/** The matched value, so the preview can show what is about to go. */
	text: string;
}

/** A stretch of the extracted text that came from one page, sheet or slide. */
export interface Part {
	/** The engine's own name for it: `page:3`, a sheet's part path, a slide. */
	part: string;
	start: number;
	end: number;
}

export interface Inspection {
	path: string;
	format: string;
	/** The whole document's length, even when the preview below is truncated. */
	characters: number;
	warnings: string[];
	/**
	 * What would be dropped that is not text: metadata, a thumbnail, comments,
	 * tracked changes, a hidden sheet.
	 *
	 * The leak users do not expect, and the preview used to be silent about it —
	 * the terminal named it and the window learned of it only after a scrub. Each
	 * `detail` is a description and never a value, which is the engine's own rule
	 * for this type.
	 */
	hidden: HiddenItem[];
	findings: Finding[];
	/**
	 * The extracted text, present only when `includeText` was asked for.
	 *
	 * The same coordinate system as every `Finding.start`, which is what makes a
	 * highlight and a `KeptSpan` describe the same characters — with one caveat
	 * this file cannot fix: these are Python code-point offsets, and JavaScript
	 * string indices are UTF-16 code units. They differ once the document
	 * contains anything outside the BMP. Convert before slicing, and convert back
	 * before sending a span.
	 */
	text?: string;
	/** Where the text stops. A finding beyond it is still reported in full. */
	text_end?: number;
	text_truncated?: boolean;
	parts?: Part[];
}

export interface HiddenItem {
	part: string;
	kind: string;
	detail: string;
}

/**
 * Stage six, as a count.
 *
 * The output is re-opened, re-extracted with hidden parts included, and searched
 * for every value that was supposed to be gone. `passed` false means nothing was
 * written at all, so this is the one fact on the result screen worth its own
 * line: a nearly-clean file is more dangerous than an obviously dirty one,
 * because it gets sent.
 */
export interface Verification {
	passed: boolean;
	values_checked: number;
	/** Too short to search for without matching ordinary text. */
	values_too_short_to_check: number;
	leaks: { entity: string; detector: string; occurrences: number }[];
}

/** The machine-readable summary. Counts and positions, never values. */
export interface Report {
	source: string;
	format: string;
	source_characters: number;
	entities: Record<
		string,
		{ removed: number; reported: number; kept: number; countries?: string[] }
	>;
	totals: { removed: number; reported_only: number };
	hidden_content_removed: HiddenItem[];
	warnings: string[];
	verification: Verification;
	/**
	 * Whether a key file was written for this document. A boolean and not a path:
	 * this report may be attached to a ticket, and where the key lives is the one
	 * thing about it worth not writing down.
	 */
	key_file_written: boolean;
	caveats: string[];
}

export interface ScrubResult {
	path: string;
	ok: boolean;
	output?: string;
	removed?: number;
	flagged?: number;
	warnings?: string[];
	hidden_removed?: HiddenItem[];
	/** Null when no review was requested. */
	review?: Review | null;
	/**
	 * Where the key file went, or null when none was asked for.
	 *
	 * The path is here and deliberately not in `report`: this response comes down a
	 * local pipe to the process that chose the location, while the report is a file
	 * that may travel.
	 */
	key_file?: string | null;
	report?: Report;
	error?: { code: number; message: string; data?: unknown };
}

/** One placeholder that was found in the returned document and replaced. */
export interface Restored {
	placeholder: string;
	entity: string;
	/** How many times it was found in the returned document. */
	occurrences: number;
	/**
	 * How many times the scrub replaced it in the original. A shortfall is not a
	 * failure — a model that summarised the document legitimately kept fewer — but
	 * it is what explains a surprising count.
	 */
	expected: number;
}

/**
 * What a restore did, and what it could not do.
 *
 * `ok: false` does *not* mean nothing was written. A scrub that fails
 * verification writes nothing, because a nearly-clean document gets sent; a
 * half-restored one is still the user's best artifact and its defect is visible
 * in it. So `output` is always a path.
 */
export interface RestoreResult {
	path: string;
	ok: boolean;
	output: string;
	format: string;
	restored: Restored[];
	/** In the key file, absent from the returned document. Usually text the model dropped. */
	not_present: string[];
	/**
	 * Placeholder-shaped tokens the key file does not know: a stem the model
	 * translated, a number it invented. Reported and left alone — matching them
	 * loosely is how somebody else's value lands in the document.
	 */
	unknown_placeholders: string[];
	/**
	 * The handler's own prose about compromises it had to make — and in *this*
	 * direction it can quote an original value: PyMuPDF's "does not fit the space
	 * its original occupied" names the text it dropped, which is the real value
	 * rather than a placeholder. Safe to render, for the same reason the review
	 * pane renders every value; **never log these, and never write them to a
	 * file.** The engine's own restore report deliberately carries a count instead.
	 */
	warnings: string[];
	problems: { placeholder: string; entity: string; kind: string }[];
	report?: Record<string, unknown>;
}

export interface EntityInfo {
	name: string;
	default_action: string;
	report_only: boolean;
	/**
	 * What would be written in place of a value of this type.
	 *
	 * Composed by the same allocator that writes the document, so a preview
	 * cannot promise `[PERSONA_1]` and produce `[PERSON_1]`.
	 */
	placeholder: string;
}

/** One question about this machine, its answer, and what to do about it. */
export interface Check {
	name: string;
	ok: boolean;
	detail: string;
	/** Something to run, when there is something to run. */
	fix: string | null;
	required: boolean;
	/** Not ok, but not fatal: this build can do less, not nothing. */
	degraded: boolean;
}

export interface Doctor {
	version: string;
	ok: boolean;
	checks: Check[];
}

export interface CountryRule {
	name: string;
	entity: string;
	confidence_without_context: number;
	needs_context: boolean;
	/** Below the current threshold, so it finds nothing without a keyword nearby. */
	inert_without_context: boolean;
}

export interface CountryDetail {
	code: string;
	selected: boolean;
	/**
	 * Whether any identifier of this country is confirmed by a checksum.
	 *
	 * False for the United States, and its own field for that reason: neither of
	 * its numbers has a check digit, so an undifferentiated list of chips would
	 * let a reader believe a social security number was confirmed.
	 */
	checksum_confirmed: boolean;
	phone_plan: boolean;
	entities: string[];
	rules: CountryRule[];
	detail: string | null;
}

export interface CountryCoverage {
	default_min_confidence: number;
	min_confidence: number;
	selected: string[] | null;
	excluded: string[];
	/** What a narrowed selection costs, in the engine's words. */
	note: string | null;
	confidence_levels: { name: string; value: number; accepts: string; meaning: string }[];
	countries: CountryDetail[];
}

/** One occurrence the user decided is not confidential after all. */
export interface KeptSpan {
	start: number;
	end: number;
	/**
	 * The text the span covered when the user saw it. Sent back so the engine can
	 * refuse a decision that has gone stale: if the file changed since the
	 * preview, these offsets point at something else, and honouring them would
	 * keep whatever moved into that range.
	 */
	text: string;
	/**
	 * Which document the decision is about. A batch is one request but these
	 * offsets belong to one extraction, so an unscoped span would be checked
	 * against every file and refused as stale on all but the first.
	 */
	path?: string;
}

/** A value the user wants gone that no detector nominated. */
export interface RemovedValue {
	value: string;
	/** Omitted means OTHER: the user said remove it without saying what it is. */
	entity?: string;
	/** Omitted means every file in the request, which for a value is meaningful. */
	path?: string;
}

export interface ScrubOptions {
	/**
	 * Entity *types* to leave alone everywhere. Not the same control as
	 * `keepSpans` below, and the difference matters: this one says "no location
	 * in this document is confidential".
	 */
	keep?: string[];
	/**
	 * Single occurrences to leave alone. The per-occurrence control, because the
	 * same city is confidential in a party's address and not in a jurisdiction
	 * clause.
	 */
	keepSpans?: KeptSpan[];
	/** Values to remove that the detectors missed, at every occurrence. */
	remove?: RemovedValue[];
	minConfidence?: number;
	detectors?: string | null;
	allowLeaks?: boolean;
	/**
	 * Countries to look for identifiers and national phone numbers from.
	 * Omitted means every supported one, which is the safe default: a wrong
	 * selection produces a file the user believes is clean.
	 */
	countries?: string[];
	/** Language of the placeholder stems written into the output. */
	placeholderLanguage?: string;
	/** Ollama model to review the scrubbed text with. Advisory; changes no output. */
	review?: string | null;
	/** Which Ollama to ask. Omitted means the engine's own default. */
	reviewHost?: string | null;
	/**
	 * Ask `inspect` for the extracted text as well as the findings.
	 *
	 * Opt-in because that text is a superset of the matched values: it contains
	 * the confidential text no layer detected. Only a caller that renders a
	 * preview should receive a document, and it must go no further — not to a
	 * report, not to a log.
	 */
	includeText?: boolean;
	/**
	 * Where to write the encrypted key file, so the scrub can be undone later.
	 *
	 * Omitted means no key file, which is the default and leaves the run
	 * irreversible by anyone. A directory gets one file per document; the engine
	 * names them.
	 */
	map?: string | null;
	/**
	 * What opens the key file. Required alongside `map` — there is no unencrypted
	 * form of it, and the engine refuses the pair rather than quietly writing
	 * nothing. Held only for the duration of the call and never stored.
	 */
	mapPassphrase?: string | null;
	/**
	 * Permit the key file inside the output directory. The engine refuses that by
	 * default, because the realistic accident is zipping the output folder and
	 * sending the scrubbed document along with the key to undo it.
	 */
	mapInOutputDir?: boolean;
}

/**
 * A failure the engine explained, as opposed to a bug.
 *
 * The Rust layer hands back the engine's error object serialised as a string.
 * Parsing it here keeps the code available, which is what lets the window say
 * "install OCR" instead of "something went wrong".
 */
export class EngineError extends Error {
	code: number | null;
	constructor(message: string, code: number | null) {
		super(message);
		this.code = code;
	}
}

function parseError(raw: unknown): EngineError {
	const text = String(raw);
	try {
		const parsed = JSON.parse(text);
		if (parsed && typeof parsed === 'object' && 'message' in parsed) {
			return new EngineError(String(parsed.message), Number(parsed.code ?? NaN) || null);
		}
	} catch {
		// Not the engine's structured error: a Rust-side failure, spawn included.
	}
	return new EngineError(text, null);
}

async function request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
	try {
		return (await invoke('engine_request', { method, params })) as T;
	} catch (raw) {
		throw parseError(raw);
	}
}

/** Whether the engine started at all, and why not if it did not. */
export async function engineStatus(): Promise<string | null> {
	try {
		await invoke('engine_status');
		return null;
	} catch (raw) {
		return String(raw);
	}
}

export function capabilities(): Promise<Capabilities> {
	return request<Capabilities>('capabilities');
}

export function entities(
	placeholderLanguage?: string
): Promise<{ placeholder_language: string; entities: EntityInfo[] }> {
	return request('entities', placeholderLanguage ? { placeholder_language: placeholderLanguage } : {});
}

/** What this machine can do, and how to repair what it cannot. */
export function doctor(reviewHost?: string): Promise<Doctor> {
	return request<Doctor>('doctor', reviewHost ? { review_host: reviewHost } : {});
}

/** What each country gets, and what narrowing to some of them costs. */
export function countries(options: {
	countries?: string[];
	minConfidence?: number;
} = {}): Promise<CountryCoverage> {
	const params: Record<string, unknown> = {};
	if (options.countries?.length) params.countries = options.countries;
	if (options.minConfidence !== undefined) params.min_confidence = options.minConfidence;
	return request<CountryCoverage>('countries', params);
}

/**
 * Which models one particular Ollama has.
 *
 * The engine refuses a host that is not this machine, and the refusal explains
 * itself, so the window can show that answer where the host was typed rather than
 * silently reporting no models.
 */
export function reviewModels(host: string): Promise<{ host: string; models: string[] }> {
	return request<{ host: string; models: string[] }>('review_models', { host });
}

export function inspect(path: string, options: ScrubOptions = {}): Promise<Inspection> {
	return request<Inspection>('inspect', toParams({ path }, options));
}

export function scrub(
	paths: string[],
	outputDir: string,
	options: ScrubOptions = {}
): Promise<{ results: ScrubResult[] }> {
	return request<{ results: ScrubResult[] }>(
		'scrub',
		toParams({ paths, output_dir: outputDir }, options)
	);
}

/**
 * Put one document's values back from its key file.
 *
 * One path, not a list: a key file describes one document, so a batch would
 * either apply one map to several documents or need a map per path and stop being
 * one request.
 */
export function restore(
	path: string,
	map: string,
	passphrase: string,
	outputDir: string
): Promise<RestoreResult> {
	return request<RestoreResult>('restore', {
		path,
		map,
		passphrase,
		output_dir: outputDir
	});
}

function toParams(base: Record<string, unknown>, options: ScrubOptions): Record<string, unknown> {
	const params: Record<string, unknown> = { ...base };
	if (options.keep?.length) params.keep = options.keep;
	if (options.keepSpans?.length) params.keep_spans = options.keepSpans;
	if (options.remove?.length) params.remove = options.remove;
	if (options.minConfidence !== undefined) params.min_confidence = options.minConfidence;
	if (options.detectors) params.detectors = options.detectors;
	if (options.allowLeaks) params.allow_leaks = true;
	// Only when it is a real narrowing. Sending every country is the same request
	// as sending none, and the engine refuses an empty list rather than reading it
	// as "no countries" — see _countries_from.
	if (options.countries?.length) params.countries = options.countries;
	if (options.includeText) params.include_text = true;
	if (options.placeholderLanguage) params.placeholder_language = options.placeholderLanguage;
	if (options.review) params.review = options.review;
	// Only alongside a model: a host on its own configures nothing, and sending it
	// anyway would make an unused field look like it had an effect.
	if (options.review && options.reviewHost) params.review_host = options.reviewHost;
	// Both or neither. A `map` without a passphrase is refused by the engine, and
	// sending one alone would make an unused field look like it had an effect — the
	// same rule the review host above follows.
	if (options.map && options.mapPassphrase) {
		params.map = options.map;
		params.map_passphrase = options.mapPassphrase;
		if (options.mapInOutputDir) params.map_in_output_dir = true;
	}
	return params;
}

export interface Progress {
	file: string;
	index: number;
	total: number;
}

/**
 * Where inside one file the engine has got to.
 *
 * Separate from `Progress`, which counts files: the two have different
 * cardinality and different lifetimes, and one notification for both would make
 * a consumer that wants the batch counter filter for it.
 *
 * There is no `percent` and there will not be one — the engine cannot know how
 * long detection takes next to extraction on a document nobody has seen.
 * `index`/`count` counts *stages*, and `done`/`of` appear only where a stage has
 * a real unit: pages, so far.
 */
export interface Stage {
	/** The request this belongs to. */
	id: number | string | null;
	file: string;
	stage: string;
	index: number;
	count: number;
	done?: number;
	of?: number;
	detail?: string;
}

/**
 * Subscribe to what the engine says unprompted: progress, and the capabilities it
 * announces before anyone asks.
 */
export function onNotify(handlers: {
	progress?: (progress: Progress) => void;
	stage?: (stage: Stage) => void;
	ready?: (capabilities: Capabilities) => void;
}) {
	return listen<{ method?: string; params?: unknown }>('engine://notify', (event) => {
		const { method, params } = event.payload ?? {};
		if (method === 'progress' && handlers.progress) handlers.progress(params as Progress);
		if (method === 'stage' && handlers.stage) handlers.stage(params as Stage);
		if (method === 'ready' && handlers.ready) handlers.ready(params as Capabilities);
	});
}
