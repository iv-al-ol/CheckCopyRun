"""Автозапуск приложения в Windows через реестр."""

import os
import sys
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from config.constants import APP_NAME
from utils.logger import get_logger

logger = get_logger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_supported() -> bool:
    return winreg is not None


def _is_compiled() -> bool:
    """Определяет, запущено ли приложение как собранный .exe."""
    if getattr(sys, "frozen", False):
        return True

    if os.environ.get("NUITKA_ONEFILE_PARENT"):
        return True
    if os.environ.get("NUITKA_ONEFILE_BINARY"):
        return True

    try:
        import __main__
        if hasattr(__main__, "__compiled__"):
            return True
    except Exception as exc:
        logger.debug(f"проверка __main__.__compiled__ не удалась: {exc!r}")

    if hasattr(sys, "__nuitka_binary_dir"):
        return True

    try:
        if sys.argv and sys.argv[0].lower().endswith(".exe"):
            return True
    except Exception as exc:
        logger.debug(f"проверка sys.argv[0] не удалась: {exc!r}")

    try:
        exe_name = Path(sys.executable).name.lower()
        if exe_name not in ("python.exe", "pythonw.exe"):
            return True
    except Exception as exc:
        logger.debug(f"проверка sys.executable не удалась: {exc!r}")

    return False


def _resolve_launch_target() -> Path | None:
    """Путь к файлу, который надо запускать при автозапуске."""
    for var in ("NUITKA_ONEFILE_BINARY", "NUITKA_ONEFILE_PARENT"):
        value = os.environ.get(var)
        if value:
            try:
                p = Path(value).resolve()
                if p.exists() and p.suffix.lower() == ".exe":
                    return p
            except Exception as exc:
                logger.debug(
                    f"не удалось разобрать {var}={value!r}: {exc!r}"
                )

    try:
        if sys.argv and sys.argv[0]:
            candidate = Path(sys.argv[0])
            if candidate.suffix.lower() == ".exe":
                resolved = candidate.resolve()
                if resolved.exists():
                    return resolved
    except Exception as exc:
        logger.debug(f"разбор sys.argv[0] не удался: {exc!r}")

    try:
        exe = Path(sys.executable).resolve()
        if exe.name.lower() not in ("python.exe", "pythonw.exe"):
            return exe
    except Exception as exc:
        logger.debug(f"разбор sys.executable не удался: {exc!r}")

    return None


def _pythonw_from_venv() -> Path | None:
    """pythonw.exe из venv — чтобы при автозапуске не мигала консоль."""
    try:
        python_exe = Path(sys.executable).resolve()
    except Exception as exc:
        logger.debug(f"resolve sys.executable не удался: {exc!r}")
        return None

    candidates = [python_exe.with_name("pythonw.exe")]

    project_root = Path(__file__).resolve().parent.parent
    candidates.append(project_root / ".venv" / "Scripts" / "pythonw.exe")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def build_command() -> str | None:
    """Команда для автозапуска: путь к .exe или pythonw + main.py."""
    logger.debug(
        f"build_command: executable={sys.executable!r}, "
        f"argv0={(sys.argv[0] if sys.argv else None)!r}, "
        f"onefile_binary={os.environ.get('NUITKA_ONEFILE_BINARY')!r}, "
        f"onefile_parent={os.environ.get('NUITKA_ONEFILE_PARENT')!r}, "
        f"compiled={_is_compiled()}"
    )

    if _is_compiled():
        target = _resolve_launch_target()
        if target is None:
            logger.error(
                "приложение собрано, но путь к .exe определить не удалось"
            )
            return None
        logger.debug(f"команда для .exe: {target!r}")
        return f'"{target}"'

    project_root = Path(__file__).resolve().parent.parent
    main_py = project_root / "main.py"

    if not main_py.exists():
        logger.error(
            f"main.py не найден: {main_py!r} "
            f"(запуск из исходников невозможен)"
        )
        return None

    pythonw = _pythonw_from_venv()
    interpreter = (
        pythonw if pythonw is not None
        else Path(sys.executable).resolve()
    )

    logger.debug(f"команда для исходников: {interpreter!r} {main_py!r}")
    return f'"{interpreter}" "{main_py}"'


def is_enabled() -> bool:
    if not is_supported():
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            try:
                winreg.QueryValueEx(key, APP_NAME)
                return True
            except FileNotFoundError:
                return False
    except OSError as exc:
        logger.error(f"чтение ключа реестра {RUN_KEY!r}: {exc!r}")
        return False


def enable() -> bool:
    if not is_supported():
        return False

    command = build_command()
    if command is None:
        logger.error("build_command вернул None — нечего записывать")
        return False

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
        logger.debug(f"запись добавлена: {command!r}")
        return True
    except OSError as exc:
        logger.error(f"не удалось записать в реестр: {exc!r}")
        return False


def disable() -> bool:
    if not is_supported():
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                logger.debug(
                    f"запись {APP_NAME!r} в реестре отсутствовала"
                )
        return True
    except OSError as exc:
        logger.error(f"не удалось удалить из реестра: {exc!r}")
        return False


def set_enabled(enabled: bool) -> bool:
    return enable() if enabled else disable()


def get_current_command() -> str | None:
    """Возвращает текущее значение из реестра или None."""
    if not is_supported():
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            try:
                value, _ = winreg.QueryValueEx(key, APP_NAME)
                return str(value)
            except FileNotFoundError:
                return None
    except OSError as exc:
        logger.error(f"чтение текущей команды из реестра: {exc!r}")
        return None
