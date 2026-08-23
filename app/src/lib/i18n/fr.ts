import type { Messages } from './messages';
import { plural } from './plural';

const L = 'fr';

/*
 * Note sur les pluriels : en français, `one` couvre zéro *et* un. Chaque forme
 * `one` ci-dessous doit donc se lire correctement pour « 0 » — « 0 valeur
 * trouvée », pas « 0 valeurs trouvées ». C'est exactement la règle que le
 * bricolage « (s) » ne pouvait pas exprimer.
 */
export const fr = {
	appName: () => 'FreeDocs',
	tagline: () =>
		"Supprime les données confidentielles d'un document, pour qu'il puisse être confié à un " +
		'service d\'IA sans lui confier les données. Tout fonctionne sur cette machine.',
	skipToContent: () => 'Aller au contenu',
	appearance: () => 'Apparence',
	appearanceAuto: () => 'Auto',
	appearanceLight: () => 'Clair',
	appearanceDark: () => 'Sombre',
	language: () => 'Langue',

	capabilitiesLabel: () => 'Ce que cette version sait faire',
	engineVersion: ({ version }) => `moteur ${version}`,
	ocrAvailable: () => 'OCR disponible',
	ocrMissing: () => 'OCR non installé',
	nothingLeaves: () => 'rien ne quitte cette machine',
	modelBundled: () => 'modèle inclus',
	ocrReasonTitle: () => 'Les pages numérisées ne peuvent pas être lues',
	limitationsTitle: () => 'Ce que cette version ne détecte pas',
	engineNotStarted: () => "Le moteur n'a pas démarré",
	quotedFromEngine: () => 'Cité du moteur, qui rend compte en anglais.',

	reviewTitle: () => 'Deuxième avis (Ollama)',
	reviewHint: () =>
		"Un modèle local lit le texte déjà nettoyé et dit ce qui l'inquiète encore. C'est un avis : " +
		'il ne change rien au résultat.',
	reviewHost: () => 'Hôte',
	reviewFindModels: () => 'Chercher les modèles',
	reviewLooking: () => 'Recherche…',
	reviewModel: () => 'Modèle',
	reviewNone: () => 'aucune relecture',
	reviewNoModelsAt: ({ host }) =>
		`Aucun modèle sur ${host}. Ollama tourne-t-il là, et quelque chose a-t-il été téléchargé ?`,
	reviewModelsAvailable: ({ count }) =>
		plural(L, count, { one: '{n} modèle disponible.', other: '{n} modèles disponibles.' }),
	reviewBadge: ({ model }) => `relecture : ${model}`,
	reviewDidNotRun: () => "n'a pas eu lieu",
	reviewPartial: () => 'seulement le début du document',
	reviewRan: () => 'effectuée',

	dropTitle: () => 'Déposez les documents ici',
	dropHint: () => 'ou cliquez pour les choisir.',
	reading: () => 'Lecture…',

	minConfidence: () => 'Confiance minimale',
	confidenceBand: ({ value }) => {
		if (value <= 0) return 'tout, y compris les règles les plus faibles';
		if (value < 0.45) return 'sous chaque règle : rien n\'est filtré';
		if (value < 0.5) return 'règles faibles incluses';
		if (value < 0.55) return 'les règles faibles exigent un mot-clé à proximité';
		if (value < 0.9) return 'seules les règles à somme de contrôle forte, et le modèle';
		return 'presque rien en dehors d\'une somme de contrôle confirmée';
	},
	placeholderLanguage: () => 'Langue des marqueurs',
	placeholderLanguageHint: () =>
		'Les mots écrits dans le résultat à la place de ce qui a été supprimé. Seuls les mots ' +
		'changent ; ce qui est supprimé ne dépend pas de ce choix.',
	countriesTitle: () => 'Pays à chercher',
	countriesHint: () =>
		'Tous, sauf indication contraire. Restreindre augmente la précision et peut masquer un ' +
		"identifiant d'un pays que vous n'attendiez pas dans le fichier.",
	keepTitle: () => 'Laisser intact',
	flagOnly: () => 'signalé seulement',
	flagOnlyHint: () => 'Signalé pour relecture, jamais supprimé, que ceci soit actif ou non.',

	fileSummary: ({ format, characters }) =>
		`${format} · ${new Intl.NumberFormat(L).format(characters)} caractères`,
	nothingMatched: () => 'Aucune correspondance.',
	showValues: ({ count }) =>
		plural(L, count, { one: 'Afficher la valeur', other: 'Afficher les {n} valeurs' }),
	tableCaption: ({ file }) => `Chaque valeur trouvée dans ${file}, et ce qui lui arrivera`,
	columnWhere: () => 'Où',
	columnType: () => 'Type',
	columnValue: () => 'Valeur',
	columnAction: () => 'Action',
	columnDecision: () => 'Décision',
	mine: () => 'de vous',
	stopRemoving: ({ value }) => `Ne plus supprimer ${value}`,
	stopRemovingShort: () => 'ne pas supprimer',
	keepThisOne: () => 'garder celle-ci',
	keepThisOneFor: ({ value }) => `Garder cette occurrence de ${value}`,
	keepThisOneWhy: () =>
		'Laisse cette seule occurrence. Toutes les autres occurrences de la même valeur sont ' +
		'supprimées quand même.',
	addValueLabel: () => 'Supprimer aussi cette valeur',
	addValuePlaceholder: () => 'un nom, un numéro, ce que les détecteurs ont manqué',
	add: () => 'Ajouter',
	keptOnPurpose: ({ count }) =>
		plural(L, count, {
			one: '{n} occurrence gardée volontairement.',
			other: '{n} occurrences gardées volontairement.'
		}),
	undoAll: () => 'tout annuler',

	scrub: ({ files }) =>
		plural(L, files, { one: 'Nettoyer le fichier', other: 'Nettoyer {n} fichiers' }),
	scrubbing: () => 'Nettoyage…',
	chooseOutputDirectory: () => 'Où écrire les copies nettoyées',
	progressLabel: () => 'Nettoyage',
	progressFile: ({ file, index, total }) => `${file} — fichier ${index} sur ${total}`,

	resultTitle: () => 'Résultat',
	removedAndFlagged: ({ removed, flagged }) => {
		const gone = plural(L, removed, {
			one: '{n} valeur supprimée',
			other: '{n} valeurs supprimées'
		});
		if (flagged === 0) return `${gone}.`;
		const seen = plural(L, flagged, {
			one: '{n} signalée pour relecture',
			other: '{n} signalées pour relecture'
		});
		return `${gone}, ${seen}.`;
	},
	hiddenRemovedTitle: () => 'Contenu caché supprimé',
	nothingWritten: () => "Rien n'a été écrit.",

	announceValuesFound: ({ file, count }) =>
		plural(L, count, {
			one: `${file} : {n} valeur trouvée`,
			other: `${file} : {n} valeurs trouvées`
		}),
	announceFinished: ({ files }) =>
		plural(L, files, {
			one: 'Terminé. {n} fichier écrit.',
			other: 'Terminé. {n} fichiers écrits.'
		}),
	announceFinishedWithFailures: ({ failed, files }) =>
		`Terminé, mais ${failed} fichiers sur ${files} n'ont pas été écrits.`,

	errorUnsupportedFormat: ({ message }) => `Ce format n'est pas pris en charge. ${message}`,
	errorMissingComponent: ({ message }) => `Un composant manque. ${message}`,
	errorInFile: ({ file, message }) => `${file} : ${message}`,

	stepsLabel: () => 'Étapes',
	stepFile: () => 'Fichier',
	stepReview: () => 'Relecture',
	stepResult: () => 'Résultat',
	stepAnnounce: ({ position, total, name }) => `Étape ${position} sur ${total} : ${name}`,
	stepReviewLocked: () => "Ajoutez d'abord un document.",
	stepResultLocked: () => "Rien n'a encore été nettoyé.",
	filesTitle: () => 'Documents',
	removeFile: ({ file }) => `Retirer ${file}`,
	clearFiles: () => 'tout retirer',
	back: () => 'Retour',
	continueToReview: () => 'Relire ce qui a été trouvé',

	reviewOf: ({ file }) => `Relecture de ${file}`,
	findingCount: ({ count }) =>
		plural(L, count, { one: '{n} valeur trouvée', other: '{n} valeurs trouvées' }),
	documentLabel: ({ file }) => `Le texte extrait de ${file}, chaque valeur marquée`,
	markName: ({ entity, action, kept }) => (kept ? `${entity}, gardée` : `${entity}, ${action}`),
	viewDocument: () => 'Document',
	viewList: () => 'Liste',
	onlyFindings: () => 'Seulement ce qui a été trouvé',
	wholeDocument: () => 'Tout le document',
	skippedParagraphs: ({ count }) =>
		plural(L, count, {
			one: '{n} paragraphe sans rien — afficher',
			other: '{n} paragraphes sans rien — afficher'
		}),
	previewTruncated: ({ shown, total }) =>
		`Les ${new Intl.NumberFormat(L).format(shown)} premiers caractères sur ` +
		`${new Intl.NumberFormat(L).format(total)}. Tout ce qui a été trouvé au-delà reste ` +
		'listé, et reste supprimé.',
	noPreview: () => "Ce document n'a pas de texte à montrer.",
	keyboardHelp: () =>
		'Les flèches ou j et k passent d\'une valeur à l\'autre. x garde ou relâche celle qui ' +
		'est choisie. a ajoute une valeur manquée. f affiche ou masque le texte intact.',
	filterByType: () => 'Type',
	allTypes: () => 'tous les types',
	searchValues: () => 'Chercher dans les valeurs',
	nothingForThisFilter: () => 'Aucune valeur ne correspond à ce filtre.',

	detailNothingSelected: () => 'Rien de sélectionné',
	detailNothingSelectedHint: () =>
		'Choisissez une valeur marquée pour voir ce qui l\'a trouvée et avec quelle confiance.',
	detailType: () => 'Type',
	detailConfidence: () => 'Confiance',
	detailFound: () => 'Trouvée par',
	detailWhere: () => 'Où',
	detailAction: () => 'Ce qui se passe',
	detailKept: () => 'Vous avez décidé de garder cette occurrence.',
	foundByChecksum: () => 'une somme de contrôle l\'a confirmée',
	foundByModel: () => 'le modèle l\'a reconnue',
	foundByYou: () => 'vous l\'avez demandée',
	foundBy: ({ detector }) => `règle : ${detector}`,
	keepThisOccurrence: () => 'Garder cette occurrence',
	stopKeeping: () => 'La supprimer finalement',
	keepEveryOne: ({ entity }) => `Garder chaque ${entity} du document`,

	advancedTitle: () => 'Avancé',
	advancedHint: () =>
		'Par défaut, tout est cherché partout. Chaque réglage ici ne peut que restreindre la ' +
		'recherche, et une recherche restreinte le dit dans le résultat.',
	detectorSpec: () => 'Couches de détection',
	detectorSpecHint: () =>
		'Quelles couches tournent. Moins de couches trouvent moins ; le moteur dit ce que ' +
		'chacune couvre.',

	verificationPassed: () => 'Vérifié',
	verificationPassedHint: ({ checked }) =>
		plural(L, checked, {
			one: 'Le résultat a été réouvert et fouillé : {n} valeur a disparu.',
			other: 'Le résultat a été réouvert et fouillé : les {n} valeurs ont disparu.'
		}),
	openFolder: () => 'Ouvrir le dossier',
	scrubAgain: () => 'Recommencer',

	diagnosticsTitle: () => 'Ce que cette machine sait faire',
	diagnosticsOk: () => 'Tout ce qu\'il faut à cette version est présent.',
	diagnosticsFix: () => 'Remède',
	diagnosticsDegraded: () => 'trouve moins',
	diagnosticsBroken: () => 'manquant',
	countryModelOnly: () => 'modèle seulement',
	rulesSilenced: ({ count }) =>
		plural(L, count, {
			one: '{n} règle ne trouve rien à ce seuil sans un mot-clé à côté.',
			other: '{n} règles ne trouvent rien à ce seuil sans un mot-clé à côté.'
		}),
	placeholderExample: ({ example }) => `écrit comme ${example}`,

	stage: {
		router: () => 'choix du lecteur',
		extract: () => 'lecture du document',
		detect: () => 'recherche des valeurs',
		policy: () => 'décision',
		'write-back': () => 'écriture de la copie',
		verify: () => 'fouille de la copie',
		review: () => 'deuxième avis'
	},
	stageOf: ({ name, index, count }) => `${name} — étape ${index} sur ${count}`,
	stagePages: ({ done, of }) => `page ${done} sur ${of}`,

	/*
	 * Les types restent génériques : le moteur met le pays sur le résultat et
	 * jamais dans le type, parce qu'un même intitulé couvre douze pays et qu'un
	 * nom national serait faux pour onze d'entre eux.
	 */
	entity: {
		PERSON: () => 'Personne',
		ORGANISATION: () => 'Société',
		LOCATION: () => 'Lieu',
		ADDRESS: () => 'Adresse',
		EMAIL: () => 'E-mail',
		PHONE: () => 'Téléphone',
		IBAN: () => 'IBAN',
		CREDIT_CARD: () => 'Carte',
		NATIONAL_ID: () => 'Numéro national',
		TAX_ID: () => 'Numéro fiscal',
		VAT_ID: () => 'Numéro de TVA',
		COMPANY_ID: () => "Numéro d'entreprise",
		IP_ADDRESS: () => 'Adresse IP',
		MAC_ADDRESS: () => 'Adresse MAC',
		URL: () => 'Adresse web',
		DATE: () => 'Date',
		JOB_TITLE: () => 'Fonction',
		AGE: () => 'Âge',
		POSTCODE: () => 'Code postal',
		OTHER: () => 'De vous'
	},

	action: {
		redact: () => 'sera supprimé',
		surrogate: () => 'sera remplacé',
		report: () => 'signalé, non supprimé',
		keep: () => 'laissé tel quel'
	}
} satisfies Messages;
