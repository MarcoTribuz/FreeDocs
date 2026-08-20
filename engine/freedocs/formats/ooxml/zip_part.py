"""The OOXML container: a zip of XML parts.

Every Office format is this same shape, so docx, xlsx and pptx share the reading
and writing here and differ only in which parts they care about.

The rule that governs this module: **a part nobody edited is written back
byte-for-byte.** Round-tripping through a convenience library is what loses
charts, images and pivot tables — `openpyxl` has no management API for them and
can drop them on save. Copying raw bytes cannot lose what it never parsed.

Only parts that were parsed *and* modified get re-serialised, and even then the
edit is made on the original tree rather than a rebuilt one, so untouched
elements keep their exact attributes and namespace prefixes.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...core.errors import MissingDependency

if TYPE_CHECKING:  # pragma: no cover
    from lxml import etree

#: Namespaces used across the Office formats. Kept in one place because the same
#: URI appears in docx, xlsx and pptx parts and a typo produces a silent no-match
#: rather than an error.
NS: dict[str, str] = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
    "xml": "http://www.w3.org/XML/1998/namespace",
}


def qn(tag: str) -> str:
    """``"w:t"`` -> ``"{http://...}t"``, the form lxml wants."""
    prefix, _, local = tag.partition(":")
    return f"{{{NS[prefix]}}}{local}"


def lxml_etree() -> etree:
    try:
        from lxml import etree
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise MissingDependency(
            "lxml is required for Office formats; install the 'ooxml' extra"
        ) from exc
    return etree


@dataclass
class OoxmlPackage:
    """An open OOXML container, with lazy per-part parsing.

    Parts are parsed only when asked for and re-serialised only when marked
    dirty. Everything else is passed through as the bytes it arrived as.
    """

    #: Original entry order and metadata, so the rewritten zip looks like the
    #: original to anything that cares (and some tools do).
    _infos: list[zipfile.ZipInfo] = field(default_factory=list, repr=False)
    _raw: dict[str, bytes] = field(default_factory=dict, repr=False)
    _trees: dict[str, object] = field(default_factory=dict, repr=False)
    _dirty: set[str] = field(default_factory=set, repr=False)
    _dropped: set[str] = field(default_factory=set, repr=False)

    @classmethod
    def open(cls, data: bytes) -> OoxmlPackage:
        package = cls()
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if archive.testzip() is not None:  # pragma: no cover - corrupt input
                raise ValueError("the OOXML container has a corrupt entry")
            package._infos = list(archive.infolist())
            for info in package._infos:
                if not info.is_dir():
                    package._raw[info.filename] = archive.read(info.filename)
        return package

    # -- inspection ------------------------------------------------------------

    def names(self) -> list[str]:
        return [name for name in self._raw if name not in self._dropped]

    def has(self, name: str) -> bool:
        return name in self._raw and name not in self._dropped

    def raw(self, name: str) -> bytes:
        return self._raw[name]

    def matching(self, prefix: str, suffix: str = ".xml") -> list[str]:
        """Part names starting with ``prefix``, sorted.

        Sorted rather than in zip order: ``header2.xml`` must always be visited
        after ``header1.xml`` or the extracted text stream would differ between
        two files that only differ in how the zip was written.
        """
        return sorted(
            name for name in self.names() if name.startswith(prefix) and name.endswith(suffix)
        )

    # -- parts -----------------------------------------------------------------

    def tree(self, name: str) -> object:
        """Parse a part and cache the tree. Editing the tree requires ``mark_dirty``."""
        if name in self._dropped or name not in self._raw:
            raise KeyError(name)
        if name not in self._trees:
            etree = lxml_etree()
            # No pretty-printing on the way out and no blank-text stripping on the
            # way in: whitespace inside a w:t is document content.
            parser = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
            self._trees[name] = etree.fromstring(self._raw[name], parser)
        return self._trees[name]

    def mark_dirty(self, name: str) -> None:
        self._dirty.add(name)

    def drop(self, name: str) -> bool:
        """Remove a part and any relationship pointing at it.

        Removing the part alone would leave a dangling relationship, which makes
        the package structurally invalid: Word offers to repair the file, and a
        strict consumer rejects it outright. The two removals belong together, so
        they live in one method rather than in every caller's discipline.
        """
        if not self.has(name):
            return False
        self._dropped.add(name)
        self.drop_relationships_to(name)
        self._drop_content_type_override(name)
        return True

    def _drop_content_type_override(self, name: str) -> None:
        """Remove the ``[Content_Types].xml`` entry for a dropped part.

        An override naming a part that no longer exists is the other half of the
        dangling-reference problem.
        """
        types_part = "[Content_Types].xml"
        if not self.has(types_part):
            return
        tree = self.tree(types_part)
        wanted = f"/{name}"
        for override in list(tree.iter()):  # type: ignore[attr-defined]
            if override.tag.endswith("}Override") and override.get("PartName") == wanted:
                parent = override.getparent()
                if parent is not None:
                    parent.remove(override)
                    self.mark_dirty(types_part)

    def relationship_parts(self) -> list[str]:
        return sorted(part for part in self.names() if part.endswith(".rels"))

    @staticmethod
    def _resolve(rels_part: str, target: str) -> str:
        """Resolve a relationship target to a package-absolute part name.

        Targets are relative to the directory of the part that owns the
        relationships: ``word/_rels/document.xml.rels`` owns ``word/document.xml``,
        so its ``comments.xml`` means ``word/comments.xml``.
        """
        directory = posixpath.dirname(posixpath.dirname(rels_part))
        return posixpath.normpath(posixpath.join(directory, target)).lstrip("/")

    def drop_relationships_to(self, target_part: str) -> int:
        """Remove every relationship resolving to ``target_part``."""
        removed = 0
        tag = f"{{{NS['rel']}}}Relationship"
        for rels_part in self.relationship_parts():
            tree = self.tree(rels_part)
            for relationship in list(tree.iter(tag)):  # type: ignore[attr-defined]
                if relationship.get("TargetMode") == "External":
                    continue
                target = relationship.get("Target") or ""
                if not target or self._resolve(rels_part, target) != target_part:
                    continue
                parent = relationship.getparent()
                if parent is not None:
                    parent.remove(relationship)
                    removed += 1
                    self.mark_dirty(rels_part)
        return removed

    def replace(self, name: str, data: bytes) -> None:
        self._raw[name] = data
        self._trees.pop(name, None)
        self._dirty.discard(name)
        self._dropped.discard(name)

    # -- output ----------------------------------------------------------------

    def to_bytes(self) -> bytes:
        etree = lxml_etree()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for info in self._infos:
                name = info.filename
                if name in self._dropped or info.is_dir():
                    continue
                if name in self._dirty:
                    payload = etree.tostring(
                        self._trees[name],
                        xml_declaration=True,
                        encoding="UTF-8",
                        standalone=True,
                    )
                else:
                    payload = self._raw[name]
                # Reuse the original ZipInfo so date, external attributes and
                # compression type survive; only the size changes.
                entry = zipfile.ZipInfo(name, date_time=info.date_time)
                entry.compress_type = info.compress_type
                entry.external_attr = info.external_attr
                entry.create_system = info.create_system
                archive.writestr(entry, payload)
        return buffer.getvalue()
