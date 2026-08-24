<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/wordmark-dark.svg">
    <img src="docs/images/wordmark-light.svg" alt="FreeDocs" width="272">
  </picture>
</p>

<h3 align="center">Retirez les données confidentielles d'un document avant qu'une IA ne les voie.</h3>

<p align="center">
  PDF, Word, Excel, PowerPoint et numérisations — entrent, ressortent nettoyés, dans le même format.<br>
  Sur votre machine. Aucun cloud, aucune clé d'API, aucune télémétrie, aucun compte.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-AGPL--3.0--or--later-2f9e79" alt="AGPL-3.0-or-later"></a>
  <img src="https://img.shields.io/badge/python-3.10%20%E2%80%93%203.12-2f9e79" alt="Python 3.10 à 3.12">
  <img src="https://img.shields.io/badge/fonctionne-100%25%20hors%20ligne-2f9e79" alt="Fonctionne entièrement hors ligne">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.it.md">Italiano</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <b>Français</b>
</p>

<p align="center"><sub>La documentation technique dans <a href="docs/"><code>docs/</code></a> est en anglais.</sub></p>

---

La plupart des outils qui promettent cela vous rendent un fichier texte, ou
dessinent des rectangles noirs par-dessus un texte qui reste sélectionnable en
dessous. FreeDocs modifie le document sur place — puis il rouvre ce qu'il vient
d'écrire, le réextrait, parties invisibles comprises, et **fait échouer
l'exécution si une seule valeur retirée a survécu**.

<p align="center">
  <img src="docs/images/review.png" alt="L'étape Review : le document extrait avec chaque détection marquée, et le panneau de détail indiquant ce qui a trouvé la valeur sélectionnée, sa confiance et les deux façons de la conserver" width="900">
</p>

<p align="center"><sub><b>Review.</b> Chaque détection est marquée dans le document lui-même, parce que c'est la phrase autour d'une valeur qui dit si une ville est l'adresse d'une partie ou une clause de juridiction. Le panneau nomme la couche qui l'a trouvée, sa confiance et la partie du fichier où elle se trouve.</sub></p>

<p align="center">
  <img src="docs/images/result.png" alt="L'étape Result : douze valeurs retirées, les parties cachées supprimées et la ligne de vérification confirmant que la sortie a été rouverte et fouillée" width="900">
</p>

<p align="center"><sub><b>Result.</b> Ce qui est parti, quelles parties cachées ont été supprimées, et la ligne qui compte : la sortie a été rouverte et fouillée, et les douze valeurs ont disparu. Le chemin de sortie est masqué sur cette capture — une capture non retouchée publierait un nom d'utilisateur, soit exactement le genre de chose que cet outil existe pour retirer. Rien d'autre n'est modifié.</sub></p>

## En trente secondes

```console
$ freedocs scrub examples/offerta-esempio.docx -o clean/
offerta-esempio.docx  [docx]
  removed:
    ADDRESS                1
    COMPANY_ID             1
    EMAIL                  1
    IBAN                   1
    ORGANISATION           2
    PERSON                 3
    PHONE                  1
    TAX_ID                 1
    VAT_ID                 1
  flagged for review: 2
  hidden content removed:
    docProps/thumbnail.jpeg page-thumbnail             rendered preview of the unredacted file
    customXml/_rels/item1.xml.rels custom-xml-store           data store behind content controls
    customXml/item1.xml custom-xml-store           data store behind content controls
    customXml/itemProps1.xml custom-xml-store           data store behind content controls
    docProps/core.xml metadata                   author, description, last editor, revision count
    docProps/app.xml extended-metadata          template path, total editing time
    word/document.xml revision-save-ids          3 rsid attribute(s) fingerprinting the editing session
    word/settings.xml revision-save-id-table     10 recorded editing session(s)
  verify: no leak: 12 distinct values checked against 564 characters of output
  written: clean/offerta-esempio.docx
```

Cette exécution est reproductible — le fichier est
[`examples/offerta-esempio.docx`](examples/) — et voici ce qui en est sorti :

| Avant | Après |
|---|---|
| Realise Consulting SA<br>Bahnhofstrasse 12, 8001 Zurigo<br>UID: CHE-116.281.710 | `[ORGANISATION_1]`<br>`[ADDRESS_1]`<br>UID: `[COMPANY_ID_1]` |
| Referente: Laura Esposito, responsabile acquisti | Referente: `[PERSON_1]`, responsabile acquisti |
| IBAN per i pagamenti: CH93 0076 2011 6238 5295 7 | IBAN per i pagamenti: `[IBAN_1]` |
| …il foro competente è **Zurigo**. | …il foro competente è **Zurigo**. |

Regardez la dernière ligne. La ville dans l'adresse de la partie a disparu ; la
même ville dans la clause de juridiction est intacte, parce qu'une juridiction
n'identifie personne. Et `Laura Esposito` était stockée par Word en trois runs
distincts : elle est ressortie en un seul marqueur, avec la mise en forme du
paragraphe, le tableau et les styles intacts.

## Ce que vous obtenez

- **Le même type de fichier, toujours mis en forme.** Les runs, les tableaux, les
  graphiques et les styles survivent, parce que la réécriture modifie les runs et
  le flux de contenu du PDF au lieu d'aplatir le document en texte. Les parties
  que le moteur n'a jamais analysées sont recopiées telles que les octets reçus.
- **Les copies dont vous ignoriez l'existence.** Les caches de tableaux croisés
  d'Excel, les caches de graphiques et les feuilles `veryHidden` ; le texte
  supprimé mais suivi de Word, son magasin `customXml` et la vignette de page déjà
  rendue ; les notes du présentateur de PowerPoint, les diapositives masquées, les
  formes hors diapositive et le classeur entier intégré dans un graphique. Chaque
  élément est retiré ou nettoyé, et nommé dans le rapport.
  → [ce qu'un document cache](docs/hidden-content.md)
- **Une étape de vérification qui peut échouer.** L'étape 6 rouvre la sortie, la
  réextrait et cherche chaque valeur censée avoir disparu. Un survivant fait sortir
  le processus avec un code non nul et **rien n'est écrit**, parce qu'un fichier
  presque propre est plus dangereux qu'un fichier visiblement sale : il part.
- **Des chiffres que vous pouvez relancer.** `freedocs benchmark` évalue les
  couches sur un corpus annoté, et l'outil imprime sa propre mise en garde chaque
  fois. → [benchmark](docs/benchmark.md)
- **Si vous le voulez, le chemin inverse.** `--map` écrit un fichier de clé
  chiffré, et `freedocs restore` remet les vraies valeurs dans ce que le modèle
  renvoie. Désactivé par défaut, car c'est la seule chose qui rend un nettoyage
  réversible : sans lui, la correspondance est détruite à la fin de l'exécution et
  personne ne peut l'annuler, vous compris.
  → [le chemin inverse](docs/restore.md)

## Démarrage

**Ligne de commande**

```bash
git clone https://github.com/MarcoTribuz/FreeDocs.git
cd FreeDocs/engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner   # ner télécharge ~1,2 Go de poids

uv run freedocs inspect ../examples/offerta-esempio.docx    # signaler, sans rien écrire
uv run freedocs scrub   ../examples/offerta-esempio.docx -o out/
uv run freedocs doctor                                      # ce que cette machine sait vraiment faire
```

Sans `--extra ner`, tout fonctionne encore sur les seules sommes de contrôle, et
chaque rapport indique que les noms, organisations, lieux et adresses ne sont pas
détectés. Une compilation qui trouve moins doit le dire.
→ [référence complète de la CLI](docs/cli.md)

**Application de bureau**

```bash
cd app && npm install
npm run tauri build     # ou : npm run tauri dev
```

Il n'y a pas encore de version signée à télécharger. Les installeurs sont
construits en CI pour macOS, Linux et Windows à chaque push sur `main` ; macOS est
le seul qu'un humain ait réellement lancé, donc pour les deux autres, lisez « se
compile » et non « fonctionne ». → [packaging](docs/packaging.md)

Il existe aussi un bundle portable par plateforme : on décompresse et on lance,
sans installation ni réseau, avec le modèle de 1,2 Go à l'intérieur plutôt que
téléchargé au premier lancement. C'est pour cela qu'il pèse 1405 Mo.
→ [portable](docs/portable.md)

## Ce qu'il trouve

| | |
|---|---|
| **Formats** | texte brut, PDF (natif et numérisé), `docx`, `xlsx`, `pptx` |
| **Retirés** | personne, organisation, adresse, lieu, e-mail, téléphone, IBAN, carte bancaire, pièce d'identité, numéro fiscal, numéro de TVA, numéro d'immatriculation d'entreprise, IP, MAC, URL |
| **Signalés, jamais retirés** | intitulé de poste, date, âge, code postal — des quasi-identifiants : en supprimer un masque le risque résiduel au lieu de le montrer |
| **Identifiants confirmés par somme de contrôle** | 🇨🇭 🇮🇹 🇩🇪 🇦🇹 🇫🇷 🇧🇪 🇪🇸 🇵🇹 🇳🇱 🇵🇱 🇸🇪 🇬🇧 — douze pays, quarante règles |
| **Langues lues** | italien, allemand, français, anglais, par un seul modèle sans indication de langue |

`freedocs countries` imprime ce que chaque pays reçoit réellement. Les États-Unis
figurent dans cette liste sans aucune règle de somme de contrôle, parce qu'aucun
de leurs deux numéros n'a de chiffre de contrôle : `stdnum.us.ssn` accepte 89 %
des valeurs aléatoires de sa forme. Ces identifiants viennent du modèle, et l'outil
le dit au lieu d'inventer une règle dans la table.

## Comment il décide

Trois couches, et c'est la stricte qui a le dernier mot.

**Les sommes de contrôle d'abord.** Une regex propose, un chiffre de contrôle
décide. Quarante règles sur douze pays, chaque validateur venant de
`python-stdnum`. La confiance de chaque règle est une mesure, pas un jugement :
chaque validateur a été exécuté sur 20 000 valeurs aléatoires de forme plausible
pour compter combien il en accepte, et les règles les plus faibles se situent sous
le seuil par défaut — trouvées et signalées, jamais retirées, sauf si un mot qui
les nomme se trouve à côté.

**Puis un encodeur multilingue** (GLiNER2 sur `mdeberta-v3-base`) pour ce qu'aucune
somme de contrôle ne peut confirmer : noms, organisations, lieux, adresses,
intitulés de poste. Un modèle, quatre langues, aucune indication de langue — et il
doit renvoyer des offsets de caractères, parce que ce sont les offsets qu'attendent
les ancres.

**Puis les sommes de contrôle auditent le modèle.** GLiNER2 a étiqueté deux
montants adjacents d'un graphique comme une carte bancaire avec une confiance de
0.87 ; aucun seuil ne distingue cela d'une vraie détection, et Luhn tranche en un
appel. Quand le modèle revendique un type structuré, la somme de contrôle
correspondante a le dernier mot — sauf lorsqu'il est impossible de savoir quel pays
l'a émis : alors il n'y a pas d'avis, et la détection survit.

Trois passes correctives nettoient ensuite la couche de texte libre : une adresse
est assemblée vers l'extérieur à partir de son code postal (la partie qui n'a
besoin d'aucun modèle), un nom d'entreprise est récupéré depuis la forme juridique
qui le suit, et les détections qui nomment quelque chose de réel sans identifier
personne sont écartées. C'est cette dernière qui explique pourquoi `Zurigo` est
resté dans la clause de juridiction ci-dessus. → [architecture](docs/architecture.md)

## Mesuré, pas promis

537 entités annotées dans des documents d'affaires en italien, allemand, français
et anglais ; 485 d'entre elles sont des entités que la politique retire vraiment.

| Couches | Couverture | Sur-rédaction | Micro-F1 exact |
|---|---|---|---|
| Sommes de contrôle seules | 70.3 % | 1.1 % | 0.738 |
| Encodeur seul | 86.6 % | 1.7 % | 0.793 |
| **Les deux (par défaut)** | **99.6 %** | **2.2 %** | **0.929** |

La **couverture** compte les entités de référence retirées *entièrement* — une
portion de span est une fuite, car un `Rossi` laissé en place identifie encore
quelqu'un. La **sur-rédaction** compte les caractères retirés qui n'étaient pas
confidentiels, car un détecteur qui noircit la page ne laisse rien fuir et ne sert
à rien. Le F1 est en troisième position volontairement : c'est le chiffre qui fait
la meilleure impression et qui compte le moins ici.

Reproduisez n'importe quelle ligne avec `--detectors l1`, `--detectors ner`, ou
sans aucun drapeau ; `--apply-min-confidence 0.5` rapporte ce qu'un nettoyage fait
réellement plutôt que ce que le détecteur a proposé. **Le corpus est petit et
synthétique : ces chiffres classent des configurations entre elles et ne sont pas
un résultat de benchmark publiable.** L'outil imprime cette mise en garde de
lui-même, chaque fois. → [benchmark](docs/benchmark.md)

## Ce qu'il ne fait pas

La liste honnête, parce que les échecs d'un outil comme celui-ci sont silencieux
par nature.

- **Il n'élimine pas le risque de ré-identification.** Un document privé de tout
  nom peut encore dire « la seule femme associée du bureau de Lugano, recrutée en
  mars 2019 ». Les quasi-identifiants sont signalés et rapportés, jamais réécrits
  en silence. Une passe optionnelle avec un LLM local *lit* la sortie anonymisée et
  pointe exactement cela — consultative, et elle ne modifie rien.
  → [le second avis](docs/llm-review.md)
- **Sur une numérisation, l'OCR est une lecture et non le texte.** Un numéro fiscal
  dont un caractère est mal lu échoue à sa somme de contrôle, n'est jamais détecté
  et survit. Chaque page lue par la machine est nommée dans un avertissement qui
  demande de la vérifier à l'œil.
- **Les noms de lieux qui sont aussi des noms de famille sont le point faible.**
  Les deux fuites restantes du corpus sont une ville qui apparaît aussi comme le
  nom de famille de quelqu'un dans le même document. La couverture LOCATION est de
  94.3 % contre 100 % pour PERSON.
- **Nettoyer un nom dans Excel renomme la chose.** Les formules désignent les
  feuilles et les tableaux par leur nom, donc un nom de feuille nettoyé casse les
  références. C'est fait quand même — laisser le nom ferait échouer le contrôle de
  fuite — et rapporté comme un avertissement qui nomme ce qui a changé.
- **Un projet de macros ne peut pas être nettoyé, seulement supprimé.**
- **Un fichier de clé est aussi confidentiel que le document d'origine.** Si vous
  en demandez un avec `--map`, ce fichier peut remettre chaque valeur retirée. Il
  est chiffré et refusé dans le dossier de destination ; ensuite, c'est à vous de
  le gérer : ne l'envoyez jamais avec la copie nettoyée. Il ne peut pas non plus
  ramener ce qui a été *supprimé* plutôt que remplacé — vignettes, métadonnées,
  diapositives masquées — car cela n'a jamais reçu de marqueur.
  → [le chemin inverse](docs/restore.md)
- **Ce n'est pas une garantie de conformité et il ne prétend jamais que la sortie
  est propre.** `report.CAVEATS` inscrit les limites dans le rapport lui-même.

## Pourquoi un outil de plus

Plusieurs projets en font une partie. La colonne du manque est ce pour quoi
FreeDocs a été construit.

| Projet | Formats | Détection | Manque |
|---|---|---|---|
| [rizzo-pii](https://github.com/Rizzo-AI-Academy/rizzo-pii) | txt, md, PDF | mmBERT + sommes de contrôle, 22 entités italiennes | aucun format Office |
| [A5-PII-Anonymizer](https://github.com/AgenticA5/A5-PII-Anonymizer) | txt, docx, xlsx, csv, pdf | Piiranha ONNX | détecteur faible, pas d'OCR, pas de pptx |
| [phileas](https://github.com/philterd/phileas) | pdf, docx, xlsx, csv, numérisations | regex + ML | pas de pptx |
| [desktop-redactor](https://github.com/williape/desktop-redactor) | csv, json, txt | Presidio | aucun document |
| [Presidio](https://github.com/microsoft/presidio) | texte, images, données structurées | NLP + motifs | pas de détection de langue, donc toutes les langues sont fusionnées : mesuré ici à 21.5 % de sur-rédaction |

## État

Tout ce qui figurait au plan initial est livré, plus la couverture
internationale : douze pays d'identifiants confirmés par somme de contrôle, quatre
langues de NER, une application de bureau et la couche de relecture optionnelle.
Tout le reste est du travail nouveau, pas un jalon en attente.

<details>
<summary>Les jalons, pour mémoire</summary>

| M | Contenu | État |
|---|---|---|
| M0 | Cœur, validateurs L1, texte brut, CLI, vérification, tests | fait |
| M1 | PDF textuel : vraie rédaction du flux de contenu, nettoyage du contenu caché | fait |
| M2 | NER L2 intégré, corpus annoté, couverture mesurée | fait |
| M3 | `docx` avec réécriture consciente des runs et nettoyage du caché | fait |
| M4 | `xlsx`, y compris caches de tableaux croisés et feuilles `veryHidden` | fait |
| M5 | `pptx` : notes, diapositives masquées, formes hors canevas, données de graphiques | fait |
| M6 | PDF numérisé : OCR et rédaction sur les boîtes englobantes des mots | fait |
| M7 | Application de bureau Tauri | fait |
| M8 | Relecture L3 par Ollama, optionnelle | fait |

</details>

Manques connus, énoncés plutôt que cachés : pas de build macOS Intel (il faut
une machine Intel), pas encore de version signée, pas de binaire Tesseract dans le
bundle portable (c'est impossible : PyMuPDF l'appelle comme processus externe), et
torch représente 501 Mo d'un bundle de 1,0 Go qu'un export ONNX ferait en grande
partie disparaître — après avoir relancé le benchmark pour prouver que les
chiffres tiennent. Les installeurs ne fournissent toujours pas d'AppImage ; la
build portable en produit un.

## Contribuer

Les rapports de bug sont bienvenus, et une règle compte plus que les autres : **ne
joignez jamais un document réel.** Construisez un fichier synthétique qui
reproduit le problème — le modèle d'issue dit la même chose en haut.

- [CONTRIBUTING.md](CONTRIBUTING.md) — installation, les marqueurs de test et les
  quatre règles que le code ne révèle pas
- [SECURITY.md](SECURITY.md) — le modèle de menace et comment signaler une
  vulnérabilité en privé
- [docs/](docs/) — la version longue de tout ce qui précède

## Licence

[AGPL-3.0-or-later](LICENSE). La couche PDF utilise PyMuPDF, qui est en AGPL ;
rester en AGPL est ce qui rend cet usage gratuit. Les travaux dérivés doivent
rester ouverts.
