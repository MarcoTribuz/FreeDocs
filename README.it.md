<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/wordmark-dark.svg">
    <img src="docs/images/wordmark-light.svg" alt="FreeDocs" width="272">
  </picture>
</p>

<h3 align="center">Togli i dati riservati da un documento prima che un'AI li veda.</h3>

<p align="center">
  PDF, Word, Excel, PowerPoint e scansioni — entrano, escono ripuliti, nello stesso formato.<br>
  Sulla tua macchina, senza nessuno in mezzo: nessun cloud, nessun intermediario, nessuna API key, nessuna telemetria, nessun account.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/licenza-AGPL--3.0--or--later-2f9e79" alt="AGPL-3.0-or-later"></a>
  <img src="https://img.shields.io/badge/python-3.10%20%E2%80%93%203.12-2f9e79" alt="Python dalla 3.10 alla 3.12">
  <img src="https://img.shields.io/badge/gira-100%25%20offline-2f9e79" alt="Gira completamente offline">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <b>Italiano</b> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.fr.md">Français</a>
</p>

<p align="center"><sub>La documentazione tecnica in <a href="docs/"><code>docs/</code></a> è in inglese.</sub></p>

---

Gli strumenti che promettono questa cosa di solito restituiscono un file di testo,
oppure disegnano rettangoli neri sopra un testo che sotto resta selezionabile.
FreeDocs modifica il documento sul posto — e poi riapre quello che ha scritto, lo
riestrae comprese le parti che non si vedono, e **fa fallire l'esecuzione se un
solo valore rimosso è sopravvissuto**.

**Tra te e il modello non c'è nessuno.** Un servizio di mascheramento che gira sul
server di qualcun altro riceve il documento prima del modello, e per questo è un
responsabile del trattamento: un accordo sul trattamento dei dati, un elenco di
sub-responsabili e, per un avvocato o un fiduciario, una questione di segreto
professionale. FreeDocs non ha niente di tutto questo perché il documento non va
da nessuna parte — e il motore blocca le connessioni in uscita verso qualsiasi
cosa non sia questa macchina, così una dipendenza che prova a chiamare casa
fallisce come su un portatile scollegato. Ferma la chiamata accidentale, non il
codice ostile; [SECURITY.md](SECURITY.md) dice esattamente fin dove arriva.

<p align="center">
  <img src="docs/images/review.png" alt="Lo step Review: il documento estratto con ogni ritrovamento marcato, e il pannello di dettaglio che mostra cosa lo ha trovato, quanto ne è sicuro e i due modi per tenerlo" width="900">
</p>

<p align="center"><sub><b>Review.</b> Ogni ritrovamento è marcato dentro il documento, perché è la frase attorno a un valore a dire se una città è l'indirizzo di una parte o una clausola sul foro competente. Il pannello nomina il layer che l'ha trovato, la confidenza e la parte del file in cui vive.</sub></p>

<p align="center">
  <img src="docs/images/result.png" alt="Lo step Result: dodici valori rimossi, le parti nascoste eliminate e la riga di verifica che conferma che l'output è stato riaperto e cercato" width="900">
</p>

<p align="center"><sub><b>Result.</b> Cosa è andato via, quali parti nascoste sono state eliminate, e la riga che conta: l'output è stato riaperto e cercato, e tutti e dodici i valori non ci sono più. Il percorso di output in questo screenshot è coperto — uno non ritoccato pubblicherebbe uno username, cioè esattamente la categoria di cose che questo strumento esiste per rimuovere. Nient'altro è modificato.</sub></p>

## In trenta secondi

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

Quell'esecuzione è riproducibile — il file è
[`examples/offerta-esempio.docx`](examples/) — ed è uscito questo:

| Prima | Dopo |
|---|---|
| Realise Consulting SA<br>Bahnhofstrasse 12, 8001 Zurigo<br>UID: CHE-116.281.710 | `[ORGANISATION_1]`<br>`[ADDRESS_1]`<br>UID: `[COMPANY_ID_1]` |
| Referente: Laura Esposito, responsabile acquisti | Referente: `[PERSON_1]`, responsabile acquisti |
| IBAN per i pagamenti: CH93 0076 2011 6238 5295 7 | IBAN per i pagamenti: `[IBAN_1]` |
| …il foro competente è **Zurigo**. | …il foro competente è **Zurigo**. |

Guarda l'ultima riga. La città nell'indirizzo della parte è sparita; la stessa
città nella clausola sul foro competente è intatta, perché una giurisdizione non
identifica nessuno. E `Laura Esposito` era memorizzata da Word come tre run
separati: è uscita come un unico segnaposto, con la formattazione del paragrafo,
la tabella e gli stili intatti.

## Cosa ottieni

- **Lo stesso tipo di file, ancora formattato.** Run, tabelle, grafici e stili
  sopravvivono, perché la riscrittura modifica i run e il content stream del PDF
  invece di appiattire il documento a testo. Le parti che il motore non ha mai
  analizzato vengono ricopiate come i byte con cui sono arrivate.
- **Le copie che non sapevi ci fossero.** Le pivot cache di Excel, le cache dei
  grafici e i fogli `veryHidden`; il testo cancellato ma tracciato di Word, il
  suo archivio `customXml` e la miniatura della pagina già renderizzata; le note
  del relatore di PowerPoint, le slide nascoste, le forme fuori dalla slide e
  l'intero foglio di calcolo incorporato dentro un grafico. Ogni elemento viene
  rimosso o ripulito, e nominato nel report.
  → [cosa nasconde un documento](docs/hidden-content.md)
- **Una fase di verifica che può fallire.** Lo stage 6 riapre l'output, lo
  riestrae e cerca ogni valore che doveva essere sparito. Un sopravvissuto fa
  uscire il processo con codice diverso da zero e **non viene scritto nulla**,
  perché un file quasi pulito è più pericoloso di uno palesemente sporco: viene
  spedito.
- **Numeri che puoi rieseguire.** `freedocs benchmark` misura i layer su un
  corpus annotato, e lo strumento stampa il proprio caveat ogni volta.
  → [benchmark](docs/benchmark.md)
- **Irreversibile per default; la strada di ritorno solo se la chiedi.** `--map`
  scrive un file chiave cifrato, e `freedocs restore` rimette i valori veri in ciò
  che il modello restituisce. Disattivato per default, perché è l'unica cosa che
  rende una pulizia annullabile: senza, la mappa viene distrutta alla fine del run
  e nessuno può annullarla, tu compreso. → [il percorso inverso](docs/restore.md)

## Partire subito

**Riga di comando**

```bash
git clone https://github.com/MarcoTribuz/FreeDocs.git
cd FreeDocs/engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner   # ner scarica ~1,2 GB di pesi

uv run freedocs inspect ../examples/offerta-esempio.docx    # segnala, non scrive niente
uv run freedocs scrub   ../examples/offerta-esempio.docx -o out/
uv run freedocs doctor                                      # cosa sa fare davvero questa macchina
```

Senza `--extra ner` tutto continua a funzionare sui soli checksum, e ogni report
dichiara che nomi, organizzazioni, luoghi e indirizzi non vengono rilevati. Una
build che trova meno deve dirlo. → [riferimento completo della CLI](docs/cli.md)

**App desktop**

```bash
cd app && npm install
npm run tauri build     # oppure: npm run tauri dev
```

Non c'è ancora una release firmata da scaricare. Gli installer vengono costruiti
in CI per macOS, Linux e Windows a ogni push su `main`; macOS è il solo che una
persona abbia effettivamente lanciato, quindi per gli altri due leggi "si
compila" e non "funziona". → [packaging](docs/packaging.md)

C'è anche un bundle portable per piattaforma: si scompatta e si avvia, senza
installazione e senza rete, con il modello da 1,2 GB dentro invece di scaricato al
primo avvio. È per questo che pesa 1405 MB. → [portable](docs/portable.md)

## Cosa trova

| | |
|---|---|
| **Formati** | testo semplice, PDF (nativo e scansionato), `docx`, `xlsx`, `pptx` |
| **Rimossi** | persona, organizzazione, indirizzo, luogo, email, telefono, IBAN, carta di credito, documento d'identità, codice fiscale, partita IVA, numero di registro imprese, IP, MAC, URL |
| **Segnalati, mai rimossi** | qualifica professionale, data, età, codice postale — quasi-identificatori: cancellarne uno nasconde il rischio residuo invece di renderlo visibile |
| **Identificatori confermati da checksum** | 🇨🇭 🇮🇹 🇩🇪 🇦🇹 🇫🇷 🇧🇪 🇪🇸 🇵🇹 🇳🇱 🇵🇱 🇸🇪 🇬🇧 — dodici paesi, quaranta regole |
| **Lingue lette** | italiano, tedesco, francese, inglese, da un solo modello senza indizi sulla lingua |

`freedocs countries` stampa cosa riceve davvero ogni paese. Gli Stati Uniti sono
in quella lista senza nessuna regola di checksum, perché nessuno dei loro due
numeri ha una cifra di controllo: `stdnum.us.ssn` accetta l'89% dei valori casuali
della sua forma. Quegli identificatori arrivano dal modello, e lo strumento lo
dichiara invece di far finta di avere una regola.

## Come decide

Tre layer, e quello severo ha l'ultima parola.

**Prima i checksum.** Una regex nomina, una cifra di controllo decide. Quaranta
regole su dodici paesi, ogni validatore da `python-stdnum`. La confidenza di ogni
regola è una misura, non un giudizio: ogni validatore è stato eseguito su 20 000
valori casuali di forma plausibile per contare quanti ne accetta, e le regole più
deboli stanno sotto la soglia predefinita — trovate e segnalate, mai rimosse, se
non c'è accanto una parola che le nomina.

**Poi un encoder multilingue** (GLiNER2 su `mdeberta-v3-base`) per le cose che
nessun checksum può confermare: nomi, organizzazioni, luoghi, indirizzi,
qualifiche. Un modello, quattro lingue, nessun indizio sulla lingua — e deve
restituire offset di caratteri, perché gli offset sono ciò che serve agli anchor.

**Poi i checksum controllano il modello.** GLiNER2 ha etichettato due importi
adiacenti di un grafico come carta di credito con confidenza 0.87; nessuna soglia
distingue quel caso da un ritrovamento vero, e Luhn lo chiude in una chiamata.
Quando il modello dichiara un tipo strutturato, il checksum corrispondente ha
l'ultima parola — tranne dove non c'è modo di sapere quale paese l'ha emesso, e
allora non c'è opinione e il ritrovamento sopravvive.

Tre passaggi correttivi ripuliscono poi il livello di testo libero: un indirizzo
viene ricostruito a partire dal suo codice postale (la parte che non ha bisogno di
un modello), il nome di un'azienda viene recuperato dalla forma giuridica che lo
segue, e i ritrovamenti che nominano qualcosa di reale senza identificare nessuno
vengono scartati. È quest'ultimo il motivo per cui `Zurigo` è rimasta nella
clausola sul foro competente. → [architettura](docs/architecture.md)

## Misurato, non promesso

537 entità annotate su documenti aziendali in italiano, tedesco, francese e
inglese; 485 di quelle sono entità che la policy rimuove davvero.

| Layer | Copertura | Sovra-redazione | Micro-F1 esatta |
|---|---|---|---|
| Solo checksum | 70.3% | 1.1% | 0.738 |
| Solo encoder | 86.6% | 1.7% | 0.793 |
| **Entrambi (default)** | **99.6%** | **2.2%** | **0.929** |

La **copertura** conta le entità gold rimosse *interamente* — una porzione di span
è una fuga, perché un `Rossi` rimasto identifica ancora qualcuno. La
**sovra-redazione** conta i caratteri rimossi che non erano riservati, perché un
detector che oscura la pagina non perde niente ed è inutile. L'F1 è al terzo posto
di proposito: è il numero che fa la figura migliore e conta meno.

Riproduci qualsiasi riga con `--detectors l1`, `--detectors ner`, o senza nessun
flag; `--apply-min-confidence 0.5` riporta quello che fa uno scrub invece di
quello che il detector ha nominato. **Il corpus è piccolo e sintetico: questi
numeri classificano configurazioni una rispetto all'altra e non sono un risultato
di benchmark pubblicabile.** Lo strumento stampa quel caveat da sé, ogni volta.
→ [benchmark](docs/benchmark.md)

## Cosa non fa

La lista onesta, perché i fallimenti di uno strumento come questo sono silenziosi
per natura.

- **Non elimina il rischio di re-identificazione.** Un documento privato di ogni
  nome può ancora dire "l'unica donna partner dell'ufficio di Lugano, assunta a
  marzo 2019". I quasi-identificatori vengono segnalati e riportati, mai riscritti
  in silenzio. Esiste un passaggio opzionale con un LLM locale che *legge*
  l'output anonimizzato e indica esattamente quello — è consultivo e non modifica
  nulla. → [la seconda opinione](docs/llm-review.md)
- **Su una scansione, l'OCR è una lettura e non il testo.** Un codice fiscale con
  un carattere letto male non passa il checksum, non viene rilevato e sopravvive.
  Ogni pagina letta a macchina è nominata in un avviso che dice di controllarla a
  occhio.
- **I nomi di luogo che sono anche cognomi sono il punto debole.** Entrambe le
  fughe residue nel corpus sono una città che nello stesso documento compare anche
  come cognome di qualcuno. La copertura LOCATION è 94.3% contro il 100% di
  PERSON.
- **Ripulire un nome in Excel rinomina la cosa.** Le formule si riferiscono a
  fogli e tabelle per nome, quindi un nome di foglio ripulito rompe i riferimenti.
  Viene fatto comunque — lasciare il nome farebbe fallire il controllo di fuga — e
  riportato come warning che dice cosa è cambiato.
- **Un progetto di macro non può essere ripulito, solo rimosso.**
- **Un file chiave è riservato quanto il documento originale.** Se lo chiedi con
  `--map`, quel file può rimettere ogni valore rimosso. È cifrato e viene rifiutato
  dentro la cartella di destinazione, e da lì in poi sta a te: non spedirlo mai
  insieme alla copia pulita. Non può nemmeno riportare ciò che è stato *rimosso*
  invece che sostituito — miniature, metadati, slide nascoste — perché a quelle non
  è mai stato dato un segnaposto. → [il percorso inverso](docs/restore.md)
- **Non parla con il modello al posto tuo.** Incolli la copia pulita
  nell'assistente che usi, e FreeDocs non vede mai la conversazione. È il prezzo
  di non avere nessuno in mezzo.
- **Non è una garanzia di conformità e non dichiara mai che l'output è pulito.**
  `report.CAVEATS` mette i limiti nel report stesso.

## Perché un altro strumento del genere

Diversi progetti ne fanno una parte. La colonna della lacuna è quella per cui
FreeDocs è stato costruito.

| Progetto | Formati | Rilevamento | Lacuna |
|---|---|---|---|
| [rizzo-pii](https://github.com/Rizzo-AI-Academy/rizzo-pii) | txt, md, PDF | mmBERT + checksum, 22 entità italiane | nessun formato Office |
| [A5-PII-Anonymizer](https://github.com/AgenticA5/A5-PII-Anonymizer) | txt, docx, xlsx, csv, pdf | Piiranha ONNX | detector debole, no OCR, no pptx |
| [phileas](https://github.com/philterd/phileas) | pdf, docx, xlsx, csv, scansioni | regex + ML | no pptx |
| [desktop-redactor](https://github.com/williape/desktop-redactor) | csv, json, txt | Presidio | nessun documento |
| [Presidio](https://github.com/microsoft/presidio) | testo, immagini, dati strutturati | NLP + pattern | nessun rilevamento della lingua, quindi tutte le lingue vengono unite: qui misurato al 21.5% di sovra-redazione |

## Stato

Tutto quello che era nel piano originale è consegnato, più la copertura
internazionale: dodici paesi di identificatori confermati da checksum, quattro
lingue di NER, un'app desktop e il layer di review opzionale. Qualsiasi cosa
oltre è lavoro nuovo, non una milestone rimasta.

<details>
<summary>Le milestone, per memoria</summary>

| M | Contenuto | Stato |
|---|---|---|
| M0 | Core, validatori L1, testo semplice, CLI, verifica, test | fatto |
| M1 | PDF testuale: redazione vera del content stream, pulizia del contenuto nascosto | fatto |
| M2 | L2 NER integrato, corpus annotato, copertura misurata | fatto |
| M3 | `docx` con riscrittura consapevole dei run e pulizia del nascosto | fatto |
| M4 | `xlsx`, comprese pivot cache e fogli `veryHidden` | fatto |
| M5 | `pptx`: note, slide nascoste, forme fuori canvas, dati dei grafici | fatto |
| M6 | PDF scansionato: OCR e redazione sui bounding box delle parole | fatto |
| M7 | App desktop Tauri | fatto |
| M8 | Review L3 con Ollama, opzionale | fatto |

</details>

Lacune note, dichiarate invece di nascoste: nessuna build per macOS Intel (serve
una macchina Intel), nessuna release firmata, nessun binario Tesseract nel bundle
portable (non può esserci: PyMuPDF lo invoca come processo esterno), e torch pesa
501 MB su un bundle da 1,0 GB che un export ONNX ridurrebbe in gran parte — dopo
aver rieseguito il benchmark per dimostrare che i numeri tengono. Gli installer
continuano a non includere un AppImage; la build portable ne produce uno.

## Contribuire

Le segnalazioni di bug sono benvenute, e una regola conta più delle altre: **non
allegare mai un documento reale.** Costruisci un file sintetico che riproduca il
problema — il template delle issue dice la stessa cosa in cima.

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, i marker dei test e le quattro
  regole che non si deducono dal codice
- [SECURITY.md](SECURITY.md) — il modello di minaccia e come segnalare una
  vulnerabilità in privato
- [docs/](docs/) — la versione lunga di tutto quello che sta qui sopra

## Licenza

[AGPL-3.0-or-later](LICENSE). Il layer PDF usa PyMuPDF, che è AGPL; restare AGPL
è ciò che rende quell'uso gratuito. I lavori derivati devono restare aperti.
