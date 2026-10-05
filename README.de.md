<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/wordmark-dark.svg">
    <img src="docs/images/wordmark-light.svg" alt="FreeDocs" width="272">
  </picture>
</p>

<h3 align="center">Vertrauliche Daten aus einem Dokument entfernen, bevor eine KI sie zu sehen bekommt.</h3>

<p align="center">
  PDF, Word, Excel, PowerPoint und Scans — rein, bereinigt, und im selben Format wieder heraus.<br>
  Auf Ihrem Rechner, ohne jemanden dazwischen: keine Cloud, kein Auftragsverarbeiter, kein API-Key, keine Telemetrie, kein Konto.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/Lizenz-AGPL--3.0--or--later-2f9e79" alt="AGPL-3.0-or-later"></a>
  <img src="https://img.shields.io/badge/python-3.10%20%E2%80%93%203.12-2f9e79" alt="Python 3.10 bis 3.12">
  <img src="https://img.shields.io/badge/l%C3%A4uft-100%25%20offline-2f9e79" alt="Läuft vollständig offline">
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="README.it.md">Italiano</a> ·
  <b>Deutsch</b> ·
  <a href="README.fr.md">Français</a>
</p>

<p align="center"><sub>Die technische Dokumentation in <a href="docs/"><code>docs/</code></a> ist auf Englisch.</sub></p>

---

Die meisten Werkzeuge, die das versprechen, geben eine Textdatei zurück — oder sie
malen schwarze Rechtecke über Text, der darunter weiterhin markierbar bleibt.
FreeDocs bearbeitet das Dokument an Ort und Stelle. Und dann öffnet es die eigene
Ausgabe erneut, extrahiert sie samt der unsichtbaren Teile und **lässt den Lauf
scheitern, wenn ein einziger entfernter Wert überlebt hat**.

**Zwischen Ihnen und dem Modell steht niemand.** Ein Maskierungsdienst, der auf
fremden Servern läuft, erhält das Dokument vor dem Modell und ist damit ein
Auftragsverarbeiter: ein Auftragsverarbeitungsvertrag, eine Liste von
Unterauftragsverarbeitern und, für eine Anwältin oder einen Treuhänder, eine Frage
des Berufsgeheimnisses. FreeDocs hat nichts davon, weil das Dokument nirgendwohin
geht — und die Engine blockiert ausgehende Verbindungen zu allem außer diesem
Rechner, sodass eine Abhängigkeit, die nach Hause telefonieren will, scheitert wie
auf einem Laptop ohne Netz. Das stoppt den versehentlichen Aufruf, nicht
feindlichen Code; [SECURITY.md](SECURITY.md) sagt genau, wie weit es reicht.

<p align="center">
  <img src="docs/images/review.png" alt="Der Review-Schritt: das extrahierte Dokument mit jedem markierten Fund und das Detailfeld, das zeigt, was den ausgewählten Wert gefunden hat, wie sicher es ist und die zwei Wege, ihn zu behalten" width="900">
</p>

<p align="center"><sub><b>Review.</b> Jeder Fund ist im Dokument selbst markiert, denn erst der Satz um einen Wert herum sagt, ob eine Stadt die Adresse einer Vertragspartei oder eine Gerichtsstandsklausel ist. Das Feld benennt die Ebene, die ihn gefunden hat, die Konfidenz und den Teil der Datei, in dem er steckt.</sub></p>

<p align="center">
  <img src="docs/images/result.png" alt="Der Result-Schritt: zwölf entfernte Werte, die entfernten verborgenen Teile und die Prüfzeile, die bestätigt, dass die Ausgabe erneut geöffnet und durchsucht wurde" width="900">
</p>

<p align="center"><sub><b>Result.</b> Was weg ist, welche verborgenen Teile entfernt wurden, und die Zeile, auf die es ankommt: die Ausgabe wurde erneut geöffnet und durchsucht, und alle zwölf Werte sind verschwunden. Der Ausgabepfad ist in diesem Screenshot überdeckt — ein unretuschierter würde einen Benutzernamen veröffentlichen, also genau die Art von Sache, für deren Entfernung dieses Werkzeug existiert. Sonst ist nichts bearbeitet.</sub></p>

## Die Kurzfassung

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

Dieser Lauf ist reproduzierbar — die Datei ist
[`examples/offerta-esempio.docx`](examples/) — und das kam dabei heraus:

| Vorher | Nachher |
|---|---|
| Realise Consulting SA<br>Bahnhofstrasse 12, 8001 Zurigo<br>UID: CHE-116.281.710 | `[ORGANISATION_1]`<br>`[ADDRESS_1]`<br>UID: `[COMPANY_ID_1]` |
| Referente: Laura Esposito, responsabile acquisti | Referente: `[PERSON_1]`, responsabile acquisti |
| IBAN per i pagamenti: CH93 0076 2011 6238 5295 7 | IBAN per i pagamenti: `[IBAN_1]` |
| …il foro competente è **Zurigo**. | …il foro competente è **Zurigo**. |

Die letzte Zeile ist der Punkt. Die Stadt in der Adresse der Vertragspartei ist
weg; dieselbe Stadt in der Gerichtsstandsklausel bleibt unberührt, denn ein
Gerichtsstand identifiziert niemanden. Und `Laura Esposito` lag in Word als drei
getrennte Runs — heraus kam ein einziger Platzhalter, mit erhaltener
Absatzformatierung, Tabelle und Formatvorlagen.

## Was Sie bekommen

- **Denselben Dateityp zurück, weiterhin formatiert.** Runs, Tabellen, Diagramme
  und Formatvorlagen überleben, weil das Zurückschreiben die Runs und den
  PDF-Content-Stream bearbeitet, statt das Dokument zu Text plattzumachen. Teile,
  die die Engine nie geparst hat, werden als die Bytes durchkopiert, mit denen sie
  angekommen sind.
- **Die Kopien, von denen Sie nichts wussten.** Excel-Pivot-Caches, Diagramm-
  Caches und `veryHidden`-Blätter; in Word gelöschter, aber nachverfolgter Text,
  der `customXml`-Speicher und das gerenderte Seiten-Thumbnail;
  PowerPoint-Notizen, versteckte Folien, Formen außerhalb der Folie und die
  komplette Arbeitsmappe innerhalb eines Diagramms. Jeder Posten wird entfernt
  oder bereinigt und im Bericht benannt.
  → [was ein Dokument verbirgt](docs/hidden-content.md)
- **Eine Prüfstufe, die scheitern kann.** Stufe 6 öffnet die Ausgabe erneut,
  extrahiert sie und sucht nach jedem Wert, der weg sein sollte. Ein Überlebender
  beendet den Lauf mit einem Fehlercode, und **es wird nichts geschrieben** — denn
  eine fast saubere Datei ist gefährlicher als eine offensichtlich schmutzige: sie
  wird verschickt.
- **Zahlen, die Sie selbst nachrechnen können.** `freedocs benchmark` bewertet die
  Ebenen gegen ein annotiertes Korpus, und das Werkzeug druckt jedes Mal seinen
  eigenen Vorbehalt mit. → [Benchmark](docs/benchmark.md)
- **Standardmäßig unumkehrbar; der Weg zurück nur auf Wunsch.** `--map` schreibt
  eine verschlüsselte Schlüsseldatei, und `freedocs restore` setzt die echten
  Werte in das ein, was das Modell zurückgibt. Standardmäßig aus, denn es ist das
  Einzige, was eine Bereinigung umkehrbar macht: ohne sie wird die Zuordnung am
  Ende des Laufs zerstört und niemand kann sie rückgängig machen, Sie
  eingeschlossen. → [der umgekehrte Weg](docs/restore.md)

## Schnellstart

**Kommandozeile**

```bash
git clone https://github.com/MarcoTribuz/FreeDocs.git
cd FreeDocs/engine
uv sync --extra dev --extra pdf --extra ooxml --extra ner   # ner lädt ~1,2 GB Modellgewichte

uv run freedocs inspect ../examples/offerta-esempio.docx    # melden, nichts schreiben
uv run freedocs scrub   ../examples/offerta-esempio.docx -o out/
uv run freedocs doctor                                      # was dieser Rechner wirklich kann
```

Ohne `--extra ner` funktioniert alles weiter, allein auf Prüfsummen, und jeder
Bericht sagt, dass Namen, Organisationen, Orte und Adressen nicht erkannt werden.
Ein Build, der weniger findet, muss das sagen.
→ [vollständige CLI-Referenz](docs/cli.md)

**Desktop-App**

```bash
cd app && npm install
npm run tauri build     # oder: npm run tauri dev
```

Es gibt noch kein signiertes Release zum Herunterladen. Die Installer werden in
der CI für macOS, Linux und Windows bei jedem Push auf `main` gebaut; macOS ist
das einzige, das ein Mensch tatsächlich gestartet hat — für die anderen zwei lesen
Sie also "baut" und nicht "funktioniert". → [Packaging](docs/packaging.md)

Es gibt außerdem ein portables Bundle pro Plattform: entpacken und starten, ohne
Installation und ohne Netz, mit dem 1,2-GB-Modell darin statt beim ersten Start
geladen. Deshalb sind es 1405 MB. → [portable](docs/portable.md)

## Was es findet

| | |
|---|---|
| **Formate** | reiner Text, PDF (digital erzeugt und gescannt), `docx`, `xlsx`, `pptx` |
| **Entfernt** | Person, Organisation, Adresse, Ort, E-Mail, Telefon, IBAN, Kreditkarte, Ausweisnummer, Steuernummer, USt-IdNr., Handelsregisternummer, IP, MAC, URL |
| **Markiert, nie entfernt** | Berufsbezeichnung, Datum, Alter, Postleitzahl — Quasi-Identifikatoren: eines davon zu löschen verbirgt das Restrisiko, anstatt es zu zeigen |
| **Per Prüfsumme bestätigte Kennungen** | 🇨🇭 🇮🇹 🇩🇪 🇦🇹 🇫🇷 🇧🇪 🇪🇸 🇵🇹 🇳🇱 🇵🇱 🇸🇪 🇬🇧 — zwölf Länder, vierzig Regeln |
| **Gelesene Sprachen** | Italienisch, Deutsch, Französisch, Englisch, aus einem Modell ohne Sprachhinweis |

`freedocs countries` druckt, was jedes Land tatsächlich bekommt. Die USA stehen in
dieser Liste ohne jede Prüfsummenregel, weil keine ihrer beiden Nummern eine
Prüfziffer hat: `stdnum.us.ssn` akzeptiert 89 % zufälliger Werte dieser Form.
Diese Kennungen kommen stattdessen vom Modell, und das Werkzeug sagt es, statt
eine Regel in die Tabelle zu erfinden.

## Wie es entscheidet

Drei Ebenen, und die strenge hat das letzte Wort.

**Zuerst die Prüfsummen.** Ein Regex nominiert, eine Prüfziffer entscheidet.
Vierzig Regeln über zwölf Länder, jeder Validator aus `python-stdnum`. Die
Konfidenz jeder Regel ist eine Messung, kein Urteil: jeder Validator wurde gegen
20 000 zufällige, formal plausible Werte laufen gelassen, um zu zählen, wie viele
er akzeptiert. Die schwächsten Regeln liegen unter der Standardschwelle — gefunden
und gemeldet, nie entfernt, solange kein sie benennendes Wort daneben steht.

**Dann ein mehrsprachiger Encoder** (GLiNER2 auf `mdeberta-v3-base`) für das, was
keine Prüfsumme bestätigen kann: Namen, Organisationen, Orte, Adressen,
Berufsbezeichnungen. Ein Modell, vier Sprachen, kein Sprachhinweis — und er muss
Zeichen-Offsets liefern, denn Offsets sind es, was die Anker brauchen.

**Dann prüfen die Prüfsummen das Modell.** GLiNER2 hielt zwei benachbarte
Diagrammbeträge mit 0.87 Konfidenz für eine Kreditkarte; keine Schwelle trennt das
von einem echten Fund, und Luhn erledigt es in einem Aufruf. Behauptet das Modell
einen strukturierten Typ, hat die passende Prüfsumme das letzte Wort — außer wenn
sich nicht feststellen lässt, welches Land ihn ausgegeben hat: dann gibt es keine
Meinung, und der Fund überlebt.

Drei Korrekturdurchläufe räumen anschließend die Freitext-Ebene auf: eine Adresse
wird von ihrer Postleitzahl aus nach außen zusammengesetzt (der Teil, der kein
Modell braucht), ein Firmenname wird aus der ihm folgenden Rechtsform gewonnen,
und Funde, die etwas Reales benennen, aber niemanden identifizieren, werden
verworfen. Der letzte ist der Grund, weshalb `Zurigo` oben in der
Gerichtsstandsklausel geblieben ist. → [Architektur](docs/architecture.md)

## Gemessen, nicht versprochen

537 annotierte Entitäten in italienischen, deutschen, französischen und
englischen Geschäftsdokumenten; 485 davon sind Entitäten, die die Policy
tatsächlich entfernt.

| Ebenen | Abdeckung | Über-Redaktion | Exakter Mikro-F1 |
|---|---|---|---|
| Nur Prüfsummen | 70.3 % | 1.1 % | 0.738 |
| Nur Encoder | 86.6 % | 1.7 % | 0.793 |
| **Beide (Standard)** | **99.6 %** | **2.2 %** | **0.929** |

**Abdeckung** meint Gold-Entitäten, die *vollständig* entfernt wurden — ein
Teil-Span ist ein Leck, denn ein übrig gebliebenes `Rossi` identifiziert immer noch
jemanden. **Über-Redaktion** meint entfernte Zeichen, die nicht vertraulich waren,
denn ein Detektor, der die Seite schwärzt, verliert nichts und ist nutzlos. Der F1
steht absichtlich an dritter Stelle: er ist die Zahl, die am besten aussieht und
hier am wenigsten bedeutet.

Jede Zeile lässt sich mit `--detectors l1`, `--detectors ner` oder ganz ohne Flag
reproduzieren; `--apply-min-confidence 0.5` berichtet, was ein Scrub tut, statt
was der Detektor nominiert hat. **Das Korpus ist klein und synthetisch — diese
Zahlen ordnen Konfigurationen gegeneinander ein und sind kein
veröffentlichungsfähiges Benchmark-Ergebnis.** Das Werkzeug druckt diesen
Vorbehalt selbst, jedes Mal. → [Benchmark](docs/benchmark.md)

## Was es nicht tut

Die ehrliche Liste, denn die Fehler eines solchen Werkzeugs sind von Natur aus
lautlos.

- **Es beseitigt das Re-Identifikationsrisiko nicht.** Ein Dokument ohne jeden
  Namen kann immer noch sagen: "die einzige Partnerin im Büro Lugano, eingestellt
  im März 2019". Quasi-Identifikatoren werden markiert und berichtet, niemals
  stillschweigend umgeschrieben. Ein optionaler Durchlauf mit einem lokalen LLM
  *liest* die anonymisierte Ausgabe und zeigt genau darauf — beratend, und er
  ändert nichts. → [die zweite Meinung](docs/llm-review.md)
- **Auf einem Scan ist OCR eine Lesung und nicht der Text.** Eine Steuernummer mit
  einem falsch gelesenen Zeichen scheitert an ihrer Prüfsumme, wird nie erkannt
  und überlebt. Jede maschinell gelesene Seite wird in einer Warnung benannt, mit
  der Aufforderung, sie mit den Augen zu prüfen.
- **Ortsnamen, die auch Familiennamen sind, sind die Schwachstelle.** Beide
  verbleibenden Lecks im Korpus sind eine Stadt, die im selben Dokument auch als
  Nachname einer Person auftaucht. Die LOCATION-Abdeckung liegt bei 94.3 % gegen
  100 % bei PERSON.
- **Einen Namen in Excel zu bereinigen benennt die Sache um.** Formeln verweisen
  über den Namen auf Blätter und Tabellen, ein bereinigter Blattname bricht also
  die Verweise darauf. Es wird trotzdem getan — den Namen stehen zu lassen würde
  die Leck-Prüfung nicht bestehen — und als Warnung berichtet, die benennt, was
  sich geändert hat.
- **Ein Makroprojekt lässt sich nicht bereinigen, nur entfernen.**
- **Eine Schlüsseldatei ist so vertraulich wie das Originaldokument.** Wenn Sie mit
  `--map` eine anfordern, kann diese Datei jeden entfernten Wert zurücksetzen. Sie
  ist verschlüsselt und wird im Zielordner abgelehnt; danach liegt sie in Ihrer
  Verantwortung: verschicken Sie sie nie mit der bereinigten Kopie. Sie kann auch
  nichts zurückbringen, was *entfernt* statt ersetzt wurde — Vorschaubilder,
  Metadaten, versteckte Folien — denn dafür gab es nie einen Platzhalter.
  → [der umgekehrte Weg](docs/restore.md)
- **Es spricht nicht an Ihrer Stelle mit dem Modell.** Sie fügen die bereinigte
  Kopie in den Assistenten ein, den Sie verwenden, und FreeDocs sieht das Gespräch
  nie. Das ist der Preis dafür, dass niemand dazwischensteht.
- **Es ist keine Compliance-Garantie und behauptet nie, die Ausgabe sei saubere
  Ware.** `report.CAVEATS` schreibt die Grenzen in den Bericht selbst.

## Warum noch so ein Werkzeug

Mehrere Projekte erledigen einen Teil davon. Die Lücken-Spalte ist der Grund, aus
dem FreeDocs gebaut wurde.

| Projekt | Formate | Erkennung | Lücke |
|---|---|---|---|
| [rizzo-pii](https://github.com/Rizzo-AI-Academy/rizzo-pii) | txt, md, PDF | mmBERT + Prüfsummen, 22 italienische Entitäten | keine Office-Formate |
| [A5-PII-Anonymizer](https://github.com/AgenticA5/A5-PII-Anonymizer) | txt, docx, xlsx, csv, pdf | Piiranha ONNX | schwacher Detektor, kein OCR, kein pptx |
| [phileas](https://github.com/philterd/phileas) | pdf, docx, xlsx, csv, Scans | Regex + ML | kein pptx |
| [desktop-redactor](https://github.com/williape/desktop-redactor) | csv, json, txt | Presidio | keine Dokumente |
| [Presidio](https://github.com/microsoft/presidio) | Text, Bilder, strukturierte Daten | NLP + Muster | keine Spracherkennung, also werden alle Sprachen zusammengeführt: hier mit 21.5 % Über-Redaktion gemessen |

## Stand

Alles aus dem ursprünglichen Plan ist ausgeliefert, dazu die internationale
Abdeckung: zwölf Länder mit prüfsummenbestätigten Kennungen, vier Sprachen NER,
eine Desktop-App und die optionale Review-Ebene. Alles Weitere ist neue Arbeit und
kein offener Meilenstein.

<details>
<summary>Die Meilensteine, fürs Protokoll</summary>

| M | Inhalt | Stand |
|---|---|---|
| M0 | Kern, L1-Validatoren, reiner Text, CLI, Verifikation, Tests | fertig |
| M1 | PDF-Text: echte Content-Stream-Redaktion, Bereinigung verborgener Inhalte | fertig |
| M2 | L2-NER integriert, annotiertes Korpus, gemessene Abdeckung | fertig |
| M3 | `docx` mit run-bewusstem Zurückschreiben und Bereinigung des Verborgenen | fertig |
| M4 | `xlsx`, inklusive Pivot-Caches und `veryHidden`-Blätter | fertig |
| M5 | `pptx`: Notizen, versteckte Folien, Formen außerhalb der Folie, Diagrammdaten | fertig |
| M6 | Gescanntes PDF: OCR und Redaktion auf Wort-Bounding-Boxen | fertig |
| M7 | Tauri-Desktop-App | fertig |
| M8 | L3-Ollama-Review, optional | fertig |

</details>

Bekannte Lücken, genannt statt versteckt: kein Build für Intel-macOS (braucht
einen Intel-Rechner), noch kein signiertes Release, keine Tesseract-Binary im
portablen Bundle (die kann es nicht geben — PyMuPDF ruft sie als externen Prozess
auf), und torch macht 501 MB eines 1,0-GB-Bundles aus, das ein ONNX-Export
größtenteils entfernen würde — nachdem der Benchmark erneut gelaufen ist und
belegt, dass die Zahlen halten. Die Installer enthalten weiterhin kein AppImage;
der portable Build erzeugt eines.

## Mitmachen

Fehlerberichte sind willkommen, und eine Regel zählt mehr als die anderen:
**niemals ein echtes Dokument anhängen.** Bauen Sie eine synthetische Datei, die
das Problem reproduziert — die Issue-Vorlage sagt oben dasselbe.

- [CONTRIBUTING.md](CONTRIBUTING.md) — Setup, die Test-Marker und die vier Regeln,
  die sich nicht aus dem Code ergeben
- [SECURITY.md](SECURITY.md) — das Bedrohungsmodell und wie man eine
  Sicherheitslücke privat meldet
- [docs/](docs/) — die lange Fassung von allem oben

## Lizenz

[AGPL-3.0-or-later](LICENSE). Die PDF-Ebene nutzt PyMuPDF, das AGPL ist; bei AGPL
zu bleiben ist es, was diese Nutzung kostenlos macht. Abgeleitete Werke müssen
offen bleiben.
