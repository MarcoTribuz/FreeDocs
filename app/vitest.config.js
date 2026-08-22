import { defineConfig } from 'vitest/config';

/*
 * A config of its own, not the SvelteKit one.
 *
 * Everything under test here is a plain module: the offset arithmetic, the
 * plural rules, the display names. None of it renders, so there is no need for
 * the SvelteKit plugin, no jsdom, and no `.svelte-kit` sync before a test run —
 * which is also what keeps the suite honest about what it covers.
 *
 * What that leaves untested, stated rather than implied: anything in a `.svelte`
 * or `.svelte.ts` file. Rendering a Chip to assert `aria-pressed="true"` tests
 * that Svelte writes an attribute we wrote. The discipline instead is to push
 * logic out of components until they are too dumb to be worth testing — the
 * review screen's keyboard map is `nextFinding` in lib/highlight.ts for exactly
 * that reason. If a component grows a branch worth testing, the branch is in the
 * wrong file.
 */
export default defineConfig({
	test: {
		environment: 'node',
		include: ['src/**/*.test.ts']
	}
});
