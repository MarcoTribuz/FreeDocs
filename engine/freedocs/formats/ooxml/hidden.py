"""Everything in a Word file that the reader never sees.

The visible text is the easy part. What actually leaks:

* **Deleted text is still there.** With track changes on, ``<w:del>`` keeps the
  removed words in ``<w:delText>``. A paragraph someone cut because it named the
  wrong client is in the file, verbatim, and Word will show it to anyone who
  turns markup on.
* **Every revision carries an author and a timestamp.** ``w:author`` appears on
  insertions, deletions, moves and formatting changes.
* **Comments are separate parts.** Redacting the body does nothing to
  ``comments.xml``, and ``people.xml`` maps each commenter to their name and
  often their email.
* **Metadata names people.** ``creator``, ``lastModifiedBy``, ``Company``,
  ``Manager``, and the total editing time.
* **Revision save IDs fingerprint the editing session.** ``w:rsid*`` attributes
  are stable per session and let two documents be linked to the same author.

The approach is: accept insertions, drop deletions, strip the markup, remove the
comment machinery, blank the metadata. Every removal is reported by name, because
a report that cannot say *what* went teaches the user nothing about where their
leaks live.
"""

from __future__ import annotations

from ..base import HiddenItem
from .zip_part import NS, OoxmlPackage, qn

#: Dropped whole. Comment bodies, the commenter directory, and custom properties
#: that applications use as a scratchpad.
DISPOSABLE_PARTS: tuple[tuple[str, str], ...] = (
    ("word/comments.xml", "comments"),
    ("word/commentsExtended.xml", "comment-threading"),
    ("word/commentsIds.xml", "comment-ids"),
    ("word/commentsExtensible.xml", "comment-metadata"),
    ("word/people.xml", "commenter-directory"),
    ("docProps/custom.xml", "custom-properties"),
)

#: Revision elements whose *content* must go: the text they hold was removed from
#: the document and only survives as markup.
CONTENT_REMOVING = ("w:del", "w:moveFrom")

#: Revision elements to unwrap: their content is real, visible document text and
#: only the revision marking around it carries the author.
CONTENT_KEEPING = ("w:ins", "w:moveTo")

#: Revision records with no content of their own, holding an author, a date and
#: the previous formatting.
MARKUP_ONLY = (
    "w:pPrChange",
    "w:rPrChange",
    "w:tblPrChange",
    "w:tcPrChange",
    "w:trPrChange",
    "w:sectPrChange",
    "w:tblGridChange",
    "w:cellIns",
    "w:cellDel",
    "w:cellMerge",
    "w:moveFromRangeStart",
    "w:moveFromRangeEnd",
    "w:moveToRangeStart",
    "w:moveToRangeEnd",
)

#: Comment anchors left in the body once the comment parts are gone.
COMMENT_MARKERS = ("w:commentRangeStart", "w:commentRangeEnd", "w:commentReference")

#: Session fingerprints. Not personal data on their own, but they link documents
#: to the same editing session, which is exactly the kind of inference this tool
#: exists to prevent.
RSID_ATTRIBUTES = (
    "w:rsid",
    "w:rsidR",
    "w:rsidRPr",
    "w:rsidRDefault",
    "w:rsidDel",
    "w:rsidP",
    "w:rsidTr",
    "w:rsidSect",
)

#: Core properties worth blanking, by local name. ``dcterms:created`` and
#: ``modified`` are left: a document with no dates at all is conspicuous, and the
#: timestamps alone identify nobody.
CORE_FIELDS = (
    ("dc:creator", "author"),
    ("cp:lastModifiedBy", "last editor"),
    ("cp:revision", "revision count"),
    ("cp:lastPrinted", "last printed"),
    ("dc:title", "title"),
    ("dc:subject", "subject"),
    ("dc:description", "description"),
    ("cp:keywords", "keywords"),
    ("cp:category", "category"),
    ("cp:contentStatus", "content status"),
)

#: Extended properties, in the ``ep`` namespace.
APP_FIELDS = (
    ("ep:Company", "company"),
    ("ep:Manager", "manager"),
    ("ep:TotalTime", "total editing time"),
    ("ep:Template", "template path"),
    ("ep:LastAuthor", "last author"),
)


def _drop_element(element: object) -> None:
    parent = element.getparent()  # type: ignore[attr-defined]
    if parent is not None:
        parent.remove(element)


def _unwrap_element(element: object) -> None:
    """Replace an element with its children, keeping document order.

    Used for insertions: the words stay, the ``w:author`` around them goes.
    """
    parent = element.getparent()  # type: ignore[attr-defined]
    if parent is None:
        return
    index = list(parent).index(element)
    for offset, child in enumerate(list(element)):  # type: ignore[call-overload]
        parent.insert(index + offset, child)
    # Text directly on the wrapper is rare but real; losing it would delete
    # content rather than markup.
    tail = element.tail  # type: ignore[attr-defined]
    if tail:
        previous = parent[index - 1] if index > 0 else None
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(element)


def scrub_docx_hidden(package: OoxmlPackage) -> list[HiddenItem]:
    """Remove non-visible content from a Word package, reporting each removal."""
    removed: list[HiddenItem] = []

    for name, kind in DISPOSABLE_PARTS:
        if package.drop(name):
            removed.append(HiddenItem(part=name, kind=kind, detail="part removed"))

    removed.extend(_drop_thumbnail(package))
    removed.extend(_drop_custom_xml(package))
    removed.extend(_scrub_core_properties(package))
    removed.extend(_scrub_app_properties(package))

    for part in _xml_body_parts(package):
        removed.extend(_scrub_revisions(package, part))

    removed.extend(_scrub_settings(package))
    return removed


def _drop_thumbnail(package: OoxmlPackage) -> list[HiddenItem]:
    """Remove the document preview image.

    Word stores a rendered picture of the first page in ``docProps/thumbnail.*``.
    Scrubbing every character of text and leaving that behind ships a screenshot
    of the unredacted document inside the redacted file. The extension varies by
    producer, so match on the stem rather than a fixed name.
    """
    out: list[HiddenItem] = []
    for name in [n for n in package.names() if n.startswith("docProps/thumbnail.")]:
        if package.drop(name):
            out.append(
                HiddenItem(
                    part=name,
                    kind="page-thumbnail",
                    detail="rendered preview of the unredacted first page",
                )
            )
    return out


def _drop_custom_xml(package: OoxmlPackage) -> list[HiddenItem]:
    """Remove the custom XML data store.

    ``customXml/`` is where data-bound content controls keep their source, so it
    routinely holds a structured copy of the very fields shown in the document —
    a record with the client's details in it, sitting outside the body text.
    """
    parts = sorted(n for n in package.names() if n.startswith("customXml/"))
    out: list[HiddenItem] = []
    for name in parts:
        if package.drop(name):
            out.append(
                HiddenItem(
                    part=name,
                    kind="custom-xml-store",
                    detail="data store behind content controls",
                )
            )
    return out


def _xml_body_parts(package: OoxmlPackage) -> list[str]:
    """Parts that can carry revision markup and comment anchors."""
    parts = [name for name in ("word/document.xml",) if package.has(name)]
    for prefix in ("word/header", "word/footer", "word/footnotes", "word/endnotes"):
        parts.extend(package.matching(prefix))
    return parts


def _scrub_revisions(package: OoxmlPackage, part: str) -> list[HiddenItem]:
    tree = package.tree(part)
    counts: dict[str, int] = {}
    touched = False

    # Deletions first: their content must not survive being unwrapped by a later
    # pass over a shared ancestor.
    for tag in CONTENT_REMOVING:
        for element in list(tree.iter(qn(tag))):  # type: ignore[attr-defined]
            _drop_element(element)
            counts[tag] = counts.get(tag, 0) + 1
            touched = True

    for tag in CONTENT_KEEPING:
        for element in list(tree.iter(qn(tag))):  # type: ignore[attr-defined]
            _unwrap_element(element)
            counts[tag] = counts.get(tag, 0) + 1
            touched = True

    for tag in (*MARKUP_ONLY, *COMMENT_MARKERS):
        for element in list(tree.iter(qn(tag))):  # type: ignore[attr-defined]
            _drop_element(element)
            counts[tag] = counts.get(tag, 0) + 1
            touched = True

    rsids = 0
    for element in tree.iter():  # type: ignore[attr-defined]
        for attribute in RSID_ATTRIBUTES:
            if element.get(qn(attribute)) is not None:
                del element.attrib[qn(attribute)]
                rsids += 1
                touched = True

    if touched:
        package.mark_dirty(part)

    out: list[HiddenItem] = []
    deleted_text = sum(counts.get(tag, 0) for tag in CONTENT_REMOVING)
    if deleted_text:
        out.append(
            HiddenItem(
                part=part,
                kind="tracked-deletions",
                detail=(
                    f"{deleted_text} deletion(s) removed - their text was still in "
                    "the file and visible with markup turned on"
                ),
            )
        )
    accepted = sum(counts.get(tag, 0) for tag in CONTENT_KEEPING)
    if accepted:
        out.append(
            HiddenItem(
                part=part,
                kind="tracked-insertions",
                detail=f"{accepted} insertion(s) accepted, author and date stripped",
            )
        )
    markup = sum(counts.get(tag, 0) for tag in MARKUP_ONLY)
    if markup:
        out.append(
            HiddenItem(
                part=part,
                kind="revision-markup",
                detail=f"{markup} formatting-change record(s) naming an author",
            )
        )
    markers = sum(counts.get(tag, 0) for tag in COMMENT_MARKERS)
    if markers:
        out.append(HiddenItem(part=part, kind="comment-anchors", detail=f"{markers} marker(s)"))
    if rsids:
        out.append(
            HiddenItem(
                part=part,
                kind="revision-save-ids",
                detail=f"{rsids} rsid attribute(s) fingerprinting the editing session",
            )
        )
    return out


def _blank_fields(
    package: OoxmlPackage, part: str, fields: tuple[tuple[str, str], ...], kind: str
) -> list[HiddenItem]:
    if not package.has(part):
        return []
    tree = package.tree(part)
    populated: list[str] = []
    for tag, label in fields:
        for element in tree.iter(qn(tag)):  # type: ignore[attr-defined]
            if element.text:
                populated.append(label)
                element.text = None
    if not populated:
        return []
    package.mark_dirty(part)
    return [HiddenItem(part=part, kind=kind, detail=", ".join(sorted(set(populated))))]


def _scrub_core_properties(package: OoxmlPackage) -> list[HiddenItem]:
    return _blank_fields(package, "docProps/core.xml", CORE_FIELDS, "metadata")


def _scrub_app_properties(package: OoxmlPackage) -> list[HiddenItem]:
    return _blank_fields(package, "docProps/app.xml", APP_FIELDS, "extended-metadata")


def _scrub_settings(package: OoxmlPackage) -> list[HiddenItem]:
    """Remove the session id table from ``settings.xml``.

    ``w:rsids`` lists every revision save id the document has ever used, so
    stripping the attributes without removing the table leaves the history.
    """
    part = "word/settings.xml"
    if not package.has(part):
        return []
    tree = package.tree(part)
    out: list[HiddenItem] = []
    for element in list(tree.iter(qn("w:rsids"))):  # type: ignore[attr-defined]
        count = len(list(element))
        _drop_element(element)
        package.mark_dirty(part)
        out.append(
            HiddenItem(
                part=part,
                kind="revision-save-id-table",
                detail=f"{count} recorded editing session(s)",
            )
        )
    return out


#: Relationship targets are read by the docx handler rather than scrubbed here,
#: because the right thing to do with them is to run the normal detectors over
#: them. See ``DocxHandler.extract``.
RELATIONSHIP_TAG = f"{{{NS['rel']}}}Relationship"
