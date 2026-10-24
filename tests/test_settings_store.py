"""Тесты сериализации AppSettings.

Проверяются _to_dict / _from_dict — чистые функции без DPAPI
и без обращения к диску. Сквозной save→load через DPAPI —
Windows-only и не нужен: там нет логики, только вызов ОС.
"""

from __future__ import annotations

from core.models import AppSettings, Profile
from core.settings_store import _from_dict, _to_dict


def test_defaults_new_fields():
    s = AppSettings()
    assert s.minimize_to_tray is False
    assert s.autostart is False
    assert s.start_minimized is False
    assert s.run_autocheck_on_restored is False


def test_notifications_defaults():
    """Уведомления включены, автоскрытие выключено."""
    from config.constants import (
        MONITOR_INTERVAL_DEFAULT,
        NOTIFY_AUTO_CLOSE_MIN,
    )

    s = AppSettings()
    assert s.notifications_enabled is True
    assert s.notify_source_changes is True
    assert s.notify_message is True
    assert s.notify_aggregate is True
    assert s.notify_auto_close_sec == NOTIFY_AUTO_CLOSE_MIN
    assert s.monitor_interval_min == MONITOR_INTERVAL_DEFAULT


def test_notifications_roundtrip():
    s = AppSettings(
        notifications_enabled=False,
        notify_source_changes=False,
        notify_message=False,
        notify_aggregate=False,
        notify_auto_close_sec=30,
        monitor_interval_min=15,
    )
    s2 = _from_dict(_to_dict(s))
    assert s2.notifications_enabled is False
    assert s2.notify_source_changes is False
    assert s2.notify_message is False
    assert s2.notify_aggregate is False
    assert s2.notify_auto_close_sec == 30
    assert s2.monitor_interval_min == 15


def test_auto_close_clamped():
    from config.constants import (
        NOTIFY_AUTO_CLOSE_MAX,
        NOTIFY_AUTO_CLOSE_MIN,
    )

    below = _from_dict({"notify_auto_close_sec": -10})
    above = _from_dict({"notify_auto_close_sec": 99999})
    garbage = _from_dict({"notify_auto_close_sec": "abc"})

    assert below.notify_auto_close_sec == NOTIFY_AUTO_CLOSE_MIN
    assert above.notify_auto_close_sec == NOTIFY_AUTO_CLOSE_MAX
    assert garbage.notify_auto_close_sec == NOTIFY_AUTO_CLOSE_MIN


def test_monitor_interval_clamped():
    from config.constants import (
        MONITOR_INTERVAL_MAX,
        MONITOR_INTERVAL_MIN,
    )

    assert _from_dict(
        {"monitor_interval_min": 0},
    ).monitor_interval_min == MONITOR_INTERVAL_MIN
    assert _from_dict(
        {"monitor_interval_min": 5000},
    ).monitor_interval_min == MONITOR_INTERVAL_MAX


def test_profile_notify_flags_roundtrip():
    p = Profile(notify_on_changes=False, notify_on_message=False)
    s = AppSettings(profiles=[p])

    s2 = _from_dict(_to_dict(s))

    assert s2.profiles[0].notify_on_changes is False
    assert s2.profiles[0].notify_on_message is False


def test_old_settings_without_notify_fields():
    """Старый settings.dat без новых полей не ломает загрузку."""
    s = _from_dict({"version": 1, "theme": "dark"})

    assert s.notifications_enabled is True
    assert s.notify_auto_close_sec == 0


def test_roundtrip_new_flags():
    s = AppSettings(
        minimize_to_tray=True,
        autostart=True,
        start_minimized=True,
        run_autocheck_on_restored=True,
    )
    s2 = _from_dict(_to_dict(s))
    assert s2.minimize_to_tray is True
    assert s2.autostart is True
    assert s2.start_minimized is True
    assert s2.run_autocheck_on_restored is True


def test_roundtrip_existing_fields_unchanged():
    s = AppSettings(
        theme="light",
        confirm_on_exit=True,
        window_geometry="900x600+100+50",
        hash_cache_enabled=False,
        backup_keep_last_enabled=True,
        backup_keep_last_n=5,
        backup_delete_older_enabled=True,
        backup_delete_older_days=14,
    )
    s2 = _from_dict(_to_dict(s))
    assert s2.theme == "light"
    assert s2.confirm_on_exit is True
    assert s2.window_geometry == "900x600+100+50"
    assert s2.hash_cache_enabled is False
    assert s2.backup_keep_last_enabled is True
    assert s2.backup_keep_last_n == 5
    assert s2.backup_delete_older_enabled is True
    assert s2.backup_delete_older_days == 14


def test_roundtrip_profiles():
    s = AppSettings(profiles=[
        Profile(
            name_base="A",
            source="C:\\src",
            destination="C:\\dst",
            check_on_startup=True,
            mirror_mode=True,
            create_backup=False,
            create_backup_warned=True,
        ),
    ])
    s2 = _from_dict(_to_dict(s))
    assert len(s2.profiles) == 1
    p = s2.profiles[0]
    assert p.name_base == "A"
    assert p.check_on_startup is True
    assert p.mirror_mode is True
    assert p.create_backup is False
    assert p.create_backup_warned is True


def test_from_dict_missing_new_fields_uses_defaults():
    """Старый settings.dat без новых полей читается корректно."""
    legacy = {
        "version": 1,
        "theme": "dark",
        "profiles": [],
    }
    s = _from_dict(legacy)
    assert s.minimize_to_tray is False
    assert s.autostart is False
    assert s.start_minimized is False
    assert s.run_autocheck_on_restored is False
