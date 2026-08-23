# What a document keeps where you cannot see it

The visible text is the easy part. Everything below was found by building a
realistic file and looking inside the container, and every item is removed or
redacted, and named in the report.

## Word

- **Deleted text is still in the file.** With track changes on, `<w:del>` keeps
  the removed words in `<w:delText>`. The paragraph someone cut because it named
  the wrong client is there verbatim, and Word shows it to anyone who turns markup
  on.
- **A rendered thumbnail of the first page.** `docProps/thumbnail.jpeg` is a
  picture of the unredacted document, shipped inside the redacted one. Scrubbing
  every character of text and leaving this behind achieves nothing, and no amount
  of reading `document.xml` reveals it.
- **Hyperlink targets live outside the body.** The visible link text is in
  `document.xml`; `mailto:mario.rossi@example.com` is in `document.xml.rels`.
  Redacting what you can read leaves the address behind.
- **`<w:instrText>`** holds a HYPERLINK field's target.
- **Comments are separate parts**, and `people.xml` maps each commenter to a name
  and usually an email.
- **`customXml/`** is the data store behind content controls, so it holds a
  structured copy of the fields shown in the document.
- **Headers, footers and footnotes** are separate parts too.
- **Revision save IDs** (`w:rsid*`) are stable per editing session and link two
  documents to the same author.
- **Metadata** names the author, the last editor, the company, the manager, and
  the local template path — which contains a username.

Relationship targets reach the pipeline as ordinary anchors through
`AttributeLocator` rather than being pattern-matched in the handler: the
detectors already know what an email looks like, and a second place deciding that
is a second answer.

## Excel

A workbook keeps more copies of its own content than any other format, and each
one survives redacting every cell on every sheet.

- **The pivot cache** stores its own copy of the source rows. A pivot over a staff
  table contains the staff table. It is *redacted in place* rather than deleted,
  so the pivot keeps working — dropping it would leave the pivot blank until
  someone refreshes it.
- **Chart caches** hold the category labels, which are usually the names.
- **External links** cache the last-seen values of the workbook they point at, and
  their relationship target is a UNC path containing a username.
- **Sheet names appear twice**, in `xl/workbook.xml` and again in
  `docProps/app.xml` as `TitlesOfParts`. Redacting one is a leak.
- **`veryHidden` sheets** are not in the sheet-tab menu at all — unhiding one needs
  the VBA editor — so they are where the raw extract behind a report ends up and
  gets forgotten.
- **Connection strings and Power Query scripts** carry server names, file paths and
  occasionally credentials.
- **The macro project** is opaque binary that cannot be redacted, only removed.

Hidden sheets, rows and columns are reported but kept: their text is redacted like
everything else, and deleting a sheet breaks every formula referencing it.

Two consequences worth knowing before running this on a workbook full of formulas:

- **Redacting a name renames the thing.** Excel refers to sheets and tables *by
  name* in formulas, so a redacted sheet name breaks the references to it. It is
  done anyway, because leaving identifying names in the file would fail the leak
  check, and the rename is reported as a warning naming what changed.
  `AttributeLocator.sanitise` exists because `[` and `]` are illegal in a sheet
  name and `[PERSON_1]` contains both — without it the output was a workbook Excel
  refused to open.
- **Numeric cells are anchored only at nine digits or more.** A sheet is mostly
  numbers and the eleven-digit partita IVA checksum passes on roughly one in ten
  arbitrary numbers of that length, so anchoring every amount would turn the ledger
  into placeholders. A `t="s"` cell's `<v>` is an index into the string table, not
  text: editing it repoints the cell at an unrelated string.

## PowerPoint

- **A chart carries its whole source workbook.** `ppt/embeddings/*.xlsx` is a
  complete OOXML package inside the presentation — sheets, string table, metadata.
  A chart of three bars can hold five hundred rows. FreeDocs nests a real
  `XlsxHandler` inside the deck and folds its anchors into the same stream, so the
  workbook inside the chart gets the same treatment as a workbook on its own. A
  pptx-in-pptx is excluded to bound the recursion.
- **Speaker notes** are a separate part per slide, invisible while presenting, and
  where the blunt version of the sentence tends to live.
- **Hidden slides** (`<p:sld show="0">`) are skipped when presenting and fully
  intact in the file.
- **Shapes dragged off the canvas** are the same habit without the menu: a text box
  at `x="-4000000"` on a slide 9144000 EMU wide is invisible and complete.
- **Alt text** on a shape is a description someone typed, so it can say anything.
- **SmartArt keeps its own data model** in `ppt/diagrams/`, duplicating the text it
  renders.

Hidden slides and off-canvas shapes are reported but kept: extraction walks the
whole slide part rather than what would be rendered, so their text is redacted
either way, and deleting a slide renumbers the deck.

## PDF

**Redaction removes, it does not cover.** `formats/pdf_text.py` uses PyMuPDF
`apply_redactions()` and always a full rewrite (`garbage=4, clean=True,
deflate=True`). Never overlay rectangles — the text stays selectable underneath,
which is the bug in more than one tool that claims to redact. Never save
incrementally: that appends the new version and leaves the redacted originals
earlier in the same file.

**PyMuPDF's `scrub()` does not remove annotations.** It has flags for links and
annotation responses but none for annotations themselves, so `scrub_hidden()`
deletes them explicitly. This regressed once: a sticky note reading
"cliente moroso" was still in the output while the report claimed the annotation
had been removed. Metadata also survives `garbage=4, clean=True` unless cleared.

Scans are their own subject — see [scanned-pdfs.md](scanned-pdfs.md).

## How write-back stays safe

**Office write-back goes through `lxml` on the zip parts.** `openpyxl`,
`python-docx` and `python-pptx` have no management API for charts, images or pivot
tables and can drop them on save, so the engine never uses them.
`formats/ooxml/zip_part.py` reads the container once and rewrites only the parts
that were both parsed *and* marked dirty. Everything else is copied through as the
bytes it arrived as, which cannot lose what it never parsed —
`test_docx_real.py` asserts `styles.xml` and `theme1.xml` come back
byte-identical.

Those two libraries *are* dev dependencies: they produce realistic packages to
validate against, so the suite is not just checking our own hand-built XML back at
us, and they read the output to confirm the file still opens. They also disagree
with Excel — openpyxl writes inline strings where Excel writes a shared string
table — which is why both paths are handled and both are covered by a fixture.

**Dropping a part means dropping what points at it.** `OoxmlPackage.drop()`
removes the part, any relationship resolving to it, and its
`[Content_Types].xml` override. Doing only the first leaves a dangling reference:
Word offers to repair the file and a strict consumer rejects it. Relationship
targets are relative to the *owning part's* directory.

**`xml:space="preserve"` is not optional.** When a replacement gains leading or
trailing whitespace it must be set, or Word eats the space and the words fuse.
Only ever added, never removed.

**Degradations get reported, never swallowed.** `FormatHandler.warn()` feeds
`ScrubResult.warnings`, the JSON report and the CLI. It exists because PyMuPDF
*silently drops* replacement text that does not fit its rectangle: the removal
still happens, but the placeholder vanishes without a word. The handler shrinks
the font and warns if even that fails.

## How the leak tests are written

- **A PDF leak test must decompress.** Content streams are Flate-compressed, so
  searching the raw file bytes for a canary proves nothing. `tests/test_pdf.py`
  walks every xref and searches the decompressed streams.
- **An OOXML leak test must search inside the zip parts**, not the zip.
- **A nested format needs the inner zip opened.** A chart's workbook is a zip
  inside a zip, so a single-level search reports a clean file that is not.
  `tests/test_pptx.py::survives_anywhere` descends one level and returns the part
  name, so a failure says where.
