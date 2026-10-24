"""Тесты tray / tray_manager — defensive-ветки.

Реальная иконка в трее не тестируется: pystray запускает
GUI-цикл, требует рабочего стола и уведомлений ОС.

Проверяем то, что можно безопасно проверить без GUI:
  • поведение при отсутствии pystray;
  • поведение при отсутствии файла иконки;
  • stop() до start() — no-op, не падает;
  • TrayManager с icon_path=None;
  • TrayManager.stop() до start() — no-op.
"""

from __future__ import annotations

from services import tray as tray_module
from services.tray import TrayIcon
from services.tray_manager import TrayManager

# --- TrayIcon ---

def test_tray_unsupported_without_pystray(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(tray_module, "pystray", None)
    icon_path = tmp_path / "icon.ico"
    icon_path.write_bytes(b"\x00")

    t = TrayIcon(
        icon_path=icon_path,
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    assert t.is_supported is False
    assert t.start() is False


def test_tray_unsupported_without_pil(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(tray_module, "Image", None)
    icon_path = tmp_path / "icon.ico"
    icon_path.write_bytes(b"\x00")

    t = TrayIcon(
        icon_path=icon_path,
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    assert t.is_supported is False
    assert t.start() is False


def test_tray_missing_icon_file(tmp_path):
    """Даже при установленном pystray отсутствие файла → False."""
    missing = tmp_path / "missing.ico"
    t = TrayIcon(
        icon_path=missing,
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    assert t.start() is False


def test_tray_stop_when_not_started(tmp_path):
    t = TrayIcon(
        icon_path=tmp_path / "x.ico",
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    # Просто не должно падать.
    t.stop()


def test_tray_notify_when_not_started(tmp_path):
    t = TrayIcon(
        icon_path=tmp_path / "x.ico",
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    # Иконка не запущена — notify() молча возвращает.
    t.notify("hi")


# --- TrayManager ---

def test_tray_manager_no_icon_path():
    tm = TrayManager(
        icon_path=None,
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    assert tm.is_active is False
    assert tm.start() is False
    assert tm.is_active is False


def test_tray_manager_stop_when_not_started():
    tm = TrayManager(
        icon_path=None,
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    # No-op — не падает.
    tm.stop()


def test_tray_manager_start_missing_icon(tmp_path):
    tm = TrayManager(
        icon_path=tmp_path / "missing.ico",
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    assert tm.start() is False
    assert tm.is_active is False


def test_tray_manager_start_twice_is_idempotent(
    monkeypatch, tmp_path,
):
    """После успешного start повторный start не создаёт второй
    экземпляр. Эмулируем успех через пустой TrayIcon."""
    monkeypatch.setattr(tray_module, "pystray", None)

    # Без pystray start вернёт False, но is_active останется False,
    # и повторный вызов не упадёт.
    tm = TrayManager(
        icon_path=tmp_path / "x.ico",
        title="T",
        on_show=lambda: None,
        on_quit=lambda: None,
    )
    assert tm.start() is False
    assert tm.start() is False
    assert tm.is_active is False
