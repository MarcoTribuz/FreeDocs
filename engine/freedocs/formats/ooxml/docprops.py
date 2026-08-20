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
    return blank_fields(package, "docProps/app.xml", APP_FIELDS, "extended-metadata")


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
