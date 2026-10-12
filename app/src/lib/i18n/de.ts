import type { Messages } from './messages';
import { plural } from './plural';

const L = 'de';

export const de = {
	appName: () => 'FreeDocs',
	tagline: () =>
		'Entfernt vertrauliche Daten aus einem Dokument, damit es an einen KI-Dienst gegeben werden ' +
		'kann, ohne die Daten mitzugeben. Alles läuft auf diesem Rechner.',
	skipToContent: () => 'Zum Inhalt springen',
	appearance: () => 'Darstellung',
	appearanceAuto: () => 'Auto',
	appearanceLight: () => 'Hell',
	appearanceDark: () => 'Dunkel',
	language: () => 'Sprache',

	capabilitiesLabel: () => 'Was dieser Build kann',
	engineVersion: ({ version }) => `Engine ${version}`,
	ocrAvailable: () => 'OCR verfügbar',
	ocrMissing: () => 'OCR nicht installiert',
	nothingLeaves: () => 'nichts verlässt diesen Rechner',
	modelBundled: () => 'Modell enthalten',
	ocrReasonTitle: () => 'Gescannte Seiten können nicht gelesen werden',
	limitationsTitle: () => 'Was dieser Build nicht erkennt',
	engineNotStarted: () => 'Die Engine ist nicht gestartet',
	quotedFromEngine: () => 'Zitat der Engine, die auf Englisch berichtet.',

	reviewTitle: () => 'Zweitmeinung (Ollama)',
	reviewHint: () =>
		'Ein lokales Modell liest den bereits bereinigten Text und sagt, was es weiterhin ' +
		'beunruhigt. Nur ein Hinweis: am Ergebnis ändert es nichts.',
	reviewHost: () => 'Host',
	reviewFindModels: () => 'Modelle suchen',
	reviewLooking: () => 'Suche…',
	reviewModel: () => 'Modell',
	reviewNone: () => 'keine Prüfung',
	reviewNoModelsAt: ({ host }) =>
		`Keine Modelle auf ${host}. Läuft Ollama dort, und wurde etwas geladen?`,
	reviewModelsAvailable: ({ count }) =>
		plural(L, count, { one: '{n} Modell verfügbar.', other: '{n} Modelle verfügbar.' }),
	reviewBadge: ({ model }) => `Prüfung: ${model}`,
	reviewDidNotRun: () => 'nicht gelaufen',
	reviewPartial: () => 'nur der erste Teil des Dokuments',
	reviewRan: () => 'gelaufen',

	dropTitle: () => 'Dokumente hierher ziehen',
	dropHint: () => 'oder klicken, um sie auszuwählen.',
	reading: () => 'Lese…',

	minConfidence: () => 'Mindestkonfidenz',
	confidenceBand: ({ value }) => {
		if (value <= 0) return 'alles, auch die schwächsten Regeln';
		if (value < 0.45) return 'unter jeder Regel: nichts wird gefiltert';
		if (value < 0.5) return 'schwache Regeln eingeschlossen';
		if (value < 0.55) return 'schwache Regeln brauchen ein Schlüsselwort in der Nähe';
		if (value < 0.9) return 'nur Regeln mit starker Prüfsumme und das Modell';
		return 'fast nichts außer einer bestätigten Prüfsumme';
	},
	placeholderLanguage: () => 'Sprache der Platzhalter',
	placeholderLanguageHint: () =>
		'Der Wortlaut, der anstelle des Entfernten in die Ausgabe geschrieben wird. Nur die Worte ' +
		'ändern sich; was entfernt wird, hängt nicht davon ab.',
	countriesTitle: () => 'Länder, in denen gesucht wird',
	countriesHint: () =>
		'Alle, sofern nichts anderes gesagt wird. Eine Einschränkung erhöht die Präzision und kann ' +
		'eine Kennnummer aus einem Land verbergen, das man in der Datei nicht erwartet hat.',
	keepTitle: () => 'Unangetastet lassen',
	flagOnly: () => 'nur markiert',
	flagOnlyHint: () =>
		'Zur Prüfung markiert, nie entfernt — unabhängig davon, ob dies aktiv ist.',

	fileSummary: ({ format, characters }) =>
		`${format} · ${new Intl.NumberFormat(L).format(characters)} Zeichen`,
	nothingMatched: () => 'Keine Treffer.',
	showValues: ({ count }) =>
		plural(L, count, { one: 'Den einen Wert zeigen', other: 'Die {n} Werte zeigen' }),
	tableCaption: ({ file }) => `Jeder in ${file} gefundene Wert, und was mit ihm geschieht`,
	columnWhere: () => 'Wo',
	columnType: () => 'Typ',
	columnValue: () => 'Wert',
	columnAction: () => 'Aktion',
	columnDecision: () => 'Entscheidung',
	mine: () => 'von dir',
	stopRemoving: ({ value }) => `${value} nicht mehr entfernen`,
	stopRemovingShort: () => 'nicht entfernen',
	keepThisOne: () => 'diese behalten',
	keepThisOneFor: ({ value }) => `Dieses eine Vorkommen von ${value} behalten`,
	keepThisOneWhy: () =>
		'Nur dieses eine Vorkommen bleibt. Jedes andere Vorkommen desselben Werts wird weiterhin ' +
		'entfernt.',
	addValueLabel: () => 'Diesen Wert ebenfalls entfernen',
	addValuePlaceholder: () => 'ein Name, eine Nummer, was die Detektoren übersehen haben',
	add: () => 'Hinzufügen',
	keptOnPurpose: ({ count }) =>
		plural(L, count, {
			one: '{n} Vorkommen absichtlich behalten.',
			other: '{n} Vorkommen absichtlich behalten.'
		}),
	undoAll: () => 'alles zurücknehmen',

	scrub: ({ files }) =>
		plural(L, files, { one: 'Eine Datei bereinigen', other: '{n} Dateien bereinigen' }),
	scrubbing: () => 'Bereinige…',
	chooseOutputDirectory: () => 'Wohin die bereinigten Kopien geschrieben werden',
	progressLabel: () => 'Bereinigung',
	progressFile: ({ file, index, total }) => `${file} — Datei ${index} von ${total}`,

	firstRunEyebrow: () => 'Erster Start',
	modelAskTitle: () => 'Ein Download, dann arbeitet FreeDocs offline',
	modelAskLead: () =>
		'Um Namen, Firmen und Adressen zu erkennen, nutzt FreeDocs ein Sprachmodell, das auf diesem Computer läuft. Es wird einmal heruntergeladen.',
	modelFactSize: () => '1,2 GB, von Hugging Face, wo das Modell veröffentlicht ist',
	modelFactPrivate: () =>
		'Ihre Dokumente verlassen diesen Computer nie. Nur das Modell kommt herein.',
	modelFactOffline: () => 'Danach braucht FreeDocs keine Internetverbindung mehr.',
	modelDownload: () => 'Modell herunterladen (1,2 GB)',
	modelNotNow: () => 'Nicht jetzt',
	modelWithout: () =>
		'Ohne das Modell findet FreeDocs trotzdem IBANs, Steuer- und Ausweisnummern, Karten, E-Mail-Adressen und Telefonnummern, aber keine Namen, Firmen oder Adressen.',
	modelDownloadingTitle: () => 'Das Modell wird heruntergeladen',
	modelBytes: ({ done, of }) => `${done} von ${of}`,
	modelEtaMinutes: ({ minutes }) => `noch etwa ${minutes} Min.`,
	modelEtaUnderMinute: () => 'noch weniger als eine Minute',
	modelKeepOpen: () =>
		'Lassen Sie dieses Fenster offen. Währenddessen wird keine Datei gelesen oder gesendet.',
	modelSampleTitle: () => 'Was es tun wird',
	modelBefore: () => 'Vorher',
	modelAfter: () => 'Nachher',
	modelSampleBefore: () =>
		'Vertrag zwischen Anna Müller und Acme AG, Bahnhofstrasse 12, 8001 Zürich.',
	modelSampleAfter: ({ person, organisation, address }) =>
		`Vertrag zwischen ${person} und ${organisation}, ${address}.`,
	modelPreparingTitle: () => 'Das Modell wird vorbereitet',
	modelPreparingLead: () => 'Es wird geprüft und geladen. Einige Sekunden.',
	modelFailedTitle: () => 'Der Download wurde unterbrochen',
	modelFailedLead: () =>
		'Auf diesem Computer wurde nichts verändert. Prüfen Sie die Verbindung und versuchen Sie es erneut.',
	modelFailedProxy: () =>
		'In einem Firmennetz kann ein Proxy oder eine Firewall huggingface.co sperren. Ihre IT kann es freigeben.',
	modelRetry: () => 'Erneut versuchen',
	modelReadyTitle: () => 'Fertig. FreeDocs arbeitet jetzt offline.',
	modelReadyLead: () => 'Namen, Firmen und Adressen werden ab dem ersten Dokument gefunden.',
	modelChooseDocument: () => 'Dokument auswählen',
	modelDeferredTitle: () => 'Namen und Adressen werden nicht gesucht',
	modelDeferredLead: () => 'Das Modell, das sie findet, ist noch nicht heruntergeladen.',
	resultTitle: () => 'Ergebnis',
	removedAndFlagged: ({ removed, flagged }) => {
		const gone = plural(L, removed, {
			one: '{n} Wert entfernt',
			other: '{n} Werte entfernt'
		});
		if (flagged === 0) return `${gone}.`;
		const seen = plural(L, flagged, {
			one: '{n} zur Prüfung markiert',
			other: '{n} zur Prüfung markiert'
		});
		return `${gone}, ${seen}.`;
	},
	hiddenRemovedTitle: () => 'Entfernte versteckte Inhalte',
	hiddenPendingTitle: () => 'Versteckte Inhalte, die entfernt werden',
	nothingWritten: () => 'Es wurde nichts geschrieben.',

	announceValuesFound: ({ file, count }) =>
		plural(L, count, {
			one: `${file}: ein Wert gefunden`,
			other: `${file}: {n} Werte gefunden`
		}),
	announceFinished: ({ files }) =>
		plural(L, files, {
			one: 'Fertig. Eine Datei geschrieben.',
			other: 'Fertig. {n} Dateien geschrieben.'
		}),
	announceFinishedWithFailures: ({ failed, files }) =>
		`Fertig, aber ${failed} von ${files} Dateien wurden nicht geschrieben.`,

	errorUnsupportedFormat: ({ message }) => `Dieses Format wird nicht unterstützt. ${message}`,
	errorMissingComponent: ({ message }) => `Eine Komponente fehlt. ${message}`,
	errorInFile: ({ file, message }) => `${file}: ${message}`,

	stepsLabel: () => 'Schritte',
	stepFile: () => 'Datei',
	stepReview: () => 'Prüfen',
	stepResult: () => 'Ergebnis',
	stepAnnounce: ({ position, total, name }) => `Schritt ${position} von ${total}: ${name}`,
	stepReviewLocked: () => 'Zuerst ein Dokument hinzufügen.',
	stepResultLocked: () => 'Es wurde noch nichts bereinigt.',
	filesTitle: () => 'Dokumente',
	removeFile: ({ file }) => `${file} entfernen`,
	clearFiles: () => 'alle entfernen',
	back: () => 'Zurück',
	continueToReview: () => 'Gefundenes prüfen',

	reviewOf: ({ file }) => `Prüfung von ${file}`,
	findingCount: ({ count }) =>
		plural(L, count, { one: '{n} Wert gefunden', other: '{n} Werte gefunden' }),
	documentLabel: ({ file }) => `Der aus ${file} gelesene Text, mit jedem Wert markiert`,
	markName: ({ entity, action, kept }) =>
		kept ? `${entity}, behalten` : `${entity}, ${action}`,
	viewDocument: () => 'Dokument',
	viewList: () => 'Liste',
	onlyFindings: () => 'Nur das Gefundene',
	wholeDocument: () => 'Ganzes Dokument',
	skippedParagraphs: ({ count }) =>
		plural(L, count, {
			one: '{n} Absatz ohne Fund — zeigen',
			other: '{n} Absätze ohne Fund — zeigen'
		}),
	previewTruncated: ({ shown, total }) =>
		`Die ersten ${new Intl.NumberFormat(L).format(shown)} von ` +
		`${new Intl.NumberFormat(L).format(total)} Zeichen. Alles darüber hinaus Gefundene ist ` +
		'weiterhin aufgeführt und wird weiterhin entfernt.',
	noPreview: () => 'Dieses Dokument hat keinen Text zu zeigen.',
	keyboardHelp: () =>
		'Pfeiltasten oder j und k wechseln zwischen den Werten. x behält den gewählten Wert ' +
		'oder gibt ihn frei. a fügt einen übersehenen Wert hinzu. f zeigt oder verbirgt den ' +
		'unberührten Text.',
	filterByType: () => 'Typ',
	allTypes: () => 'jeder Typ',
	searchValues: () => 'Werte durchsuchen',
	nothingForThisFilter: () => 'Kein Wert passt zu diesem Filter.',

	detailNothingSelected: () => 'Nichts ausgewählt',
	detailNothingSelectedHint: () =>
		'Einen markierten Wert wählen, um zu sehen, wer ihn gefunden hat und wie sicher.',
	detailType: () => 'Typ',
	detailConfidence: () => 'Konfidenz',
	detailFound: () => 'Gefunden von',
	detailWhere: () => 'Wo',
	detailAction: () => 'Was passiert',
	detailKept: () => 'Sie haben entschieden, dieses Vorkommen zu behalten.',
	foundByChecksum: () => 'eine Prüfsumme hat es bestätigt',
	foundByModel: () => 'das Modell hat es erkannt',
	foundByYou: () => 'Sie haben danach gefragt',
	foundBy: ({ detector }) => `Regel: ${detector}`,
	keepThisOccurrence: () => 'Dieses Vorkommen behalten',
	stopKeeping: () => 'Doch entfernen',
	keepEveryOne: ({ entity }) => `Jeden Eintrag "${entity}" im Dokument behalten`,

	advancedTitle: () => 'Erweitert',
	advancedHint: () =>
		'Die Voreinstellungen suchen überall nach allem. Jede Einstellung hier kann die Suche ' +
		'nur einschränken, und ein eingeschränkter Lauf sagt es im Ergebnis.',
	detectorSpec: () => 'Erkennungsschichten',
	detectorSpecHint: () =>
		'Welche Schichten laufen. Weniger Schichten finden weniger; die Engine sagt, was jede ' +
		'abdeckt.',

	verificationPassed: () => 'Geprüft',
	verificationPassedHint: ({ checked }) =>
		plural(L, checked, {
			one: 'Die Ausgabe wurde erneut geöffnet und durchsucht: {n} Wert ist weg.',
			other: 'Die Ausgabe wurde erneut geöffnet und durchsucht: alle {n} Werte sind weg.'
		}),
	openFolder: () => 'Ordner öffnen',
	scrubAgain: () => 'Neu beginnen',

	diagnosticsRecheck: () => 'Erneut prüfen',
	announceRechecked: () => 'Erneut geprüft.',
	copyFix: () => 'Kopieren',
	copied: () => 'Kopiert',
	copyUnavailable: () => 'Markieren und kopieren',
	locateTesseract: () => 'Tesseract suchen…',
	locateTesseractHint: () =>
		'Wenn Tesseract an einem ungewöhnlichen Ort installiert ist, verweisen Sie diesen Build darauf. Die Engine prüft die Datei, bevor sie sie verwendet.',
	chooseTesseract: () => 'Tesseract-Programm auswählen',
	tesseractAccepted: () => 'Tesseract akzeptiert.',
	tesseractRefusal: {
		not_executable: () => 'Diese Datei lässt sich nicht ausführen. Wählen Sie das Tesseract-Programm selbst.',
		wrong_name: () => 'Diese Datei muss „tesseract“ heißen, denn unter diesem Namen sucht der PDF-Leser sie.'
	},
	tesseractRefusalOther: () => 'Die Engine hat diese Datei abgelehnt.',
	engineBuild: () => 'Engine',
	engineSource: {
		override: () => 'mit FREEDOCS_ENGINE gewählt',
		bundled: () => 'mit der App geliefert',
		checkout: () => 'aus dem Quellbaum'
	},
	engineBuiltOn: (a) => `erstellt ${a.when}`,
	engineBuildDateUnknown: () => 'Erstellungsdatum unbekannt',
	diagnosticsTitle: () => 'Was dieser Rechner kann',
	diagnosticsOk: () => 'Alles, was dieser Build braucht, ist vorhanden.',
	diagnosticsFix: () => 'Abhilfe',
	diagnosticsDegraded: () => 'findet weniger',
	diagnosticsBroken: () => 'fehlt',
	countryModelOnly: () => 'nur Modell',
	rulesSilenced: ({ count }) =>
		plural(L, count, {
			one: '{n} Regel findet bei dieser Schwelle nichts ohne Schlüsselwort daneben.',
			other: '{n} Regeln finden bei dieser Schwelle nichts ohne Schlüsselwort daneben.'
		}),
	placeholderExample: ({ example }) => `geschrieben als ${example}`,

	stage: {
		router: () => 'wähle den Leser',
		extract: () => 'lese das Dokument',
		detect: () => 'suche Werte',
		policy: () => 'entscheide',
		'write-back': () => 'schreibe die Kopie',
		verify: () => 'durchsuche die Kopie',
		match: () => 'suche die Platzhalter',
		review: () => 'Zweitmeinung'
	},
	stageOf: ({ name, index, count }) => `${name} — Schritt ${index} von ${count}`,
	stagePages: ({ done, of }) => `Seite ${done} von ${of}`,

	/*
	 * Die Typen bleiben allgemein: die Engine setzt das Land auf den Fund und nie
	 * in den Typ, weil ein Stamm für zwölf Länder steht und ein nationaler Name
	 * für elf falsch wäre. Also "USt-Nummer", nicht "Umsatzsteuer-Identnummer".
	 */
	// ---- der umgekehrte Weg -------------------------------------------------
	modeLabel: () => 'Was tun',
	modeScrub: () => 'Entfernen',
	modeRestore: () => 'Zurücksetzen',
	modeAnnounce: ({ name }) => `Gewechselt zu ${name}`,

	keyFileTitle: () => 'Schlüsseldatei',
	keyFileHint: () =>
		'Schreibt eine verschlüsselte Datei, mit der die entfernten Werte in das ' +
		'zurückkommen, was das Modell liefert. Ohne sie kann diese Bereinigung niemand rückgängig machen.',
	keyFileEnable: () => 'Auch eine Schlüsseldatei schreiben',
	keyFileWhere: () => 'Wohin damit',
	keyFileChooseWhere: () => 'Ordner wählen',
	keyFilePassphrase: () => 'Passphrase',
	keyFileConfirm: () => 'Passphrase wiederholen',
	keyFileUnavailable: () => 'Dieser Build kann keine Schlüsseldatei schreiben.',
	keyFileNeedsDirectory: () => 'Wähle einen Ordner außerhalb des Zielordners.',
	keyFileNeedsPassphrase: ({ min }) => `Mindestens ${min} Zeichen.`,
	keyFileMismatch: () => 'Die beiden Passphrasen stimmen nicht überein.',
	keyFileDanger: () =>
		'Diese Datei ist so vertraulich wie das Originaldokument. Halte sie von der ' +
		'bereinigten Kopie fern, und verschicke die beiden nie zusammen.',
	keyFileWritten: () => 'Schlüsseldatei',
	chooseKeyDirectory: () => 'Wohin mit der Schlüsseldatei',
	chooseKeyFile: () => 'Schlüsseldatei wählen',
	keyFileFilter: () => 'FreeDocs-Schlüsseldatei',

	// ---- text mode ----------------------------------------------------------
	modeText: () => 'Text einfügen',
	stepText: () => 'Text',
	textTitle: () => 'Text einfügen',
	textHint: () => 'Fügen Sie ein, was Sie an ein Modell senden wollen. Es wird hier bereinigt und nie auf die Festplatte geschrieben; fügen Sie danach die Antwort ein, um die Werte zurückzusetzen.',
	textLabel: () => 'Text',
	textPlaceholder: () => 'Hier einfügen…',
	textCount: ({ count }) =>
		plural(L, count, { one: 'Ein Zeichen', other: '{n} Zeichen' }),
	textTooLong: ({ max }) => `Länger als die zulässigen ${max.toLocaleString(L)} Zeichen. Speichern Sie ihn als Datei und bereinigen Sie diese.`,
	textInspect: () => 'Werte suchen',
	textReviewTitle: () => 'Eingefügten Text prüfen',
	textScrub: () => 'Text bereinigen',
	textKeepTitle: () => 'Danach',
	textKeepNone: () => 'Keinen Rückweg behalten',
	textKeepNoneHint: () => 'Unumkehrbar wie jede Bereinigung. Eine Antwort kann nicht wiederhergestellt werden.',
	textKeepMemory: () => 'Behalten, bis ich FreeDocs schließe',
	textKeepMemoryHint: () => 'Die Antwort hier wiederherstellen, ohne etwas einzugeben.',
	textKeepMemoryWarning: () => 'Die Engine hält das Entfernte im Speicher, bis Sie einen neuen Text beginnen, den Modus wechseln oder FreeDocs schließen. Nichts wird auf die Festplatte geschrieben.',
	textKeepFile: () => 'Schlüsseldatei speichern',
	textKeepFileHint: () => 'Verschlüsselt, für eine Antwort, die an einem anderen Tag kommt.',
	textKeyNeedsDirectory: () => 'Wählen Sie einen Ordner für die Schlüsseldatei.',
	textResultTitle: () => 'Bereinigter Text',
	textScrubbedTitle: () => 'Zum Senden',
	textNew: () => 'Neuer Text',
	textCopy: () => 'Kopieren',
	textCopied: () => 'Kopiert',
	textCopyFailed: () => 'Nicht kopiert. Markieren Sie den Text und kopieren Sie ihn von Hand.',
	textHeld: () => 'Der Rückweg wird gehalten, bis Sie einen neuen Text beginnen, den Modus wechseln oder FreeDocs schließen.',
	textNotKept: () => 'Kein Rückweg behalten: Dieser Text kann nicht wiederhergestellt werden.',
	textNothingProduced: () => 'Es wurde kein bereinigter Text erzeugt.',
	textReplyTitle: () => 'Die Antwort',
	textReplyLabel: () => 'Was das Modell geantwortet hat',
	textReplyPlaceholder: () => 'Antwort hier einfügen…',
	textRestore: () => 'Werte zurücksetzen',
	textRestoredTitle: () => 'Wiederhergestellte Antwort',
	announceTextScrubbed: ({ count }) =>
		plural(L, count, { one: 'Text bereinigt, ein Wert entfernt', other: 'Text bereinigt, {n} Werte entfernt' }),

	// ---- the term list ------------------------------------------------------
	termsTitle: () => 'Begriffsliste',
	termsHint: () => 'Eine verschlüsselte Liste von Namen und Kennungen, die Ihre Kanzlei immer entfernt: Mandanten, Akten, Projekte. Einmal pro Sitzung entsperrt; die Einträge bleiben in der Engine.',
	termsUnavailable: () => 'Dieser Build kann keine Begriffsliste öffnen.',
	termsOpen: () => 'Öffnen…',
	termsNew: () => 'Neu…',
	termsCancel: () => 'Abbrechen',
	termsPassphrase: () => 'Passphrase',
	termsConfirm: () => 'Passphrase wiederholen',
	termsUnlock: () => 'Entsperren',
	termsCreate: () => 'Liste anlegen',
	termsLock: () => 'Sperren',
	termsForget: () => 'Schließen',
	termsNeedsPassphrase: ({ min }) => `Mindestens ${min} Zeichen.`,
	termsMismatch: () => 'Die beiden Passphrasen stimmen nicht überein.',
	termsNewWarning: () => 'Ohne die Passphrase kann niemand diese Liste öffnen, auch FreeDocs nicht. Bewahren Sie sie dort auf, wo Ihre Kanzlei ihre anderen Passwörter aufbewahrt.',
	termsCount: ({ count }) =>
		plural(L, count, { one: 'Ein Eintrag', other: '{n} Einträge' }),
	termsUse: () => 'Bei jeder Bereinigung entfernen',
	termsSearch: () => 'Liste durchsuchen',
	termsNoMatch: () => 'Kein Eintrag passt.',
	termsEmpty: () => 'Die Liste ist leer.',
	termsNewValue: () => 'Wert hinzufügen',
	termsEntity: () => 'Was es ist',
	termsEntityUnspecified: () => 'Nicht angegeben',
	termsAdd: () => 'Hinzufügen',
	termsRemoveOne: ({ value }) => `${value} aus der Liste entfernen`,
	termsImport: () => 'Importieren…',
	termsExport: () => 'Exportieren…',
	termsExportWarning: () => 'Ein Export ist eine unverschlüsselte Textdatei: Wer sie lesen kann, liest jeden Eintrag, und die Passphrase schützt sie nicht. Löschen Sie sie, wenn Sie fertig sind.',
	termsExportConfirm: () => 'Unverschlüsselt exportieren',
	termsExportedTitle: () => 'Exportiert, nicht verschlüsselt',
	termsImportedTitle: ({ added, skipped }) => `${plural(L, added, { one: 'Ein Eintrag hinzugefügt', other: '{n} Einträge hinzugefügt' })}, ${plural(L, skipped, { one: 'einer war schon vorhanden', other: '{n} waren schon vorhanden' })}.`,
	termsDeleteSource: ({ file }) => `${file} ist nicht verschlüsselt und enthält noch jeden Eintrag. Löschen Sie die Datei jetzt: FreeDocs tut es nicht für Sie.`,
	termsDismiss: () => 'Erledigt',
	termsFilter: () => 'FreeDocs-Begriffsliste',
	termsRekey: () => 'Passphrase ändern…',
	termsCurrentPassphrase: () => 'Aktuelle Passphrase',
	termsNextPassphrase: () => 'Neue Passphrase',
	termsRekeyConfirm: () => 'Passphrase ändern',
	termsRekeyed: () => 'Passphrase geändert',
	termsImportFilter: () => 'Text oder CSV',
	termsChooseFile: () => 'Begriffsliste wählen',
	termsChooseNew: () => 'Wo die neue Liste gespeichert wird',
	termsChooseImport: () => 'Datei zum Importieren wählen',
	termsChooseExport: () => 'Wohin der unverschlüsselte Export geschrieben wird',
	termsUnlocked: ({ count }) =>
		plural(L, count, { one: 'Begriffsliste entsperrt, ein Eintrag', other: 'Begriffsliste entsperrt, {n} Einträge' }),
	termsLocked: () => 'Begriffsliste gesperrt',
	termsAdded: ({ count }) =>
		plural(L, count, { one: 'Ein Eintrag hinzugefügt', other: '{n} Einträge hinzugefügt' }),
	termsAlreadyThere: () => 'Schon in der Liste',
	termsRemoved: ({ count }) =>
		plural(L, count, { one: 'Ein Eintrag entfernt', other: '{n} Einträge entfernt' }),
	termsImportedAnnounce: ({ count }) =>
		plural(L, count, { one: 'Ein Eintrag importiert. Löschen Sie die Quelldatei.', other: '{n} Einträge importiert. Löschen Sie die Quelldatei.' }),
	termsExportedAnnounce: ({ count }) =>
		plural(L, count, { one: 'Ein Eintrag exportiert, unverschlüsselt', other: '{n} Einträge exportiert, unverschlüsselt' }),
	fromTermList: () => 'Liste',
	foundByTermList: () => 'die Begriffsliste Ihrer Kanzlei',
	termsMatched: ({ matched, loaded }) => `Begriffsliste: ${matched} von ${plural(L, loaded, { one: 'einem Eintrag', other: '{n} Einträgen' })} in diesem Dokument gefunden.`,

	stepRestoreFile: () => 'Dokument und Schlüssel',
	restoreTitle: () => 'Werte zurücksetzen',
	restoreHint: () =>
		'Wähle, was vom Modell zurückkam, und die Schlüsseldatei der Bereinigung, die es erzeugt hat.',
	restoreDocument: () => 'Dokument vom Modell',
	restoreChooseDocument: () => 'Dokument wählen',
	restoreKey: () => 'Schlüsseldatei',
	restoreChooseKey: () => 'Schlüsseldatei wählen',
	restorePassphrase: () => 'Passphrase',
	restoreNeedsDocument: () => 'Wähle das zurückgekommene Dokument.',
	restoreNeedsKey: () => 'Wähle die Schlüsseldatei dieser Bereinigung.',
	restoreNeedsPassphrase: () => 'Gib die Passphrase dieser Schlüsseldatei ein.',
	restoreRun: () => 'Werte zurücksetzen',
	restoring: () => 'Setze die Werte zurück…',
	restoreAgain: () => 'Weiteres zurücksetzen',

	restoreResultTitle: () => 'Was zurückkam',
	restoredSummary: ({ values, occurrences }) =>
		`${values} ${values === 1 ? 'Wert' : 'Werte'} zurückgesetzt, an ` +
		`${occurrences} ${occurrences === 1 ? 'Stelle' : 'Stellen'}`,
	restoreNothingMatched: () =>
		'Kein Platzhalter aus dieser Schlüsseldatei war im Dokument.',
	restoreNotPresentTitle: () => 'Nicht in diesem Dokument',
	restoreNotPresentHint: () =>
		'Diese standen in der Schlüsseldatei und nicht im Rückläufer — meist Text, den das Modell weggelassen hat.',
	restoreUnknownTitle: () => 'Unangetastet',
	restoreUnknownHint: () =>
		'Diese sehen wie Platzhalter aus und diese Schlüsseldatei kennt sie nicht. ' +
		'Zu raten, welcher Wert gemeint war, würde die falschen Daten ins Dokument schreiben — also blieben sie stehen.',
	restoreProblemsTitle: () => 'Nicht zurückgekommen',
	restoreVerified: () => 'Das Dokument wurde erneut geöffnet, und jeder Wert ist angekommen.',
	restoreIncomplete: ({ count }) =>
		`${count} ${count === 1 ? 'Wert ist' : 'Werte sind'} nicht zurückgekommen. ` +
		'Das Dokument wurde trotzdem geschrieben — was fehlt, ist darin sichtbar.',
	restoreCaveatsTitle: () => 'Was das Zurücksetzen nicht leistet',

	announceRestored: ({ count }) =>
		`Fertig. ${count} ${count === 1 ? 'Wert' : 'Werte'} zurückgesetzt.`,
	announceRestoredWithProblems: ({ count }) =>
		`Fertig, aber ${count} ${count === 1 ? 'Wert ist' : 'Werte sind'} nicht zurückgekommen.`,

	entity: {
		PERSON: () => 'Person',
		ORGANISATION: () => 'Firma',
		LOCATION: () => 'Ort',
		ADDRESS: () => 'Adresse',
		EMAIL: () => 'E-Mail',
		PHONE: () => 'Telefon',
		IBAN: () => 'IBAN',
		CREDIT_CARD: () => 'Karte',
		NATIONAL_ID: () => 'Nationale Kennnummer',
		TAX_ID: () => 'Steuernummer',
		VAT_ID: () => 'USt-Nummer',
		COMPANY_ID: () => 'Firmennummer',
		IP_ADDRESS: () => 'IP-Adresse',
		MAC_ADDRESS: () => 'MAC-Adresse',
		URL: () => 'Webadresse',
		DATE: () => 'Datum',
		JOB_TITLE: () => 'Rolle',
		AGE: () => 'Alter',
		POSTCODE: () => 'PLZ',
		OTHER: () => 'Von dir'
	},

	action: {
		redact: () => 'wird entfernt',
		surrogate: () => 'wird ersetzt',
		report: () => 'markiert, nicht entfernt',
		keep: () => 'bleibt unverändert'
	}
} satisfies Messages;
