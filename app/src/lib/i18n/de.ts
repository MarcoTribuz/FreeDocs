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

	/*
	 * Die Typen bleiben allgemein: die Engine setzt das Land auf den Fund und nie
	 * in den Typ, weil ein Stamm für zwölf Länder steht und ein nationaler Name
	 * für elf falsch wäre. Also "USt-Nummer", nicht "Umsatzsteuer-Identnummer".
	 */
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
