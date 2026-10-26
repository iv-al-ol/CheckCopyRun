"""Тесты чтения и создания !CCRun/message.txt."""

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
    MESSAGE_TEMPLATE,
    ensure_message_template,
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
    # Пустой файл — sha256 не считаем (даже не читаем).
    assert msg.sha256 == ""


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


# --- Комментарии ---

def test_read_message_strips_comment_lines(tmp_path):
    _write_message(
        tmp_path,
        "# комментарий\n"
        "Сборка готова\n"
        "# ещё коммент",
    )

    msg = read_message(str(tmp_path))

    assert "комментарий" not in msg.preview
    assert "комментарий" not in msg.text
    assert msg.preview == "Сборка готова"


def test_read_message_only_comments_is_empty(tmp_path):
    _write_message(
        tmp_path,
        "# только\n# комментарии\n#",
    )

    msg = read_message(str(tmp_path))

    assert msg.is_empty is True
    # sha256 заполнен — файл прочитан, монитор не перечитает
    # его каждый цикл.
    assert msg.sha256 != ""


def test_read_message_comment_with_indent(tmp_path):
    _write_message(
        tmp_path,
        "   # с отступом\nТекст",
    )

    msg = read_message(str(tmp_path))

    assert msg.preview == "Текст"
    assert "отступом" not in msg.preview


def test_read_message_inline_hash_is_not_comment(tmp_path):
    _write_message(tmp_path, "Сборка #42 готова")

    msg = read_message(str(tmp_path))

    assert msg.preview == "Сборка #42 готова"


def test_read_message_hash_includes_comments(tmp_path):
    """sha256 считается по сырым байтам: изменение комментария
    меняет хэш, но не превью."""
    _write_message(tmp_path, "# версия 1\nТекст")
    first = read_message(str(tmp_path))

    _write_message(tmp_path, "# версия 2\nТекст")
    second = read_message(str(tmp_path))

    assert first.preview == second.preview
    assert first.sha256 != second.sha256


# --- ensure_message_template ---

def test_ensure_template_empty_source():
    ok, err = ensure_message_template("")
    assert ok is False
    assert "папка-источник" in err.lower()


def test_ensure_template_creates_file(tmp_path):
    ok, err = ensure_message_template(str(tmp_path))

    assert ok is True
    assert err == ""

    path = tmp_path / CCRUN_DIR_NAME / MESSAGE_FILE_NAME
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text == MESSAGE_TEMPLATE
    assert "напишите сообщение ниже этой строки" in text


def test_ensure_template_creates_nested_dir(tmp_path):
    """!CCRun создаётся, если её нет."""
    source = tmp_path / "src"
    source.mkdir()

    ok, _ = ensure_message_template(str(source))

    assert ok is True
    assert (source / CCRUN_DIR_NAME).is_dir()
    assert (source / CCRUN_DIR_NAME / MESSAGE_FILE_NAME).is_file()


def test_ensure_template_does_not_overwrite(tmp_path):
    """Существующий файл не перезаписывается."""
    user_text = "Моё сообщение\nвторая строка"
    _write_message(tmp_path, user_text)

    ok, err = ensure_message_template(str(tmp_path))

    assert ok is True
    assert err == ""

    path = tmp_path / CCRUN_DIR_NAME / MESSAGE_FILE_NAME
    assert path.read_text(encoding="utf-8") == user_text


def test_ensure_template_idempotent(tmp_path):
    """Повторный вызов не падает и не меняет файл."""
    ensure_message_template(str(tmp_path))
    path = tmp_path / CCRUN_DIR_NAME / MESSAGE_FILE_NAME
    mtime_first = path.stat().st_mtime_ns

    ok, _ = ensure_message_template(str(tmp_path))
    assert ok is True

    assert path.stat().st_mtime_ns == mtime_first


def test_template_reads_as_empty(tmp_path):
    """Свежий шаблон — только комментарии. Пользователь не
    видит инструкцию в уведомлении."""
    ensure_message_template(str(tmp_path))

    msg = read_message(str(tmp_path))

    assert msg.is_empty is True
    assert msg.preview == ""
    # sha256 есть — монитор обновит базу без уведомления.
    assert msg.sha256 != ""
