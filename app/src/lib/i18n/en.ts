import type { Messages } from './messages';
import { plural } from './plural';

const L = 'en';

export const en = {
	appName: () => 'FreeDocs',
	tagline: () =>
		'Removes confidential data from a document so it can be handed to an AI service without ' +
		'handing over the data. Everything runs on this machine.',
	skipToContent: () => 'Skip to content',
	appearance: () => 'Appearance',
	appearanceAuto: () => 'Auto',
	appearanceLight: () => 'Light',
	appearanceDark: () => 'Dark',
	language: () => 'Language',

	capabilitiesLabel: () => 'What this build can do',
	engineVersion: ({ version }) => `engine ${version}`,
	ocrAvailable: () => 'OCR available',
	ocrMissing: () => 'OCR not installed',
	nothingLeaves: () => 'nothing leaves this machine',
	ocrReasonTitle: () => 'Scanned pages cannot be read',
	limitationsTitle: () => 'What this build is not detecting',
	engineNotStarted: () => 'The engine did not start',
	quotedFromEngine: () => 'Quoted from the engine, which reports in English.',

	reviewTitle: () => 'Second opinion (Ollama)',
	reviewHint: () =>
		'A local model reads the scrubbed text and says what still worries it. Advisory: it changes ' +
		'nothing in the output.',
	reviewHost: () => 'Host',
	reviewFindModels: () => 'Find models',
	reviewLooking: () => 'Looking…',
	reviewModel: () => 'Model',
	reviewNone: () => 'no review',
	reviewNoModelsAt: ({ host }) =>
		`No models at ${host}. Is Ollama running there, and has anything been pulled?`,
	reviewModelsAvailable: ({ count }) =>
		plural(L, count, { one: '{n} model available.', other: '{n} models available.' }),
	reviewBadge: ({ model }) => `review: ${model}`,
	reviewDidNotRun: () => 'did not run',
	reviewPartial: () => 'first part of the document only',
	reviewRan: () => 'ran',

	dropTitle: () => 'Drop documents here',
	dropHint: () => 'or click to choose.',
	reading: () => 'Reading…',

	minConfidence: () => 'Minimum confidence',
	/*
	 * The bands are the engine's, from detect/validators.py: STRONG_CHECK 0.55,
	 * MEDIUM_CHECK 0.5, WEAK_CHECK 0.45, each measured by running the validator
	 * against 20 000 format-plausible values. The words are the window's, and
	 * they exist because "0.50" is not something a screen reader can usefully say
	 * and not something a person can act on.
	 */
	confidenceBand: ({ value }) => {
		if (value <= 0) return 'everything, including the weakest rules';
		if (value < 0.45) return 'below every rule: nothing is filtered out';
		if (value < 0.5) return 'weak rules included';
		if (value < 0.55) return 'weak rules need a keyword nearby';
		if (value < 0.9) return 'only checksum-strong rules and the model';
		return 'almost nothing but a confirmed checksum';
	},
	placeholderLanguage: () => 'Placeholder language',
	placeholderLanguageHint: () =>
		'The wording written into the output in place of what was removed. Only the words change; ' +
		'nothing about what gets removed depends on this.',
	countriesTitle: () => 'Countries to look for',
	countriesHint: () =>
		'All of them unless you say otherwise. Narrowing raises precision and can hide an identifier ' +
		'from a country you did not expect in the file.',
	keepTitle: () => 'Leave untouched',
	flagOnly: () => 'flag only',
	flagOnlyHint: () => 'Flagged for review, never removed, whether or not this is on.',

	fileSummary: ({ format, characters }) =>
		`${format} · ${new Intl.NumberFormat(L).format(characters)} characters`,
	nothingMatched: () => 'Nothing matched.',
	showValues: ({ count }) =>
		plural(L, count, { one: 'Show the one value', other: 'Show the {n} values' }),
	tableCaption: ({ file }) => `Every value found in ${file}, and what will happen to it`,
	columnWhere: () => 'Where',
	columnType: () => 'Type',
	columnValue: () => 'Value',
	columnAction: () => 'Action',
	columnDecision: () => 'Decision',
	mine: () => 'yours',
	stopRemoving: ({ value }) => `Stop removing ${value}`,
	stopRemovingShort: () => "don't remove",
	keepThisOne: () => 'keep this one',
	keepThisOneFor: ({ value }) => `Keep this one occurrence of ${value}`,
	keepThisOneWhy: () =>
		'Leave this one occurrence alone. Every other occurrence of the same value is still removed.',
	addValueLabel: () => 'Also remove this value',
	addValuePlaceholder: () => 'a name, a number, anything the detectors missed',
	add: () => 'Add',
	keptOnPurpose: ({ count }) =>
		plural(L, count, {
			one: '{n} occurrence kept on purpose.',
			other: '{n} occurrences kept on purpose.'
		}),
	undoAll: () => 'undo all',

	scrub: ({ files }) => plural(L, files, { one: 'Scrub one file', other: 'Scrub {n} files' }),
	scrubbing: () => 'Scrubbing…',
	chooseOutputDirectory: () => 'Where to write the scrubbed copies',
	progressLabel: () => 'Scrubbing',
	progressFile: ({ file, index, total }) => `${file} — file ${index} of ${total}`,

	resultTitle: () => 'Result',
	removedAndFlagged: ({ removed, flagged }) => {
		const gone = plural(L, removed, { one: '{n} value removed', other: '{n} values removed' });
		if (flagged === 0) return `${gone}.`;
		const seen = plural(L, flagged, {
			one: '{n} flagged for review',
			other: '{n} flagged for review'
		});
		return `${gone}, ${seen}.`;
	},
	hiddenRemovedTitle: () => 'Hidden content removed',
	nothingWritten: () => 'Nothing was written.',

	announceValuesFound: ({ file, count }) =>
		plural(L, count, {
			one: `${file}: one value found`,
			other: `${file}: {n} values found`
		}),
	announceFinished: ({ files }) =>
		plural(L, files, { one: 'Finished. One file written.', other: 'Finished. {n} files written.' }),
	announceFinishedWithFailures: ({ failed, files }) =>
		`Finished with ${failed} of ${files} files not written.`,

	errorUnsupportedFormat: ({ message }) => `This format is not supported. ${message}`,
	errorMissingComponent: ({ message }) => `A component is missing. ${message}`,
	errorInFile: ({ file, message }) => `${file}: ${message}`,

	stepsLabel: () => 'Steps',
	stepFile: () => 'File',
	stepReview: () => 'Review',
	stepResult: () => 'Result',
	stepAnnounce: ({ position, total, name }) => `Step ${position} of ${total}: ${name}`,
	stepReviewLocked: () => 'Add a document first.',
	stepResultLocked: () => 'Nothing has been scrubbed yet.',
	filesTitle: () => 'Documents',
	removeFile: ({ file }) => `Remove ${file}`,
	clearFiles: () => 'remove all',
	back: () => 'Back',
	continueToReview: () => 'Review what was found',

	reviewOf: ({ file }) => `Reviewing ${file}`,
	findingCount: ({ count }) =>
		plural(L, count, { one: '{n} value found', other: '{n} values found' }),
	documentLabel: ({ file }) => `The text extracted from ${file}, with every value marked`,
	markName: ({ entity, action, kept }) => (kept ? `${entity}, kept` : `${entity}, ${action}`),
	viewDocument: () => 'Document',
	viewList: () => 'List',
	onlyFindings: () => 'Only what was found',
	wholeDocument: () => 'Whole document',
	skippedParagraphs: ({ count }) =>
		plural(L, count, {
			one: '{n} paragraph with nothing found — show',
			other: '{n} paragraphs with nothing found — show'
		}),
	previewTruncated: ({ shown, total }) =>
		`Showing the first ${new Intl.NumberFormat(L).format(shown)} of ` +
		`${new Intl.NumberFormat(L).format(total)} characters. Everything found beyond that ` +
		'point is still listed, and still removed.',
	noPreview: () => 'This document has no text to show.',
	keyboardHelp: () =>
		'Arrow keys or j and k move between values. x keeps or unkeeps the selected one. ' +
		'a adds a value the detectors missed. f shows or hides the untouched text.',
	filterByType: () => 'Type',
	allTypes: () => 'every type',
	searchValues: () => 'Search the values',
	nothingForThisFilter: () => 'No value matches this filter.',

	detailNothingSelected: () => 'Nothing selected',
	detailNothingSelectedHint: () =>
		'Pick a marked value to see what found it and how sure it is.',
	detailType: () => 'Type',
	detailConfidence: () => 'Confidence',
	detailFound: () => 'Found by',
	detailWhere: () => 'Where',
	detailAction: () => 'What happens',
	detailKept: () => 'You decided to keep this one.',
	foundByChecksum: () => 'a checksum confirmed it',
	foundByModel: () => 'the model recognised it',
	foundByYou: () => 'you asked for it',
	foundBy: ({ detector }) => `rule: ${detector}`,
	keepThisOccurrence: () => 'Keep this occurrence',
	stopKeeping: () => 'Remove it after all',
	keepEveryOne: ({ entity }) => `Keep every ${entity} in the document`,

	advancedTitle: () => 'Advanced',
	advancedHint: () =>
		'The defaults look for everything, everywhere. Every control here can only make the ' +
		'search narrower, and a narrowed run says so in the result.',
	detectorSpec: () => 'Detection layers',
	detectorSpecHint: () =>
		'Which layers run. Fewer layers find less; the engine states what each one covers.',

	verificationPassed: () => 'Verified',
	verificationPassedHint: ({ checked }) =>
		plural(L, checked, {
			one: 'The output was re-opened and searched: {n} value is gone.',
			other: 'The output was re-opened and searched: all {n} values are gone.'
		}),
	openFolder: () => 'Open the folder',
	scrubAgain: () => 'Start again',

	/*
	 * The engine's own type names, as words.
	 *
	 * Enumerable on the wire, so translating them is safe in a way translating a
	 * warning is not. The country-issued four stay generic on purpose: the engine
	 * puts the country on the finding and never in the type, because one stem
	 * stands for twelve countries and a national name for it would be wrong on
	 * eleven.
	 */
	entity: {
		PERSON: () => 'Person',
		ORGANISATION: () => 'Organisation',
		LOCATION: () => 'Place',
		ADDRESS: () => 'Address',
		EMAIL: () => 'Email',
		PHONE: () => 'Phone',
		IBAN: () => 'IBAN',
		CREDIT_CARD: () => 'Card',
		NATIONAL_ID: () => 'National ID',
		TAX_ID: () => 'Tax number',
		VAT_ID: () => 'VAT number',
		COMPANY_ID: () => 'Company number',
		IP_ADDRESS: () => 'IP address',
		MAC_ADDRESS: () => 'MAC address',
		URL: () => 'Web address',
		DATE: () => 'Date',
		JOB_TITLE: () => 'Job title',
		AGE: () => 'Age',
		POSTCODE: () => 'Postcode',
		OTHER: () => 'Yours'
	},

	action: {
		redact: () => 'will be removed',
		surrogate: () => 'will be replaced',
		report: () => 'flagged, not removed',
		keep: () => 'left alone'
	}
} satisfies Messages;
