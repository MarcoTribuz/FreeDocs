import type { Messages } from './messages';
import { plural } from './plural';

const L = 'it';

export const it = {
	appName: () => 'FreeDocs',
	tagline: () =>
		'Rimuove i dati riservati da un documento, così può essere consegnato a un servizio di AI ' +
		'senza consegnare i dati. Tutto gira su questa macchina.',
	skipToContent: () => 'Vai al contenuto',
	appearance: () => 'Aspetto',
	appearanceAuto: () => 'Auto',
	appearanceLight: () => 'Chiaro',
	appearanceDark: () => 'Scuro',
	language: () => 'Lingua',

	capabilitiesLabel: () => 'Cosa può fare questa build',
	engineVersion: ({ version }) => `motore ${version}`,
	ocrAvailable: () => 'OCR disponibile',
	ocrMissing: () => 'OCR non installato',
	nothingLeaves: () => 'niente lascia questa macchina',
	ocrReasonTitle: () => 'Le pagine scansionate non possono essere lette',
	limitationsTitle: () => 'Cosa questa build non sta rilevando',
	engineNotStarted: () => 'Il motore non è partito',
	quotedFromEngine: () => 'Citato dal motore, che riporta in inglese.',

	reviewTitle: () => 'Seconda opinione (Ollama)',
	reviewHint: () =>
		'Un modello locale legge il testo già ripulito e dice cosa ancora lo preoccupa. È un ' +
		'parere: non cambia nulla nel risultato.',
	reviewHost: () => 'Host',
	reviewFindModels: () => 'Cerca i modelli',
	reviewLooking: () => 'Cerco…',
	reviewModel: () => 'Modello',
	reviewNone: () => 'nessuna revisione',
	reviewNoModelsAt: ({ host }) =>
		`Nessun modello su ${host}. Ollama è in esecuzione lì, e è stato scaricato qualcosa?`,
	reviewModelsAvailable: ({ count }) =>
		plural(L, count, { one: '{n} modello disponibile.', other: '{n} modelli disponibili.' }),
	reviewBadge: ({ model }) => `revisione: ${model}`,
	reviewDidNotRun: () => 'non è stata eseguita',
	reviewPartial: () => 'solo la prima parte del documento',
	reviewRan: () => 'eseguita',

	dropTitle: () => 'Trascina qui i documenti',
	dropHint: () => 'oppure clicca per scegliere.',
	reading: () => 'Leggo…',

	minConfidence: () => 'Confidenza minima',
	confidenceBand: ({ value }) => {
		if (value <= 0) return 'tutto, comprese le regole più deboli';
		if (value < 0.45) return 'sotto ogni regola: non si scarta niente';
		if (value < 0.5) return 'regole deboli incluse';
		if (value < 0.55) return 'le regole deboli servono una parola chiave vicina';
		if (value < 0.9) return 'solo le regole con checksum forte e il modello';
		return 'quasi nulla oltre a un checksum confermato';
	},
	placeholderLanguage: () => 'Lingua dei segnaposto',
	placeholderLanguageHint: () =>
		'Le parole scritte nel risultato al posto di ciò che è stato rimosso. Cambiano solo le ' +
		'parole: nulla di ciò che viene rimosso dipende da questa scelta.',
	countriesTitle: () => 'Paesi da cercare',
	countriesHint: () =>
		'Tutti, se non dici altrimenti. Restringere alza la precisione e può nascondere un ' +
		'identificatore di un paese che non ti aspettavi nel file.',
	keepTitle: () => 'Lascia invariato',
	flagOnly: () => 'solo segnalato',
	flagOnlyHint: () => 'Segnalato per la revisione, mai rimosso, che questo sia attivo o no.',

	fileSummary: ({ format, characters }) =>
		`${format} · ${new Intl.NumberFormat(L).format(characters)} caratteri`,
	nothingMatched: () => 'Nessuna corrispondenza.',
	showValues: ({ count }) =>
		plural(L, count, { one: 'Mostra il valore trovato', other: 'Mostra i {n} valori' }),
	tableCaption: ({ file }) => `Ogni valore trovato in ${file}, e cosa gli succederà`,
	columnWhere: () => 'Dove',
	columnType: () => 'Tipo',
	columnValue: () => 'Valore',
	columnAction: () => 'Azione',
	columnDecision: () => 'Decisione',
	mine: () => 'tuo',
	stopRemoving: ({ value }) => `Non rimuovere più ${value}`,
	stopRemovingShort: () => 'non rimuovere',
	keepThisOne: () => 'tieni questa',
	keepThisOneFor: ({ value }) => `Tieni questa occorrenza di ${value}`,
	keepThisOneWhy: () =>
		'Lascia in pace questa sola occorrenza. Ogni altra occorrenza dello stesso valore viene ' +
		'rimossa comunque.',
	addValueLabel: () => 'Rimuovi anche questo valore',
	addValuePlaceholder: () => 'un nome, un numero, qualunque cosa i detector abbiano mancato',
	add: () => 'Aggiungi',
	keptOnPurpose: ({ count }) =>
		plural(L, count, {
			one: '{n} occorrenza tenuta di proposito.',
			other: '{n} occorrenze tenute di proposito.'
		}),
	undoAll: () => 'annulla tutto',

	scrub: ({ files }) =>
		plural(L, files, { one: 'Ripulisci il file', other: 'Ripulisci {n} file' }),
	scrubbing: () => 'Ripulisco…',
	chooseOutputDirectory: () => 'Dove scrivere le copie ripulite',
	progressLabel: () => 'Ripulitura',
	progressFile: ({ file, index, total }) => `${file} — file ${index} di ${total}`,

	resultTitle: () => 'Risultato',
	removedAndFlagged: ({ removed, flagged }) => {
		const gone = plural(L, removed, {
			one: '{n} valore rimosso',
			other: '{n} valori rimossi'
		});
		if (flagged === 0) return `${gone}.`;
		const seen = plural(L, flagged, {
			one: '{n} segnalato per la revisione',
			other: '{n} segnalati per la revisione'
		});
		return `${gone}, ${seen}.`;
	},
	hiddenRemovedTitle: () => 'Contenuto nascosto rimosso',
	nothingWritten: () => 'Non è stato scritto nulla.',

	announceValuesFound: ({ file, count }) =>
		plural(L, count, {
			one: `${file}: un valore trovato`,
			other: `${file}: {n} valori trovati`
		}),
	announceFinished: ({ files }) =>
		plural(L, files, {
			one: 'Finito. Un file scritto.',
			other: 'Finito. {n} file scritti.'
		}),
	announceFinishedWithFailures: ({ failed, files }) =>
		`Finito, ma ${failed} file su ${files} non sono stati scritti.`,

	errorUnsupportedFormat: ({ message }) => `Questo formato non è supportato. ${message}`,
	errorMissingComponent: ({ message }) => `Manca un componente. ${message}`,
	errorInFile: ({ file, message }) => `${file}: ${message}`,

	/*
	 * I tipi restano generici anche qui: il motore mette il paese sul finding e
	 * mai nel tipo, perché uno stem sta per dodici paesi e un nome nazionale
	 * sarebbe sbagliato su undici. Quindi "Numero IVA", non "Partita IVA".
	 */
	entity: {
		PERSON: () => 'Persona',
		ORGANISATION: () => 'Azienda',
		LOCATION: () => 'Luogo',
		ADDRESS: () => 'Indirizzo',
		EMAIL: () => 'Email',
		PHONE: () => 'Telefono',
		IBAN: () => 'IBAN',
		CREDIT_CARD: () => 'Carta',
		NATIONAL_ID: () => 'Numero nazionale',
		TAX_ID: () => 'Numero fiscale',
		VAT_ID: () => 'Numero IVA',
		COMPANY_ID: () => "Numero d'impresa",
		IP_ADDRESS: () => 'Indirizzo IP',
		MAC_ADDRESS: () => 'Indirizzo MAC',
		URL: () => 'Indirizzo web',
		DATE: () => 'Data',
		JOB_TITLE: () => 'Ruolo',
		AGE: () => 'Età',
		POSTCODE: () => 'CAP',
		OTHER: () => 'Tuo'
	},

	action: {
		redact: () => 'verrà rimosso',
		surrogate: () => 'verrà sostituito',
		report: () => 'segnalato, non rimosso',
		keep: () => 'lasciato invariato'
	}
} satisfies Messages;
