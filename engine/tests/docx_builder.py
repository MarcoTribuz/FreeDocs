"""Builds minimal but valid .docx files for the tests.

Written by hand rather than with ``python-docx`` for two reasons. It needs no
extra dependency, and more importantly it gives exact control over the structures
that matter here: a name split across three runs, a tracked deletion whose text
is still in the file, a comment part, an rsid attribute. A convenience library
would normalise away the very things under test.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ODREL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

CONTENT_TYPES = """{decl}
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
{extra}
</Types>"""

PACKAGE_RELS = """{decl}
<Relationships xmlns="{rel}">
<Relationship Id="rId1" Type="{odrel}/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="{odrel}/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

CORE = """{decl}
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:creator>{creator}</dc:creator>
<cp:lastModifiedBy>{last_modified_by}</cp:lastModifiedBy>
<dc:title>{title}</dc:title>
<dc:subject>{subject}</dc:subject>
<cp:keywords>{keywords}</cp:keywords>
<cp:revision>{revision}</cp:revision>
<dcterms:created xsi:type="dcterms:W3CDTF">2024-03-03T09:00:00Z</dcterms:created>
</cp:coreProperties>"""

APP = """{decl}
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
<Company>{company}</Company>
<Manager>{manager}</Manager>
<TotalTime>{total_time}</TotalTime>
<Template>{template}</Template>
</Properties>"""

SETTINGS = """{decl}
<w:settings xmlns:w="{w}">
<w:rsids><w:rsidRoot w:val="00A12B34"/><w:rsid w:val="00A12B34"/><w:rsid w:val="00B56C78"/></w:rsids>
</w:settings>"""

COMMENTS = """{decl}
<w:comments xmlns:w="{w}">
<w:comment w:id="1" w:author="{author}" w:date="2024-03-03T10:00:00Z" w:initials="MT">
<w:p><w:r><w:t>{text}</w:t></w:r></w:p>
</w:comment>
</w:comments>"""

PEOPLE = """{decl}
<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"
 xmlns:w="{w}">
<w15:person w15:author="{author}"><w15:presenceInfo w15:providerId="AD" w15:userId="{user_id}"/></w15:person>
</w15:people>"""

HEADER = """{decl}
<w:hdr xmlns:w="{w}"><w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p></w:hdr>"""

FOOTER = """{decl}
<w:ftr xmlns:w="{w}"><w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p></w:ftr>"""


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def runs_xml(runs: list[str], *, bold_first: bool = False) -> str:
    """Render each string as its own ``<w:r>``, so callers control the split."""
    out = []
    for index, text in enumerate(runs):
        properties = "<w:rPr><w:b/></w:rPr>" if bold_first and index == 0 else ""
        space = ' xml:space="preserve"' if text != text.strip() else ""
        out.append(f"<w:r>{properties}<w:t{space}>{_escape(text)}</w:t></w:r>")
    return "".join(out)


@dataclass
class DocxSpec:
    """What to put in the generated document."""

    #: Each entry is one paragraph, given as the list of runs it is split into.
    paragraphs: list[list[str]] = field(default_factory=list)
    creator: str = "Marco Tribuzio"
    last_modified_by: str = "Anna Bianchi"
    title: str = "Scheda cliente riservata"
    subject: str = "mario.rossi@example.com"
    keywords: str = "CH93 0076 2011 6238 5295 7"
    company: str = "Realise Consulting SA"
    manager: str = "Giuseppe Conti"
    template: str = "C:\\Users\\mtribuzio\\Templates\\Riservato.dotx"
    #: Blankable so a genuinely clean document can be built for the tests.
    revision: str = "7"
    total_time: str = "412"
    #: Text inside a tracked deletion: removed from view, still in the file.
    deleted: str | None = None
    #: Text inside a tracked insertion: visible, but the markup names an author.
    inserted: str | None = None
    revision_author: str = "Marco Tribuzio"
    comment: str | None = None
    comment_author: str = "Anna Bianchi"
    comment_user_id: str = "a.bianchi@example.com"
    header: str | None = None
    footer: str | None = None
    #: ``(link text, target)`` rendered as an external relationship.
    hyperlink: tuple[str, str] | None = None
    #: A run following the hyperlink *inside the same paragraph*. Word writes
    #: this whenever a link sits mid-sentence, and the two texts then meet with
    #: no structural element between them - which is how ``Malakoff Humanis``
    #: and ``consulte`` arrived in one stream as ``Malakoff Humanisconsulte``.
    hyperlink_tail: str | None = None
    #: Text inside a table cell, to exercise cell boundaries.
    table_cell: str | None = None
    #: Text inside a text box, which nests a paragraph inside a run.
    textbox: str | None = None
    #: None means no rsid attribute at all, as a file saved without a history.
    rsid: str | None = "00A12B34"
    #: Whether to emit the settings.xml rsid table.
    rsid_table: bool = True


def _document_xml(spec: DocxSpec) -> str:
    body = []
    for runs in spec.paragraphs:
        attribute = f' w:rsidR="{spec.rsid}"' if spec.rsid else ""
        body.append(f"<w:p{attribute}>{runs_xml(runs)}</w:p>")

    if spec.deleted:
        body.append(
            f'<w:p><w:del w:id="10" w:author="{spec.revision_author}" '
            f'w:date="2024-03-03T10:00:00Z"><w:r><w:delText>'
            f"{_escape(spec.deleted)}</w:delText></w:r></w:del></w:p>"
        )
    if spec.inserted:
        body.append(
            f'<w:p><w:ins w:id="11" w:author="{spec.revision_author}" '
            f'w:date="2024-03-03T10:05:00Z"><w:r><w:t>'
            f"{_escape(spec.inserted)}</w:t></w:r></w:ins></w:p>"
        )
    if spec.comment:
        body.append(
            '<w:p><w:commentRangeStart w:id="1"/><w:r><w:t>testo commentato</w:t></w:r>'
            '<w:commentRangeEnd w:id="1"/><w:r><w:commentReference w:id="1"/></w:r></w:p>'
        )
    if spec.hyperlink:
        text, _ = spec.hyperlink
        tail = (
            f"<w:r><w:t>{_escape(spec.hyperlink_tail)}</w:t></w:r>" if spec.hyperlink_tail else ""
        )
        body.append(
            f'<w:p><w:hyperlink r:id="rId90"><w:r><w:t>{_escape(text)}</w:t></w:r>'
            f"</w:hyperlink>{tail}</w:p>"
        )
    if spec.table_cell:
        body.append(
            "<w:tbl><w:tr>"
            f"<w:tc><w:p><w:r><w:t>{_escape(spec.table_cell)}</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>seconda cella</w:t></w:r></w:p></w:tc>"
            "</w:tr></w:tbl>"
        )
    if spec.textbox:
        body.append(
            "<w:p><w:r><mc:AlternateContent "
            'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
            '<mc:Fallback><w:pict><v:shape xmlns:v="urn:schemas-microsoft-com:vml">'
            "<v:textbox><w:txbxContent><w:p><w:r><w:t>"
            f"{_escape(spec.textbox)}"
            "</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict>"
            "</mc:Fallback></mc:AlternateContent></w:r></w:p>"
        )

    header_ref = '<w:headerReference w:type="default" r:id="rId80"/>' if spec.header else ""
    footer_ref = '<w:footerReference w:type="default" r:id="rId81"/>' if spec.footer else ""
    return (
        f"{DECL}\n"
        f'<w:document xmlns:w="{W}" xmlns:r="{ODREL}">'
        f"<w:body>{''.join(body)}"
        f"<w:sectPr>{header_ref}{footer_ref}</w:sectPr>"
        "</w:body></w:document>"
    )


def _document_rels(spec: DocxSpec) -> str:
    entries = [f'<Relationship Id="rId50" Type="{ODREL}/settings" Target="settings.xml"/>']
    if spec.comment:
        entries.append(f'<Relationship Id="rId60" Type="{ODREL}/comments" Target="comments.xml"/>')
        entries.append(
            '<Relationship Id="rId61" '
            'Type="http://schemas.microsoft.com/office/2011/relationships/people" '
            'Target="people.xml"/>'
        )
    if spec.header:
        entries.append(f'<Relationship Id="rId80" Type="{ODREL}/header" Target="header1.xml"/>')
    if spec.footer:
        entries.append(f'<Relationship Id="rId81" Type="{ODREL}/footer" Target="footer1.xml"/>')
    if spec.hyperlink:
        _, target = spec.hyperlink
        entries.append(
            f'<Relationship Id="rId90" Type="{ODREL}/hyperlink" '
            f'Target="{_escape(target)}" TargetMode="External"/>'
        )
    return f'{DECL}\n<Relationships xmlns="{REL}">{"".join(entries)}</Relationships>'


def build_docx(spec: DocxSpec) -> bytes:
    extra_types = []
    if spec.comment:
        extra_types.append(
            '<Override PartName="/word/comments.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.comments+xml"/>'
        )
    parts: dict[str, str] = {
        "[Content_Types].xml": CONTENT_TYPES.format(decl=DECL, extra="".join(extra_types)),
        "_rels/.rels": PACKAGE_RELS.format(decl=DECL, rel=REL, odrel=ODREL),
        "word/document.xml": _document_xml(spec),
        "word/_rels/document.xml.rels": _document_rels(spec),
        "word/settings.xml": (
            SETTINGS.format(decl=DECL, w=W)
            if spec.rsid_table
            else f'{DECL}\n<w:settings xmlns:w="{W}"/>'
        ),
        "docProps/core.xml": CORE.format(
            decl=DECL,
            creator=_escape(spec.creator),
            last_modified_by=_escape(spec.last_modified_by),
            title=_escape(spec.title),
            subject=_escape(spec.subject),
            keywords=_escape(spec.keywords),
            revision=_escape(spec.revision),
        ),
        "docProps/app.xml": APP.format(
            decl=DECL,
            company=_escape(spec.company),
            manager=_escape(spec.manager),
            template=_escape(spec.template),
            total_time=_escape(spec.total_time),
        ),
    }
    if spec.comment:
        parts["word/comments.xml"] = COMMENTS.format(
            decl=DECL, w=W, author=_escape(spec.comment_author), text=_escape(spec.comment)
        )
        parts["word/people.xml"] = PEOPLE.format(
            decl=DECL,
            w=W,
            author=_escape(spec.comment_author),
            user_id=_escape(spec.comment_user_id),
        )
    if spec.header:
        parts["word/header1.xml"] = HEADER.format(decl=DECL, w=W, text=_escape(spec.header))
    if spec.footer:
        parts["word/footer1.xml"] = FOOTER.format(decl=DECL, w=W, text=_escape(spec.footer))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in parts.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def write_docx(path: Path, spec: DocxSpec) -> Path:
    path.write_bytes(build_docx(spec))
    return path


def part_text(data: bytes, name: str) -> str:
    """Raw text of one part of a .docx, for leak checks inside the container."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if name not in archive.namelist():
            return ""
        return archive.read(name).decode("utf-8")


def part_names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.namelist()


def all_part_text(data: bytes) -> str:
    """Every part concatenated.

    A leak check must look inside the zip, not at the zip: the container is
    compressed, so searching its bytes for a canary proves nothing.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist()
        )
