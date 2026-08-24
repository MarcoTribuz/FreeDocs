"""What a workbook hides.

Excel's hiding is more literal than Word's, and more dangerous, because a hidden
sheet is a full copy of something rather than a stray attribute:

* **``veryHidden`` sheets are not in the sheet-tab menu at all.** Unhiding one
  needs the VBA editor, so people use them for the raw extract a report is built
  from and forget they exist.
* **Hidden rows and columns** are the ordinary version of the same habit: the
  column with the salaries, hidden before sending.
* **Connections and query tables** hold the connection string and, for Power
  Query, the M script — which contains server names, file paths with usernames,
  and occasionally credentials.
* **Comments carry an author list**, and threaded comments keep a separate
  ``persons`` directory mapping each author to an identity.
* **The macro project** is a binary blob that can contain both code and the data
  it was written to process, and cannot be inspected as XML.

Hidden *sheets, rows and columns are reported but left in place.* Their text is
redacted like everything else, because the string table covers every sheet
whether it is visible or not, so keeping them costs no confidentiality — and
deleting a sheet breaks every formula that references it. Reporting them matters
because the user may not know they are there.
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

WORKBOOK = "xl/workbook.xml"

#: Comment bodies and their author directories. Excel writes ``xl/comments1.xml``;
#: other producers write ``xl/comments/comment1.xml``. Both prefixes are covered.
COMMENT_PREFIXES = (
    "xl/comments",
    "xl/threadedComments/",
    "xl/persons/",
)

#: The VML shapes that draw comment boxes. They outlive the comment part and can
#: carry the author's name in the shape metadata.
COMMENT_DRAWING_PREFIXES = (
    "xl/drawings/vmlDrawing",
    "xl/drawings/commentsDrawing",
)

#: Refresh machinery. Dropping it leaves the values that were last fetched, which
#: are content and get redacted normally, and removes the connection details.
CONNECTION_PREFIXES = (
    "xl/connections.xml",
    "xl/queryTables/",
)

#: Macros. Opaque binary, so it cannot be redacted, only removed.
MACRO_PREFIXES = ("xl/vbaProject.bin",)

#: Sheet states that hide a sheet from the reader.
HIDDEN_STATES = {"hidden": "hidden", "veryHidden": "very hidden - needs the VBA editor to reveal"}


def scrub_xlsx_hidden(package: OoxmlPackage) -> list[HiddenItem]:
    removed: list[HiddenItem] = []

    removed.extend(
        drop_matching(package, COMMENT_PREFIXES, "comments", "comment text and author list")
    )
    removed.extend(
        drop_matching(package, COMMENT_DRAWING_PREFIXES, "comment-shapes", "comment box shapes")
    )
    removed.extend(
        drop_matching(
            package,
            CONNECTION_PREFIXES,
            "data-connections",
            "connection strings and query scripts, which hold server names and paths",
        )
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

    removed.extend(_report_hidden_sheets(package))
    removed.extend(_report_hidden_rows_and_columns(package))
    removed.extend(_report_caches(package))
    return removed


def _report_hidden_sheets(package: OoxmlPackage) -> list[HiddenItem]:
    """Locate every sheet the reader cannot see. Reported, not removed."""
    if not package.has(WORKBOOK):
        return []
    tree = package.tree(WORKBOOK)
    out: list[HiddenItem] = []
    for position, sheet in enumerate(tree.iter(qn("s:sheet")), start=1):  # type: ignore[attr-defined]
        state = sheet.get("state")
        if state in HIDDEN_STATES:
            out.append(
                HiddenItem(
                    part=WORKBOOK,
                    kind="hidden-sheet",
                    # Its position, never its name. This reaches `build_report`,
                    # which is written to disk beside the scrubbed workbook, and a
                    # sheet called `Clienti-Rossi` is exactly the identifying value
                    # the scrub is about to remove from it. The position locates
                    # the sheet in the output, where its redacted name is visible
                    # anyway.
                    detail=f"sheet {position} is {HIDDEN_STATES[state]}",
                )
            )
    return out


def _report_hidden_rows_and_columns(package: OoxmlPackage) -> list[HiddenItem]:
    out: list[HiddenItem] = []
    for part in package.matching("xl/worksheets/sheet"):
        tree = package.tree(part)
        rows = sum(1 for row in tree.iter(qn("s:row")) if row.get("hidden") == "1")
        columns = sum(1 for col in tree.iter(qn("s:col")) if col.get("hidden") == "1")
        details = []
        if rows:
            details.append(f"{rows} hidden row(s)")
        if columns:
            details.append(f"{columns} hidden column group(s)")
        if details:
            out.append(
                HiddenItem(
                    part=part,
                    kind="hidden-cells",
                    detail=", ".join(details) + " - content redacted, layout left alone",
                )
            )
    return out


def _report_caches(package: OoxmlPackage) -> list[HiddenItem]:
    """Announce the caches that hold their own copy of the data.

    They are redacted in place rather than dropped, so this is a note about where
    the user's data was duplicated, not a removal.
    """
    out: list[HiddenItem] = []
    pivots = package.matching("xl/pivotCache/")
    if pivots:
        out.append(
            HiddenItem(
                part="xl/pivotCache/",
                kind="pivot-cache",
                detail=(
                    f"{len(pivots)} part(s) holding a copy of the source rows - "
                    "redacted in place so the pivot table keeps working"
                ),
            )
        )
    external = package.matching("xl/externalLinks/")
    if external:
        out.append(
            HiddenItem(
                part="xl/externalLinks/",
                kind="external-link-cache",
                detail=(
                    f"{len(external)} part(s) caching values from another workbook - "
                    "redacted in place"
                ),
            )
        )
    return out
