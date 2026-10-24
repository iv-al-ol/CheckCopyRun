"""Сборка CheckCopyRun через Nuitka.

Имя .exe и папки сборки — CCRun (сокращение от CheckCopyRun).

Запуск:
    uv run build.py                 # папочная сборка (CCRun.dist/)
    uv run build.py --onefile       # единый CCRun.exe
    uv run build.py --debug         # с консолью (для отладки)

Что делает:
  1. Проверяет точку входа, иконку, config/constants.py.
  2. Читает APP_NAME / APP_TITLE / APP_VERSION из constants.
  3. Удаляет старые артефакты, чтобы не смешивались.
  4. Запускает Nuitka.
  5. Переименовывает main.build / main.dist в CCRun.*
  6. Печатает путь к готовому .exe.

Иконка берётся из assets/icon.ico: встраивается в .exe
и копируется как data-файл — чтобы Tkinter мог её подхватить
для окна.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# --- Параметры сборки ---

ENTRY_SCRIPT = "main.py"
# Имя exe и папки сборки — CCRun (сокращение от CheckCopyRun).
# Метаданные exe (CompanyName / ProductName) берутся из
# config/constants.py — APP_NAME / APP_TITLE.
OUTPUT_NAME = "CCRun"
ICON_FILE = "assets/icon.ico"
# Манифест с dpiAwareness=PerMonitorV2: без него Windows растягивает
# готовое изображение окна и на 2K/4K интерфейс получается мыльным,
# а ScalingTracker видит масштаб 1.0 и ломает расчёт геометрии.
MANIFEST_FILE = "assets/app.manifest"
ASSETS_DIR = "assets"
OUTPUT_DIR = "build"

# Nuitka создаёт папки по имени главного скрипта: main.build,
# main.dist, main.onefile-build. Переименовываем в CCRun.*
_MAIN_STEM = Path(ENTRY_SCRIPT).stem
_RENAMED_STEM = OUTPUT_NAME

_RENAME_MAP = {
    f"{_MAIN_STEM}.build": f"{_RENAMED_STEM}.build",
    f"{_MAIN_STEM}.dist": f"{_RENAMED_STEM}.dist",
    f"{_MAIN_STEM}.onefile-build": f"{_RENAMED_STEM}.onefile-build",
}

# Пакеты, которые Nuitka не всегда подхватывает автоматически.
_INCLUDE_PACKAGES = [
    "customtkinter",
    "PIL",
]

# Модули, которые точно не нужны в собранном виде.
_NOFOLLOW_IMPORTS = [
    "*.tests",
    "*.tests.*",
    "test",
    "tests",
    "unittest",
    "pydoc",
    "lib2to3",
    "pip",
    "setuptools",
    "pytest",
    "_pytest",
    "ruff",
    "mypy",
]


# --- Метаданные ---

def _load_app_metadata() -> dict[str, str]:
    """Читает APP_NAME / APP_TITLE / APP_VERSION из config/constants.py."""
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    try:
        from config.constants import (
            APP_NAME,
            APP_TITLE,
            APP_VERSION,
        )
    except Exception as exc:
        print(f"  Не удалось прочитать config/constants.py: {exc!r}")
        return {
            "name": OUTPUT_NAME,
            "title": OUTPUT_NAME,
            "version": "1.0.0.0",
        }

    # Windows file-version: ровно четыре числа.
    parts = str(APP_VERSION).split(".")
    while len(parts) < 4:
        parts.append("0")
    version = ".".join(parts[:4])

    return {
        "name": str(APP_NAME),
        "title": str(APP_TITLE),
        "version": version,
    }


# --- Формирование команды ---

def _build_command(
    project_root: Path, *, onefile: bool, debug: bool,
) -> list[str]:
    meta = _load_app_metadata()

    cmd: list[str] = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        f"--output-dir={OUTPUT_DIR}",
        f"--output-filename={OUTPUT_NAME}",
        f"--windows-icon-from-ico={ICON_FILE}",
        f"--windows-manifest={MANIFEST_FILE}",
        "--enable-plugin=tk-inter",
        "--jobs=4",
        "--assume-yes-for-downloads",
        # Метаданные exe.
        f"--company-name={meta['name']}",
        f"--product-name={meta['title']}",
        f"--file-version={meta['version']}",
        f"--product-version={meta['version']}",
        f"--file-description={meta['title']}",
        # Данные: assets/ (иконка приложения).
        f"--include-data-dir={ASSETS_DIR}={ASSETS_DIR}",
    ]

    if onefile:
        cmd.append("--onefile")

    if debug:
        # В дебаге консоль оставляем, чтобы видеть ошибки запуска.
        cmd.append("--windows-console-mode=force")
    else:
        cmd.append("--windows-console-mode=disable")

    for pkg in _INCLUDE_PACKAGES:
        cmd.append(f"--include-package={pkg}")

    for skip in _NOFOLLOW_IMPORTS:
        cmd.append(f"--nofollow-import-to={skip}")

    cmd.append(ENTRY_SCRIPT)
    return cmd


# --- Проверка окружения ---

def _check_prerequisites(project_root: Path) -> bool:
    errors: list[str] = []

    entry = project_root / ENTRY_SCRIPT
    if not entry.is_file():
        errors.append(f"Точка входа не найдена: {entry}")

    icon = project_root / ICON_FILE
    if not icon.is_file():
        errors.append(
            f"Иконка не найдена: {icon}\n"
            f"Положите .ico в {ICON_FILE}."
        )

    manifest = project_root / MANIFEST_FILE
    if not manifest.is_file():
        errors.append(
            f"Манифест не найден: {manifest}\n"
            f"Без него ломается масштабирование на HiDPI."
        )

    constants = project_root / "config" / "constants.py"
    if not constants.is_file():
        errors.append(f"Не найден config/constants.py: {constants}")

    # Nuitka
    try:
        result = subprocess.run(
            [sys.executable, "-m", "nuitka", "--version"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        errors.append("Nuitka не найден. Установите: uv add nuitka")
    except subprocess.TimeoutExpired:
        errors.append("Nuitka не отвечает. Проверьте установку.")
    else:
        if result.returncode != 0:
            errors.append(
                "Nuitka не запускается. Установите: uv add nuitka",
            )
        else:
            version_line = (result.stdout or "").strip().splitlines()
            version = version_line[0] if version_line else "?"
            print(f"Nuitka: {version}")

    if errors:
        print("\nОшибки перед сборкой:")
        for e in errors:
            print(f"  • {e}")
        return False

    return True


# --- Очистка / переименование ---

def _clean_output(project_root: Path) -> None:
    """Удаляет старые артефакты, чтобы не смешивались с новыми."""
    out_dir = project_root / OUTPUT_DIR
    if not out_dir.exists():
        print("  Нечего чистить.")
        return

    targets = [out_dir / name for name in _RENAME_MAP.values()]
    targets.append(out_dir / f"{_MAIN_STEM}.build")
    targets.append(out_dir / f"{_MAIN_STEM}.dist")
    targets.append(out_dir / f"{_MAIN_STEM}.onefile-build")

    for t in targets:
        if not t.exists():
            continue
        try:
            if t.is_dir():
                shutil.rmtree(t)
            else:
                t.unlink()
            print(f"  Удалено: {t.relative_to(project_root)}")
        except OSError as exc:
            print(f"  Не удалось удалить {t}: {exc!r}")


def _rename_artifacts(project_root: Path) -> None:
    """Переименовывает main.* в CCRun.*"""
    out_dir = project_root / OUTPUT_DIR
    if not out_dir.exists():
        return

    renamed_any = False
    for src_name, dst_name in _RENAME_MAP.items():
        src = out_dir / src_name
        dst = out_dir / dst_name

        if not src.exists():
            continue

        if dst.exists():
            try:
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            except OSError as exc:
                print(f"  Не удалось удалить {dst}: {exc!r}")
                continue

        try:
            src.rename(dst)
            print(f"  {src_name} → {dst_name}")
            renamed_any = True
        except OSError as exc:
            print(f"  Не удалось переименовать {src}: {exc!r}")

    if not renamed_any:
        print("  Нечего переименовывать.")


def _find_result(
    project_root: Path, *, onefile: bool,
) -> Path | None:
    out_dir = project_root / OUTPUT_DIR
    if not out_dir.exists():
        return None

    if onefile:
        candidate = out_dir / f"{OUTPUT_NAME}.exe"
        return candidate if candidate.is_file() else None

    candidate = (
        out_dir / f"{_RENAMED_STEM}.dist" / f"{OUTPUT_NAME}.exe"
    )
    return candidate if candidate.is_file() else None


# --- Точка входа ---

def main() -> int:
    project_root = Path(__file__).resolve().parent
    print(f"Корень проекта: {project_root}")
    print()

    argv = sys.argv[1:]
    onefile = "--onefile" in argv
    debug = "--debug" in argv

    if debug:
        print("Режим: debug (с консолью)")
    if onefile:
        print("Режим: onefile (единый .exe)")
    if debug or onefile:
        print()

    if not _check_prerequisites(project_root):
        return 1

    print("Очистка старых артефактов:")
    _clean_output(project_root)
    print()

    cmd = _build_command(project_root, onefile=onefile, debug=debug)

    print("Команда сборки:")
    print("  " + " \\\n  ".join(cmd))
    print()
    print("Запускаю Nuitka... (первая сборка может занять 3–10 минут)")
    print()

    try:
        result = subprocess.run(cmd, cwd=project_root)
    except KeyboardInterrupt:
        print("\nСборка прервана пользователем.")
        return 130

    if result.returncode != 0:
        print(
            f"\nСборка завершилась с ошибкой "
            f"(код {result.returncode}).",
        )
        return result.returncode

    print()
    print("Переименование артефактов:")
    _rename_artifacts(project_root)

    print()
    print("=" * 60)
    dist_exe = _find_result(project_root, onefile=onefile)
    if dist_exe is not None:
        size_mb = dist_exe.stat().st_size / (1024 * 1024)
        print(f"Готово: {dist_exe} ({size_mb:.1f} МБ)")
    else:
        print(f"Готово. Проверьте: {project_root / OUTPUT_DIR}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
