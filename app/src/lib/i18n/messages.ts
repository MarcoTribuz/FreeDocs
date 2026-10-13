/**
 * The message contract.
 *
 * Functions, not strings — including the ones that take no arguments. That
 * costs nothing and buys four things: arguments are typed, so a caller who
 * forgets `count` fails `npm run check`; there is no interpolation format to
 * invent and no runtime parser; `satisfies Messages` on each catalogue catches
 * a missing key *and* a misspelled extra one; and a message whose wording
 * depends on its own arguments — a plural, a gendered noun, a reordered clause
 * — is expressible without a template language.
 *
 * What is *not* here: anything the engine composed. Warnings, limitations,
 * caveats, review summaries, concern explanations and error messages arrive in
 * English from Python and are quoted rather than translated. Four reasons, and
 * none of them is style:
 *
 *  - They are asserted on. `tests/test_rpc.py` and the leak tests check message
 *    content, and `Leak.describe()` is safety-critical prose. A bug report
 *    reading "il layer NER non è disponibile" is not greppable against the
 *    source that produced it.
 *  - A locale is a property of a UI session, not of a pipe. The engine also
 *    answers to the CLI, to a JSON report on disk and to stderr; threading a
 *    locale through every RPC call would make its output depend on presentation.
 *  - Four chances to soften a warning. These sentences exist to say that a layer
 *    is missing or that a value survived. A mistranslated "not installed" that
 *    reads as "not required" is a build that quietly finds less.
 *  - It is a second catalogue to keep in step with the first, in a codebase
 *    whose whole discipline is that one place decides.
 *
 * The rule that follows: if it came from an enum, translate it; if it came from
 * an f-string, quote it. Entity names, actions and country codes are
 * enumerable, so they get real words. Sentences do not.
 */
export interface Messages {
	// ---- chrome -------------------------------------------------------------
	appName(): string;
	tagline(): string;
	skipToContent(): string;
	appearance(): string;
	appearanceAuto(): string;
	appearanceLight(): string;
	appearanceDark(): string;
	language(): string;

	// ---- what this build can do --------------------------------------------
	capabilitiesLabel(): string;
	engineVersion(a: { version: string }): string;
	ocrAvailable(): string;
	ocrMissing(): string;
	nothingLeaves(): string;
	/**
	 * Shown only when the weights travel with the build. There is no counterpart
	 * for the ordinary case: a badge on every installer run saying the model will
	 * be downloaded is noise, and this one is worth its space because it is what
	 * makes the offline claim beside it true on first use too.
	 */
	modelBundled(): string;
	ocrReasonTitle(): string;
	limitationsTitle(): string;
	engineNotStarted(): string;
	/** One line, in the reader's language, saying the quoted text is not. */
	quotedFromEngine(): string;

	// ---- second opinion -----------------------------------------------------
	reviewTitle(): string;
	reviewHint(): string;
	reviewHost(): string;
	reviewFindModels(): string;
	reviewLooking(): string;
	reviewModel(): string;
	reviewNone(): string;
	reviewNoModelsAt(a: { host: string }): string;
	reviewModelsAvailable(a: { count: number }): string;
	reviewBadge(a: { model: string }): string;
	reviewDidNotRun(): string;
	reviewPartial(): string;
	reviewRan(): string;

	// ---- picking files ------------------------------------------------------
	dropTitle(): string;
	dropHint(): string;
	reading(): string;

	// ---- options ------------------------------------------------------------
	minConfidence(): string;
	/** What raising the threshold does, in words, for the value announced. */
	confidenceBand(a: { value: number }): string;
	placeholderLanguage(): string;
	placeholderLanguageHint(): string;
	countriesTitle(): string;
	countriesHint(): string;
	keepTitle(): string;
	flagOnly(): string;
	flagOnlyHint(): string;

	// ---- the preview --------------------------------------------------------
	fileSummary(a: { format: string; characters: number }): string;
	nothingMatched(): string;
	showValues(a: { count: number }): string;
	tableCaption(a: { file: string }): string;
	columnWhere(): string;
	columnType(): string;
	columnValue(): string;
	columnAction(): string;
	columnDecision(): string;
	mine(): string;
	stopRemoving(a: { value: string }): string;
	stopRemovingShort(): string;
	keepThisOne(): string;
	keepThisOneFor(a: { value: string }): string;
	keepThisOneWhy(): string;
	addValueLabel(): string;
	addValuePlaceholder(): string;
	add(): string;
	keptOnPurpose(a: { count: number }): string;
	undoAll(): string;

	// ---- scrubbing ----------------------------------------------------------
	scrub(a: { files: number }): string;
	scrubbing(): string;
	chooseOutputDirectory(): string;
	progressLabel(): string;
	progressFile(a: { file: string; index: number; total: number }): string;
	/** Stage names: enumerable on the wire, so translated rather than quoted. */
	stage: Record<string, () => string>;
	stageOf(a: { name: string; index: number; count: number }): string;
	stagePages(a: { done: number; of: number }): string;

	// ---- first run: fetching the model --------------------------------------
	//
	// The one screen that asks the network for something, so it says exactly
	// what, how much, from where, and what never goes the other way. The size is
	// written here rather than asked for: before the download the engine cannot
	// know it without the network call this screen exists to ask permission for.
	firstRunEyebrow(): string;
	modelAskTitle(): string;
	modelAskLead(): string;
	modelFactSize(): string;
	modelFactPrivate(): string;
	modelFactOffline(): string;
	modelDownload(): string;
	modelNotNow(): string;
	/** What still works without the model. Checksum-layer types only. */
	modelWithout(): string;
	modelDownloadingTitle(): string;
	modelBytes(a: { done: string; of: string }): string;
	modelEtaMinutes(a: { minutes: number }): string;
	modelEtaUnderMinute(): string;
	modelKeepOpen(): string;
	modelSampleTitle(): string;
	modelBefore(): string;
	modelAfter(): string;
	modelSampleBefore(): string;
	/** The placeholders come from the engine's allocator, never from here. */
	modelSampleAfter(a: { person: string; organisation: string; address: string }): string;
	modelPreparingTitle(): string;
	modelPreparingLead(): string;
	modelFailedTitle(): string;
	modelFailedLead(): string;
	modelFailedProxy(): string;
	modelRetry(): string;
	modelReadyTitle(): string;
	modelReadyLead(): string;
	modelChooseDocument(): string;
	modelDeferredTitle(): string;
	modelDeferredLead(): string;

	// ---- the result ---------------------------------------------------------
	resultTitle(): string;
	removedAndFlagged(a: { removed: number; flagged: number }): string;
	hiddenRemovedTitle(): string;
	/** The same list before the scrub, so the preview is not silent about it. */
	hiddenPendingTitle(): string;
	nothingWritten(): string;

	// ---- announced, not shown ----------------------------------------------
	announceValuesFound(a: { file: string; count: number }): string;
	announceFinished(a: { files: number }): string;
	announceFinishedWithFailures(a: { failed: number; files: number }): string;

	// ---- errors the window words around an engine message -------------------
	errorUnsupportedFormat(a: { message: string }): string;
	errorMissingComponent(a: { message: string }): string;
	errorInFile(a: { file: string; message: string }): string;

	// ---- the three steps ----------------------------------------------------
	stepsLabel(): string;
	stepFile(): string;
	stepReview(): string;
	stepResult(): string;
	stepAnnounce(a: { position: number; total: number; name: string }): string;
	stepReviewLocked(): string;
	stepResultLocked(): string;
	filesTitle(): string;
	removeFile(a: { file: string }): string;
	clearFiles(): string;
	back(): string;
	continueToReview(): string;

	// ---- the review pane ----------------------------------------------------
	reviewOf(a: { file: string }): string;
	findingCount(a: { count: number }): string;
	documentLabel(a: { file: string }): string;
	/** The accessible name of one highlight: what it is, and what happens to it. */
	markName(a: { entity: string; action: string; kept: boolean }): string;
	viewDocument(): string;
	viewList(): string;
	onlyFindings(): string;
	wholeDocument(): string;
	skippedParagraphs(a: { count: number }): string;
	previewTruncated(a: { shown: number; total: number }): string;
	noPreview(): string;
	keyboardHelp(): string;
	filterByType(): string;
	allTypes(): string;
	searchValues(): string;
	nothingForThisFilter(): string;

	// ---- the detail panel ---------------------------------------------------
	detailNothingSelected(): string;
	detailNothingSelectedHint(): string;
	detailType(): string;
	detailConfidence(): string;
	detailFound(): string;
	detailWhere(): string;
	detailAction(): string;
	detailKept(): string;
	foundByChecksum(): string;
	foundByModel(): string;
	foundByYou(): string;
	foundBy(a: { detector: string }): string;
	keepThisOccurrence(): string;
	stopKeeping(): string;
	keepEveryOne(a: { entity: string }): string;

	// ---- advanced ----------------------------------------------------------
	advancedTitle(): string;
	advancedHint(): string;
	detectorSpec(): string;
	detectorSpecHint(): string;

	// ---- what this machine can do ------------------------------------------
	/** The pane's re-ask control. */
	diagnosticsRecheck(): string;
	announceRechecked(): string;
	copyFix(): string;
	copied(): string;
	copyUnavailable(): string;
	locateTesseract(): string;
	locateTesseractHint(): string;
	/** The file dialog's own title, like `chooseKeyFile`. */
	chooseTesseract(): string;
	/**
	 * Worded about the *binary*, never about OCR.
	 *
	 * An accepted Tesseract with no language data is still an OCR this build
	 * cannot do, and the two halves install separately — so a message saying "OCR
	 * is ready" would be the window making a claim only the engine can.
	 */
	tesseractAccepted(): string;
	/**
	 * The engine's refusal, by key.
	 *
	 * A literal-union record rather than `Record<string, ...>`, so `satisfies
	 * Messages` proves every entry present in all four catalogues. The looser
	 * shape used by `stage` cannot see a missing one.
	 */
	tesseractRefusal: Record<'not_executable' | 'wrong_name', () => string>;
	/** A refusal key added in Python later must still render as something. */
	tesseractRefusalOther(): string;
	/** The button that asks the engine to run the install line it showed. */
	ocrInstall(): string;
	/** Under Install: what it reaches and that it runs exactly the line shown. */
	ocrInstallNote(): string;
	/** Under Copy, where the engine names a line it will not run. */
	ocrCopyNote(): string;
	/** Announced when an install starts, finishes, or fails. */
	ocrInstalling(): string;
	ocrInstalled(): string;
	ocrInstallFailedTitle(): string;

	// ---- the first-run dependency list ---------------------------------------
	/** The screen opened for the dependencies alone, with the model present. */
	setupTitle(): string;
	setupLead(): string;
	setupContinue(): string;
	setupListTitle(): string;
	depOcr(): string;
	/** Why OCR matters, and that most documents do not need it. */
	depOcrWhy(): string;
	depReview(): string;
	depReviewWhy(): string;
	depReady(): string;
	depMissing(): string;
	depOptional(): string;
	engineBuild(): string;
	/** Where the engine came from, by key. A closed vocabulary from Rust. */
	engineSource: Record<'override' | 'bundled' | 'checkout', () => string>;
	engineBuiltOn(a: { when: string }): string;
	/** Absent, which is not the same as a wrong date. */
	engineBuildDateUnknown(): string;
	diagnosticsTitle(): string;
	diagnosticsOk(): string;
	diagnosticsFix(): string;
	/** A layer that is absent: this build does less, not nothing. */
	diagnosticsDegraded(): string;
	/** Something this build needs and does not have. */
	diagnosticsBroken(): string;
	countryModelOnly(): string;
	rulesSilenced(a: { count: number }): string;
	placeholderExample(a: { example: string }): string;

	// ---- the result --------------------------------------------------------
	verificationPassed(): string;
	verificationPassedHint(a: { checked: number }): string;
	openFolder(): string;
	scrubAgain(): string;


	// ---- the reverse path: a key file, and putting the values back ----------
	//
	// UI copy about a UI action, so it is translated. The rule that keeps engine
	// prose in English is about sentences the engine composed - a warning, a
	// caveat, an error - and none of these is one.
	modeLabel(): string;
	modeScrub(): string;
	modeRestore(): string;
	modeAnnounce(a: { name: string }): string;

	keyFileTitle(): string;
	/** What the file is, said where the choice is made rather than afterwards. */
	keyFileHint(): string;
	keyFileEnable(): string;
	keyFileWhere(): string;
	keyFileChooseWhere(): string;
	keyFilePassphrase(): string;
	keyFileConfirm(): string;
	/** Why the controls are disabled: this build has no cipher for the file. */
	keyFileUnavailable(): string;
	keyFileNeedsDirectory(): string;
	keyFileNeedsPassphrase(a: { min: number }): string;
	keyFileMismatch(): string;
	/** The one warning that matters: this file undoes the scrub. */
	keyFileDanger(): string;
	keyFileWritten(): string;
	chooseKeyDirectory(): string;
	chooseKeyFile(): string;
	keyFileFilter(): string;

	// ---- text mode: paste in, scrubbed text out, the reply back ---------------
	modeText(): string;
	stepText(): string;
	textTitle(): string;
	/** What the mode is, and that nothing is written to disk. */
	textHint(): string;
	textLabel(): string;
	textPlaceholder(): string;
	textCount(a: { count: number }): string;
	/** The engine's ceiling, from capabilities. */
	textTooLong(a: { max: number }): string;
	textInspect(): string;
	textReviewTitle(): string;
	textScrub(): string;
	textKeepTitle(): string;
	textKeepNone(): string;
	textKeepNoneHint(): string;
	textKeepMemory(): string;
	textKeepMemoryHint(): string;
	/** The one mapping the engine keeps past the request that made it. */
	textKeepMemoryWarning(): string;
	textKeepFile(): string;
	textKeepFileHint(): string;
	textKeyNeedsDirectory(): string;
	textResultTitle(): string;
	textScrubbedTitle(): string;
	textNew(): string;
	textCopy(): string;
	textCopied(): string;
	/** Said aloud: a failed copy pastes the previous clipboard into a model. */
	textCopyFailed(): string;
	textHeld(): string;
	textNotKept(): string;
	textNothingProduced(): string;
	textReplyTitle(): string;
	textReplyLabel(): string;
	textReplyPlaceholder(): string;
	textRestore(): string;
	textRestoredTitle(): string;
	announceTextScrubbed(a: { count: number }): string;

	// ---- the term list: the persistent half of "also remove" -----------------
	termsTitle(): string;
	/** What the list is, said where it is opened. */
	termsHint(): string;
	/** The build has no cipher for the list. */
	termsUnavailable(): string;
	termsOpen(): string;
	termsNew(): string;
	termsCancel(): string;
	termsPassphrase(): string;
	termsConfirm(): string;
	termsUnlock(): string;
	termsCreate(): string;
	termsLock(): string;
	/** Lock, and stop remembering which file it was. */
	termsForget(): string;
	termsNeedsPassphrase(a: { min: number }): string;
	termsMismatch(): string;
	/** Said before the list exists: nothing recovers a forgotten passphrase. */
	termsNewWarning(): string;
	termsCount(a: { count: number }): string;
	termsUse(): string;
	termsSearch(): string;
	termsNoMatch(): string;
	termsEmpty(): string;
	termsNewValue(): string;
	termsEntity(): string;
	/** OTHER, in the entity picker: the person has not said. */
	termsEntityUnspecified(): string;
	termsAdd(): string;
	/** Accessible name of the per-row remove button. */
	termsRemoveOne(a: { value: string }): string;
	termsImport(): string;
	termsExport(): string;
	/** The cost of an export, said before the file is chosen. */
	termsExportWarning(): string;
	termsExportConfirm(): string;
	termsExportedTitle(): string;
	termsImportedTitle(a: { added: number; skipped: number }): string;
	/** The engine never deletes the source; the person must. */
	termsDeleteSource(a: { file: string }): string;
	termsDismiss(): string;
	termsFilter(): string;
	termsRekey(): string;
	termsCurrentPassphrase(): string;
	termsNextPassphrase(): string;
	termsRekeyConfirm(): string;
	termsRekeyed(): string;
	termsImportFilter(): string;
	termsChooseFile(): string;
	termsChooseNew(): string;
	termsChooseImport(): string;
	termsChooseExport(): string;
	termsUnlocked(a: { count: number }): string;
	termsLocked(): string;
	termsAdded(a: { count: number }): string;
	termsAlreadyThere(): string;
	termsRemoved(a: { count: number }): string;
	termsImportedAnnounce(a: { count: number }): string;
	termsExportedAnnounce(a: { count: number }): string;
	/** Tag on a finding the term list put there, beside `mine`. */
	fromTermList(): string;
	foundByTermList(): string;
	/** Counts from the report. The entries that matched nothing are named nowhere. */
	termsMatched(a: { matched: number; loaded: number }): string;

	stepRestoreFile(): string;
	restoreTitle(): string;
	restoreHint(): string;
	restoreDocument(): string;
	restoreChooseDocument(): string;
	restoreKey(): string;
	restoreChooseKey(): string;
	restorePassphrase(): string;
	restoreNeedsDocument(): string;
	restoreNeedsKey(): string;
	restoreNeedsPassphrase(): string;
	restoreRun(): string;
	restoring(): string;
	restoreAgain(): string;

	restoreResultTitle(): string;
	restoredSummary(a: { values: number; occurrences: number }): string;
	restoreNothingMatched(): string;
	restoreNotPresentTitle(): string;
	restoreNotPresentHint(): string;
	restoreUnknownTitle(): string;
	restoreUnknownHint(): string;
	restoreProblemsTitle(): string;
	restoreVerified(): string;
	restoreIncomplete(a: { count: number }): string;
	/** What a restore cannot do. Quoted from the engine, like every caveat. */
	restoreCaveatsTitle(): string;

	announceRestored(a: { count: number }): string;
	announceRestoredWithProblems(a: { count: number }): string;

	// ---- engine vocabulary: enumerable, so translated ----------------------
	entity: Record<string, () => string>;
	action: Record<'redact' | 'surrogate' | 'report' | 'keep', () => string>;
}
