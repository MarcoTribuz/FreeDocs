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

export interface Capabilities {
	version: string;
	formats: string[];
	detector_specs: string[];
	layers: string[];
	/** What this build cannot do. Rendered, never hidden. */
	limitations: string[];
	ocr_available: boolean;
	/** Countries whose identifiers this build knows. The engine's list, not ours. */
	countries: string[];
	/** Local Ollama models available for the optional review. Empty when Ollama is absent. */
	review_models: string[];
	/** Where the engine looks for Ollama. Prefilled from here, never hardcoded here. */
	review_host: string;
	caveats: string[];
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
	part: string;
	/** The matched value, so the preview can show what is about to go. */
	text: string;
}

export interface Inspection {
	path: string;
	format: string;
	characters: number;
	warnings: string[];
	findings: Finding[];
}

export interface HiddenItem {
	part: string;
	kind: string;
	detail: string;
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
	report?: unknown;
	error?: { code: number; message: string; data?: unknown };
}

export interface EntityInfo {
	name: string;
	default_action: string;
	report_only: boolean;
}

export interface ScrubOptions {
	keep?: string[];
	minConfidence?: number;
	detectors?: string | null;
	allowLeaks?: boolean;
	/**
	 * Countries to look for identifiers and national phone numbers from.
	 * Omitted means every supported one, which is the safe default: a wrong
	 * selection produces a file the user believes is clean.
	 */
	countries?: string[];
	/** Ollama model to review the scrubbed text with. Advisory; changes no output. */
	review?: string | null;
	/** Which Ollama to ask. Omitted means the engine's own default. */
	reviewHost?: string | null;
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

export function entities(): Promise<{ entities: EntityInfo[] }> {
	return request<{ entities: EntityInfo[] }>('entities');
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

function toParams(base: Record<string, unknown>, options: ScrubOptions): Record<string, unknown> {
	const params: Record<string, unknown> = { ...base };
	if (options.keep?.length) params.keep = options.keep;
	if (options.minConfidence !== undefined) params.min_confidence = options.minConfidence;
	if (options.detectors) params.detectors = options.detectors;
	if (options.allowLeaks) params.allow_leaks = true;
	// Only when it is a real narrowing. Sending every country is the same request
	// as sending none, and the engine refuses an empty list rather than reading it
	// as "no countries" — see _countries_from.
	if (options.countries?.length) params.countries = options.countries;
	if (options.review) params.review = options.review;
	// Only alongside a model: a host on its own configures nothing, and sending it
	// anyway would make an unused field look like it had an effect.
	if (options.review && options.reviewHost) params.review_host = options.reviewHost;
	return params;
}

export interface Progress {
	file: string;
	index: number;
	total: number;
}

/**
 * Subscribe to what the engine says unprompted: progress, and the capabilities it
 * announces before anyone asks.
 */
export function onNotify(handlers: {
	progress?: (progress: Progress) => void;
	ready?: (capabilities: Capabilities) => void;
}) {
	return listen<{ method?: string; params?: unknown }>('engine://notify', (event) => {
		const { method, params } = event.payload ?? {};
		if (method === 'progress' && handlers.progress) handlers.progress(params as Progress);
		if (method === 'ready' && handlers.ready) handlers.ready(params as Capabilities);
	});
}
