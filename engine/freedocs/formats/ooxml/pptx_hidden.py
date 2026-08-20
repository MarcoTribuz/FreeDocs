"""What a deck hides.

The two that matter most are not metadata at all, they are content the file keeps
and the screen does not show:

* **A hidden slide** (``<p:sld show="0">``) is skipped when presenting and fully
  intact in the file. It is where the previous client's numbers go when a deck is
  reused.
* **A shape dragged off the canvas** is the same habit without the menu. A text
  box at ``x="-4000000"`` on a slide 9144000 wide is invisible on screen, present
  in the XML, and copied along with the deck forever.

Both are reported, not removed. Their text is redacted like everything else,
because extraction walks the whole slide part rather than what would be rendered,
so keeping them costs no confidentiality — and deleting a slide renumbers the
deck and breaks every relationship pointing at it. The report exists because the
user very likely does not know they are there.
"""

from __future__ import annotations

from ..base import HiddenItem
from .docprops import (
    drop_custom_xml,
    drop_matching,
    drop_thumbnail,
    scrub_app_properties,
    scrub_core_properties,
)
from .zip_part import OoxmlPackage, qn

PRESENTATION = "ppt/presentation.xml"

#: Comment bodies and the author directory they point at. PowerPoint writes both
#: the legacy ``ppt/comments/`` parts and the modern ``ppt/authors.xml``.
COMMENT_PREFIXES = ("ppt/comments/", "ppt/authors.xml", "ppt/modernComments/")

#: Printer settings carry the printer's name, which is usually a machine or an
#: office, and occasionally a person.
DEVICE_PREFIXES = ("ppt/printerSettings/",)

#: Macros. Opaque binary, so it can only be removed.
MACRO_PREFIXES = ("ppt/vbaProject.bin",)


def scrub_pptx_hidden(package: OoxmlPackage) -> list[HiddenItem]:
    removed: list[HiddenItem] = []

    removed.extend(
        drop_matching(package, COMMENT_PREFIXES, "comments", "comment text and author list")
    )
    removed.extend(
        drop_matching(package, DEVICE_PREFIXES, "printer-settings", "printer name and page setup")
    )
    removed.extend(
        drop_matching(
            package, MACRO_PREFIXES, "macro-project", "binary macro project, cannot be redacted"
        )
    )
    removed.extend(drop_thumbnail(package))
    removed.extend(drop_custom_xml(package))
    removed.extend(scrub_core_properties(package))
    removed.extend(scrub_app_properties(package))

    removed.extend(_report_hidden_slides(package))
    removed.extend(_report_offscreen_shapes(package))
    return removed


def _report_hidden_slides(package: OoxmlPackage) -> list[HiddenItem]:
    out: list[HiddenItem] = []
    for part in package.matching("ppt/slides/slide"):
        tree = package.tree(part)
        if tree.get("show") == "0":  # type: ignore[attr-defined]
            out.append(
                HiddenItem(
                    part=part,
                    kind="hidden-slide",
                    detail="skipped when presenting, fully present in the file",
                )
            )
    return out


def _slide_size(package: OoxmlPackage) -> tuple[int, int] | None:
    """The slide canvas in EMU, or None if the presentation does not say."""
    if not package.has(PRESENTATION):
        return None
    tree = package.tree(PRESENTATION)
    for element in tree.iter(qn("p:sldSz")):  # type: ignore[attr-defined]
        try:
            return int(element.get("cx")), int(element.get("cy"))
        except (TypeError, ValueError):  # pragma: no cover - malformed input
            return None
    return None


def _report_offscreen_shapes(package: OoxmlPackage) -> list[HiddenItem]:
    """Find shapes lying entirely outside the slide canvas.

    Only shapes whose own transform puts them outside are considered. A shape
    inside a group has coordinates relative to the group, so judging it would
    need the group's transform chain; treating those as off-canvas would produce
    confident nonsense, and their text is redacted either way.
    """
    size = _slide_size(package)
    if size is None:
        return []
    width, height = size

    out: list[HiddenItem] = []
    for part in package.matching("ppt/slides/slide"):
        tree = package.tree(part)
        count = 0
        for shape in tree.iter(qn("p:sp"), qn("p:pic"), qn("p:graphicFrame")):  # type: ignore[attr-defined]
            if shape.getparent() is None or shape.getparent().tag != qn("p:spTree"):
                continue
            box = _bounding_box(shape)
            if box is None:
                continue
            left, top, right, bottom = box
            if right <= 0 or bottom <= 0 or left >= width or top >= height:
                count += 1
        if count:
            out.append(
                HiddenItem(
                    part=part,
                    kind="offscreen-shape",
                    detail=(
                        f"{count} shape(s) positioned entirely outside the slide - "
                        "invisible on screen, content redacted"
                    ),
                )
            )
    return out


def _bounding_box(shape: object) -> tuple[int, int, int, int] | None:
    for transform in shape.iter(qn("a:xfrm")):  # type: ignore[attr-defined]
        offset = transform.find(qn("a:off"))
        extent = transform.find(qn("a:ext"))
        if offset is None or extent is None:
            continue
        try:
            left, top = int(offset.get("x")), int(offset.get("y"))
            return left, top, left + int(extent.get("cx")), top + int(extent.get("cy"))
        except (TypeError, ValueError):  # pragma: no cover - malformed input
            return None
    return None
