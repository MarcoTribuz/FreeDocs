"""Anchoring and write-back shared by every Office format.

Word, Excel and PowerPoint keep their text in different elements but need the
same two things: a way to anchor an XML *attribute* as well as element text, and
one place where an edit is turned back into a change on the tree.

Attributes matter more than they sound. A hyperlink's address, a sheet's name, a
table column heading and every value in a pivot cache are attributes, not text
nodes. A handler that only anchors ``.text`` cannot reach any of them, and those
are exactly the places a reader never looks.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ...core.stream import AnchorEdit, TextStreamBuilder, apply_anchor_edits
from .zip_part import NS, OoxmlPackage

RELATIONSHIP_TAG = f"{{{NS['rel']}}}Relationship"


@dataclass(frozen=True)
class AttributeLocator:
    """An anchor pointing at an XML attribute rather than element text.

    ``sanitise`` exists because some attributes are not free text. An Excel sheet
    name cannot contain ``[`` or ``]``, so writing ``[PERSONA_1]`` into one
    produces a workbook Excel refuses to open — which was exactly what happened
    before this hook was added. The constraint is format-specific, so the handler
    supplies the function and this module stays ignorant of it.
    """

    element: object
    name: str
    sanitise: Callable[[str], str] | None = None

    def read(self) -> str:
        return self.element.get(self.name) or ""  # type: ignore[attr-defined]

    def write(self, value: str) -> None:
        if self.sanitise is not None:
            value = self.sanitise(value)
        self.element.set(self.name, value)  # type: ignore[attr-defined]


def add_attribute(
    builder: TextStreamBuilder,
    element: object,
    attribute: str,
    *,
    part: str,
    separator: str = "\n",
    sanitise: Callable[[str], str] | None = None,
) -> None:
    """Anchor an attribute's value, if it has one."""
    value = element.get(attribute)  # type: ignore[attr-defined]
    if not value:
        return
    builder.add(value, part=part, locator=AttributeLocator(element, attribute, sanitise))
    builder.add_filler(separator)


def add_relationship_targets(
    package: OoxmlPackage, builder: TextStreamBuilder, prefix: str
) -> None:
    """Anchor every external relationship target under ``prefix``.

    Internal targets are skipped: they name other parts of the same package and
    hold no addresses. External ones hold ``mailto:`` addresses and UNC paths
    with usernames in them, neither of which appears in the visible document.
    """
    for part in package.matching(prefix, ".rels"):
        tree = package.tree(part)
        for relationship in tree.iter(RELATIONSHIP_TAG):  # type: ignore[attr-defined]
            if relationship.get("TargetMode") != "External":
                continue
            add_attribute(builder, relationship, "Target", part=part)


def apply_ooxml_edits(package: OoxmlPackage, edits: Iterable[AnchorEdit]) -> None:
    """Push edits back through their anchors and mark the parts dirty.

    Grouped by locator identity rather than by part: several edits can land in
    one element, and each element's text has to be spliced in a single pass or
    the offsets of the later edits are wrong.
    """
    grouped: dict[int, list[AnchorEdit]] = {}
    for edit in edits:
        grouped.setdefault(id(edit.anchor.locator), []).append(edit)

    for element_edits in grouped.values():
        locator = element_edits[0].anchor.locator
        part = element_edits[0].part
        if isinstance(locator, AttributeLocator):
            original = locator.read()
            replaced = apply_anchor_edits(original, element_edits)
            if replaced != original:
                locator.write(replaced)
                package.mark_dirty(part)
            continue

        original = locator.text or ""  # type: ignore[attr-defined]
        replaced = apply_anchor_edits(original, element_edits)
        if replaced == original:
            continue
        locator.text = replaced  # type: ignore[attr-defined]
        preserve_space(locator, replaced)
        package.mark_dirty(part)


XML_SPACE = f"{{{NS['xml']}}}space"


def preserve_space(element: object, text: str) -> None:
    """Keep leading and trailing whitespace from being stripped.

    Without ``xml:space="preserve"`` Word and Excel both drop it, and the word
    before the replacement runs into the one after. Only ever added, never
    removed: a document that already declared it meant it.
    """
    if text != text.strip() and element.get(XML_SPACE) != "preserve":  # type: ignore[attr-defined]
        element.set(XML_SPACE, "preserve")  # type: ignore[attr-defined]
