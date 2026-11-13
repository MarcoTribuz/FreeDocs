"""Package-level metadata and stores, identical across the Office formats.

``docProps/``, ``customXml/`` and the page thumbnail sit outside the format-
specific parts and leak the same things whether the file is a document, a
workbook or a presentation, so they are handled once here.
"""

from __future__ import annotations

from collections.abc import Iterable

from ...core.stream import Anchor
from ..base import HiddenItem
from .zip_part import OoxmlPackage, qn

#: Core properties worth blanking. ``dcterms:created`` and ``modified`` are left:
#: a file with no dates at all is conspicuous, and the timestamps alone identify
#: nobody.
CORE_FIELDS: tuple[tuple[str, str], ...] = (
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

#: Extended properties. ``TitlesOfParts`` is deliberately absent: in a workbook it
#: holds the sheet names, which are content and are redacted through the normal
#: detectors rather than blanked wholesale.
APP_FIELDS: tuple[tuple[str, str], ...] = (
    ("ep:Company", "company"),
    ("ep:Manager", "manager"),
    ("ep:TotalTime", "total editing time"),
    ("ep:Template", "template path"),
    ("ep:LastAuthor", "last author"),
    # The base every relative hyperlink resolves against: in practice a server
    # path or an intranet address, which names the organisation as surely as
    # ``Company`` does.
    ("ep:HyperlinkBase", "hyperlink base"),
)


def blank_fields(
    package: OoxmlPackage, part: str, fields: tuple[tuple[str, str], ...], kind: str
) -> list[HiddenItem]:
    """Remove the named elements, reporting which of them held anything.

    Removed, not emptied. Several are typed — ``cp:lastPrinted`` is an
    ``xsd:dateTime``, ``ep:TotalTime`` an ``xsd:int`` — and an empty one is not
    a valid value of either: Word called a real scrubbed document "unreadable
    content" for exactly that, while every part was well-formed XML. Every
    field here is optional in its schema, so absence is valid for all of them.
    """
    if not package.has(part):
        return []
    tree = package.tree(part)
    populated: list[str] = []
    for tag, label in fields:
        for element in list(tree.iter(qn(tag))):  # type: ignore[attr-defined]
            if element.text:
                populated.append(label)
                element.getparent().remove(element)
    if not populated:
        return []
    package.mark_dirty(part)
    return [HiddenItem(part=part, kind=kind, detail=", ".join(sorted(set(populated))))]


def scrub_core_properties(package: OoxmlPackage) -> list[HiddenItem]:
    return blank_fields(package, "docProps/core.xml", CORE_FIELDS, "metadata")


def scrub_app_properties(package: OoxmlPackage) -> list[HiddenItem]:
    return [
        *blank_fields(package, "docProps/app.xml", APP_FIELDS, "extended-metadata"),
        *drop_hyperlink_cache(package),
    ]


def blank_titles_of_parts(package: OoxmlPackage, holds: str) -> list[HiddenItem]:
    """Empty ``TitlesOfParts`` in a document or a presentation.

    Office writes a table of contents of the package here. In a Word document
    it is the title - the one ``dc:title`` already blanks in ``core.xml``, so
    leaving this copy undid that. In a presentation it is every slide title,
    beside the fonts and theme names, so a client named in a heading survived
    the redaction of the slide it heads.

    Blanked rather than redacted, because nothing here is content a reader sees:
    Office rebuilds the list on the next save. The entries are emptied rather
    than removed so the vector still agrees with its own ``size`` and with the
    counts in ``HeadingPairs``. **Not for workbooks**: there the entries are the
    sheet names, which ``XlsxHandler`` anchors and redacts in place so they
    stay in step with ``workbook.xml``.

    ``holds`` says what the list holds in the caller's format, because the
    report is read by somebody who has one document in front of them, and a
    Word user told about slide titles reads that as a mistake.
    """
    part = "docProps/app.xml"
    if not package.has(part):
        return []
    tree = package.tree(part)
    blanked = 0
    for titles in tree.iter(qn("ep:TitlesOfParts")):  # type: ignore[attr-defined]
        for tag in ("vt:lpstr", "vt:lpwstr"):
            for entry in titles.iter(qn(tag)):
                if entry.text:
                    entry.text = None
                    blanked += 1
    if not blanked:
        return []
    package.mark_dirty(part)
    return [
        HiddenItem(
            part=part,
            kind="titles-of-parts",
            detail=f"{blanked} cached title(s): {holds}",
        )
    ]


def drop_hyperlink_cache(package: OoxmlPackage) -> list[HiddenItem]:
    """Remove ``HLinks``, Office's second copy of every hyperlink target.

    Word writes each link's address into ``docProps/app.xml`` as well as into
    the relationship the link actually uses. The relationship is anchored and
    redacted; this copy was not, so on a real document every URL the scrub had
    removed from the body was still in the package, and stage 6 - which reads
    the parts a handler extracts, not ``docProps/`` - passed over all of them.

    The whole element goes rather than its strings being edited: it is a cache
    Office rebuilds on the next save, a stale one does no harm, and an emptied
    vector would still have to agree with its own ``size`` attribute.
    """
    part = "docProps/app.xml"
    if not package.has(part):
        return []
    tree = package.tree(part)
    removed = 0
    for element in list(tree.iter(qn("ep:HLinks"))):  # type: ignore[attr-defined]
        # Six variants per link; the targets are the string-valued ones.
        removed += sum(1 for value in element.iter(qn("vt:lpwstr")) if value.text)
        element.getparent().remove(element)
        package.mark_dirty(part)
    if not removed:
        return []
    return [
        HiddenItem(
            part=part,
            kind="hyperlink-cache",
            detail=f"{removed} cached hyperlink address(es)",
        )
    ]


def drop_thumbnail(package: OoxmlPackage) -> list[HiddenItem]:
    """Remove the preview image.

    Office stores a rendered picture of the first page or sheet in
    ``docProps/thumbnail.*``. Scrubbing every character of text and leaving that
    behind ships a screenshot of the unredacted file inside the redacted one. The
    extension varies by producer, so match on the stem.
    """
    out: list[HiddenItem] = []
    for name in [n for n in package.names() if n.startswith("docProps/thumbnail.")]:
        if package.drop(name):
            out.append(
                HiddenItem(
                    part=name,
                    kind="page-thumbnail",
                    detail="rendered preview of the unredacted file",
                )
            )
    return out


def drop_custom_xml(package: OoxmlPackage) -> list[HiddenItem]:
    """Remove the custom XML data store.

    ``customXml/`` is where data-bound content controls keep their source, so it
    routinely holds a structured copy of the very fields the file displays.
    """
    out: list[HiddenItem] = []
    for name in sorted(n for n in package.names() if n.startswith("customXml/")):
        if package.drop(name):
            out.append(
                HiddenItem(
                    part=name,
                    kind="custom-xml-store",
                    detail="data store behind content controls",
                )
            )
    return out


def drop_matching(
    package: OoxmlPackage, prefixes: tuple[str, ...], kind: str, detail: str
) -> list[HiddenItem]:
    """Drop every part starting with one of ``prefixes``."""
    out: list[HiddenItem] = []
    for name in sorted(package.names()):
        if name.startswith(prefixes) and package.drop(name):
            out.append(HiddenItem(part=name, kind=kind, detail=detail))
    return out


#: Producer identity rather than document content. ``Microsoft Office Word`` is
#: in nearly every file, and a document that names Microsoft as a party would
#: otherwise fail verification on the program that wrote it.
_PRODUCER_FIELDS = frozenset({qn("ep:Application"), qn("ep:AppVersion")})


def unextracted_properties_text(package: OoxmlPackage, anchors: Iterable[Anchor]) -> str:
    """Everything in ``docProps/`` that ``anchors`` do not already cover.

    For :meth:`FormatHandler.verification_extras`, so it errs towards searching
    too much: every node's text and tail, comments and processing instructions
    included, and every attribute value. Markup and identifiers in the haystack
    can only add matches, never hide one.

    Exclusion is per **element**, not per part. A workbook anchors the sheet
    names in ``TitlesOfParts`` and that text is already in the stream, so
    counting it again would break the allowance a kept occurrence earns - but
    skipping the whole of ``app.xml`` for it went blind to ``HLinks`` beside
    them, the leak this exists for. ``anchors`` must be the ones that belong to
    ``package``: a nested package's anchors name their own parts with the same
    names.

    The producer fields (``Application``, ``AppVersion``) are skipped; see
    ``_PRODUCER_FIELDS``. A part that does not parse is searched raw.
    """
    anchored_text: set[int] = set()
    anchored_attributes: set[tuple[int, str]] = set()
    for anchor in anchors:
        if not anchor.part.startswith("docProps/"):
            continue
        locator = anchor.locator
        element = getattr(locator, "element", None)
        attribute = getattr(locator, "name", None)
        if element is not None and isinstance(attribute, str):
            anchored_attributes.add((id(element), attribute))
        else:
            anchored_text.add(id(locator))

    chunks: list[str] = []
    for name in package.matching("docProps/"):
        try:
            tree = package.tree(name)
        except Exception:
            # Searched raw rather than skipped: a part verification cannot parse
            # is exactly the part it must not go blind to.
            chunks.append(package.raw(name).decode("utf-8", errors="replace"))
            continue
        for node in tree.iter():  # type: ignore[attr-defined]
            skip_text = node.tag in _PRODUCER_FIELDS or id(node) in anchored_text
            if node.text and not skip_text:
                chunks.append(node.text)
            if node.tail:
                chunks.append(node.tail)
            for key, value in getattr(node, "attrib", {}).items():
                if (id(node), key) not in anchored_attributes:
                    chunks.append(value)
    return "\n".join(chunk for chunk in chunks if chunk.strip())
