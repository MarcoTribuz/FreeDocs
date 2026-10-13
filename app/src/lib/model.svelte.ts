/**
 * The first-run download: whether the model is here, and the screen that fetches it.
 *
 * Its own module rather than more fields on `session`, because it has its own
 * lifetime: it is decided once at launch, it can block every step, and once the
 * model is here nothing else in the window needs to know it was ever missing.
 *
 * Holds no rules. Whether the model is present, and whether this build could
 * use it at all, are the engine's answers (`model_status`). What the window adds
 * is the user's choice to wait - and the consequence of that choice, which is
 * `detectorSpec()`: a scrub asked for while the model is missing must not be the
 * request that downloads 1.2 GB with nobody watching, which is what every first
 * document did before this screen existed.
 */
import { announce } from './announce.svelte';
import {
	EngineError,
	MODEL_DOWNLOAD_FAILED,
	modelFetch,
	modelStatus,
	type Download,
	type ModelStatus
} from './engine';
import { record, type Sample } from './download';
import { i18n } from './i18n/index.svelte';

/**
 * `setup` is the screen opened for the dependencies alone: the model is here and
 * something else is not. The other five are the model's own.
 */
export type Phase = 'ask' | 'downloading' | 'preparing' | 'failed' | 'ready' | 'setup';

export const model = $state({
	status: null as ModelStatus | null,
	/** Which state the screen is in; null when it is not showing. */
	phase: null as Phase | null,
	done: 0,
	of: 0,
	samples: [] as Sample[],
	/** The engine's sentence for a failed download: quoted, never translated. */
	problem: null as string | null,
	/** Whether the failure was the download's own, which is what "try again" fixes. */
	retryable: false
});

/** The model would be used by this build, and is not on this machine. */
export function modelMissing(): boolean {
	const status = model.status;
	return !!status && status.source === 'hub' && status.ner_available && !status.present;
}

/**
 * The detector layers to ask for, or undefined for the engine's default.
 *
 * Checksums only while the model is missing. Without it, the engine's default
 * registry would reach for the weights inside the request and download them
 * there - the silent multi-minute first document this screen replaces. The user
 * has been told, by the callout on the file step, that names and addresses are
 * not being looked for.
 */
export function detectorSpec(): string | undefined {
	return modelMissing() ? 'l1' : undefined;
}

/**
 * Ask the engine at launch; open the screen when the model is missing, or when
 * `setupWanted` - the caller's reading of `offerSetup` - says the dependency list
 * has something to show that the user has not seen.
 */
export async function checkModel(setupWanted = false): Promise<void> {
	model.status = await modelStatus();
	if (modelMissing()) show('ask');
	else if (setupWanted) show('setup');
}

/**
 * Whether the dependency list has been seen, remembered per webview profile.
 *
 * A convenience, like the theme: if storage is unavailable the list opens again
 * next launch, which is the safe direction to fail in.
 */
const SETUP_SEEN_KEY = 'freedocs.setup-seen';

export function setupSeen(): boolean {
	try {
		return localStorage.getItem(SETUP_SEEN_KEY) === '1';
	} catch {
		return false;
	}
}

function markSetupSeen(): void {
	try {
		localStorage.setItem(SETUP_SEEN_KEY, '1');
	} catch {
		// Opens again next launch; nothing depends on it.
	}
}

export function onDownload(download: Download): void {
	if (model.phase !== 'downloading') return;
	model.done = download.done;
	model.of = download.of;
	model.samples = record(model.samples, {
		at: performance.now(),
		done: download.done
	});
	// Every byte is here and the engine is now verifying and loading - seconds,
	// with no unit to count, so the bar gives way to a sentence.
	if (download.of > 0 && download.done >= download.of) show('preparing');
}

export async function fetchModel(): Promise<void> {
	model.done = 0;
	model.of = 0;
	model.samples = [];
	model.problem = null;
	show('downloading');
	try {
		await modelFetch();
		model.status = await modelStatus();
		show('ready');
	} catch (error) {
		model.problem = error instanceof Error ? error.message : String(error);
		model.retryable = error instanceof EngineError && error.code === MODEL_DOWNLOAD_FAILED;
		show('failed');
	}
}

/** "Not now": the screen closes, and the file step says what is missing. */
export function deferModel(): void {
	markSetupSeen();
	model.phase = null;
}

/** Reopen the screen from the file step's callout. */
export function askForModel(): void {
	show('ask');
}

export function closeModel(): void {
	markSetupSeen();
	model.phase = null;
}

function show(phase: Phase): void {
	model.phase = phase;
	const m = i18n.m;
	// The bar itself is outside any live region (see Progress.svelte), so the
	// moments worth interrupting for are announced here: a start, a stop, an end.
	const titles: Record<Phase, () => string> = {
		ask: m.modelAskTitle,
		downloading: m.modelDownloadingTitle,
		preparing: m.modelPreparingTitle,
		failed: m.modelFailedTitle,
		ready: m.modelReadyTitle,
		setup: m.setupTitle
	};
	announce(titles[phase](), { assertive: phase === 'failed' });
}
