/**
 * What verification left behind, named from the preview the window already has.
 *
 * The engine never puts a surviving value in an error: that message may be
 * logged, and an error about confidential values surviving must not carry them.
 * It sends where one occurrence of each was found instead - `start`/`end` in the
 * source extraction, in code points - and the window holds the findings of that
 * same extraction with their text. Matching the two is all this does.
 *
 * Both sides are the engine's own offsets, so the code-point/UTF-16 trap does
 * not arise: nothing here slices a string, it compares numbers from one
 * coordinate system. Pure, so it is tested without a window.
 */
import type { Finding, ScrubResult } from './engine';

/** One value verification found still in the output. */
export interface Survivor {
	entity: string;
	detector: string;
	occurrences: number;
	/** The value, when the preview holds the finding it came from. */
	value: string | null;
}

interface LeakDetail {
	entity: string;
	detector: string;
	occurrences: number;
	start?: number;
	end?: number;
}

/** The leaks of one result: from the refusal's data, or from a written report. */
function details(result: ScrubResult): LeakDetail[] {
	if (result.ok) return result.report?.verification.leaks ?? [];
	const data = result.error?.data as { detail?: LeakDetail[] } | undefined;
	return Array.isArray(data?.detail) ? data.detail : [];
}

export function survivors(result: ScrubResult, findings: readonly Finding[] = []): Survivor[] {
	return details(result).map((leak) => {
		const match = findings.find(
			(finding) => finding.start === leak.start && finding.end === leak.end
		);
		return {
			entity: leak.entity,
			detector: leak.detector,
			occurrences: leak.occurrences,
			value: match ? match.text : null
		};
	});
}

/** Whether a result was written with values still in it, at the caller's request. */
export function writtenWithLeaks(result: ScrubResult): boolean {
	return result.ok && result.report?.verification.passed === false;
}
