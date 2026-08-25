"""Tests for the version authority.

Every case here pins a failure that has a cost outside this file: a spelling
difference read as drift, a hotfix number colliding with develop, a lockfile
edited in a way that makes `npm ci` reformat the file, an anchor that matched
the wrong line.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import version as V

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# The value


@pytest.mark.parametrize(
    "text",
    ["0.2.0-dev.1", "0.2.0.dev1", "0.2.0-dev1", "0.2.0_dev_1", "0.2.0.dev.1"],
)
def test_both_spellings_of_a_development_version_parse_to_one_value(text: str) -> None:
    # The reason `check` compares parsed values and never strings: the Python
    # half of the tree is written PEP 440 and the JavaScript half SemVer, and
    # comparing them as text would report drift on every single read.
    assert V.parse(text) == V.Version(0, 2, 0, 1)


def test_a_release_version_has_no_development_counter() -> None:
    assert V.parse("1.4.9") == V.Version(1, 4, 9, None)


@pytest.mark.parametrize("text", ["", "0.2", "0.2.0.1", "v0.2.0", "0.2.0-rc.1", "01.2.0"])
def test_a_version_this_project_cannot_write_is_refused(text: str) -> None:
    with pytest.raises(V.VersionError):
        V.parse(text)


def test_a_development_version_sorts_below_the_release_it_leads_to() -> None:
    # This ordering is what keeps hotfix space free: develop may run ahead of
    # main for a whole release cycle without ever reaching a number main will
    # want. Break it and 0.3.0-dev.7 outranks the 0.3.0 it was leading to.
    assert V.parse("0.3.0-dev.7") < V.parse("0.3.0") < V.parse("0.3.1")
    assert V.parse("0.2.1") > V.parse("0.2.0")
    assert V.parse("0.3.0-dev.2") > V.parse("0.3.0-dev.1")


def test_the_two_renderings_agree_on_a_release_version() -> None:
    version = V.parse("1.0.0")
    assert version.pep440() == version.semver() == "1.0.0"


def test_the_two_renderings_differ_on_a_development_version() -> None:
    version = V.parse("0.2.0-dev.3")
    assert version.pep440() == "0.2.0.dev3"
    assert version.semver() == "0.2.0-dev.3"


# --------------------------------------------------------------------------
# The arithmetic


def test_bump_dev_advances_the_counter() -> None:
    assert V.bump(V.parse("0.2.0-dev.1"), "dev") == V.parse("0.2.0-dev.2")


def test_bump_dev_on_a_release_version_is_refused() -> None:
    # On develop the version always carries a counter. Reaching this means the
    # tree is in a state the branching model does not produce, and inventing a
    # counter would hide it.
    with pytest.raises(V.VersionError):
        V.bump(V.parse("0.2.0"), "dev")


@pytest.mark.parametrize(
    ("part", "expected"),
    [("patch", "0.2.4-dev.0"), ("minor", "0.3.0-dev.0"), ("major", "1.0.0-dev.0")],
)
def test_bumping_a_component_opens_a_development_line(part: str, expected: str) -> None:
    # A version reached by bumping is never a version anything ships: the
    # release number is set on the release branch, by `release`.
    assert V.bump(V.parse("0.2.3"), part) == V.parse(expected)


def test_release_drops_the_development_counter() -> None:
    assert V.release(V.parse("0.3.0-dev.9")) == V.parse("0.3.0")


def test_release_on_a_release_version_is_a_no_op_rather_than_an_error() -> None:
    # `release` is run from a runbook, and a runbook step that fails when it has
    # already been done is a step people learn to skip.
    version = V.parse("0.3.0")
    assert V.release(version) == version


# --------------------------------------------------------------------------
# The nine sites


def test_every_site_is_found_exactly_once_in_the_real_tree() -> None:
    for site, raw in V.readings(ROOT):
        assert V.parse(raw), f"{site.path}: {site.what}"


def test_the_real_tree_agrees_with_itself() -> None:
    # The check `scripts/ci.py` runs, as a test, so a bump that missed a file
    # fails the suite as well as the gate.
    assert V.current(ROOT)


def test_an_anchor_matching_twice_raises_rather_than_writing() -> None:
    # A pattern that matches twice would rewrite one occurrence and leave the
    # other, which in a lockfile is invisible until `npm ci` fails in somebody
    # else's checkout.
    site = V.Site("x", re.compile(r'"version": "([^"]+)"'), "semver", "version")
    text = '{"version": "1.0.0", "deps": {"version": "2.0.0"}}'
    with pytest.raises(V.VersionError, match="found 2"):
        site.read(text)
    with pytest.raises(V.VersionError, match="found 2"):
        site.write(text, V.parse("3.0.0"))


def test_an_anchor_matching_nothing_raises() -> None:
    site = V.Site("x", re.compile(r'"nope": "([^"]+)"'), "semver", "version")
    with pytest.raises(V.VersionError, match="found 0"):
        site.read('{"version": "1.0.0"}')


def _tree(tmp_path: Path) -> Path:
    for relative in V.PATHS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return tmp_path


def test_a_write_changes_the_version_line_and_nothing_else(tmp_path: Path) -> None:
    # The lockfiles are edited in place rather than regenerated, so the proof
    # that the edit is surgical is that every other byte survives it.
    root = _tree(tmp_path)
    before = {p: (ROOT / p).read_text(encoding="utf-8") for p in V.PATHS}
    V.write(V.parse("9.8.7-dev.6"), root)

    for relative in V.PATHS:
        after = (root / relative).read_text(encoding="utf-8")
        original = before[relative].splitlines()
        rewritten = after.splitlines()
        assert len(original) == len(rewritten), relative
        differing = [i for i, (a, b) in enumerate(zip(original, rewritten, strict=True)) if a != b]
        # package-lock.json carries the version twice; every other file once.
        expected = 2 if relative.endswith("package-lock.json") else 1
        assert len(differing) == expected, f"{relative}: {differing}"


def test_a_write_round_trips_through_both_spellings(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    V.write(V.parse("0.4.0-dev.2"), root)
    assert V.current(root) == V.parse("0.4.0-dev.2")

    python_sites = {s.path for s in V._SITES if s.spelling == "pep440"}
    for site, raw in V.readings(root):
        expected = "0.4.0.dev2" if site.path in python_sites else "0.4.0-dev.2"
        assert raw == expected, f"{site.path}: {site.what}"


def test_a_tree_whose_sites_disagree_refuses_to_name_a_version(tmp_path: Path) -> None:
    # Derived from the tree, never a literal: a hard-coded "0.1.0" here stopped
    # matching the moment the project bumped itself, and the test then failed
    # while the code it covers was fine.
    root = _tree(tmp_path)
    site = next(s for s in V._SITES if s.path.endswith("tauri.conf.json"))
    conf = root / site.path
    odd_one_out = V.bump(V.current(root), "major")  # different from whatever the tree says
    conf.write_text(site.write(conf.read_text(encoding="utf-8"), odd_one_out), encoding="utf-8")
    assert site.read(conf.read_text(encoding="utf-8")) == odd_one_out.semver()

    with pytest.raises(V.VersionError, match="disagree"):
        V.current(root)
