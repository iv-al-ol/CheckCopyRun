"""Загрузка и атомарное сохранение settings.dat (DPAPI + JSON)."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from config.constants import (
    HASH_CACHE_ENABLED_DEFAULT,
    ICONS_DIR_NAME,
    MONITOR_INTERVAL_DEFAULT,
    MONITOR_INTERVAL_MAX,
    MONITOR_INTERVAL_MIN,
    NOTIFY_AUTO_CLOSE_DEFAULT,
    NOTIFY_AUTO_CLOSE_MAX,
    NOTIFY_AUTO_CLOSE_MIN,
    SETTINGS_DIR_NAME,
    SETTINGS_FILE_NAME,
    SETTINGS_VERSION,
    THEME_DEFAULT,
)
from core.models import AppSettings, Profile
from core.paths import get_documents_dir
from services.system.dpapi import DpapiError, protect, unprotect
from utils.logger import get_logger

logger = get_logger(__name__)

_PROFILE_FIELDS = {
    "id",
    "name_base",
    "name_manual",
    "name_auto",
    "icon",
    "icon_auto",
    "source",
    "destination",
    "exe_relative",
    "create_backup",
    "create_backup_warned",
    "run_after_copy",
    "check_on_startup",
    "mirror_mode",
    "notify_on_changes",
    "notify_on_message",
    "pinned",
    "last_used_at",
}


def get_settings_path() -> Path:
    return get_documents_dir() / SETTINGS_DIR_NAME / SETTINGS_FILE_NAME


def get_icons_dir() -> Path:
    return get_documents_dir() / SETTINGS_DIR_NAME / ICONS_DIR_NAME


def load_settings() -> AppSettings:
    path = get_settings_path()
    if not path.exists():
        logger.info("settings.dat отсутствует — дефолтные настройки")
        return AppSettings()

    try:
        raw = path.read_bytes()
    except OSError as exc:
        logger.error("Не удалось прочитать %s: %r", path, exc)
        return AppSettings()

    try:
        decrypted = unprotect(raw)
        data = json.loads(decrypted.decode("utf-8"))
    except (DpapiError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.error(
            "settings.dat не расшифрован/не разобран: %r", exc,
        )
        return AppSettings()

    try:
        return _from_dict(data)
    except Exception as exc:
        logger.error("Некорректная структура настроек: %r", exc)
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    path = get_settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            _to_dict(settings), ensure_ascii=False, indent=2,
        ).encode("utf-8")
        encrypted = protect(payload)
    except Exception as exc:
        logger.error(
            "Не удалось подготовить settings.dat: %r", exc,
        )
        return

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(encrypted)
        os.replace(tmp_name, path)
        logger.debug(
            "settings.dat сохранён (%d байт)", len(encrypted),
        )
    except Exception as exc:
        logger.error(
            "Не удалось записать settings.dat: %r", exc,
        )
        try:
            os.unlink(tmp_name)
        except OSError as cleanup_exc:
            logger.debug(
                "Не удалось удалить временный файл %s: %r",
                tmp_name, cleanup_exc,
            )


# --- Сериализация ---

def _to_dict(s: AppSettings) -> dict:
    return {
        "version": s.version,
        "theme": s.theme,
        "confirm_on_exit": s.confirm_on_exit,
        "window_geometry": s.window_geometry,
        "hash_cache_enabled": s.hash_cache_enabled,
        "run_autocheck_on_restored": s.run_autocheck_on_restored,
        "minimize_to_tray": s.minimize_to_tray,
        "autostart": s.autostart,
        "start_minimized": s.start_minimized,
        "notifications_enabled": s.notifications_enabled,
        "notify_source_changes": s.notify_source_changes,
        "notify_message": s.notify_message,
        "notify_aggregate": s.notify_aggregate,
        "notify_auto_close_sec": s.notify_auto_close_sec,
        "monitor_interval_min": s.monitor_interval_min,
        "backup_keep_last_enabled": s.backup_keep_last_enabled,
        "backup_keep_last_n": s.backup_keep_last_n,
        "backup_delete_older_enabled": (
            s.backup_delete_older_enabled
        ),
        "backup_delete_older_days": s.backup_delete_older_days,
        "profiles": [asdict(p) for p in s.profiles],
    }


def _from_dict(data: dict) -> AppSettings:
    profiles: list[Profile] = []
    raw_profiles = data.get("profiles", [])

    # profiles может оказаться чем угодно: ручная правка JSON,
    # баг прошлой версии, повреждённая запись DPAPI. Если
    # элемент — не словарь, `raw.items()` бросит
    # AttributeError, и весь settings.dat вернётся к дефолтам
    # (`load_settings` ловит исключение и отдаёт AppSettings()).
    # Одна кривая запись не должна ронять все настройки.
    if not isinstance(raw_profiles, list):
        logger.warning(
            "settings.dat: profiles не список (%s) — пропущен",
            type(raw_profiles).__name__,
        )
        raw_profiles = []

    for idx, raw in enumerate(raw_profiles):
        if not isinstance(raw, dict):
            logger.warning(
                "settings.dat: profiles[%d] не словарь (%s) — "
                "пропущен",
                idx, type(raw).__name__,
            )
            continue
        clean = {
            k: v for k, v in raw.items()
            if k in _PROFILE_FIELDS
        }
        try:
            profiles.append(Profile(**clean))
        except TypeError as exc:
            # Несовместимые типы/неожиданный аргумент — тоже
            # не повод терять остальные профили.
            logger.warning(
                "settings.dat: profiles[%d] не загружен: %r",
                idx, exc,
            )

    def _int(value: object, default: int, min_v: int = 1) -> int:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return default
        return max(min_v, n)

    return AppSettings(
        version=data.get("version", SETTINGS_VERSION),
        theme=data.get("theme", THEME_DEFAULT),
        confirm_on_exit=bool(data.get("confirm_on_exit", False)),
        window_geometry=data.get("window_geometry", ""),
        hash_cache_enabled=bool(
            data.get(
                "hash_cache_enabled",
                HASH_CACHE_ENABLED_DEFAULT,
            )
        ),
        run_autocheck_on_restored=bool(
            data.get("run_autocheck_on_restored", False)
        ),
        minimize_to_tray=bool(
            data.get("minimize_to_tray", False)
        ),
        autostart=bool(data.get("autostart", False)),
        start_minimized=bool(data.get("start_minimized", False)),
        notifications_enabled=bool(
            data.get("notifications_enabled", True)
        ),
        notify_source_changes=bool(
            data.get("notify_source_changes", True)
        ),
        notify_message=bool(data.get("notify_message", True)),
        notify_aggregate=bool(data.get("notify_aggregate", True)),
        notify_auto_close_sec=max(
            NOTIFY_AUTO_CLOSE_MIN,
            min(
                NOTIFY_AUTO_CLOSE_MAX,
                _int(
                    data.get("notify_auto_close_sec"),
                    NOTIFY_AUTO_CLOSE_DEFAULT,
                    min_v=NOTIFY_AUTO_CLOSE_MIN,
                ),
            ),
        ),
        monitor_interval_min=max(
            MONITOR_INTERVAL_MIN,
            min(
                MONITOR_INTERVAL_MAX,
                _int(
                    data.get("monitor_interval_min"),
                    MONITOR_INTERVAL_DEFAULT,
                ),
            ),
        ),
        # Дефолт True — новый дефолт модели.
        backup_keep_last_enabled=bool(
            data.get("backup_keep_last_enabled", True)
        ),
        backup_keep_last_n=_int(
            data.get("backup_keep_last_n", 10), 10,
        ),
        backup_delete_older_enabled=bool(
            data.get("backup_delete_older_enabled", False)
        ),
        backup_delete_older_days=_int(
            data.get("backup_delete_older_days", 30), 30,
        ),
        profiles=profiles,
    )
