"""Тесты кэша хэшей."""

from __future__ import annotations

from pathlib import Path

from services.common.hash_cache import CacheEntry, HashCache, hash_file


def _make_cache(tmp_path: Path, **kwargs) -> HashCache:
    dst = tmp_path / "dst"
    dst.mkdir(exist_ok=True)
    return HashCache(str(dst), **kwargs)


def test_roundtrip(tmp_path):
    cache = _make_cache(tmp_path)
    cache.put(
        "a.txt", size=10, src_mtime_ns=100,
        dst_mtime_ns=200, sha256="deadbeef",
    )
    cache.put(
        "sub/b.txt", size=20, src_mtime_ns=300,
        dst_mtime_ns=400, sha256="cafebabe",
    )
    cache.save()

    fresh = _make_cache(tmp_path)
    fresh.load()

    e = fresh.get("a.txt")
    assert isinstance(e, CacheEntry)
    assert e.size == 10
    assert e.src_mtime_ns == 100
    assert e.dst_mtime_ns == 200
    assert e.sha256 == "deadbeef"

    e2 = fresh.get("sub/b.txt")
    assert e2 is not None
    assert e2.sha256 == "cafebabe"


def test_missing_file(tmp_path):
    cache = _make_cache(tmp_path)
    cache.load()   # нет файла — не падаем
    assert cache.get("anything") is None


def test_corrupted_file(tmp_path):
    cache = _make_cache(tmp_path)
    path = cache._path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json {", encoding="utf-8")

    fresh = _make_cache(tmp_path)
    fresh.load()   # повреждённый — пусто, без падения
    assert fresh.get("anything") is None


def test_wrong_algorithm(tmp_path):
    cache = _make_cache(tmp_path, algorithm="sha256")
    cache.put(
        "a.txt", size=1, src_mtime_ns=1,
        dst_mtime_ns=1, sha256="x",
    )
    cache.save()

    fresh = _make_cache(tmp_path, algorithm="sha1")
    fresh.load()   # алгоритм не совпал — пусто
    assert fresh.get("a.txt") is None


def test_disabled_cache_noop(tmp_path):
    cache = _make_cache(tmp_path, enabled=False)
    cache.put(
        "a.txt", size=1, src_mtime_ns=1,
        dst_mtime_ns=1, sha256="x",
    )
    cache.save()
    assert not cache._path().exists()
    cache.load()
    assert cache.get("a.txt") is None


def test_no_save_when_not_dirty(tmp_path):
    cache = _make_cache(tmp_path)
    cache.save()   # пустой и не dirty — файла нет
    assert not cache._path().exists()

    cache.put(
        "a.txt", size=1, src_mtime_ns=1,
        dst_mtime_ns=1, sha256="x",
    )
    cache.save()
    assert cache._path().exists()

    # Второй save без изменений — файл не трогаем.
    mtime_before = cache._path().stat().st_mtime_ns
    cache.save()
    mtime_after = cache._path().stat().st_mtime_ns
    assert mtime_before == mtime_after


def test_hash_file(tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"hello")
    assert hash_file(str(p)) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


def test_remove_and_paths(tmp_path):
    cache = _make_cache(tmp_path)
    cache.put(
        "a.txt", size=1, src_mtime_ns=1,
        dst_mtime_ns=1, sha256="x",
    )
    cache.put(
        "b.txt", size=1, src_mtime_ns=1,
        dst_mtime_ns=1, sha256="y",
    )
    assert set(cache.paths()) == {"a.txt", "b.txt"}

    cache.remove("a.txt")
    assert cache.paths() == ["b.txt"]
