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

	// ---- what this machine can do ------------------------------------------
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

	// ---- the result ---------------------------------------------------------
	resultTitle(): string;
	removedAndFlagged(a: { removed: number; flagged: number }): string;
	hiddenRemovedTitle(): string;
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
