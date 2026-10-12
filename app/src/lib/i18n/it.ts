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
	modelBundled: () => 'modello incluso',
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

	firstRunEyebrow: () => 'Primo avvio',
	modelAskTitle: () => 'Un solo download, poi FreeDocs lavora offline',
	modelAskLead: () =>
		'Per riconoscere nomi, aziende e indirizzi, FreeDocs usa un modello linguistico che gira su questo computer. Si scarica una volta sola.',
	modelFactSize: () => '1,2 GB, da Hugging Face, dove il modello è pubblicato',
	modelFactPrivate: () =>
		'I tuoi documenti non lasciano mai questo computer. Entra solo il modello.',
	modelFactOffline: () => 'Dopo, FreeDocs non ha più bisogno di internet.',
	modelDownload: () => 'Scarica il modello (1,2 GB)',
	modelNotNow: () => 'Non ora',
	modelWithout: () =>
		"Senza il modello FreeDocs trova comunque IBAN, codici fiscali e numeri d'identità, carte, e-mail e telefoni, ma non nomi, aziende o indirizzi.",
	modelDownloadingTitle: () => 'Sto scaricando il modello',
	modelBytes: ({ done, of }) => `${done} di ${of}`,
	modelEtaMinutes: ({ minutes }) => `mancano circa ${minutes} min`,
	modelEtaUnderMinute: () => 'manca meno di un minuto',
	modelKeepOpen: () =>
		'Lascia aperta questa finestra. Nel frattempo nessun file viene letto o inviato.',
	modelSampleTitle: () => 'Cosa farà',
	modelBefore: () => 'Prima',
	modelAfter: () => 'Dopo',
	modelSampleBefore: () => 'Contratto tra Mario Rossi e Acme SA, Via Cantonale 12, 6900 Lugano.',
	modelSampleAfter: ({ person, organisation, address }) =>
		`Contratto tra ${person} e ${organisation}, ${address}.`,
	modelPreparingTitle: () => 'Preparo il modello',
	modelPreparingLead: () => 'Lo controllo e lo carico. Qualche secondo.',
	modelFailedTitle: () => 'Il download si è interrotto',
	modelFailedLead: () =>
		'Su questo computer non è cambiato nulla. Controlla la connessione e riprova.',
	modelFailedProxy: () =>
		'In una rete aziendale un proxy o un firewall può bloccare huggingface.co. Il reparto IT può sbloccarlo.',
	modelRetry: () => 'Riprova',
	modelReadyTitle: () => 'Pronto. Da ora FreeDocs lavora offline.',
	modelReadyLead: () => 'Nomi, aziende e indirizzi verranno trovati già dal primo documento.',
	modelChooseDocument: () => 'Scegli un documento',
	modelDeferredTitle: () => 'Nomi e indirizzi non vengono cercati',
	modelDeferredLead: () => 'Il modello che li trova non è ancora stato scaricato.',
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
	hiddenPendingTitle: () => 'Contenuto nascosto che verrà rimosso',
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

	stepsLabel: () => 'Passi',
	stepFile: () => 'File',
	stepReview: () => 'Verifica',
	stepResult: () => 'Risultato',
	stepAnnounce: ({ position, total, name }) => `Passo ${position} di ${total}: ${name}`,
	stepReviewLocked: () => 'Prima aggiungi un documento.',
	stepResultLocked: () => 'Non è ancora stato ripulito nulla.',
	filesTitle: () => 'Documenti',
	removeFile: ({ file }) => `Togli ${file}`,
	clearFiles: () => 'togli tutti',
	back: () => 'Indietro',
	continueToReview: () => 'Verifica cosa è stato trovato',

	reviewOf: ({ file }) => `Verifica di ${file}`,
	findingCount: ({ count }) =>
		plural(L, count, { one: '{n} valore trovato', other: '{n} valori trovati' }),
	documentLabel: ({ file }) => `Il testo estratto da ${file}, con ogni valore evidenziato`,
	markName: ({ entity, action, kept }) => (kept ? `${entity}, tenuto` : `${entity}, ${action}`),
	viewDocument: () => 'Documento',
	viewList: () => 'Elenco',
	onlyFindings: () => 'Solo ciò che è stato trovato',
	wholeDocument: () => 'Tutto il documento',
	skippedParagraphs: ({ count }) =>
		plural(L, count, {
			one: '{n} paragrafo senza nulla — mostra',
			other: '{n} paragrafi senza nulla — mostra'
		}),
	previewTruncated: ({ shown, total }) =>
		`Mostro i primi ${new Intl.NumberFormat(L).format(shown)} caratteri su ` +
		`${new Intl.NumberFormat(L).format(total)}. Tutto ciò che è stato trovato oltre quel ` +
		'punto è comunque elencato, e comunque rimosso.',
	noPreview: () => 'Questo documento non ha testo da mostrare.',
	keyboardHelp: () =>
		'Le frecce o j e k spostano tra i valori. x tiene o non tiene quello selezionato. ' +
		'a aggiunge un valore che i detector hanno mancato. f mostra o nasconde il testo intatto.',
	filterByType: () => 'Tipo',
	allTypes: () => 'ogni tipo',
	searchValues: () => 'Cerca nei valori',
	nothingForThisFilter: () => 'Nessun valore corrisponde a questo filtro.',

	detailNothingSelected: () => 'Niente selezionato',
	detailNothingSelectedHint: () =>
		'Scegli un valore evidenziato per vedere chi lo ha trovato e quanto è sicuro.',
	detailType: () => 'Tipo',
	detailConfidence: () => 'Confidenza',
	detailFound: () => 'Trovato da',
	detailWhere: () => 'Dove',
	detailAction: () => 'Cosa succede',
	detailKept: () => 'Hai deciso di tenere questa occorrenza.',
	foundByChecksum: () => 'un checksum lo ha confermato',
	foundByModel: () => 'il modello lo ha riconosciuto',
	foundByYou: () => "l'hai chiesto tu",
	foundBy: ({ detector }) => `regola: ${detector}`,
	keepThisOccurrence: () => 'Tieni questa occorrenza',
	stopKeeping: () => 'Rimuovila comunque',
	keepEveryOne: ({ entity }) => `Tieni ogni ${entity} nel documento`,

	advancedTitle: () => 'Avanzate',
	advancedHint: () =>
		'Le impostazioni predefinite cercano tutto, in ogni paese. Ogni controllo qui può solo ' +
		'restringere la ricerca, e una ricerca restretta lo dichiara nel risultato.',
	detectorSpec: () => 'Livelli di rilevamento',
	detectorSpecHint: () =>
		'Quali livelli girano. Meno livelli trovano meno; il motore dichiara cosa copre ognuno.',

	verificationPassed: () => 'Verificato',
	verificationPassedHint: ({ checked }) =>
		plural(L, checked, {
			one: 'Il risultato è stato riaperto e cercato: {n} valore non c’è più.',
			other: 'Il risultato è stato riaperto e cercato: tutti i {n} valori non ci sono più.'
		}),
	openFolder: () => 'Apri la cartella',
	scrubAgain: () => 'Ricomincia',

	diagnosticsRecheck: () => 'Controlla di nuovo',
	announceRechecked: () => 'Controllato di nuovo.',
	copyFix: () => 'Copia',
	copied: () => 'Copiato',
	copyUnavailable: () => 'Seleziona e copia',
	locateTesseract: () => 'Individua Tesseract…',
	locateTesseractHint: () =>
		'Se Tesseract è installato in una posizione insolita, indicala a questa build. Il motore verifica il file prima di usarlo.',
	chooseTesseract: () => 'Scegli l’eseguibile Tesseract',
	tesseractAccepted: () => 'Tesseract accettato.',
	tesseractRefusal: {
		not_executable: () => 'Quel file non può essere eseguito. Scegli il programma Tesseract vero e proprio.',
		wrong_name: () => 'Quel file deve chiamarsi «tesseract», perché è il nome che cerca il lettore PDF.'
	},
	tesseractRefusalOther: () => 'Il motore ha rifiutato quel file.',
	engineBuild: () => 'Motore',
	engineSource: {
		override: () => 'scelto con FREEDOCS_ENGINE',
		bundled: () => 'incluso nell’app',
		checkout: () => 'dal codice sorgente'
	},
	engineBuiltOn: (a) => `compilato ${a.when}`,
	engineBuildDateUnknown: () => 'data di compilazione sconosciuta',
	diagnosticsTitle: () => 'Cosa può fare questa macchina',
	diagnosticsOk: () => 'Tutto ciò che serve a questa build è presente.',
	diagnosticsFix: () => 'Rimedio',
	diagnosticsDegraded: () => 'trova meno',
	diagnosticsBroken: () => 'manca',
	countryModelOnly: () => 'solo modello',
	rulesSilenced: ({ count }) =>
		plural(L, count, {
			one: '{n} regola non trova nulla a questa soglia senza una parola chiave vicina.',
			other: '{n} regole non trovano nulla a questa soglia senza una parola chiave vicina.'
		}),
	placeholderExample: ({ example }) => `scritto come ${example}`,

	stage: {
		router: () => 'scelgo il lettore',
		extract: () => 'leggo il documento',
		detect: () => 'cerco i valori',
		policy: () => 'decido',
		'write-back': () => 'scrivo la copia',
		verify: () => 'cerco nella copia',
		match: () => 'cerco i segnaposto',
		review: () => 'seconda opinione'
	},
	stageOf: ({ name, index, count }) => `${name} — passo ${index} di ${count}`,
	stagePages: ({ done, of }) => `pagina ${done} di ${of}`,

	/*
	 * I tipi restano generici anche qui: il motore mette il paese sul finding e
	 * mai nel tipo, perché uno stem sta per dodici paesi e un nome nazionale
	 * sarebbe sbagliato su undici. Quindi "Numero IVA", non "Partita IVA".
	 */
	// ---- il percorso inverso ------------------------------------------------
	modeLabel: () => 'Cosa fare',
	modeScrub: () => 'Rimuovere',
	modeRestore: () => 'Rimettere',
	modeAnnounce: ({ name }) => `Passato a ${name}`,

	keyFileTitle: () => 'File chiave',
	keyFileHint: () =>
		'Scrive un file cifrato che permette di rimettere i valori rimossi in ciò ' +
		'che il modello restituisce. Senza, questa pulizia non è annullabile da nessuno.',
	keyFileEnable: () => 'Scrivi anche un file chiave',
	keyFileWhere: () => 'Dove metterlo',
	keyFileChooseWhere: () => 'Scegli una cartella',
	keyFilePassphrase: () => 'Passphrase',
	keyFileConfirm: () => 'Ripeti la passphrase',
	keyFileUnavailable: () => 'Questa build non può scrivere un file chiave.',
	keyFileNeedsDirectory: () => 'Scegli una cartella fuori da quella di destinazione.',
	keyFileNeedsPassphrase: ({ min }) => `Almeno ${min} caratteri.`,
	keyFileMismatch: () => 'Le due passphrase non corrispondono.',
	keyFileDanger: () =>
		'Questo file è riservato quanto il documento originale. Tienilo lontano ' +
		'dalla copia pulita, e non spedire mai i due insieme.',
	keyFileWritten: () => 'File chiave',
	chooseKeyDirectory: () => 'Dove mettere il file chiave',
	chooseKeyFile: () => 'Scegli un file chiave',
	keyFileFilter: () => 'File chiave FreeDocs',

	// ---- text mode ----------------------------------------------------------
	modeText: () => 'Incolla testo',
	stepText: () => 'Testo',
	textTitle: () => 'Incolla il testo',
	textHint: () => 'Incolla ciò che vuoi mandare a un modello. Viene ripulito qui e non finisce mai su disco; poi incolla la risposta per rimettere i valori.',
	textLabel: () => 'Testo',
	textPlaceholder: () => 'Incolla qui…',
	textCount: ({ count }) =>
		plural(L, count, { one: 'Un carattere', other: '{n} caratteri' }),
	textTooLong: ({ max }) => `Più lungo dei ${max.toLocaleString(L)} caratteri ammessi. Salvalo in un file e ripulisci quello.`,
	textInspect: () => 'Cerca i valori',
	textReviewTitle: () => 'Controlla il testo incollato',
	textScrub: () => 'Ripulisci il testo',
	textKeepTitle: () => 'Dopo',
	textKeepNone: () => 'Non tenere un modo per tornare indietro',
	textKeepNoneHint: () => 'Irreversibile, come ogni pulizia. Una risposta non si potrà ripristinare.',
	textKeepMemory: () => 'Tieni finché chiudo FreeDocs',
	textKeepMemoryHint: () => 'Ripristina qui la risposta, senza scrivere nulla.',
	textKeepMemoryWarning: () => 'Il motore tiene ciò che è stato rimosso, in memoria, finché non inizi un nuovo testo, cambi modalità o chiudi FreeDocs. Niente viene scritto su disco.',
	textKeepFile: () => 'Salva un key file',
	textKeepFileHint: () => 'Cifrato, per una risposta che arriva un altro giorno.',
	textKeyNeedsDirectory: () => 'Scegli una cartella per il key file.',
	textResultTitle: () => 'Testo ripulito',
	textScrubbedTitle: () => 'Da mandare',
	textNew: () => 'Nuovo testo',
	textCopy: () => 'Copia',
	textCopied: () => 'Copiato',
	textCopyFailed: () => 'Non copiato. Seleziona il testo e copialo a mano.',
	textHeld: () => 'Il modo per tornare indietro è tenuto finché non inizi un nuovo testo, cambi modalità o chiudi FreeDocs.',
	textNotKept: () => 'Nessun modo per tornare indietro: questo testo non si può ripristinare.',
	textNothingProduced: () => 'Nessun testo ripulito è stato prodotto.',
	textReplyTitle: () => 'La risposta',
	textReplyLabel: () => 'Cosa ha risposto il modello',
	textReplyPlaceholder: () => 'Incolla qui la risposta…',
	textRestore: () => 'Rimetti i valori',
	textRestoredTitle: () => 'Risposta ripristinata',
	announceTextScrubbed: ({ count }) =>
		plural(L, count, { one: 'Testo ripulito, un valore rimosso', other: 'Testo ripulito, {n} valori rimossi' }),

	// ---- the term list ------------------------------------------------------
	termsTitle: () => 'Elenco termini',
	termsHint: () => 'Un elenco cifrato di nomi e codici che il tuo studio rimuove sempre: clienti, pratiche, progetti. Si sblocca una volta per sessione; le voci restano nel motore.',
	termsUnavailable: () => 'Questa build non può aprire un elenco termini.',
	termsOpen: () => 'Apri…',
	termsNew: () => 'Nuovo…',
	termsCancel: () => 'Annulla',
	termsPassphrase: () => 'Passphrase',
	termsConfirm: () => 'Ripeti la passphrase',
	termsUnlock: () => 'Sblocca',
	termsCreate: () => 'Crea l\'elenco',
	termsLock: () => 'Blocca',
	termsForget: () => 'Chiudi',
	termsNeedsPassphrase: ({ min }) => `Almeno ${min} caratteri.`,
	termsMismatch: () => 'Le due passphrase non coincidono.',
	termsNewWarning: () => 'Senza la passphrase nessuno può aprire questo elenco, nemmeno FreeDocs. Conservala dove lo studio conserva le altre password.',
	termsCount: ({ count }) =>
		plural(L, count, { one: 'Una voce', other: '{n} voci' }),
	termsUse: () => 'Rimuovili a ogni pulizia',
	termsSearch: () => 'Cerca nell\'elenco',
	termsNoMatch: () => 'Nessuna voce corrisponde.',
	termsEmpty: () => 'L\'elenco è vuoto.',
	termsNewValue: () => 'Aggiungi un valore',
	termsEntity: () => 'Che cos\'è',
	termsEntityUnspecified: () => 'Non specificato',
	termsAdd: () => 'Aggiungi',
	termsRemoveOne: ({ value }) => `Togli ${value} dall\'elenco`,
	termsImport: () => 'Importa…',
	termsExport: () => 'Esporta…',
	termsExportWarning: () => 'L\'esportazione è un file di testo in chiaro: chiunque possa leggerlo legge ogni voce, e la passphrase non lo protegge. Eliminalo quando hai finito.',
	termsExportConfirm: () => 'Esporta in chiaro',
	termsExportedTitle: () => 'Esportato, non cifrato',
	termsImportedTitle: ({ added, skipped }) => `${plural(L, added, { one: 'Una voce aggiunta', other: '{n} voci aggiunte' })}, ${plural(L, skipped, { one: 'una già presente', other: '{n} già presenti' })}.`,
	termsDeleteSource: ({ file }) => `${file} non è cifrato e contiene ancora tutte le voci. Eliminalo adesso: FreeDocs non lo fa al posto tuo.`,
	termsDismiss: () => 'Fatto',
	termsFilter: () => 'Elenco termini FreeDocs',
	termsRekey: () => 'Cambia passphrase…',
	termsCurrentPassphrase: () => 'Passphrase attuale',
	termsNextPassphrase: () => 'Nuova passphrase',
	termsRekeyConfirm: () => 'Cambia passphrase',
	termsRekeyed: () => 'Passphrase cambiata',
	termsImportFilter: () => 'Testo o CSV',
	termsChooseFile: () => 'Scegli un elenco termini',
	termsChooseNew: () => 'Dove salvare il nuovo elenco',
	termsChooseImport: () => 'Scegli un file da importare',
	termsChooseExport: () => 'Dove scrivere l\'esportazione in chiaro',
	termsUnlocked: ({ count }) =>
		plural(L, count, { one: 'Elenco sbloccato, una voce', other: 'Elenco sbloccato, {n} voci' }),
	termsLocked: () => 'Elenco bloccato',
	termsAdded: ({ count }) =>
		plural(L, count, { one: 'Una voce aggiunta', other: '{n} voci aggiunte' }),
	termsAlreadyThere: () => 'Già nell\'elenco',
	termsRemoved: ({ count }) =>
		plural(L, count, { one: 'Una voce tolta', other: '{n} voci tolte' }),
	termsImportedAnnounce: ({ count }) =>
		plural(L, count, { one: 'Una voce importata. Elimina il file di origine.', other: '{n} voci importate. Elimina il file di origine.' }),
	termsExportedAnnounce: ({ count }) =>
		plural(L, count, { one: 'Una voce esportata, non cifrata', other: '{n} voci esportate, non cifrate' }),
	fromTermList: () => 'elenco',
	foundByTermList: () => 'l\'elenco termini dello studio',
	termsMatched: ({ matched, loaded }) => `Elenco termini: ${matched} su ${plural(L, loaded, { one: 'una voce', other: '{n} voci' })} trovate in questo documento.`,

	stepRestoreFile: () => 'Documento e chiave',
	restoreTitle: () => 'Rimetti i valori',
	restoreHint: () =>
		'Scegli ciò che è tornato dal modello, e il file chiave della pulizia che lo ha prodotto.',
	restoreDocument: () => 'Documento tornato dal modello',
	restoreChooseDocument: () => 'Scegli un documento',
	restoreKey: () => 'File chiave',
	restoreChooseKey: () => 'Scegli un file chiave',
	restorePassphrase: () => 'Passphrase',
	restoreNeedsDocument: () => 'Scegli il documento che è tornato.',
	restoreNeedsKey: () => 'Scegli il file chiave di quella pulizia.',
	restoreNeedsPassphrase: () => 'Scrivi la passphrase di quel file chiave.',
	restoreRun: () => 'Rimetti i valori',
	restoring: () => 'Rimetto i valori…',
	restoreAgain: () => 'Rimetti in un altro',

	restoreResultTitle: () => 'Cosa è tornato',
	restoredSummary: ({ values, occurrences }) =>
		`${values} ${values === 1 ? 'valore rimesso' : 'valori rimessi'}, in ` +
		`${occurrences} ${occurrences === 1 ? 'punto' : 'punti'}`,
	restoreNothingMatched: () =>
		'Nessun segnaposto di questo file chiave era nel documento.',
	restoreNotPresentTitle: () => 'Non in questo documento',
	restoreNotPresentHint: () =>
		'Erano nel file chiave e non in ciò che è tornato: di solito testo che il modello ha eliminato.',
	restoreUnknownTitle: () => 'Lasciati stare',
	restoreUnknownHint: () =>
		'Sembrano segnaposto e questo file chiave non li conosce. Indovinare quale ' +
		'valore intendessero metterebbe i dati sbagliati nel documento, quindi sono stati lasciati così.',
	restoreProblemsTitle: () => 'Non sono tornati',
	restoreVerified: () => 'Il documento è stato riaperto, e ogni valore è arrivato.',
	restoreIncomplete: ({ count }) =>
		`${count} ${count === 1 ? 'valore non è' : 'valori non sono'} tornato. ` +
		'Il documento è stato scritto comunque: ciò che manca è visibile dentro.',
	restoreCaveatsTitle: () => 'Cosa rimettere i valori non fa',

	announceRestored: ({ count }) =>
		`Finito. ${count} ${count === 1 ? 'valore rimesso' : 'valori rimessi'}.`,
	announceRestoredWithProblems: ({ count }) =>
		`Finito, ma ${count} ${count === 1 ? 'valore non è' : 'valori non sono'} tornato.`,

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
