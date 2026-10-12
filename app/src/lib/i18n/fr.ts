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

	firstRunEyebrow: () => 'Premier lancement',
	modelAskTitle: () => 'Un seul téléchargement, puis FreeDocs fonctionne hors ligne',
	modelAskLead: () =>
		'Pour repérer les noms, les entreprises et les adresses, FreeDocs utilise un modèle de langage qui tourne sur cet ordinateur. Il se télécharge une seule fois.',
	modelFactSize: () => '1,2 Go, depuis Hugging Face, où le modèle est publié',
	modelFactPrivate: () =>
		'Vos documents ne quittent jamais cet ordinateur. Seul le modèle entre.',
	modelFactOffline: () => "Ensuite, FreeDocs n'a plus besoin d'Internet.",
	modelDownload: () => 'Télécharger le modèle (1,2 Go)',
	modelNotNow: () => 'Pas maintenant',
	modelWithout: () =>
		"Sans le modèle, FreeDocs trouve quand même les IBAN, les numéros fiscaux et d'identité, les cartes, les e-mails et les numéros de téléphone, mais pas les noms, les entreprises ni les adresses.",
	modelDownloadingTitle: () => 'Téléchargement du modèle',
	modelBytes: ({ done, of }) => `${done} sur ${of}`,
	modelEtaMinutes: ({ minutes }) => `encore environ ${minutes} min`,
	modelEtaUnderMinute: () => "encore moins d'une minute",
	modelKeepOpen: () =>
		"Laissez cette fenêtre ouverte. Pendant ce temps, aucun fichier n'est lu ni envoyé.",
	modelSampleTitle: () => "Ce qu'il va faire",
	modelBefore: () => 'Avant',
	modelAfter: () => 'Après',
	modelSampleBefore: () =>
		'Contrat entre Claire Dubois et Acme SA, rue du Rhône 12, 1204 Genève.',
	modelSampleAfter: ({ person, organisation, address }) =>
		`Contrat entre ${person} et ${organisation}, ${address}.`,
	modelPreparingTitle: () => 'Préparation du modèle',
	modelPreparingLead: () => 'Vérification et chargement. Quelques secondes.',
	modelFailedTitle: () => "Le téléchargement s'est interrompu",
	modelFailedLead: () =>
		"Rien n'a été modifié sur cet ordinateur. Vérifiez la connexion et réessayez.",
	modelFailedProxy: () =>
		"Sur un réseau d'entreprise, un proxy ou un pare-feu peut bloquer huggingface.co. Votre service informatique peut l'autoriser.",
	modelRetry: () => 'Réessayer',
	modelReadyTitle: () => 'Prêt. FreeDocs fonctionne désormais hors ligne.',
	modelReadyLead: () =>
		'Les noms, les entreprises et les adresses seront trouvés dès le premier document.',
	modelChooseDocument: () => 'Choisir un document',
	modelDeferredTitle: () => 'Les noms et les adresses ne sont pas recherchés',
	modelDeferredLead: () => "Le modèle qui les trouve n'est pas encore téléchargé.",
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
	hiddenPendingTitle: () => 'Contenu caché qui sera supprimé',
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

	diagnosticsRecheck: () => 'Vérifier à nouveau',
	announceRechecked: () => 'Vérifié à nouveau.',
	copyFix: () => 'Copier',
	copied: () => 'Copié',
	copyUnavailable: () => 'Sélectionner et copier',
	locateTesseract: () => 'Localiser Tesseract…',
	locateTesseractHint: () =>
		'Si Tesseract est installé à un endroit inhabituel, indiquez-le à cette version. Le moteur vérifie le fichier avant de l’utiliser.',
	chooseTesseract: () => 'Choisir l’exécutable Tesseract',
	tesseractAccepted: () => 'Tesseract accepté.',
	tesseractRefusal: {
		not_executable: () => 'Ce fichier ne peut pas être exécuté. Choisissez le programme Tesseract lui-même.',
		wrong_name: () => 'Ce fichier doit s’appeler « tesseract », car c’est le nom que cherche le lecteur PDF.'
	},
	tesseractRefusalOther: () => 'Le moteur a refusé ce fichier.',
	engineBuild: () => 'Moteur',
	engineSource: {
		override: () => 'choisi avec FREEDOCS_ENGINE',
		bundled: () => 'fourni avec l’application',
		checkout: () => 'depuis les sources'
	},
	engineBuiltOn: (a) => `compilé ${a.when}`,
	engineBuildDateUnknown: () => 'date de compilation inconnue',
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
		match: () => 'je cherche les marqueurs',
		review: () => 'deuxième avis'
	},
	stageOf: ({ name, index, count }) => `${name} — étape ${index} sur ${count}`,
	stagePages: ({ done, of }) => `page ${done} sur ${of}`,

	/*
	 * Les types restent génériques : le moteur met le pays sur le résultat et
	 * jamais dans le type, parce qu'un même intitulé couvre douze pays et qu'un
	 * nom national serait faux pour onze d'entre eux.
	 */
	// ---- le chemin inverse --------------------------------------------------
	modeLabel: () => 'Que faire',
	modeScrub: () => 'Retirer',
	modeRestore: () => 'Remettre',
	modeAnnounce: ({ name }) => `Passé à ${name}`,

	keyFileTitle: () => 'Fichier de clé',
	keyFileHint: () =>
		'Écrit un fichier chiffré qui permet de remettre les valeurs retirées dans ' +
		'ce que le modèle renvoie. Sans lui, ce nettoyage est irréversible pour tout le monde.',
	keyFileEnable: () => 'Écrire aussi un fichier de clé',
	keyFileWhere: () => 'Où le mettre',
	keyFileChooseWhere: () => 'Choisir un dossier',
	keyFilePassphrase: () => 'Phrase secrète',
	keyFileConfirm: () => 'Répéter la phrase secrète',
	keyFileUnavailable: () => 'Cette version ne peut pas écrire de fichier de clé.',
	keyFileNeedsDirectory: () => 'Choisis un dossier en dehors du dossier de destination.',
	keyFileNeedsPassphrase: ({ min }) => `Au moins ${min} caractères.`,
	keyFileMismatch: () => 'Les deux phrases secrètes ne correspondent pas.',
	keyFileDanger: () =>
		'Ce fichier est aussi confidentiel que le document d’origine. Garde-le loin ' +
		'de la copie nettoyée, et n’envoie jamais les deux ensemble.',
	keyFileWritten: () => 'Fichier de clé',
	chooseKeyDirectory: () => 'Où mettre le fichier de clé',
	chooseKeyFile: () => 'Choisir un fichier de clé',
	keyFileFilter: () => 'Fichier de clé FreeDocs',

	// ---- text mode ----------------------------------------------------------
	modeText: () => 'Coller du texte',
	stepText: () => 'Texte',
	textTitle: () => 'Collez le texte',
	textHint: () => 'Collez ce que vous voulez envoyer à un modèle. Il est nettoyé ici et jamais écrit sur le disque ; collez ensuite la réponse pour remettre les valeurs.',
	textLabel: () => 'Texte',
	textPlaceholder: () => 'Collez ici…',
	textCount: ({ count }) =>
		plural(L, count, { one: '{n} caractère', other: '{n} caractères' }),
	textTooLong: ({ max }) => `Plus long que les ${max.toLocaleString(L)} caractères admis. Enregistrez-le dans un fichier et nettoyez celui-ci.`,
	textInspect: () => 'Chercher les valeurs',
	textReviewTitle: () => 'Vérifier le texte collé',
	textScrub: () => 'Nettoyer le texte',
	textKeepTitle: () => 'Ensuite',
	textKeepNone: () => 'Ne pas garder de retour',
	textKeepNoneHint: () => 'Irréversible, comme tout nettoyage. Une réponse ne pourra pas être restaurée.',
	textKeepMemory: () => 'Garder jusqu\'à la fermeture de FreeDocs',
	textKeepMemoryHint: () => 'Restaurer la réponse ici, sans rien saisir.',
	textKeepMemoryWarning: () => 'Le moteur garde ce qui a été retiré, en mémoire, jusqu\'à ce que vous commenciez un nouveau texte, changiez de mode ou fermiez FreeDocs. Rien n\'est écrit sur le disque.',
	textKeepFile: () => 'Enregistrer un fichier de clé',
	textKeepFileHint: () => 'Chiffré, pour une réponse qui arrive un autre jour.',
	textKeyNeedsDirectory: () => 'Choisissez un dossier pour le fichier de clé.',
	textResultTitle: () => 'Texte nettoyé',
	textScrubbedTitle: () => 'À envoyer',
	textNew: () => 'Nouveau texte',
	textCopy: () => 'Copier',
	textCopied: () => 'Copié',
	textCopyFailed: () => 'Non copié. Sélectionnez le texte et copiez-le à la main.',
	textHeld: () => 'Le retour est gardé jusqu\'à un nouveau texte, un changement de mode ou la fermeture de FreeDocs.',
	textNotKept: () => 'Aucun retour gardé : ce texte ne peut pas être restauré.',
	textNothingProduced: () => 'Aucun texte nettoyé n\'a été produit.',
	textReplyTitle: () => 'La réponse',
	textReplyLabel: () => 'Ce que le modèle a répondu',
	textReplyPlaceholder: () => 'Collez la réponse ici…',
	textRestore: () => 'Remettre les valeurs',
	textRestoredTitle: () => 'Réponse restaurée',
	announceTextScrubbed: ({ count }) =>
		plural(L, count, { one: 'Texte nettoyé, {n} valeur retirée', other: 'Texte nettoyé, {n} valeurs retirées' }),

	// ---- the term list ------------------------------------------------------
	termsTitle: () => 'Liste de termes',
	termsHint: () => 'Une liste chiffrée des noms et codes que votre cabinet retire toujours : clients, dossiers, projets. Déverrouillée une fois par session ; les entrées restent dans le moteur.',
	termsUnavailable: () => 'Cette version ne peut pas ouvrir de liste de termes.',
	termsOpen: () => 'Ouvrir…',
	termsNew: () => 'Nouvelle…',
	termsCancel: () => 'Annuler',
	termsPassphrase: () => 'Phrase secrète',
	termsConfirm: () => 'Phrase secrète, à nouveau',
	termsUnlock: () => 'Déverrouiller',
	termsCreate: () => 'Créer la liste',
	termsLock: () => 'Verrouiller',
	termsForget: () => 'Fermer',
	termsNeedsPassphrase: ({ min }) => `Au moins ${min} caractères.`,
	termsMismatch: () => 'Les deux phrases secrètes ne correspondent pas.',
	termsNewWarning: () => 'Sans sa phrase secrète, personne ne peut ouvrir cette liste, pas même FreeDocs. Conservez-la là où votre cabinet garde ses autres mots de passe.',
	termsCount: ({ count }) =>
		plural(L, count, { one: '{n} entrée', other: '{n} entrées' }),
	termsUse: () => 'Les retirer à chaque nettoyage',
	termsSearch: () => 'Chercher dans la liste',
	termsNoMatch: () => 'Aucune entrée ne correspond.',
	termsEmpty: () => 'La liste est vide.',
	termsNewValue: () => 'Ajouter une valeur',
	termsEntity: () => 'Ce que c\'est',
	termsEntityUnspecified: () => 'Non précisé',
	termsAdd: () => 'Ajouter',
	termsRemoveOne: ({ value }) => `Retirer ${value} de la liste`,
	termsImport: () => 'Importer…',
	termsExport: () => 'Exporter…',
	termsExportWarning: () => 'Un export est un fichier texte en clair : quiconque peut le lire lit chaque entrée, et la phrase secrète ne le protège pas. Supprimez-le une fois terminé.',
	termsExportConfirm: () => 'Exporter en clair',
	termsExportedTitle: () => 'Exporté, non chiffré',
	termsImportedTitle: ({ added, skipped }) => `${plural(L, added, { one: '{n} entrée ajoutée', other: '{n} entrées ajoutées' })}, ${plural(L, skipped, { one: '{n} déjà présente', other: '{n} déjà présentes' })}.`,
	termsDeleteSource: ({ file }) => `${file} n\'est pas chiffré et contient encore chaque entrée. Supprimez-le maintenant : FreeDocs ne le fera pas à votre place.`,
	termsDismiss: () => 'Terminé',
	termsFilter: () => 'Liste de termes FreeDocs',
	termsRekey: () => 'Changer la phrase secrète…',
	termsCurrentPassphrase: () => 'Phrase secrète actuelle',
	termsNextPassphrase: () => 'Nouvelle phrase secrète',
	termsRekeyConfirm: () => 'Changer la phrase secrète',
	termsRekeyed: () => 'Phrase secrète changée',
	termsImportFilter: () => 'Texte ou CSV',
	termsChooseFile: () => 'Choisir une liste de termes',
	termsChooseNew: () => 'Où enregistrer la nouvelle liste',
	termsChooseImport: () => 'Choisir un fichier à importer',
	termsChooseExport: () => 'Où écrire l\'export en clair',
	termsUnlocked: ({ count }) =>
		plural(L, count, { one: 'Liste déverrouillée, {n} entrée', other: 'Liste déverrouillée, {n} entrées' }),
	termsLocked: () => 'Liste verrouillée',
	termsAdded: ({ count }) =>
		plural(L, count, { one: '{n} entrée ajoutée', other: '{n} entrées ajoutées' }),
	termsAlreadyThere: () => 'Déjà dans la liste',
	termsRemoved: ({ count }) =>
		plural(L, count, { one: '{n} entrée retirée', other: '{n} entrées retirées' }),
	termsImportedAnnounce: ({ count }) =>
		plural(L, count, { one: '{n} entrée importée. Supprimez le fichier source.', other: '{n} entrées importées. Supprimez le fichier source.' }),
	termsExportedAnnounce: ({ count }) =>
		plural(L, count, { one: '{n} entrée exportée, non chiffrée', other: '{n} entrées exportées, non chiffrées' }),
	fromTermList: () => 'liste',
	foundByTermList: () => 'la liste de termes de votre cabinet',
	termsMatched: ({ matched, loaded }) => `Liste de termes : ${matched} sur ${plural(L, loaded, { one: 'une entrée', other: '{n} entrées' })} trouvées dans ce document.`,

	stepRestoreFile: () => 'Document et clé',
	restoreTitle: () => 'Remettre les valeurs',
	restoreHint: () =>
		'Choisis ce qui est revenu du modèle, et le fichier de clé du nettoyage qui l’a produit.',
	restoreDocument: () => 'Document revenu du modèle',
	restoreChooseDocument: () => 'Choisir un document',
	restoreKey: () => 'Fichier de clé',
	restoreChooseKey: () => 'Choisir un fichier de clé',
	restorePassphrase: () => 'Phrase secrète',
	restoreNeedsDocument: () => 'Choisis le document qui est revenu.',
	restoreNeedsKey: () => 'Choisis le fichier de clé de ce nettoyage.',
	restoreNeedsPassphrase: () => 'Saisis la phrase secrète de ce fichier de clé.',
	restoreRun: () => 'Remettre les valeurs',
	restoring: () => 'Je remets les valeurs…',
	restoreAgain: () => 'Remettre dans un autre',

	restoreResultTitle: () => 'Ce qui est revenu',
	restoredSummary: ({ values, occurrences }) =>
		`${values} ${values <= 1 ? 'valeur remise' : 'valeurs remises'}, à ` +
		`${occurrences} ${occurrences <= 1 ? 'endroit' : 'endroits'}`,
	restoreNothingMatched: () =>
		'Aucun marqueur de ce fichier de clé n’était dans le document.',
	restoreNotPresentTitle: () => 'Pas dans ce document',
	restoreNotPresentHint: () =>
		'Ils étaient dans le fichier de clé et pas dans le retour — le plus souvent du texte que le modèle a supprimé.',
	restoreUnknownTitle: () => 'Laissés tels quels',
	restoreUnknownHint: () =>
		'Ils ressemblent à des marqueurs et ce fichier de clé ne les connaît pas. ' +
		'Deviner la valeur visée mettrait les mauvaises données dans le document, ils ont donc été laissés en place.',
	restoreProblemsTitle: () => 'Non revenues',
	restoreVerified: () => 'Le document a été réouvert, et chaque valeur est arrivée.',
	restoreIncomplete: ({ count }) =>
		`${count} ${count <= 1 ? 'valeur n’est pas revenue' : 'valeurs ne sont pas revenues'}. ` +
		'Le document a été écrit quand même — ce qui manque y est visible.',
	restoreCaveatsTitle: () => 'Ce que remettre les valeurs ne fait pas',

	announceRestored: ({ count }) =>
		`Terminé. ${count} ${count <= 1 ? 'valeur remise' : 'valeurs remises'}.`,
	announceRestoredWithProblems: ({ count }) =>
		`Terminé, mais ${count} ${count <= 1 ? 'valeur n’est pas revenue' : 'valeurs ne sont pas revenues'}.`,

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
