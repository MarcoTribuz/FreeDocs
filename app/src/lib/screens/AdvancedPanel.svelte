<script lang="ts">
	import {
		forgetModels,
		offeredModels,
		refreshModels,
		reinspectAll,
		session,
		toggleCountry,
		toggleKeep
	} from '$lib/app.svelte';
	import { i18n } from '$lib/i18n/index.svelte';
	import { countryName, languageName } from '$lib/format';
	import { categoryOf } from '$lib/entities';
	import Button from '$lib/components/Button.svelte';
	import Chip from '$lib/components/Chip.svelte';
	import Disclosure from '$lib/components/Disclosure.svelte';
	import Select from '$lib/components/Select.svelte';
	import Slider from '$lib/components/Slider.svelte';
	import TextField from '$lib/components/TextField.svelte';

	const m = $derived(i18n.m);

	let open = $state(false);

	const languageOptions = $derived(
		(session.caps?.placeholder_languages ?? []).map((code) => ({
			value: code,
			label: languageName(code, i18n.locale)
		}))
	);

	const modelOptions = $derived([
		{ value: '', label: m.reviewNone() },
		...offeredModels().map((model) => ({ value: model, label: model }))
	]);

	function entityLabel(name: string): string {
		return m.entity[name]?.() ?? name;
	}
</script>

<!--
	Progressive disclosure, and the direction matters: every control in here can
	only make the search *narrower*. The defaults look for everything, everywhere,
	because a caller obliged to name its countries to be safe produces a leak by
	naming the wrong ones. A narrowed run is stated in the result by the engine,
	not remembered by the window.
-->
<Disclosure bind:open summary={m.advancedTitle()}>
	<p class="hint">{m.advancedHint()}</p>

	<div class="grid">
		<section>
			<Slider
				label={m.minConfidence()}
				bind:value={session.minConfidence}
				onchange={reinspectAll}
				describe={(value) => `${value.toFixed(2)}, ${m.confidenceBand({ value })}`}
			/>
		</section>

		<section>
			<Select
				label={m.placeholderLanguage()}
				bind:value={session.placeholderLanguage}
				options={languageOptions}
				hint={m.placeholderLanguageHint()}
			/>
		</section>

		<section class="wide">
			<h3 id="adv-countries">{m.countriesTitle()}</h3>
			<p class="hint" id="adv-countries-hint">{m.countriesHint()}</p>
			<div
				class="chips"
				role="group"
				aria-labelledby="adv-countries"
				aria-describedby="adv-countries-hint"
			>
				{#each session.caps?.countries ?? [] as code (code)}
					<Chip
						pressed={!session.dropped.has(code)}
						label={countryName(code, i18n.locale)}
						onchange={() => toggleCountry(code)}
					/>
				{/each}
			</div>
		</section>

		<section class="wide">
			<h3 id="adv-keep">{m.keepTitle()}</h3>
			<div class="chips" role="group" aria-labelledby="adv-keep">
				{#each session.entityList as entity (entity.name)}
					<Chip
						pressed={session.kept.has(entity.name)}
						label={entityLabel(entity.name)}
						category={categoryOf(entity.name)}
						hint={entity.report_only ? m.flagOnlyHint() : undefined}
						onchange={() => toggleKeep(entity.name)}
					>
						{entityLabel(entity.name)}{entity.report_only ? ` (${m.flagOnly()})` : ''}
					</Chip>
				{/each}
			</div>
		</section>

		<section class="wide">
			<h3>{m.reviewTitle()}</h3>
			<p class="hint">{m.reviewHint()}</p>
			<div class="row">
				<TextField
					label={m.reviewHost()}
					mono
					inline
					spellcheck="false"
					bind:value={session.reviewHost}
					oninput={forgetModels}
				/>
				<Button
					onclick={refreshModels}
					loading={session.modelsBusy}
					disabled={!session.reviewHost}
				>
					{session.modelsBusy ? m.reviewLooking() : m.reviewFindModels()}
				</Button>
				<Select
					label={m.reviewModel()}
					inline
					bind:value={session.reviewModel}
					options={modelOptions}
				/>
			</div>
			{#if session.modelsProblem}
				<p class="warnline" lang="en">{session.modelsProblem}</p>
			{:else if offeredModels().length === 0}
				<p class="warnline">{m.reviewNoModelsAt({ host: session.reviewHost })}</p>
			{:else}
				<p class="hint">{m.reviewModelsAvailable({ count: offeredModels().length })}</p>
			{/if}
		</section>
	</div>
</Disclosure>

<style>
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
		gap: var(--space-4);
	}

	.wide {
		grid-column: 1 / -1;
	}

	h3 {
		margin-bottom: var(--space-1);
		font-size: var(--text-xs);
		font-weight: var(--weight-medium);
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
		color: var(--text-3);
	}

	.hint {
		margin-bottom: var(--space-2);
		max-width: 42rem;
		font-size: var(--text-xs);
		color: var(--text-3);
	}

	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
	}

	.row {
		display: flex;
		align-items: flex-end;
		gap: var(--space-3);
		flex-wrap: wrap;
	}

	.warnline {
		margin-top: var(--space-2);
		font-size: var(--text-xs);
		color: var(--warn-text);
	}
</style>
