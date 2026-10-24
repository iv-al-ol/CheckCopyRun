"""Тесты MonitorService: синхронный цикл без потоков и sleep."""

from __future__ import annotations

import os
from pathlib import Path

from config.constants import (
    MONITOR_INTERVAL_DEFAULT,
    MONITOR_INTERVAL_MAX,
    MONITOR_INTERVAL_MIN,
)
from core.models import AppSettings, Profile
from services.common.copy_constants import (
    CCRUN_DIR_NAME,
    MESSAGE_FILE_NAME,
)
from services.monitor.monitor_service import (
    MonitorService,
    clamp_interval,
)
from services.monitor.monitor_state import MonitorStore


class RecordingNotifier:
    def __init__(self):
        self.notifications = []

    def notify(self, notification):
        self.notifications.append(notification)
        return True


def _make_profile(tmp_path: Path, name: str = "p") -> Profile:
    src = tmp_path / f"src_{name}"
    dst = tmp_path / f"dst_{name}"
    src.mkdir()
    dst.mkdir()
    return Profile(
        name_base=name,
        source=str(src),
        destination=str(dst),
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def _service(tmp_path: Path, notifier=None, busy=None) -> MonitorService:
    return MonitorService(
        notifier=notifier or RecordingNotifier(),
        store=MonitorStore(tmp_path / "state"),
        is_busy=busy,
    )


# --- clamp_interval ---

def test_clamp_interval_bounds():
    assert clamp_interval(0) == MONITOR_INTERVAL_MIN
    assert clamp_interval(-5) == MONITOR_INTERVAL_MIN
    assert clamp_interval(999) == MONITOR_INTERVAL_MAX
    assert clamp_interval(15) == 15


def test_clamp_interval_garbage():
    assert clamp_interval("oops") == MONITOR_INTERVAL_DEFAULT
    assert clamp_interval(None) == MONITOR_INTERVAL_DEFAULT


# --- run_once ---

def test_first_run_creates_base_without_notification(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())

    result = service.run_once()

    assert result.checked == 1
    assert result.with_changes == 0
    assert notifier.notifications == []
    assert service._store.load(profile.id) is not None


def test_second_run_reports_changes(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    _write(Path(profile.source) / "new.txt", "new")
    result = service.run_once()

    assert result.with_changes == 1
    assert len(notifier.notifications) == 1
    assert notifier.notifications[0].title == profile.display_name
    assert "Добавлено 1" in notifier.notifications[0].body


def test_no_changes_no_notification(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    service.run_once()

    assert notifier.notifications == []


def test_message_shown_on_first_run(tmp_path):
    profile = _make_profile(tmp_path)
    message = (
        Path(profile.source) / CCRUN_DIR_NAME / MESSAGE_FILE_NAME
    )
    _write(message, "Сборка готова")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())

    service.run_once()

    assert len(notifier.notifications) == 1
    assert "Сборка готова" in notifier.notifications[0].body


def test_message_not_repeated(tmp_path):
    profile = _make_profile(tmp_path)
    message = (
        Path(profile.source) / CCRUN_DIR_NAME / MESSAGE_FILE_NAME
    )
    _write(message, "Сообщение")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    service.run_once()

    assert len(notifier.notifications) == 1


def test_message_update_shown_again(tmp_path):
    profile = _make_profile(tmp_path)
    message = (
        Path(profile.source) / CCRUN_DIR_NAME / MESSAGE_FILE_NAME
    )
    _write(message, "Версия 1")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    _write(message, "Версия 2")
    service.run_once()

    assert len(notifier.notifications) == 2
    assert "Версия 2" in notifier.notifications[1].body


def test_changes_and_message_merged(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    _write(Path(profile.source) / "b.txt", "bbb")
    message = (
        Path(profile.source) / CCRUN_DIR_NAME / MESSAGE_FILE_NAME
    )
    _write(message, "Готово")
    service.run_once()

    assert len(notifier.notifications) == 1
    body = notifier.notifications[0].body
    assert "Добавлено 1" in body
    assert "Готово" in body


def test_busy_profile_skipped(tmp_path):
    profile = _make_profile(tmp_path)
    notifier = RecordingNotifier()
    service = _service(
        tmp_path, notifier, busy=lambda _pid: True,
    )
    service.configure([profile], AppSettings())

    result = service.run_once()

    assert result.skipped_busy == 1
    assert result.checked == 0
    assert notifier.notifications == []


def test_disabled_notifications_do_nothing(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    settings = AppSettings(notifications_enabled=False)
    service.configure([profile], settings)

    result = service.run_once()

    assert result.checked == 0
    assert notifier.notifications == []


def test_channel_disabled_globally(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure(
        [profile],
        AppSettings(notify_source_changes=False),
    )
    service.run_once()

    _write(Path(profile.source) / "b.txt", "bbb")
    service.run_once()

    assert notifier.notifications == []


def test_channel_disabled_per_profile(tmp_path):
    profile = _make_profile(tmp_path)
    profile.notify_on_changes = False
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    _write(Path(profile.source) / "b.txt", "bbb")
    service.run_once()

    assert notifier.notifications == []


def test_profile_without_source_skipped(tmp_path):
    profile = Profile(name_base="broken", destination=str(tmp_path))
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())

    result = service.run_once()

    assert result.checked == 0
    assert notifier.notifications == []


def test_source_disappeared_is_not_deletions(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    import shutil

    shutil.rmtree(profile.source)
    result = service.run_once()

    assert result.skipped_unavailable == 1
    assert notifier.notifications == []


def test_aggregation_of_two_profiles(tmp_path):
    p1 = _make_profile(tmp_path, "one")
    p2 = _make_profile(tmp_path, "two")
    _write(Path(p1.source) / "a.txt", "a")
    _write(Path(p2.source) / "b.txt", "b")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([p1, p2], AppSettings())
    service.run_once()

    _write(Path(p1.source) / "a2.txt", "a2")
    _write(Path(p2.source) / "b2.txt", "b2")
    service.run_once()

    assert len(notifier.notifications) == 1
    assert "Обновления в 2 профиля" in (
        notifier.notifications[0].title
    )


def test_no_aggregation_sends_each(tmp_path):
    p1 = _make_profile(tmp_path, "one")
    p2 = _make_profile(tmp_path, "two")
    _write(Path(p1.source) / "a.txt", "a")
    _write(Path(p2.source) / "b.txt", "b")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure(
        [p1, p2], AppSettings(notify_aggregate=False),
    )
    service.run_once()

    _write(Path(p1.source) / "a2.txt", "a2")
    _write(Path(p2.source) / "b2.txt", "b2")
    service.run_once()

    assert len(notifier.notifications) == 2


def test_reset_profile_silences_next_diff(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    _write(Path(profile.source) / "b.txt", "bbb")
    service.reset_profile(profile.id)
    service.run_once()

    assert notifier.notifications == []


def test_source_change_resets_base(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    new_src = tmp_path / "another_src"
    new_src.mkdir()
    _write(new_src / "x.txt", "x")
    profile.source = str(new_src)

    service.configure([profile], AppSettings())
    result = service.run_once()

    assert result.with_changes == 0
    assert notifier.notifications == []


def test_prune_removes_deleted_profiles(tmp_path):
    p1 = _make_profile(tmp_path, "keep")
    p2 = _make_profile(tmp_path, "drop")
    service = _service(tmp_path)
    service.configure([p1, p2], AppSettings())
    service.run_once()

    service.configure([p1], AppSettings())
    service.run_once()

    assert service._store.load(p2.id) is None


def test_auto_close_applied_to_notification(tmp_path):
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    _write(Path(profile.source) / "b.txt", "bbb")
    service.configure(
        [profile], AppSettings(notify_auto_close_sec=30),
    )
    service.run_once()

    assert notifier.notifications[-1].auto_close_sec == 30


def test_default_auto_close_is_zero(tmp_path):
    """По умолчанию уведомление не исчезает само."""
    profile = _make_profile(tmp_path)
    _write(Path(profile.source) / "a.txt", "aaa")
    notifier = RecordingNotifier()
    service = _service(tmp_path, notifier)
    service.configure([profile], AppSettings())
    service.run_once()

    _write(Path(profile.source) / "b.txt", "bbb")
    service.run_once()

    assert notifier.notifications[-1].auto_close_sec == 0
