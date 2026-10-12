import { describe, expect, it } from 'vitest';
import { SETTLE_MS, WINDOW_MS, eta, megabytes, record, type Sample } from './download';

const MB = 1_000_000;

function feed(points: [number, number][]): Sample[] {
	return points.reduce<Sample[]>((samples, [at, done]) => record(samples, { at, done }), []);
}

describe('eta', () => {
	it('says nothing before there is a rate to say it from', () => {
		expect(eta(feed([[0, 0]]), 1244 * MB)).toBeNull();
		expect(
			eta(
				feed([
					[0, 0],
					[SETTLE_MS - 1, 10 * MB]
				]),
				1244 * MB
			)
		).toBeNull();
	});

	it('works from the observed rate', () => {
		// 10 MB/s with 600 MB left is a minute; 1200 MB left is two.
		const samples = feed([
			[0, 0],
			[5000, 50 * MB]
		]);
		expect(eta(samples, 650 * MB)).toEqual({ minutes: 1 });
		expect(eta(samples, 1250 * MB)).toEqual({ minutes: 2 });
	});

	it('rounds up, so the last minute is not promised early', () => {
		const samples = feed([
			[0, 0],
			[5000, 50 * MB]
		]);
		expect(eta(samples, 660 * MB)).toEqual({ minutes: 2 });
	});

	it('says under a minute rather than zero', () => {
		const samples = feed([
			[0, 0],
			[5000, 50 * MB]
		]);
		expect(eta(samples, 100 * MB)).toBe('under-minute');
	});

	it('follows a connection that slowed down', () => {
		const fast = [
			[0, 0],
			[5000, 500 * MB]
		] as [number, number][];
		const slow = [
			[5000 + WINDOW_MS + 1, 510 * MB],
			[5000 + WINDOW_MS + 5001, 520 * MB]
		] as [number, number][];
		const samples = feed([...fast, ...slow]);
		// 2 MB/s over the recent window, 724 MB left: about six minutes, not one.
		expect(eta(samples, 1244 * MB)).toEqual({ minutes: 7 });
	});

	it('treats a count that restarted as a new attempt', () => {
		const samples = feed([
			[0, 0],
			[4000, 400 * MB],
			[5000, 0],
			[9000, 40 * MB]
		]);
		expect(samples[0].at).toBe(5000);
		// 10 MB/s since the restart, 1204 MB left.
		expect(eta(samples, 1244 * MB)).toEqual({ minutes: 3 });
	});
});

describe('megabytes', () => {
	it('uses the reader’s unit', () => {
		expect(megabytes(412 * MB, 'en')).toBe('412 MB');
		expect(megabytes(412 * MB, 'fr')).toMatch(/^412\s?Mo$/);
	});
});
