"""Тесты files_identical."""

from __future__ import annotations

import os
from pathlib import Path

from services.file_compare import (
    ComparisonResult,
    files_identical,
)
from services.hash_cache import HashCache


def _prepare(
    tmp_path: Path, content_src: bytes, content_dst: bytes,
):
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_bytes(content_src)
    dst.write_bytes(content_dst)

    cache_dir = tmp_path / "dst_root"
    cache_dir.mkdir(exist_ok=True)
    cache = HashCache(str(cache_dir))

    return str(src), str(dst), cache


def _set_mtime(path: str, ns: int) -> None:
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, ns))


def test_different_size_no_read(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"abc", b"abcdef")
    # Патчим hash_file — если он будет вызван, тест упадёт.
    out = files_identical(src, dst, "f.txt", cache)
    assert out.result == ComparisonResult.DIFFERENT
    assert out.src_hash is None


def test_no_cache_same(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"same", b"same")
    out = files_identical(src, dst, "f.txt", cache)
    assert out.result == ComparisonResult.SAME
    assert out.src_hash is not None
    # Запись в кэше появилась.
    assert cache.get("f.txt") is not None


def test_no_cache_different(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"aaa", b"bbb")
    out = files_identical(src, dst, "f.txt", cache)
    assert out.result == ComparisonResult.DIFFERENT
    assert out.src_hash is not None
    # Запись в кэше тоже появилась (с хэшем src).
    entry = cache.get("f.txt")
    assert entry is not None
    assert entry.sha256 == out.src_hash


def test_cache_hit_both_unchanged(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"same", b"same")

    # Первый вызов — заполняет кэш.
    out1 = files_identical(src, dst, "f.txt", cache)
    assert out1.result == ComparisonResult.SAME

    # Второй — должен попасть в кэш, без чтения файлов.
    # Проверяем по mtime файла кэша: он не должен измениться.
    cache.save()
    cache_file_mtime = cache._path().stat().st_mtime_ns

    out2 = files_identical(src, dst, "f.txt", cache)
    assert out2.result == ComparisonResult.SAME
    assert out2.used_cache is True

    # Повторный save без изменений — файл кэша не трогается.
    cache.save()
    assert cache._path().stat().st_mtime_ns == cache_file_mtime


def test_cache_src_changed(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"same", b"same")

    files_identical(src, dst, "f.txt", cache)
    old_src_stat = os.stat(src)

    # Меняем mtime src, содержимое — то же.
    _set_mtime(src, old_src_stat.st_mtime_ns + 1_000_000_000)

    out = files_identical(src, dst, "f.txt", cache)
    assert out.result == ComparisonResult.SAME
    assert out.used_cache is True


def test_cache_dst_changed(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"same", b"same")
    files_identical(src, dst, "f.txt", cache)

    old_dst_stat = os.stat(dst)
    _set_mtime(dst, old_dst_stat.st_mtime_ns + 1_000_000_000)

    out = files_identical(src, dst, "f.txt", cache)
    assert out.result == ComparisonResult.SAME


def test_both_changed_content_differs(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"aaa", b"aaa")
    files_identical(src, dst, "f.txt", cache)

    # Оба меняем — содержимое разное, mtime разный.
    src_path = Path(src)
    dst_path = Path(dst)
    src_path.write_bytes(b"newAAA")
    dst_path.write_bytes(b"newBBB")

    out = files_identical(src, dst, "f.txt", cache)
    assert out.result == ComparisonResult.DIFFERENT


def test_cache_disabled_uses_filecmp(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"same", b"same")
    # Отключаем кэш принудительно.
    cache._enabled = False

    out = files_identical(src, dst, "f.txt", cache)
    assert out.result == ComparisonResult.SAME
    assert out.src_hash is None
    assert cache.get("f.txt") is None


def test_size_mismatch_clears_cache(tmp_path):
    src, dst, cache = _prepare(tmp_path, b"aaa", b"aaa")
    files_identical(src, dst, "f.txt", cache)
    assert cache.get("f.txt") is not None

    # Меняем размер — кэш должен быть очищен для этого файла.
    Path(dst).write_bytes(b"aaaa")

    out = files_identical(src, dst, "f.txt", cache)
    assert out.result == ComparisonResult.DIFFERENT
    assert cache.get("f.txt") is None
