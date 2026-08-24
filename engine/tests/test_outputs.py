"""Who may read what this engine writes, and where it may be redirected to.

Two failures, and they were not the same one. The key file was meticulously
``0o600`` while the *restored* document - which is the originals, reassembled -
went out at whatever the umask said. And every output was written with
``write_bytes`` after ``mkdir(exist_ok=True)``, which follows a symbolic link, so
in a shared or predictable output directory a pre-planted link redirects the
write.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from freedocs.core.errors import OutputRefused
from freedocs.core.outputs import (
    PRIVATE_DIR_MODE,
    PRIVATE_MODE,
    private_directory,
    write_output,
    write_private,
    write_private_json,
)

posix_only = pytest.mark.skipif(
    os.name == "nt", reason="permission bits and O_NOFOLLOW do not exist here"
)


@posix_only
def test_a_private_output_is_readable_by_nobody_else(tmp_path: Path):
    path = tmp_path / "restored.txt"
    write_private(path, b"Mario Rossi")
    assert path.stat().st_mode & 0o777 == PRIVATE_MODE


@posix_only
def test_writing_over_a_loose_file_tightens_its_mode(tmp_path: Path):
    """O_CREAT leaves an existing file's mode alone, so yesterday's output would
    keep yesterday's permissions. The same case `write_key_map` chmods for."""
    path = tmp_path / "restored.txt"
    path.write_bytes(b"old")
    path.chmod(0o644)
    write_private(path, b"Mario Rossi")
    assert path.stat().st_mode & 0o777 == PRIVATE_MODE


@posix_only
def test_a_handed_over_output_is_left_to_the_umask(tmp_path: Path):
    """The scrubbed copy is the one artifact whose purpose is to be sent.

    Asserted against the umask actually in force rather than against 0644, so
    this says "we did not narrow it" rather than "the machine's umask is 022".
    """
    previous = os.umask(0o022)
    try:
        path = tmp_path / "clean.txt"
        write_output(path, b"[PERSON_1]")
        assert path.stat().st_mode & 0o777 == 0o666 & ~0o022
    finally:
        os.umask(previous)


@posix_only
@pytest.mark.parametrize("write", [write_private, write_output])
def test_a_symlink_where_an_output_belongs_is_refused(tmp_path: Path, write):
    """The realistic accident and the realistic attack are the same shape: the
    output directory is shared or predictable, and something is waiting there."""
    elsewhere = tmp_path / "config"
    elsewhere.write_bytes(b"do not touch")
    path = tmp_path / "out.txt"
    path.symlink_to(elsewhere)

    with pytest.raises(OutputRefused):
        write(path, b"redirected")
    assert elsewhere.read_bytes() == b"do not touch"


def test_an_existing_output_file_is_overwritten_rather_than_refused(tmp_path: Path):
    """O_EXCL was rejected on purpose. Re-running a scrub into the same output
    directory is ordinary use, and it buys nothing the symlink guard does not."""
    path = tmp_path / "clean.txt"
    write_output(path, b"first")
    write_output(path, b"second")
    assert path.read_bytes() == b"second"


@posix_only
def test_a_directory_made_for_private_output_is_owner_only(tmp_path: Path):
    path = tmp_path / "back"
    private_directory(path)
    assert path.stat().st_mode & 0o777 == PRIVATE_DIR_MODE


@posix_only
def test_a_directory_that_already_existed_is_left_as_it_was(tmp_path: Path):
    """An existing directory belongs to whoever made it. Quietly narrowing a path
    the user already had is a surprise, not a hardening."""
    path = tmp_path / "back"
    path.mkdir()
    path.chmod(0o755)
    private_directory(path)
    assert path.stat().st_mode & 0o777 == 0o755


def test_a_report_is_written_with_the_same_bytes_everywhere(tmp_path: Path):
    """`write_text` translates "\\n" to the platform terminator, which is the class
    of difference that broke three tests on the Windows runner once."""
    path = tmp_path / "r.json"
    write_private_json(path, [{"file": "offerta.txt"}])
    assert b"\r\n" not in path.read_bytes()
    assert path.read_bytes().endswith(b"\n")
