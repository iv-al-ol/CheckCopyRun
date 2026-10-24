"""Тесты чтения !CCRun/message.txt."""

from __future__ import annotations

from config.constants import (
    MESSAGE_FILE_MAX_BYTES,
    MESSAGE_PREVIEW_CHARS,
    MESSAGE_PREVIEW_LINES,
)
from services.common.copy_constants import (
    CCRUN_DIR_NAME,
    MESSAGE_FILE_NAME,
)
from services.monitor.message_file import (
    message_path,
    read_message,
)


def _write_message(source, text: str, encoding: str = "utf-8"):
    path = source / CCRUN_DIR_NAME / MESSAGE_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode(encoding))
    return path


def test_message_path_empty_source():
    assert message_path("") == ""


def test_message_path_points_into_ccrun(tmp_path):
    path = message_path(str(tmp_path))
    assert path.endswith(
        f"{CCRUN_DIR_NAME}\\{MESSAGE_FILE_NAME}",
    ) or path.endswith(f"{CCRUN_DIR_NAME}/{MESSAGE_FILE_NAME}")


def test_read_message_missing_file(tmp_path):
    msg = read_message(str(tmp_path))
    assert msg.is_empty is True
    assert msg.sha256 == ""


def test_read_message_utf8(tmp_path):
    _write_message(tmp_path, "Привет\nМир")

    msg = read_message(str(tmp_path))

    assert msg.text.strip() == "Привет\nМир"
    assert msg.preview == "Привет\nМир"
    assert len(msg.sha256) == 64
    assert msg.truncated is False


def test_read_message_utf8_with_bom(tmp_path):
    _write_message(tmp_path, "с BOM", encoding="utf-8-sig")

    msg = read_message(str(tmp_path))

    assert msg.text == "с BOM"


def test_read_message_cp1251(tmp_path):
    _write_message(tmp_path, "Кириллица", encoding="cp1251")

    msg = read_message(str(tmp_path))

    assert msg.text == "Кириллица"


def test_read_message_empty_file(tmp_path):
    _write_message(tmp_path, "")

    msg = read_message(str(tmp_path))

    assert msg.is_empty is True


def test_read_message_preview_limits_lines(tmp_path):
    lines = [f"строка {i}" for i in range(20)]
    _write_message(tmp_path, "\n".join(lines))

    msg = read_message(str(tmp_path))

    preview_lines = msg.preview.rstrip("…").splitlines()
    assert len(preview_lines) <= MESSAGE_PREVIEW_LINES
    assert msg.preview.endswith("…")


def test_read_message_preview_limits_chars(tmp_path):
    _write_message(tmp_path, "x" * (MESSAGE_PREVIEW_CHARS + 100))

    msg = read_message(str(tmp_path))

    assert len(msg.preview) <= MESSAGE_PREVIEW_CHARS + 1
    assert msg.preview.endswith("…")


def test_read_message_large_file_is_truncated(tmp_path):
    _write_message(tmp_path, "y" * (MESSAGE_FILE_MAX_BYTES + 10))

    msg = read_message(str(tmp_path))

    assert msg.truncated is True
    assert msg.text != ""


def test_read_message_hash_stable(tmp_path):
    _write_message(tmp_path, "одно и то же")

    first = read_message(str(tmp_path))
    second = read_message(str(tmp_path))

    assert first.sha256 == second.sha256
    assert first.sha256 != ""


def test_read_message_hash_changes(tmp_path):
    _write_message(tmp_path, "версия 1")
    first = read_message(str(tmp_path))

    _write_message(tmp_path, "версия 2")
    second = read_message(str(tmp_path))

    assert first.sha256 != second.sha256


def test_read_message_skips_blank_lines_in_preview(tmp_path):
    _write_message(tmp_path, "\n\n\nТекст\n\n")

    msg = read_message(str(tmp_path))

    assert msg.preview == "Текст"
