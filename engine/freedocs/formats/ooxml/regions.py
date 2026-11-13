"""Name an Office part the way a reader would: a footnote, slide 3, a header.

The stream records where each character came from as a package path -
``word/footnotes.xml``, ``ppt/slides/slide7.xml`` - which means nothing to the
person told that a word was left in their document. This module turns that into
a :class:`~freedocs.formats.base.Region` for the window to translate.

**A number is given only where it is the one the reader sees.** A slide's file
name is not its position: PowerPoint keeps ``slide7.xml`` as ``slide7.xml`` when
the slide is dragged to the front, so the position is read from the order of
``sldIdLst`` in ``presentation.xml``, and a sheet's from ``<sheets>`` in
``workbook.xml``. A notes page takes the number of the slide it belongs to. A
Word document gets no numbers at all: it has no pages until Word lays it out,
and inventing one would send a reader to the wrong place.
"""

from __future__ import annotations

import posixpath

from ..base import Region
from .common import RELATIONSHIP_TAG
from .zip_part import NS, OoxmlPackage

_REL_ID = f"{{{NS['r']}}}id"


def _rels_of(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


def _targets(package: OoxmlPackage, part: str) -> dict[str, str]:
    """Relationship id to package-absolute part, for one owning part."""
    rels = _rels_of(part)
    if not package.has(rels):
        return {}
    out: dict[str, str] = {}
    for relationship in package.tree(rels).iter(RELATIONSHIP_TAG):  # type: ignore[attr-defined]
        if relationship.get("TargetMode") == "External":
            continue
        target = relationship.get("Target") or ""
        if target:
            out[relationship.get("Id") or ""] = OoxmlPackage._resolve(rels, target)
    return out


def ordered_parts(package: OoxmlPackage, owner: str, tag: str) -> dict[str, int]:
    """Position (from 1) of each part ``owner`` lists through ``tag`` elements.

    Never raises: a package whose ordering cannot be read loses its numbers,
    and a region without a number is still a correct region.
    """
    try:
        if not package.has(owner):
            return {}
        targets = _targets(package, owner)
        order: dict[str, int] = {}
        for element in package.tree(owner).iter(tag):  # type: ignore[attr-defined]
            target = targets.get(element.get(_REL_ID) or "")
            if target and target not in order:
                order[target] = len(order) + 1
        return order
    except Exception:
        return {}


def slide_of_notes(package: OoxmlPackage, notes_part: str) -> str | None:
    """The slide a notes page belongs to, read from the notes page's own rels."""
    try:
        for target in _targets(package, notes_part).values():
            if target.startswith("ppt/slides/slide"):
                return target
    except Exception:
        return None
    return None


def ooxml_region(part: str) -> Region:
    """The region of a part, by its name alone - no numbers."""
    name = posixpath.basename(part)
    if "/_rels/" in f"/{part}" or part.endswith(".rels"):
        return Region("link")
    if part.startswith("docProps/") or part.startswith("customXml/"):
        return Region("metadata")
    if part == "word/document.xml":
        return Region("body")
    if name.startswith("header"):
        return Region("header")
    if name.startswith("footer"):
        return Region("footer")
    if name == "footnotes.xml":
        return Region("footnote")
    if name == "endnotes.xml":
        return Region("endnote")
    if name.startswith("comments") or "/comments/" in part:
        return Region("comment")
    if part.startswith("xl/charts/") or part.startswith("ppt/charts/") or "/charts/" in part:
        return Region("chart")
    if part.startswith("xl/"):
        # Shared strings, the workbook's sheet names, tables, pivot caches: all
        # sheet content a reader finds in some sheet.
        return Region("sheet")
    if part.startswith("ppt/slides/"):
        return Region("slide")
    if part.startswith("ppt/notesSlides/"):
        return Region("notes")
    return Region("other")
