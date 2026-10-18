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
    SETTINGS_DIR_NAME,
    SETTINGS_FILE_NAME,
    SETTINGS_VERSION,
    THEME_DEFAULT,
)
from core.models import AppSettings, Profile
from core.paths import get_documents_dir
from services.dpapi import DpapiError, protect, unprotect
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
    "run_after_copy",
    "check_on_startup",
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
        logger.error("settings.dat не расшифрован/не разобран: %r", exc)
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
        logger.error("Не удалось подготовить settings.dat: %r", exc)
        return

    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(encrypted)
        os.replace(tmp_name, path)
        logger.debug("settings.dat сохранён (%d байт)", len(encrypted))
    except Exception as exc:
        logger.error("Не удалось записать settings.dat: %r", exc)
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
        "last_view": s.last_view,
        "hash_cache_enabled": s.hash_cache_enabled,
        "profiles": [asdict(p) for p in s.profiles],
    }


def _from_dict(data: dict) -> AppSettings:
    profiles: list[Profile] = []
    for raw in data.get("profiles", []):
        clean = {k: v for k, v in raw.items() if k in _PROFILE_FIELDS}
        profiles.append(Profile(**clean))

    return AppSettings(
        version=data.get("version", SETTINGS_VERSION),
        theme=data.get("theme", THEME_DEFAULT),
        confirm_on_exit=bool(data.get("confirm_on_exit", False)),
        window_geometry=data.get("window_geometry", ""),
        last_view=data.get("last_view", "main"),
        hash_cache_enabled=bool(
            data.get(
                "hash_cache_enabled",
                HASH_CACHE_ENABLED_DEFAULT,
            )
        ),
        profiles=profiles,
    )
