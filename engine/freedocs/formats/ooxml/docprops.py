"""Package-level metadata and stores, identical across the Office formats.

``docProps/``, ``customXml/`` and the page thumbnail sit outside the format-
specific parts and leak the same things whether the file is a document, a
workbook or a presentation, so they are handled once here.
"""

from __future__ import annotations

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
    """Empty the named elements, reporting which of them held anything."""
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


def scrub_core_properties(package: OoxmlPackage) -> list[HiddenItem]:
    return blank_fields(package, "docProps/core.xml", CORE_FIELDS, "metadata")


def scrub_app_properties(package: OoxmlPackage) -> list[HiddenItem]:
    return [
        *blank_fields(package, "docProps/app.xml", APP_FIELDS, "extended-metadata"),
        *drop_hyperlink_cache(package),
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


def unextracted_properties_text(package: OoxmlPackage, anchored_parts: set[str]) -> str:
    """The text of every ``docProps/`` part the handler did not extract.

    For :meth:`FormatHandler.verification_extras`. Text nodes only: attribute
    values here are schema URIs and identifiers, and a value hiding in one is
    not how these parts are written. Parts already in the stream are skipped
    (a workbook anchors ``TitlesOfParts`` to redact its sheet names), because
    counting them twice would break a kept occurrence's allowance.
    """
    chunks: list[str] = []
    for name in package.matching("docProps/"):
        if name in anchored_parts:
            continue
        try:
            tree = package.tree(name)
        except Exception:
            # Searched raw rather than skipped: a part verification cannot parse
            # is exactly the part it must not go blind to. Markup in the haystack
            # can only add matches, never hide one.
            chunks.append(package.raw(name).decode("utf-8", errors="replace"))
            continue
        for element in tree.iter():  # type: ignore[attr-defined]
            if element.tag in _PRODUCER_FIELDS:
                continue
            if isinstance(element.tag, str) and element.text and element.text.strip():
                chunks.append(element.text)
    return "\n".join(chunks)
