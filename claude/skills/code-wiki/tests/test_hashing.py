"""Tests for bin/lib/hashing.py."""

from __future__ import annotations

from pathlib import Path

from lib import hashing


def test_sha256_text_known_value() -> None:
    # SHA-256 of empty string.
    assert hashing.sha256_text("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_sha256_text_changes_with_content() -> None:
    a = hashing.sha256_text("hello")
    b = hashing.sha256_text("Hello")
    assert a != b


def test_sha256_text_unicode() -> None:
    # Should not crash on non-ASCII.
    digest = hashing.sha256_text("한글 텍스트 ✨")
    assert len(digest) == 64


def test_sha256_file_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"some bytes here")
    expected = hashing.sha256_text("")  # placeholder
    # Compute via direct hashlib for cross-check.
    import hashlib
    expected = hashlib.sha256(b"some bytes here").hexdigest()
    assert hashing.sha256_file(f) == expected


def test_sha256_file_handles_large_file(tmp_path: Path) -> None:
    f = tmp_path / "big.bin"
    payload = b"x" * (200 * 1024)  # > one block
    f.write_bytes(payload)
    import hashlib
    expected = hashlib.sha256(payload).hexdigest()
    assert hashing.sha256_file(f) == expected


def test_sha256_file_empty(tmp_path: Path) -> None:
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert hashing.sha256_file(f) == hashing.sha256_text("")
