"""Тесты CAS-хранилища blob-ов."""

from __future__ import annotations

import hashlib

import pytest

from services.cas.blob_store import (
    BlobHashMismatch,
    BlobStore,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_put_and_get(tmp_path):
    store = BlobStore(str(tmp_path))
    src = tmp_path / "f.bin"
    src.write_bytes(b"hello")
    sha = _sha(b"hello")

    assert store.has(sha) is False
    assert store.put(src, sha) is True
    assert store.has(sha) is True

    p = store.get(sha)
    assert p is not None
    assert p.read_bytes() == b"hello"


def test_put_dedup(tmp_path):
    store = BlobStore(str(tmp_path))
    src = tmp_path / "f.bin"
    src.write_bytes(b"hello")
    sha = _sha(b"hello")

    assert store.put(src, sha) is True
    assert store.put(src, sha) is False


def test_put_hash_mismatch(tmp_path):
    store = BlobStore(str(tmp_path))
    src = tmp_path / "f.bin"
    src.write_bytes(b"hello")

    with pytest.raises(BlobHashMismatch):
        store.put(src, "0" * 64)

    # Мусорный blob не остался.
    assert list(store.iter_all()) == []


def test_get_missing(tmp_path):
    store = BlobStore(str(tmp_path))
    assert store.get("0" * 64) is None
    assert store.has("0" * 64) is False


def test_get_invalid_sha(tmp_path):
    store = BlobStore(str(tmp_path))
    assert store.get("not-a-sha") is None
    assert store.has("not-a-sha") is False


def test_iter_all(tmp_path):
    store = BlobStore(str(tmp_path))
    a = tmp_path / "a.bin"
    a.write_bytes(b"aaa")
    b = tmp_path / "b.bin"
    b.write_bytes(b"bbb")
    sa, sb = _sha(b"aaa"), _sha(b"bbb")
    store.put(a, sa)
    store.put(b, sb)

    names = {name for name, _ in store.iter_all()}
    assert names == {sa, sb}


def test_stats(tmp_path):
    store = BlobStore(str(tmp_path))
    a = tmp_path / "a.bin"
    a.write_bytes(b"aaaa")
    store.put(a, _sha(b"aaaa"))

    count, size = store.stats()
    assert count == 1
    assert size == 4


def test_gc_removes_unused(tmp_path):
    store = BlobStore(str(tmp_path))
    a = tmp_path / "a.bin"
    a.write_bytes(b"aaa")
    b = tmp_path / "b.bin"
    b.write_bytes(b"bbbbbb")
    sa, sb = _sha(b"aaa"), _sha(b"bbbbbb")
    store.put(a, sa)
    store.put(b, sb)

    deleted, freed = store.gc([sa])
    assert deleted == 1
    assert freed == 6
    assert store.has(sa) is True
    assert store.has(sb) is False


def test_gc_removes_empty_subdirs(tmp_path):
    store = BlobStore(str(tmp_path))
    a = tmp_path / "a.bin"
    a.write_bytes(b"aaa")
    sa = _sha(b"aaa")
    store.put(a, sa)

    store.gc([])

    sub = store.root / sa[:2]
    assert not sub.exists()


def test_gc_keeps_all(tmp_path):
    store = BlobStore(str(tmp_path))
    a = tmp_path / "a.bin"
    a.write_bytes(b"aaa")
    sa = _sha(b"aaa")
    store.put(a, sa)

    deleted, freed = store.gc([sa])
    assert deleted == 0
    assert freed == 0
    assert store.has(sa)


def test_clear(tmp_path):
    store = BlobStore(str(tmp_path))
    a = tmp_path / "a.bin"
    a.write_bytes(b"aaa")
    store.put(a, _sha(b"aaa"))

    store.clear()
    assert list(store.iter_all()) == []
